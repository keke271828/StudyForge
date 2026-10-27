import asyncio
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from studyforge import artifact_sources, conversations, server
from studyforge.ai import save_settings
from studyforge.config import artifacts_dir
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid
from studyforge.exporters import export_document
from studyforge.materials import read_original_sources


def setup_sources(tmp_path):
    project = create_project('项目一')
    other = create_project('项目二')
    ids = []
    for name in ['A', 'B', 'C']:
        path = tmp_path / (name + '.txt')
        path.write_text(name + '完整原文\n末尾依据：' + name, encoding='utf-8')
        source_id = uid()
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
                (source_id, project['id'], path.name, '.txt', str(path), j([{'locator':'预览','text':'摘要不能替代原文件'}]), 'ready', now()))
        ids.append(source_id)
    return project, other, ids


def new_chat(client, project):
    response = client.post(f"/api/projects/{project['id']}/conversations", json={'provider':'deepseek', 'model':'fixture', 'model_choice':'fixture'})
    assert response.status_code == 200, response.text
    return response.json()


def update(client, chat, **changes):
    response = client.put('/api/conversations/' + chat['id'], json={'project_id':chat['project_id'], **changes})
    assert response.status_code == 200, response.text
    return response.json()


def test_independent_selections_drafts_and_modes_survive_new_client(tmp_path):
    project, _, ids = setup_sources(tmp_path)
    client = TestClient(server.app)
    a, b = new_chat(client, project), new_chat(client, project)
    assert a['source_ids'] == b['source_ids'] == []
    update(client, a, source_ids=ids[:2], draft='A与B的问题', learning_mode='research')
    update(client, b, source_ids=ids[1:], draft='B与C的问题', learning_mode='overview')
    reopened = TestClient(server.app, base_url='http://restarted-server')
    for chat, selected, draft, mode in [(a, ids[:2], 'A与B的问题', 'research'), (b, ids[1:], 'B与C的问题', 'overview')]:
        row = reopened.get(f"/api/conversations/{chat['id']}?project_id={project['id']}").json()
        assert row['source_ids'] == selected and row['draft'] == draft and row['learning_mode'] == mode


def test_last_project_and_chat_restored_without_llm(tmp_path, monkeypatch):
    project, other, _ = setup_sources(tmp_path)
    client = TestClient(server.app)
    a, b = new_chat(client, project), new_chat(client, other)
    monkeypatch.setattr(server, 'client_for', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('恢复不应调用模型')))
    assert client.post(f"/api/conversations/{a['id']}/activate?project_id={project['id']}").status_code == 200
    reopened = TestClient(server.app)
    assert reopened.get('/api/workspace').json()['project_id'] == project['id']
    assert reopened.get(f"/api/projects/{project['id']}/conversations").json()['active_conversation_id'] == a['id']
    assert reopened.get(f"/api/projects/{other['id']}/conversations").json()['active_conversation_id'] == b['id']


def test_legacy_chats_are_listed_and_manual_names_preserved(tmp_path):
    project, _, _ = setup_sources(tmp_path)
    chat_id = uid()
    execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)', (chat_id, project['id'], 'deepseek', None, now(), '[]', None, None))
    message_id = uid()
    execute('INSERT INTO messages VALUES (?,?,?,?,?)', (message_id, chat_id, 'user', '请解释构造的动机。', now()))
    client = TestClient(server.app)
    row = client.get(f"/api/projects/{project['id']}/conversations").json()['conversations'][0]
    assert row['id'] == chat_id and row['title'] == '请解释构造的动机。'
    assert row['message_count'] == 1
    client.put('/api/conversations/' + chat_id, json={'project_id':project['id'], 'title':'我的独立论证'})
    conversations.touch(chat_id, '其他自动标题')
    assert conversations.detail(chat_id, project['id'])['title'] == '我的独立论证'
    assert one('SELECT content FROM messages WHERE id=?', (message_id,))['content'] == '请解释构造的动机。'


def test_project_boundary_for_chats_reading_and_sources(tmp_path):
    project, other, ids = setup_sources(tmp_path)
    client = TestClient(server.app)
    chat = new_chat(client, other)
    assert client.put('/api/conversations/' + chat['id'], json={'project_id':other['id'], 'source_ids':[ids[0]]}).status_code == 400
    assert client.get(f"/api/conversations/{chat['id']}?project_id={project['id']}").status_code == 404
    assert client.get(f"/api/conversations/{chat['id']}/messages?project_id={project['id']}").status_code == 404
    assert client.post(f"/api/conversations/{chat['id']}/activate?project_id={project['id']}").status_code == 404


def test_chat_history_isolated_while_each_selection_can_change(tmp_path, monkeypatch):
    project, _, ids = setup_sources(tmp_path)
    client = TestClient(server.app)
    a, b = new_chat(client, project), new_chat(client, project)
    calls = []
    class FakeAI:
        def __init__(self, model=None, effort=None): self.model = model or 'fixture'; self.effort=effort
        async def agent_stream(self, messages):
            calls.append((messages, self.agent_runtime))
            yield 'final', '已解释该资料的动机和边界。'
    monkeypatch.setattr(server, 'DeepSeekClient', FakeAI)
    for chat, selected, text in [(a, ids[:2], '只属于对话A的要求'), (b, ids[1:], '只属于对话B的要求'), (a, [ids[2]], '同一对话换资料C')]:
        response = client.post('/api/chat/stream', json={'project_id':project['id'], 'conversation_id':chat['id'], 'source_ids':selected,
            'provider':'deepseek', 'model':'fixture', 'text':text})
        assert response.status_code == 200, response.text
    assert 'A完整原文' in calls[0][0][0]['content'] and 'C完整原文' not in calls[0][0][0]['content']
    assert 'B完整原文' in calls[1][0][0]['content'] and 'C完整原文' in calls[1][0][0]['content']
    assert '只属于对话A' not in j(calls[1][0]) and '只属于对话B' not in j(calls[2][0])
    assert '只属于对话A' in j(calls[2][0])
    assert conversations.detail(a['id'], project['id'])['source_ids'] == [ids[2]]
    assert conversations.detail(b['id'], project['id'])['source_ids'] == ids[1:]
    assert '摘要不能替代' not in j([call[0] for call in calls])


def test_unchanged_reading_is_restored_without_model_and_changed_file_invalidates(tmp_path, monkeypatch):
    project, _, ids = setup_sources(tmp_path)
    client = TestClient(server.app)
    chat = new_chat(client, project)
    update(client, chat, source_ids=ids[:2])
    class FakeAI:
        model = 'fixture'
        async def complete(self, *a, **kw): return '已通读完整A与B'
    monkeypatch.setattr(server, 'client_for', lambda *a, **kw: FakeAI())
    value = server.ReadIn(project_id=project['id'], source_ids=ids[:2], provider='deepseek', model='fixture')
    job_id = create_job(project['id'], 'read', value.model_dump())
    asyncio.run(server._read_job(job_id, value))
    result = json.loads(one('SELECT result_json FROM jobs WHERE id=?', (job_id,))['result_json'])
    monkeypatch.setattr(server, 'client_for', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('不应重复通读')))
    row = client.get(f"/api/conversations/{chat['id']}?project_id={project['id']}").json()
    assert row['reading']['reading_id'] == result['reading_id'] and row['reading']['cached']
    restore = client.post('/api/read/restore', json=value.model_dump()).json()['reading']
    assert restore['reading_id'] == result['reading_id']
    (tmp_path / 'B.txt').write_text('原文B已修改', encoding='utf-8')
    assert client.post('/api/read/restore', json=value.model_dump()).json()['reading'] is None


def test_generated_artifact_available_without_import_and_project_isolated(tmp_path):
    project, other, _ = setup_sources(tmp_path)
    client = TestClient(server.app)
    chat = new_chat(client, project)
    content = '# AI成果\n\n全文依据。\n\n' + '详细解释。' * 800 + '\n重要末尾：不要忽略限制条件。'
    path = export_document(content, 'docx', '讲解成果', 'fixture.docx')
    artifact = server.add_artifact(project['id'], [], 'explanation', 'docx', '讲解成果', path)
    refs = client.get(f"/api/projects/{project['id']}/sources").json()
    ref = next(row for row in refs if row['artifact_id'] == artifact['id'])
    assert client.get(f"/api/projects/{other['id']}/sources").json() == []
    assert client.get(f"/api/projects/{other['id']}/artifacts").json() == []
    assert conversations.detail(chat['id'], project['id'])['source_ids'] == []
    assert one('SELECT original_path FROM sources WHERE id=?', (ref['id'],))['original_path'] == str(path.resolve())
    originals = read_original_sources(server.source_records([ref['id']], project['id']))
    assert '重要末尾：不要忽略限制条件' in j(originals[0]['segments'])
    assert originals[0]['read_manifest']['artifact_id'] == artifact['id']
    assert '重要末尾' in j(client.get('/api/sources/' + ref['id']).json())


def test_artifact_rename_delete_keeps_reference_in_sync(tmp_path):
    project, _, _ = setup_sources(tmp_path)
    client = TestClient(server.app)
    path = export_document('# 讲解\n可阅读内容', 'docx', '旧名', 'rename.docx')
    artifact = server.add_artifact(project['id'], [], 'explanation', 'docx', '旧名', path)
    ref = next(row for row in client.get(f"/api/projects/{project['id']}/sources").json() if row['artifact_id'] == artifact['id'])
    chat = new_chat(client, project)
    update(client, chat, source_ids=[ref['id']])
    response = client.put('/api/artifacts/' + artifact['id'], json={'name':'概念与边界'}).json()
    assert one('SELECT name FROM sources WHERE id=?', (ref['id'],))['name'] == response['download_filename']
    assert client.delete('/api/sources/' + ref['id']).status_code == 400
    assert client.delete('/api/artifacts/' + artifact['id']).status_code == 200
    assert not path.exists() and not one('SELECT id FROM sources WHERE id=?', (ref['id'],))
    restored = client.get(f"/api/conversations/{chat['id']}?project_id={project['id']}").json()
    assert restored['source_ids'] == [] and restored['removed_source_ids'] == [ref['id']]


def test_parallel_reference_sync_creates_only_one_link(tmp_path):
    project, _, _ = setup_sources(tmp_path)
    path = artifacts_dir() / 'linked.py'
    path.write_text('print(1)', encoding='utf-8')
    artifact_id = uid()
    execute('INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?)', (artifact_id, project['id'], '[]', 'explanation', 'py', str(path), '代码', '{}', now()))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: artifact_sources.sync_project(project['id']), range(6)))
    assert len(many('SELECT * FROM artifact_sources WHERE artifact_id=?', (artifact_id,))) == 1


def test_code_package_reference_reads_all_files_without_execution(tmp_path):
    project, _, _ = setup_sources(tmp_path)
    path = artifacts_dir() / 'code.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('README.md', '# 参数与适用条件\n仅作教学')
        archive.writestr('src/main.js', 'const parameter = 2;\nconsole.log(parameter);')
        archive.writestr('notebook.ipynb', j({'cells':[{'cell_type':'markdown','source':['构造动机']},{'cell_type':'code','source':['x = 2'] }]}))
    artifact = server.add_artifact(project['id'], [], 'explanation', 'zip', '代码包', path)
    link = one('SELECT * FROM artifact_sources WHERE artifact_id=?', (artifact['id'],))
    parts = read_original_sources(server.source_records([link['source_id']], project['id']))[0]['segments']
    assert all(word in j(parts) for word in ['参数与适用条件','const parameter','构造动机','x = 2','src/main.js'])


def test_unstarted_chat_has_its_own_saved_mode(tmp_path):
    project, _, _ = setup_sources(tmp_path)
    save_settings({'learning_mode':'deep'})
    client = TestClient(server.app)
    first = new_chat(client, project)
    save_settings({'learning_mode':'overview'})
    second = new_chat(client, project)
    assert conversations.detail(first['id'], project['id'])['learning_mode'] == 'deep'
    assert conversations.detail(second['id'], project['id'])['learning_mode'] == 'overview'


def test_default_model_reading_does_not_use_old_default_cache(tmp_path, monkeypatch):
    project, _, ids = setup_sources(tmp_path)
    save_settings({'deepseek_model':'deepseek-flash'})
    client = TestClient(server.app)
    chat = client.post(f"/api/projects/{project['id']}/conversations", json={
        'provider':'deepseek', 'model':'deepseek-flash', 'model_choice':''}).json()
    update(client, chat, source_ids=ids[:1])
    class FakeAI:
        model = 'deepseek-flash'
        async def complete(self, *a, **kw): return '已通读A'
    monkeypatch.setattr(server, 'client_for', lambda *a, **kw: FakeAI())
    value = server.ReadIn(project_id=project['id'], source_ids=ids[:1], provider='deepseek', model='deepseek-flash')
    job_id = create_job(project['id'], 'read', value.model_dump())
    asyncio.run(server._read_job(job_id, value))
    url = f"/api/conversations/{chat['id']}?project_id={project['id']}"
    assert client.get(url).json()['reading']
    save_settings({'deepseek_model':'deepseek-v4-pro'})
    restored = client.get(url).json()
    assert restored['reading'] is None and restored['resolved_model'] == 'deepseek-v4-pro'
