import io
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from studyforge import ai, appearance, server
from studyforge.config import data_dir
from studyforge.db import many
from studyforge.surfaces import SURFACE_BASES, SURFACE_DEFAULTS, READABILITY_DEFAULTS


def font_file(family='Test Local Font', flavor=None):
    builder=FontBuilder(1000,isTTF=True)
    glyphs=['.notdef','space','A','han']
    builder.setupGlyphOrder(glyphs)
    builder.setupCharacterMap({32:'space',65:'A',0x5B66:'han'})
    outlines={}
    for glyph in glyphs:
        pen=TTGlyphPen(None)
        if glyph!='space':
            pen.moveTo((100,0));pen.lineTo((500,0));pen.lineTo((300,700));pen.closePath()
        outlines[glyph]=pen.glyph()
    builder.setupGlyf(outlines)
    builder.setupHorizontalMetrics({name:(600,0) for name in glyphs})
    builder.setupHorizontalHeader(ascent=800,descent=-200)
    builder.setupNameTable({'familyName':family,'styleName':'Regular','uniqueFontIdentifier':family,
                           'fullName':family,'psName':family.replace(' ','')})
    builder.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200)
    builder.setupPost();builder.setupMaxp()
    builder.font.flavor=flavor
    output=io.BytesIO();builder.save(output)
    return output.getvalue()


@pytest.mark.parametrize('region',SURFACE_BASES)
def test_region_range_endpoints_and_persisted_independence(region):
    client=TestClient(server.app)
    ai.save_settings({'deepseek_model':'selected','ui_background':'dusk'})
    for opacity in [0,100]:
        before=ai.settings()
        values={f'ui_{region}_opacity':opacity,f'ui_{region}_blur':40,
                f'ui_{region}_text_color':'#fAfA10',f'ui_{region}_stroke_width':.75,
                f'ui_{region}_stroke_color':'#123456'}
        response=client.put('/api/settings',json=values)
        assert response.status_code==200
        restored=client.get('/api/settings').json()
        assert all(restored[key]==value for key,value in values.items())
        assert all(restored[key]==value for key,value in before.items() if key not in values)


@pytest.mark.parametrize('region',SURFACE_BASES)
@pytest.mark.parametrize('field,value',[('opacity',-1),('opacity',101),('opacity',True),('blur',41),
                                      ('blur','12'),('stroke_width',2.1),('stroke_width',True),
                                      ('text_color','red'),('stroke_color','url(bad)')])
def test_invalid_region_change_cannot_partially_save(region,field,value):
    before=ai.settings()
    response=TestClient(server.app).put('/api/settings',json={'ui_theme':'night',f'ui_{region}_{field}':value})
    assert response.status_code==400 and ai.settings()==before


@pytest.mark.parametrize('value',[float('nan'),float('inf'),float('-inf')])
def test_nonfinite_outline_rejected(value):
    with pytest.raises(ValueError):ai.save_settings({'ui_surface_stroke_width':value})


def test_independent_settings_changes_can_overlap_without_losing_values():
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda region:ai.save_settings({f'ui_{region}_opacity':0,f'ui_{region}_blur':17}),SURFACE_BASES))
    saved=ai.settings()
    assert all(saved[f'ui_{region}_opacity']==0 and saved[f'ui_{region}_blur']==17 for region in SURFACE_BASES)


def test_surface_and_background_resets_are_independent_of_each_other_and_font():
    client=TestClient(server.app)
    uploaded=appearance.install_font(font_file(),'local.ttf')
    ai.save_settings({'ui_background':'dusk','ui_background_blur':4,'deepseek_model':'chosen',
                      'ui_surface_opacity':0,'ui_sidebar_opacity':23,'ui_sidebar_blur':16})
    client.post('/api/appearance/background/reset')
    assert ai.settings()['ui_surface_opacity']==0 and ai.settings()['ui_sidebar_opacity']==23
    ai.save_settings({'ui_background':'mist','ui_background_blur':7,'ui_readability':'off'})
    before=ai.settings()
    result=client.post('/api/appearance/surfaces/reset').json()
    assert all(result[key]==value for key,value in SURFACE_DEFAULTS.items())
    assert result['ui_readability']=='auto'
    assert all(result[key]==value for key,value in before.items() if key not in SURFACE_DEFAULTS | READABILITY_DEFAULTS)
    assert appearance.font_path(uploaded['ui_font_asset']).is_file()


@pytest.mark.parametrize('flavor',[None,'woff','woff2'])
def test_valid_font_is_normalized_to_local_sfnt_copy_and_does_not_enter_learning_context(tmp_path,flavor):
    client=TestClient(server.app);raw=font_file(flavor=flavor)
    original=tmp_path/('原字体.'+(flavor or 'ttf'));original.write_bytes(raw)
    before=ai.settings()
    response=client.post('/api/appearance/font',files={'file':(original.name,raw)})
    assert response.status_code==200,response.text
    config=response.json();asset=config['ui_font_asset']
    assert config['ui_font_family']=='custom' and config['ui_font_name']==original.name
    assert original.read_bytes()==raw
    result=client.get('/api/appearance/font/'+asset)
    assert result.status_code==200 and result.content[:4]==b'\x00\x01\x00\x00'
    assert result.headers['x-content-type-options']=='nosniff'
    with TTFont(io.BytesIO(result.content)) as face:assert face.getBestCmap()[0x5B66]=='han'
    assert all(config[key]==value for key,value in before.items() if key not in {'ui_font_family','ui_font_asset','ui_font_name'})
    for table in ['sources','messages','jobs','learning_events']:assert not many('SELECT * FROM '+table)
    client.delete('/api/appearance/font')
    assert original.read_bytes()==raw and client.get('/api/appearance/font/'+asset).status_code==404
    assert ai.settings()['ui_font_family']=='system'


@pytest.mark.parametrize('raw',[b'bad',b'\x00\x01\x00\x00bad',b'wOFFbroken',b'wOF2broken',b'OTTObroken',
                              b'wOF2'+b'\x00'*12+(appearance.MAX_FONT_BYTES+1).to_bytes(4,'big')])
def test_invalid_font_keeps_previous_local_copy(raw):
    previous=appearance.install_font(font_file(),'good.ttf');before=ai.settings()
    response=TestClient(server.app).post('/api/appearance/font',files={'file':('broken.ttf',raw)})
    assert response.status_code==400 and ai.settings()==before
    assert appearance.font_path(previous['ui_font_asset']).is_file()


@pytest.mark.parametrize('change',[{'ui_font_family':'custom'},{'ui_font_family':'bad'},
                                   {'ui_font_asset':'../settings.json'},{'ui_font_asset':False},
                                   {'ui_font_name':'bad\nline'},{'ui_font_name':'x'*181}])
def test_invalid_font_preferences_cannot_change_settings(change):
    before=ai.settings()
    response=TestClient(server.app).put('/api/settings',json=change)
    assert response.status_code==400 and ai.settings()==before


def test_font_replace_removes_old_copy_and_failure_rolls_back(monkeypatch):
    previous=appearance.install_font(font_file('Old'),'old.ttf')
    newer=appearance.install_font(font_file('New'),'new.ttf')
    assert not appearance.font_path(previous['ui_font_asset']).exists()
    before=ai.settings()
    def fail(*args,**kwargs):raise OSError('simulated disk error')
    monkeypatch.setattr(ai,'save_settings',fail)
    with pytest.raises(OSError):appearance.install_font(font_file('Next'),'next.ttf')
    assert ai.settings()==before and appearance.font_path(newer['ui_font_asset']).is_file()
    assert len(list((data_dir()/'appearance'/'fonts').glob('*.font')))==1
    assert not list((data_dir()/'appearance'/'fonts').glob('*.tmp'))


def test_font_identifier_cannot_read_arbitrary_files():
    client=TestClient(server.app)
    for identifier in ['settings.json','f'*64,'..%2Fsettings.json']:
        assert client.get('/api/appearance/font/'+identifier).status_code==404
