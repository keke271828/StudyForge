"""Whole-resource URL/image actions cannot fall into the PDF excerpt workflow."""
import asyncio
import io
import json
import sqlite3
import time
import httpx
import fitz
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from studyforge import parsers, server, urls
from studyforge.config import data_dir, temp_dir
from studyforge.db import create_project, execute, j, many, one
from studyforge.source_scope import parsing_policy


def terminal(client, job_id):
    for _ in range(200):
        row = client.get('/api/jobs/' + job_id).json()
        if row['status'] in ('completed', 'failed', 'cancelled'):
            return row
        time.sleep(.025)
    pytest.fail('Explicit parsing job did not finish')


def upload_image(client, project):
    content = io.BytesIO()
    Image.new('RGB', (180, 70), 'white').save(content, 'PNG')
    response = client.post('/api/import/file', data={'project_id': project['id']},
                           files={'file': ('diagram.png', content.getvalue(), 'image/png')})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('kind', ['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'])
def test_registered_images_are_excluded_from_partial_parsing(kind):
    assert parsing_policy({'kind': kind}) == {'parse_type': 'image', 'partial_parse_supported': False}
    assert parsing_policy({'kind': kind.upper()})['partial_parse_supported'] is False
    assert parsing_policy({'kind': '.pdf'})['partial_parse_supported'] is True


def test_image_stays_stored_until_explicit_whole_image_action(monkeypatch):
    calls = []
    def ocr(path):
        assert Image.open(path).size == (180, 70)
        calls.append(str(path))
        return 'WHOLE_IMAGE_CONTENT'
    monkeypatch.setattr(parsers, '_ocr', ocr)
    project = create_project('图片独立解析')
    with TestClient(server.app) as client:
        uploaded = upload_image(client, project)
        ident = uploaded['source_id']
        assert uploaded['job_id'] is None and uploaded['parse_type'] == 'image'
        assert not calls and not many('SELECT * FROM jobs')
        for mode in ('pages', 'text'):
            response = client.post(f'/api/sources/{ident}/parse', json={
                'mode': mode, 'page_spec': '1', 'selected_text': 'do not turn this into an excerpt'})
            assert response.status_code == 400 and '不参与部分解析' in response.text
        assert one('SELECT status FROM sources WHERE id=?', (ident,))['status'] == 'stored'
        assert not many('SELECT * FROM source_scopes')
        response = client.post(f'/api/sources/{ident}/parse', json={'mode': 'full'})
        assert response.status_code == 200, response.text
        assert terminal(client, response.json()['job_id'])['status'] == 'completed'
        assert len(calls) == 1
        row = one('SELECT * FROM sources WHERE id=?', (ident,))
        assert row['status'] == 'ready' and Path(row['original_path']).is_file()
        assert 'WHOLE_IMAGE_CONTENT' in row['segments_json']
        listed = client.get(f'/api/projects/{project["id"]}/sources').json()[0]
        assert listed['parse_type'] == 'image' and not listed['partial_parse_supported']


def test_url_parser_failure_can_retry_original_url_and_keep_its_type(monkeypatch):
    downloads, parses = [], []
    def download(url, source_id, **kwargs):
        downloads.append(url)
        path = temp_dir() / f'url-{source_id}.html'
        path.write_text('<article><h1>URL_TITLE</h1><p>WHOLE_URL_BODY</p></article>', encoding='utf-8')
        return path
    original = server.parse_file
    def parse(path):
        parses.append(str(path))
        if len(parses) == 1:
            raise ValueError('Temporary parsing failure for retry verification')
        return original(path)
    monkeypatch.setattr(server, 'download_public_resource', download)
    monkeypatch.setattr(server, 'parse_file', parse)
    project = create_project('网址失败后重试')
    url = 'https://example.org/lesson'
    with TestClient(server.app) as client:
        result = client.post('/api/import/url', json={'project_id': project['id'], 'url': url}).json()
        ident = result['source_id']
        assert not downloads and result['job_id'] is None
        assert result['parse_type'] == 'url'
        assert client.post(f'/api/sources/{ident}/parse', json={'mode': 'text', 'selected_text': 'fragment'}).status_code == 400
        first = client.post(f'/api/sources/{ident}/parse', json={'mode': 'full'}).json()
        assert terminal(client, first['job_id'])['status'] == 'failed'
        row = one('SELECT * FROM sources WHERE id=?', (ident,))
        assert row['origin_url'] == url and row['original_path'] == url and row['kind'] == 'url'
        assert not Path(parses[0]).exists()
        # Also recover a legacy failure whose kind/path had already changed.
        execute("UPDATE sources SET kind='.html',original_path=? WHERE id=?", (parses[0], ident))
        retried = client.post(f'/api/sources/{ident}/parse', json={'mode': 'full'}).json()
        assert terminal(client, retried['job_id'])['status'] == 'completed'
        row = one('SELECT * FROM sources WHERE id=?', (ident,))
        assert downloads == [url, url] and row['kind'] == '.html'
        assert Path(row['original_path']).is_file() and 'WHOLE_URL_BODY' in row['segments_json']
        listed = client.get(f'/api/projects/{project["id"]}/sources').json()[0]
        assert listed['parse_type'] == 'url' and not listed['partial_parse_supported']
        assert listed['origin_url'] == url
        assert client.post(f'/api/sources/{ident}/parse', json={'mode': 'text', 'selected_text': 'WHOLE_URL_BODY'}).status_code == 400
        cached = client.post(f'/api/sources/{ident}/parse', json={'mode': 'full'}).json()
        assert cached['cached'] and cached['scope'] == 'full'
        assert len(downloads) == 2


def test_restricted_website_preserves_browser_recovery_and_original_url(monkeypatch):
    def blocked(*args, **kwargs):
        raise urls.BrowserImportRequired('网站需要登录，请使用浏览器导入')
    monkeypatch.setattr(server, 'download_public_resource', blocked)
    project = create_project('受限网页有正确恢复入口')
    with TestClient(server.app) as client:
        ident = client.post('/api/import/url', json={'project_id': project['id'], 'url': 'https://example.org/restricted'}).json()['source_id']
        job = client.post(f'/api/sources/{ident}/parse', json={'mode': 'full'}).json()['job_id']
        result = terminal(client, job)
        assert result['status'] == 'failed' and result['result']['requires_browser'] is True
        assert result['result']['url'] == 'https://example.org/restricted'
        row = one('SELECT * FROM sources WHERE id=?', (ident,))
        assert row['origin_url'] == row['original_path'] and row['kind'] == 'url'


def test_old_downloaded_urls_migrate_without_exposing_partial_modes():
    path = data_dir() / 'studyforge.sqlite3'
    with sqlite3.connect(path) as database:
        database.executescript('''
            CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT,created_at TEXT);
            CREATE TABLE sources(id TEXT PRIMARY KEY,project_id TEXT,name TEXT,kind TEXT,
              original_path TEXT,segments_json TEXT,status TEXT,error TEXT,created_at TEXT);
            CREATE TABLE jobs(id TEXT PRIMARY KEY,project_id TEXT,kind TEXT,status TEXT,progress INTEGER,
              payload_json TEXT,result_json TEXT,error TEXT,created_at TEXT,updated_at TEXT);
            INSERT INTO projects VALUES('legacy-project','旧项目','2026-01-01');
            INSERT INTO sources VALUES('legacy-source','legacy-project','已解析的文章','.html','missing.html','[]','error','failed','2026-01-01');
        ''')
        database.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)', ('legacy-job', 'legacy-project', 'import_url', 'failed', 100,
            j({'source_id': 'legacy-source', 'url': 'https://example.org/legacy'}), '{}', 'failed', '2026-01-01', '2026-01-01'))
    row = one('SELECT * FROM sources WHERE id=?', ('legacy-source',))
    assert row['origin_url'] == 'https://example.org/legacy'
    assert parsing_policy(row)['partial_parse_supported'] is False


def test_image_discussion_does_not_trigger_document_excerpt_gate(monkeypatch):
    from studyforge import conversations
    from studyforge.agent_tools import AgentRuntime
    from studyforge.ai import save_settings
    monkeypatch.setattr(parsers, '_ocr', lambda path: 'IMAGE_READ_BY_AGENT')
    project = create_project('图片讨论不要求粘贴选段')
    with TestClient(server.app) as client:
        ident = upload_image(client, project)['source_id']
        job = client.post(f'/api/sources/{ident}/parse', json={'mode': 'full'}).json()['job_id']
        assert terminal(client, job)['status'] == 'completed'
    chat = conversations.create(project['id'], 'deepseek')
    save_settings({'agent_permission_mode': 'full_access'})
    runtime = AgentRuntime(project['id'], [ident], conversation_id=chat['id'])
    monkeypatch.setattr('studyforge.agent_tools.get_secret', lambda key: None)
    metadata = json.loads(runtime.context())['source_files'][0]
    assert metadata['parse_type'] == 'image' and metadata['partial_parse_supported'] is False
    runtime.source_read_request = '只解释这段内容，不需要全文讲解'
    result = asyncio.run(runtime.execute('sf_read_source', {'source_id': ident}))
    assert 'error' not in result, result
    assert 'IMAGE_READ_BY_AGENT' in json.dumps(result)


def test_url_pdf_is_not_reclassified_as_a_partial_document_in_tutor_chat(monkeypatch):
    from studyforge import conversations
    prompts = []
    class Teacher:
        model = 'direct-source-fixture'
        async def agent_stream(self, messages):
            prompts.append(messages)
            yield 'final', '网址已经解析；这次讨论只聚焦你提出的内容。'
    def download(url, source_id, **kwargs):
        path = temp_dir() / f'url-{source_id}.pdf'
        document = fitz.open()
        for number in (1, 2):
            page = document.new_page()
            page.insert_text((50, 70), f'URL_PAGE_{number}: This is the complete content of this page with enough text.')
        document.save(path)
        document.close()
        return path
    monkeypatch.setattr(server, 'download_public_resource', download)
    monkeypatch.setattr(server, 'DeepSeekClient', lambda *args, **kwargs: Teacher())
    monkeypatch.setattr(server, 'client_for', lambda *args, **kwargs: Teacher())
    project = create_project('网址类型在导师上下文中保持一致')
    with TestClient(server.app) as client:
        ident = client.post('/api/import/url', json={'project_id': project['id'], 'url': 'https://example.org/lesson.pdf'}).json()['source_id']
        job = client.post(f'/api/sources/{ident}/parse', json={'mode': 'full'}).json()['job_id']
        assert terminal(client, job)['status'] == 'completed'
        assert client.get(f'/api/sources/{ident}/page?page=2').status_code == 400
        chat = conversations.create(project['id'], 'deepseek')
        response = client.post('/api/chat/stream', json={'project_id': project['id'], 'conversation_id': chat['id'],
            'provider': 'deepseek', 'source_ids': [ident], 'text': '请只解释这个网址中第2页第1段的概念'})
        assert response.status_code == 200 and prompts, response.text
    context = prompts[0][0]['content']
    assert 'URL_PAGE_1' in context and 'URL_PAGE_2' in context
    assert '请学生点击资料旁的范围入口' not in context


@pytest.mark.parametrize('failure,word', [(httpx.ConnectTimeout('handshake timed out'), '超时'),
    (httpx.ConnectError('SSL certificate verify failed'), '加密连接失败')])
def test_url_network_failures_have_actionable_messages(monkeypatch, failure, word):
    monkeypatch.setattr(urls, 'validate_public_url', lambda value: value)
    native = httpx.Client
    def handler(request):
        raise failure
    monkeypatch.setattr(urls.httpx, 'Client', lambda *args, **kwargs: native(transport=httpx.MockTransport(handler)))
    with pytest.raises(urls.BrowserImportRequired) as error:
        urls.download_public_resource('https://example.org/lesson', 'network-test')
    assert word in str(error.value) and 'example.org' in str(error.value)
    assert '重试网址' in str(error.value)
