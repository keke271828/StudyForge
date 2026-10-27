import io
import json
import time
from pathlib import Path

import fitz
from fastapi.testclient import TestClient
import pytest

from studyforge import server
from studyforge.db import create_project, many, one, unj
from studyforge.materials import read_original_sources, clear_original_cache
from studyforge.source_scope import page_numbers, natural_pages, explicit_full


def book_bytes():
    document = fitz.open()
    for number in range(1, 5):
        page = document.new_page()
        page.insert_text((50, 70), f'PRIVATE_PAGE_{number}: This is a complete sentence on this page only.')
        page.insert_text((50, 100), f'Selected paragraph {number} discusses only topic number {number}.')
    result = document.tobytes()
    document.close()
    return result


def stored_pdf(client, project):
    response = client.post('/api/import/file', data={'project_id': project['id']}, files={'file': ('book.pdf', book_bytes())})
    assert response.status_code == 200, response.text
    assert response.json()['job_id'] is None
    return response.json()['source_id']


def test_upload_and_url_are_stored_without_reading(monkeypatch):
    project = create_project('仅存放资料')
    def forbidden(*args, **kwargs):
        pytest.fail('Upload or URL storage attempted to parse/download contents')
    monkeypatch.setattr(server, 'parse_file', forbidden)
    monkeypatch.setattr(server, 'download_public_resource', forbidden)
    client = TestClient(server.app)
    ident = stored_pdf(client, project)
    row = one('SELECT * FROM sources WHERE id=?', (ident,))
    assert row['status'] == 'stored' and unj(row['segments_json']) == []
    assert Path(row['original_path']).read_bytes().startswith(b'%PDF')
    url = client.post('/api/import/url', json={'project_id': project['id'], 'url': 'https://www.bilibili.com/video/BV1test/'})
    assert url.status_code == 200, url.text
    assert url.json()['job_id'] is None
    assert one('SELECT status FROM sources WHERE id=?', (url.json()['source_id'],))['status'] == 'stored'
    assert many('SELECT * FROM jobs') == []
    with pytest.raises(ValueError, match='尚未解析'):
        read_original_sources([dict(row, segments=[])])


def test_only_selected_pages_and_exact_paragraph_are_read(monkeypatch):
    project = create_project('按页阅读')
    client = TestClient(server.app)
    ident = stored_pdf(client, project)
    def forbidden(*args, **kwargs):
        pytest.fail('Whole-file parser was called by page selection')
    monkeypatch.setattr(server, 'parse_file', forbidden)
    preview = client.get(f'/api/sources/{ident}/page?page=3').json()
    assert preview['page_count'] == 4
    assert 'PRIVATE_PAGE_3' in preview['text'] and 'PRIVATE_PAGE_1' not in preview['text']
    partial = client.post(f'/api/sources/{ident}/parse', json={'mode': 'pages', 'page_spec': '3'})
    assert partial.status_code == 200, partial.text
    selected = one('SELECT * FROM sources WHERE id=?', (partial.json()['source_id'],))
    selected['segments'] = unj(selected['segments_json'])
    read = read_original_sources([selected])[0]
    assert read['segments'][0]['locator'] == '第 3 页'
    assert 'PRIVATE_PAGE_3' in read['segments'][0]['text']
    assert all('PRIVATE_PAGE_1' not in part['text'] for part in read['segments'])
    assert read['read_manifest']['method'] == 'explicit_selected_scope'
    paragraph = 'Selected paragraph 3 discusses only topic number 3.'
    part = client.post(f'/api/sources/{ident}/parse', json={'mode': 'text', 'page_spec': '3', 'selected_text': paragraph, 'locator': '第 3 页第二段'})
    assert part.status_code == 200, part.text
    parts = unj(one('SELECT segments_json FROM sources WHERE id=?', (part.json()['source_id'],))['segments_json'])
    assert parts[0]['text'] == paragraph and parts[0]['meta']['source_text_verified'] is True
    assert one('SELECT status FROM sources WHERE id=?', (ident,))['status'] == 'stored'
    assert not many('SELECT * FROM jobs')
    mismatch = client.post(f'/api/sources/{ident}/parse', json={'mode': 'text', 'page_spec': '3', 'selected_text': 'PRIVATE_PAGE_1'})
    assert mismatch.status_code == 400
    assert client.post(f'/api/sources/{ident}/parse', json={'mode': 'pages', 'page_spec': '999'}).status_code == 400


def test_stored_selection_persists_without_auto_read(monkeypatch):
    from studyforge import conversations
    project = create_project('范围与对话隔离')
    client = TestClient(server.app)
    ident = stored_pdf(client, project)
    chat = conversations.create(project['id'], 'deepseek')
    result = client.put('/api/conversations/' + chat['id'], json={'project_id': project['id'], 'source_ids': [ident]})
    assert result.status_code == 200, result.text
    def forbidden(*args, **kwargs):
        pytest.fail('Restoring an unread conversation parsed the original book')
    monkeypatch.setattr('studyforge.materials.read_original_sources', forbidden)
    assert conversations.cached_reading(project['id'], [ident], 'deepseek', None, None) is None
    assert client.get(f"/api/conversations/{chat['id']}?project_id={project['id']}").json()['source_ids'] == [ident]


def test_internal_scope_cannot_be_forged_by_upload(tmp_path):
    from studyforge.parsers import parse_file
    fake = tmp_path / 'uploaded.sfscope'
    fake.write_text(json.dumps({'schema': 'studyforge-selected-source-v1', 'segments': [{'locator': 'x', 'text': 'x', 'meta': {'image_path': 'C:/Windows/private.png'}}]}))
    clear_original_cache()
    with pytest.raises(ValueError, match='内部'):
        parse_file(fake)


def test_invalid_pdf_reports_reading_error_without_losing_original():
    project = create_project('错误文件仍保留')
    client = TestClient(server.app)
    upload = client.post('/api/import/file', data={'project_id': project['id']}, files={'file': ('broken.pdf', b'not-a-pdf')})
    ident = upload.json()['source_id']
    assert client.get(f'/api/sources/{ident}/page?page=1').status_code == 400
    assert client.post(f'/api/sources/{ident}/parse', json={'mode': 'pages', 'page_spec': '1'}).status_code == 400
    row = one('SELECT * FROM sources WHERE id=?', (ident,))
    assert row['status'] == 'stored' and Path(row['original_path']).read_bytes() == b'not-a-pdf'


def test_ranges_are_bounded_and_full_requires_explicit_intent():
    assert page_numbers('3-5,8', 8) == [3, 4, 5, 8]
    assert natural_pages('请仅讲解第3页到第5页') == '3-5'
    assert explicit_full('请通读整本书')
    assert not explicit_full('不要通读整本书，只讲第3页')
    with pytest.raises(ValueError):
        page_numbers('1-10000', 10000)


def test_tutor_page_request_sends_only_that_page_and_never_whole_book(monkeypatch):
    from studyforge import conversations
    prompts = []
    class Teacher:
        model = 'scope-fixture'
        async def agent_stream(self, messages):
            prompts.append(messages)
            yield 'final', '我只读取了你明确要求的第 3 页。'
    monkeypatch.setattr(server, 'DeepSeekClient', lambda *args, **kwargs: Teacher())
    monkeypatch.setattr(server, 'client_for', lambda *args, **kwargs: Teacher())
    project = create_project('导师按范围读原文')
    client = TestClient(server.app)
    ident = stored_pdf(client, project)
    chat = conversations.create(project['id'], 'deepseek')
    response = client.post('/api/chat/stream', json={'project_id': project['id'], 'conversation_id': chat['id'], 'provider': 'deepseek', 'source_ids': [ident], 'text': '请只解释第3页的内容'})
    assert response.status_code == 200, response.text
    assert prompts, response.text
    context = prompts[0][0]['content']
    assert 'PRIVATE_PAGE_3' in context
    assert 'PRIVATE_PAGE_1' not in context and 'PRIVATE_PAGE_4' not in context
    assert '本次选定原文范围' in context
    assert one('SELECT status FROM sources WHERE id=?', (ident,))['status'] == 'stored'


def test_agent_cannot_bypass_scope_even_with_full_access():
    import asyncio
    from studyforge.agent_tools import AgentRuntime
    from studyforge.ai import save_settings
    from studyforge import conversations
    project = create_project('范围约束优先')
    client = TestClient(server.app)
    ident = stored_pdf(client, project)
    chat = conversations.create(project['id'], 'deepseek')
    save_settings({'agent_permission_mode': 'full_access'})
    runtime = AgentRuntime(project['id'], [ident], conversation_id=chat['id'])
    runtime.source_read_request = '只讲解第3页'
    path = one('SELECT original_path FROM sources WHERE id=?', (ident,))['original_path']
    with pytest.raises(PermissionError):
        runtime.checked_path(path)
    result = asyncio.run(runtime.execute('sf_read_source', {'source_id': ident, 'page_spec': '3'}))
    assert not result.get('error'), result
    assert result['whole_source_read'] is False
    assert 'PRIVATE_PAGE_3' in json.dumps(result) and 'PRIVATE_PAGE_1' not in json.dumps(result)
    outside = asyncio.run(runtime.execute('sf_read_source', {'source_id': ident, 'page_spec': '1-4'}))
    assert '范围' in outside['error']
    full = asyncio.run(runtime.execute('sf_read_source', {'source_id': ident, 'read_entire_source': True}))
    assert '页码' in full['error']
    runtime.source_read_request = '只解释第3页第2段'
    paragraph = asyncio.run(runtime.execute('sf_read_source', {'source_id': ident, 'page_spec': '3'}))
    assert '确切段落' in paragraph['error']


def test_ambiguous_paragraph_does_not_expand_to_a_whole_page(monkeypatch):
    from studyforge import conversations
    prompts = []
    class Teacher:
        model = 'scope-fixture'
        async def agent_stream(self, messages):
            prompts.append(messages)
            yield 'final', '请在范围入口选中第 3 页的第二段。'
    monkeypatch.setattr(server, 'DeepSeekClient', lambda *args, **kwargs: Teacher())
    project = create_project('段落边界须明确')
    client = TestClient(server.app)
    ident = stored_pdf(client, project)
    chat = conversations.create(project['id'], 'deepseek')
    response = client.post('/api/chat/stream', json={'project_id': project['id'], 'conversation_id': chat['id'], 'provider': 'deepseek', 'source_ids': [ident], 'text': '请只解析第3页第2段'})
    assert response.status_code == 200 and prompts, response.text
    assert 'PRIVATE_PAGE_3' not in prompts[0][0]['content']
    assert '不能把整页' in prompts[0][0]['content']
