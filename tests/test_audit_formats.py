import asyncio
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import zipfile

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from studyforge import server
from studyforge.db import create_project, execute, j, now, uid
from studyforge.parsers import parse_file
from studyforge.media import run_ffmpeg, video_frames, video_frame_timestamps


def test_actual_video_frame_timestamps_and_short_clip(tmp_path, monkeypatch):
    video = tmp_path / 'sample.mp4'
    run_ffmpeg('-f', 'lavfi', '-i', 'testsrc=size=80x60:rate=4', '-t', '2.2',
               '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video))
    frames = video_frames(video, every_seconds=1)
    timestamps = video_frame_timestamps(frames)
    assert len(frames) == 3
    assert [timestamps[frame.name] for frame in frames] == [0, 1, 2]
    short = tmp_path / 'short.mp4'
    run_ffmpeg('-i', str(video), '-t', '0.3', str(short))
    assert len(video_frames(short)) == 1
    # The source parser uses the measured value, rather than its default interval.
    monkeypatch.setattr('studyforge.parsers.video_frames', lambda path: frames)
    monkeypatch.setattr('studyforge.parsers._ocr', lambda path: path.name)
    parts = [part for part in parse_file(video) if part['kind'] == 'video_frame']
    assert [part['meta']['time'] for part in parts] == [0, 1, 2]


def test_bom_notebook_import(tmp_path):
    file = tmp_path / 'bom.ipynb'
    file.write_text(json.dumps({'cells': [{'cell_type': 'markdown', 'source': ['中文公式 $x^2$']}]}), encoding='utf-8-sig')
    assert parse_file(file)[0]['text'] == '中文公式 $x^2$'


@pytest.mark.parametrize('suffix', ['mm', 'opml', 'xmind', 'xmind-xml'])
def test_mindmap_notes_survive_import(tmp_path, suffix):
    file = tmp_path / ('notes.xmind' if suffix.startswith('xmind') else 'notes.' + suffix)
    if suffix == 'mm':
        file.write_text('<map><node><richcontent TYPE="NODE"><html><body><p>概念</p></body></html></richcontent>'
                        '<richcontent TYPE="NOTE"><html><body><p>不能忽略的解释</p></body></html></richcontent>'
                        '<node TEXT="边界"/></node></map>', encoding='utf-8')
    elif suffix == 'opml':
        file.write_text('<opml><body><outline text="概念" _note="不能忽略的解释"><outline text="边界"/></outline></body></opml>', encoding='utf-8')
    else:
        with zipfile.ZipFile(file, 'w') as package:
            if suffix == 'xmind':
                package.writestr('content.json', json.dumps([{'rootTopic': {'title': '概念', 'notes': {'plain': {'content': '不能忽略的解释'}},
                                                'children': {'attached': [{'title': '边界'}]}}}], ensure_ascii=False))
            else:
                package.writestr('content.xml', '<xmap-content><sheet><topic><title>概念</title><notes><plain>不能忽略的解释</plain></notes>'
                                                '<children><topics><topic><title>边界</title></topic></topics></children></topic></sheet></xmap-content>')
    parts = parse_file(file)
    assert '不能忽略的解释' in parts[0]['text']
    assert parts[1]['locator'].endswith('概念 / 边界')


@pytest.mark.parametrize('modern', [False, True])
def test_anki_real_compression_fields_and_embedded_image(tmp_path, modern):
    import zstandard
    file = tmp_path / 'deck.apkg'
    database = tmp_path / 'notes.sqlite'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE notes(id INTEGER, flds TEXT, tags TEXT)')
        db.execute('INSERT INTO notes VALUES (1,?,?)', ('正面<img src="图.png">\x1f背面 $x^2$', '数学'))
    image = io.BytesIO()
    Image.new('RGB', (10, 10), 'red').save(image, format='PNG')
    with zipfile.ZipFile(file, 'w') as package:
        if modern:
            compress = zstandard.ZstdCompressor().compress
            package.writestr('collection.anki21b', compress(database.read_bytes()))
            # Protobuf MediaEntries containing one MediaEntry(name = 图.png).
            name = '图.png'.encode()
            entry = b'\x0a' + bytes([len(name)]) + name
            package.writestr('media', compress(b'\x0a' + bytes([len(entry)]) + entry))
            package.writestr('0', compress(image.getvalue()))
            # Real newer exports include a legacy placeholder: never read it first.
            package.writestr('collection.anki2', b'not-the-source-database')
        else:
            package.writestr('collection.anki2', database.read_bytes())
            package.writestr('media', json.dumps({'0': '图.png'}, ensure_ascii=False))
            package.writestr('0', image.getvalue())
    parts = parse_file(file)
    assert '正面' in parts[0]['meta']['fields'][0] and parts[0]['meta']['fields'][1] == '背面 $x^2$'
    assert parts[0]['meta']['tags'] == ['数学']
    image_path = Path(parts[1]['meta']['image_path'])
    with Image.open(image_path) as loaded: assert loaded.getpixel((0, 0)) == (255, 0, 0)
    assert image_path.resolve().is_relative_to(Path(os.environ['STUDYFORGE_DATA_DIR']).resolve())


def test_missing_anki_picture_is_marked(tmp_path):
    file = tmp_path / 'missing.apkg'
    database = tmp_path / 'db.sqlite'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE notes(id, flds, tags)')
        db.execute('INSERT INTO notes VALUES (1,?,?)', ('<img src="missing.png">\x1f解释', ''))
    with zipfile.ZipFile(file, 'w') as package: package.write(database, 'collection.anki2')
    assert '无法确认' in parse_file(file)[1]['text']


def test_anki_decompression_limit_and_bad_media_map(monkeypatch):
    import zstandard
    from studyforge import anki_import
    monkeypatch.setattr(anki_import, 'MAX_ENTRY_BYTES', 2048)
    with pytest.raises(ValueError, match='解压'):
        anki_import.decompress(zstandard.ZstdCompressor().compress(b'x' * 4096))
    with pytest.raises(ValueError, match='索引'):
        anki_import.media_map(zstandard.ZstdCompressor().compress(b'\x0a\xff'), modern=True)


def test_mcp_reads_full_original_and_returns_external_artifact(tmp_path):
    project = create_project('双向 MCP 审计')
    file = tmp_path / 'source.txt'
    file.write_text('原文件的完整内容\n最后的限定条件', encoding='utf-8')
    source_id = uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,error,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
            (source_id, project['id'], file.name, '.txt', str(file), j([{'locator': '预览', 'text': '过时概括'}]), 'ready', None, now()))
    result_file = tmp_path / 'external.md'
    result_file.write_text('# 外部 agent 成果\n成果内容', encoding='utf-8')

    async def check():
        params = StdioServerParameters(command=sys.executable, args=['-m', 'studyforge.mcp_server'], env=dict(os.environ))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.call_tool('read_source', {'source_id': source_id})
                assert not response.isError
                data = response.structuredContent or json.loads(next(part.text for part in response.content if part.type == 'text'))
                assert '最后的限定条件' in data['segments'][0]['text'] and '过时概括' not in json.dumps(data, ensure_ascii=False)
                assert data['read_manifest']['method'] == 'original_file'
                attached = await session.call_tool('attach_artifact', {'project_id': project['id'], 'absolute_path': str(result_file), 'title': '外部成果'})
                artifact = attached.structuredContent or json.loads(next(part.text for part in attached.content if part.type == 'text'))
                assert not attached.isError and artifact['title'] == '外部成果'

    asyncio.run(check())


def test_gbk_code_submission_keeps_original_characters(tmp_path, monkeypatch):
    project = create_project('代码编码')
    assignment = uid()
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
            (assignment, project['id'], '[]', '乘法', j([{'index':0, 'question':'返回 a*b', 'topic':'乘法', 'language':'python'}]),
             j([{'solution':'def f(a,b): return a*b', 'test_code':'pass'}]), 1, 'assigned', now()))
    captured = []

    async def client(*args): return object()

    async def grade(client, assignment_id, code):
        captured.append(code)
        return {'score': 100}

    monkeypatch.setattr(server, 'assessment_client', client)
    monkeypatch.setattr(server, 'grade_code', grade)
    response = TestClient(server.app).post(f'/api/coding/{assignment}/submit', files={'file': ('solution.py', '# 中文注释\ndef f(a,b): return a*b'.encode('gb18030'))})
    assert response.status_code == 200 and '中文注释' in captured[0] and '\ufffd' not in captured[0]
