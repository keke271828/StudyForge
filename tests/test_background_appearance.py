import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from studyforge import ai, appearance, server
from studyforge.config import data_dir
from studyforge.db import many


def picture(color='navy', fmt='PNG', **kwargs):
    out = io.BytesIO()
    Image.new('RGB', (400, 180), color).save(out, format=fmt, **kwargs)
    return out.getvalue()


def test_upload_is_local_copy_without_learning_events_and_serves_decoded_pixels(tmp_path):
    original = tmp_path / '原图.png'
    original.write_bytes(picture())
    ai.save_settings({'learning_mode': 'research', 'deepseek_model': 'chosen-model', 'ui_theme': 'night'})
    before = ai.settings()
    client = TestClient(server.app)
    response = client.post('/api/appearance/background', files={'file': ('原图.png', original.read_bytes(), 'image/png')})
    assert response.status_code == 200
    config = response.json()
    assert config['ui_background'] == 'image' and config['ui_background_name'] == '原图.png'
    assert config['learning_mode'] == 'research' and config['deepseek_model'] == 'chosen-model'
    assert all(config[key] == value for key, value in before.items() if key not in
               {'ui_background', 'ui_background_asset', 'ui_background_name'})
    stored = appearance.background_path(config['ui_background_asset'])
    original.unlink()
    result = client.get('/api/appearance/background/' + config['ui_background_asset'])
    assert result.status_code == 200 and result.headers['content-type'] == 'image/png'
    assert result.headers['x-content-type-options'] == 'nosniff'
    with Image.open(io.BytesIO(result.content)) as image:
        assert image.size == (400, 180) and not image.info
    assert stored.is_file() and ai.settings()['ui_background_asset'] == config['ui_background_asset']
    for table in ['sources', 'jobs', 'learning_events', 'messages']:
        assert not many(f'SELECT * FROM {table}')


def test_exif_rotation_and_metadata_are_not_kept():
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = 'private original description'
    pixels = appearance.normalize_image(picture(fmt='JPEG', exif=exif))
    with Image.open(io.BytesIO(pixels)) as image:
        assert image.size == (180, 400)
        assert not image.getexif() and not image.info


def test_replace_delete_and_reset_preserve_unrelated_settings():
    client = TestClient(server.app)
    ai.save_settings({'ui_theme': 'forest', 'ui_text_size': 'large', 'ui_send_key': 'ctrl-enter',
                      'deepseek_model': 'selected', 'ui_background_blur': 19})
    first = client.post('/api/appearance/background', files={'file': ('first.png', picture())}).json()
    second = client.post('/api/appearance/background', files={'file': ('second.png', picture('gold'))}).json()
    assert not appearance.background_path(first['ui_background_asset']).exists()
    assert appearance.background_path(second['ui_background_asset']).is_file()
    client.put('/api/settings', json={'ui_background': 'mist'})
    removed = client.delete('/api/appearance/background').json()
    assert removed['ui_background'] == 'mist' and removed['ui_background_asset'] == ''
    assert not appearance.background_path(second['ui_background_asset']).exists()
    assert client.get('/api/appearance/background/' + second['ui_background_asset']).status_code == 404
    reset = client.post('/api/appearance/background/reset').json()
    assert all(reset[key] == value for key, value in appearance.BACKGROUND_DEFAULTS.items())
    assert reset['ui_theme'] == 'forest' and reset['ui_text_size'] == 'large'
    assert reset['ui_send_key'] == 'ctrl-enter' and reset['deepseek_model'] == 'selected'


@pytest.mark.parametrize('raw,name', [(b'<svg onload="alert(1)"></svg>', 'fake.png'),
                                    (b'not image', 'fake.jpg'), (picture(fmt='GIF'), 'image.gif')])
def test_invalid_upload_keeps_previous_background(raw, name):
    client = TestClient(server.app)
    client.post('/api/appearance/background', files={'file': ('good.png', picture())})
    before = ai.settings()
    response = client.post('/api/appearance/background', files={'file': (name, raw)})
    assert response.status_code == 400
    assert ai.settings() == before
    assert len(list((data_dir() / 'appearance').glob('*.png'))) == 1


def test_failed_settings_write_rolls_back_new_asset(monkeypatch):
    initial = appearance.install_background(picture(), 'old.png')
    before = ai.settings()
    def fail(*args, **kwargs):
        raise OSError('simulated disk failure')
    monkeypatch.setattr(ai, 'save_settings', fail)
    with pytest.raises(OSError):
        appearance.install_background(picture('red'), 'new.png')
    assert ai.settings() == before
    assert appearance.background_path(initial['ui_background_asset']).is_file()
    assert len(list((data_dir() / 'appearance').glob('*.png'))) == 1
    assert not list((data_dir() / 'appearance').glob('*.tmp'))


def test_upload_disk_failure_is_readable_and_does_not_change_settings(monkeypatch):
    before = ai.settings()
    def fail(*args, **kwargs):
        raise OSError('private disk path')
    monkeypatch.setattr(appearance, 'install_background', fail)
    result = TestClient(server.app).post('/api/appearance/background', files={'file': ('x.png', picture())})
    assert result.status_code == 500
    assert '已保留原设置' in result.json()['detail'] and 'private disk path' not in result.text
    assert ai.settings() == before


@pytest.mark.parametrize('value', [
    {'ui_background': 'anything'}, {'ui_background': []}, {'ui_background': 'image'},
    {'ui_background_asset': '../settings.json'}, {'ui_background_asset': 'f' * 64},
    {'ui_background_asset': False}, {'ui_background_transparency': -1},
    {'ui_background_transparency': 101}, {'ui_background_transparency': True},
    {'ui_background_blur': 25}, {'ui_background_blur': 1.5},
    {'ui_background_x': -2}, {'ui_background_y': '30'}, {'ui_surface_opacity': -1},
    {'ui_background_quiet_focus': 'yes'}, {'ui_background_name': 'line\nbreak'},
])
def test_invalid_preferences_never_change_saved_values(value):
    before = ai.settings()
    result = TestClient(server.app).put('/api/settings', json=value)
    assert result.status_code == 400 and ai.settings() == before


def test_background_identifier_cannot_read_settings_or_arbitrary_files(tmp_path):
    ai.save_settings({'deepseek_model': 'private'})
    client = TestClient(server.app)
    for name in ['settings.json', 'f' * 64, 'file:///C:/Windows/win.ini', '..%2Fsettings.json']:
        assert client.get('/api/appearance/background/' + name).status_code == 404


def test_background_decode_limits_work_and_uploaded_size_is_checked(monkeypatch):
    monkeypatch.setattr(appearance, 'MAX_PIXELS', 10)
    with pytest.raises(ValueError, match='分辨率'):
        appearance.normalize_image(picture())
    monkeypatch.setattr(appearance, 'MAX_UPLOAD_BYTES', 10)
    result = TestClient(server.app).post('/api/appearance/background', files={'file': ('x.png', picture())})
    assert result.status_code == 413 and ai.settings()['ui_background_asset'] == ''


def test_missing_asset_and_animated_image_are_rejected():
    first = Image.new('RGB', (10, 10), 'navy')
    out = io.BytesIO()
    first.save(out, format='PNG', save_all=True, append_images=[Image.new('RGB', (10, 10), 'red')], duration=100)
    with pytest.raises(ValueError, match='静态'):
        appearance.normalize_image(out.getvalue())


def test_file_selection_cannot_replace_learning_agent_internal_access_boundaries():
    from studyforge.agent_tools import AgentRuntime
    cfg = appearance.install_background(picture(), 'private-wallpaper.png')
    runtime = AgentRuntime()
    with pytest.raises(PermissionError):
        runtime.checked_path(str(appearance.background_path(cfg['ui_background_asset'])))
