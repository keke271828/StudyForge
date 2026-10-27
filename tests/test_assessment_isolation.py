import asyncio
import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from studyforge import server
from studyforge.ai import CodexClient, DeepSeekClient, client_for
from studyforge.agent_tools import AgentRuntime
from studyforge.config import data_dir
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid


def dialogue(tmp_path):
    project = create_project('答案隔离'); conversation = uid(); source = uid()
    path = tmp_path / 'original.txt'
    path.write_text('相关不足以证明因果。可能存在共同原因。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (source, project['id'], path.name, '.txt', str(path), 'ready', now()))
    execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)',
            (conversation, project['id'], 'deepseek', None, now(), j([source]), 'mentor-selected', None))
    execute('INSERT INTO messages VALUES (?,?,?,?,?)', (uid(), conversation, 'user', '请讲解因果。', now()))
    return server.GenerateIn(project_id=project['id'], source_ids=[source], provider='deepseek',
                             conversation_id=conversation, exercises=True, model='mentor-selected')


def transport(monkeypatch, respond):
    original = httpx.AsyncClient
    monkeypatch.setattr('studyforge.ai.get_secret', lambda key: 'test-key')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *args, **kwargs: original(transport=httpx.MockTransport(respond)))


def response(content):
    return httpx.Response(200, text='data: ' + j({'choices': [{'delta': {'content': content},
                                     'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n')


def test_actual_private_exercise_protocol_never_enters_followup_context(tmp_path, monkeypatch):
    value = dialogue(tmp_path); requests = []; states = []; hidden = 'PRIVATE_REFERENCE_ANSWER_314159'
    def respond(request):
        body = json.loads(request.content); requests.append(body)
        assert body['model'] == 'mentor-selected'
        return response(hidden if len(requests) == 2 else '# 因果\n可能存在共同原因。\n\n## 系统性总结\n相关不足以证明因果。')
    transport(monkeypatch, respond)
    async def exercises(client, project_id, source_ids, digest, title, difficulty, **kwargs):
        states.append(one('SELECT * FROM agent_dialogue_state WHERE conversation_id=?', (value.conversation_id,)))
        assert await client.complete('私有参考解核查', '请独立解题并保存参考解。') == hidden
        states.append(one('SELECT * FROM agent_dialogue_state WHERE conversation_id=?', (value.conversation_id,)))
        set_id = uid()
        execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
                (set_id, project_id, j(source_ids), title, j([{'index': 0, 'question': '为什么相关不足以证明因果？', 'topic': '因果'}]),
                 j([{'index': 0, 'solution': hidden, 'rubric': '指出共同原因'}]), difficulty, 'assigned', now()))
        return set_id, []
    monkeypatch.setattr(server, 'generate_set', exercises)
    job = create_job(value.project_id, 'generate', value.model_dump())
    asyncio.run(server._generate_job(job, value))
    result = one('SELECT * FROM jobs WHERE id=?', (job,))
    assert result['status'] == 'completed', result['error']
    assert states[0] == states[1] and states[0] is None, 'A document job must not create or mutate the public chat tool protocol'
    reply = TestClient(server.app).post('/api/chat/stream', json={'project_id': value.project_id,
        'source_ids': value.source_ids, 'conversation_id': value.conversation_id,
        'provider': 'deepseek', 'model': 'mentor-selected', 'text': '再讲解一下资料。'})
    assert '"error"' not in reply.text and len(requests) == 3
    assert hidden not in j(requests[-1])
    assert '已生成讲解文档' in j(requests[-1])
    assert hidden not in j(many('SELECT * FROM messages'))
    assert hidden in one('SELECT solutions_json FROM exercise_sets')['solutions_json']
    public = TestClient(server.app).get('/api/exercises/' + one('SELECT id FROM exercise_sets')['id'])
    assert hidden not in public.text and 'solutions' not in public.json()


def test_private_runtime_rejects_public_conversation_and_answer_file_publication(tmp_path, monkeypatch):
    value = dialogue(tmp_path); requests = []
    transport(monkeypatch, lambda request: requests.append(json.loads(request.content)) or response('private-answer'))
    runtime = AgentRuntime(value.project_id, value.source_ids, 'deepseek', conversation_id=value.conversation_id,
                           private_context=True)
    client = client_for('deepseek', agent_runtime=runtime, conversation={'id': value.conversation_id})
    assert client.conversation is None and CodexClient(agent_runtime=runtime, conversation={'id': value.conversation_id}).conversation is None
    assert asyncio.run(client.complete('批改', '学生作答')) == 'private-answer'
    assert len(requests[0]['messages']) == 2 and runtime.conversation_id is None
    assert many('SELECT * FROM agent_dialogue_state') == []
    rejected = asyncio.run(runtime.execute('sf_write_text', j({'path': 'answers.txt', 'text': 'private-answer'})))
    assert rejected['type'] == 'PermissionError' and not (runtime.workspace / 'answers.txt').exists()
    assert one('SELECT conversation_id FROM agent_tool_events')['conversation_id'] is None


def test_legacy_unversioned_protocol_is_migrated_without_restoring_private_answers(monkeypatch):
    path = data_dir() / 'studyforge.sqlite3'; project = uid(); conversation = uid()
    with sqlite3.connect(path) as database:
        database.executescript('''
            CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE conversations(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,provider TEXT NOT NULL,
              remote_thread_id TEXT,created_at TEXT NOT NULL,source_ids_json TEXT NOT NULL,model TEXT,reasoning_effort TEXT);
            CREATE TABLE agent_dialogue_state(conversation_id TEXT PRIMARY KEY,published_count INTEGER NOT NULL,
              messages_json TEXT NOT NULL,updated_at TEXT NOT NULL);
        ''')
        database.execute('INSERT INTO projects VALUES (?,?,?)', (project, '旧版数据', now()))
        database.execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)',
                         (conversation, project, 'deepseek', None, now(), '[]', 'test-model', None))
        database.execute('INSERT INTO agent_dialogue_state VALUES (?,?,?,?)',
                         (conversation, 0, j([{'role': 'assistant', 'content': 'LEGACY_PRIVATE_ANSWER'}]), now()))
    assert one('SELECT protocol_version FROM agent_dialogue_state')['protocol_version'] == 0
    execute('INSERT INTO messages VALUES (?,?,?,?,?)', (uid(), conversation, 'user', '保留的公开聊天', now()))
    requests = []
    transport(monkeypatch, lambda request: requests.append(json.loads(request.content)) or response('新回复'))
    client = DeepSeekClient('test-model', AgentRuntime(project, provider='deepseek', conversation_id=conversation))
    async def run():
        return [event async for event in client.agent_stream([{'role': 'system', 'content': '导师'},
                     {'role': 'user', 'content': '保留的公开聊天'}, {'role': 'user', 'content': '继续'}])]
    asyncio.run(run())
    assert 'LEGACY_PRIVATE_ANSWER' not in j(requests) and '保留的公开聊天' in j(requests)
    assert one('SELECT content FROM messages')['content'] == '保留的公开聊天'
    assert one('SELECT protocol_version FROM agent_dialogue_state')['protocol_version'] == 1


@pytest.mark.parametrize('provider', ['codex', 'deepseek'])
@pytest.mark.parametrize('entry', ['quiz', 'feynman', 'extract', 'coding_generate', 'coding_submit'])
def test_selected_model_and_effort_reach_each_assessment_entry(tmp_path, monkeypatch, provider, entry):
    project = create_project('模型传递'); set_id = uid(); calls = []; validated = []
    source = uid(); original = tmp_path / 'functions.txt'; original.write_text('函数 add 返回两数之和。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (source, project['id'], original.name, '.txt', str(original), 'ready', now()))
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)', (set_id, project['id'], '[]', '练习',
            j([{'index': 0, 'question': '定义 add(a,b)', 'topic': '函数', 'language': 'javascript'}]),
            j([{'index': 0, 'solution': 'a+b', 'rubric': '求和'}]), 1, 'assigned', now()))
    async def validate(model, effort): validated.append((model, effort))
    monkeypatch.setattr(server.model_catalog, 'validate_effort', validate)
    async def stream(self, prompt, remote_thread_id=None, model=None, effort=None, **kwargs):
        calls.append((model, effort, kwargs['agent_runtime']))
        yield 'final', '{"answers":["a+b"],"uncertainties":[]}'
    monkeypatch.setattr('studyforge.codex_bridge.CodexBridge.stream_turn', stream)
    transport(monkeypatch, lambda request: calls.append((json.loads(request.content)['model'], None, None))
              or response('{"answers":["a+b"],"uncertainties":[]}'))
    async def grade(client, *args):
        await client.complete('核对', '作答')
        return {'score': 85, 'passed': False}
    async def digest(client, records): return '原资料：函数求和。', []
    async def assignment(client, *args):
        await client.complete('出题', '函数求和')
        return set_id, []
    monkeypatch.setattr(server, 'grade_submission', grade)
    monkeypatch.setattr(server, 'grade_feynman', grade)
    monkeypatch.setattr(server, 'grade_code', grade)
    monkeypatch.setattr(server, 'source_digest', digest)
    monkeypatch.setattr(server, 'create_assignment', assignment)
    selected = {'provider': provider, 'model': 'chosen-assessment', 'reasoning_effort': 'high' if provider == 'codex' else None}
    api = TestClient(server.app)
    if entry == 'quiz': result = api.post(f'/api/exercises/{set_id}/submit', json=selected | {'answers': ['a+b']})
    elif entry == 'feynman': result = api.post(f'/api/exercises/{set_id}/feynman', json=selected | {'explanation': '解释函数'})
    elif entry == 'extract': result = api.post(f'/api/exercises/{set_id}/extract-answers',
            data={key: value for key, value in selected.items() if value}, files={'file': ('answers.txt', b'a+b')})
    elif entry == 'coding_generate': result = api.post('/api/coding/generate', json=selected | {
            'project_id': project['id'], 'source_ids': [source], 'language': 'javascript'})
    else: result = api.post(f'/api/coding/{set_id}/submit', data={key: value for key, value in selected.items() if value},
                           files={'file': ('answer.js', b'function add(a,b){return a+b;}')})
    assert result.status_code == 200, result.text
    assert len(calls) == 1 and calls[0][:2] == ('chosen-assessment', selected['reasoning_effort'])
    if provider == 'codex':
        assert validated == [('chosen-assessment', 'high')]
        assert calls[0][2].private_context and calls[0][2].conversation_id is None
    else: assert validated == [], 'DeepSeek must never probe Codex models'


def test_deepseek_assessment_rejects_codex_effort_before_any_network_call(monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('不应调用任何模型')
    monkeypatch.setattr(server, 'client_for', forbidden)
    with pytest.raises(ValueError, match='仅支持 Codex'):
        asyncio.run(server.assessment_client('deepseek', 'chosen', 'high'))


def test_legacy_advanced_exercise_metadata_cannot_reveal_solutions(tmp_path):
    project = create_project('旧进阶习题'); path = tmp_path / 'exercise.docx'; path.write_bytes(b'public questions')
    server.add_artifact(project['id'], [], 'exercise', 'docx', '进阶习题', path,
        {'reviews': [{'stage': '独立解题', 'result': {'answers': [{'solution': 'PRIVATE_OLD_SOLUTION'}]}}],
         'exercise_set_id': 'example'})
    result = TestClient(server.app).get(f"/api/projects/{project['id']}/artifacts")
    assert result.status_code == 200 and 'PRIVATE_OLD_SOLUTION' not in result.text
    assert result.json()[0]['metadata']['exercise_set_id'] == 'example'
