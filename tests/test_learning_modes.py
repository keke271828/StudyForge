import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from studyforge import ai, server
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid
from studyforge.generation_control import control_for
from studyforge.learning_modes import MODE_LABELS, MODE_FEATURES, mode_structure, resolve_mode, save_conversation_mode
from studyforge.review import review_explanation
from studyforge.teaching import finish_explanation


def material(tmp_path):
    project = create_project('多学科学习'); source = uid()
    original = tmp_path / '论证.txt'
    original.write_text('开头定义：论证由前提支持结论。\n关键条件：不能把类比当作因果证明。\n末尾限制：来源不足时保留疑问。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (source, project['id'], original.name, '.txt', str(original), j([{'locator': '旧预览', 'text': '不能代替全文的摘要'}]), 'ready', now()))
    return project['id'], source


def cloud(monkeypatch):
    ai.save_settings({'chat_provider': 'deepseek', 'deepseek_model': 'chosen-model', 'background_learning_enabled': False,
                      'agent_network_enabled': False, 'agent_web_video_enabled': False})
    monkeypatch.setattr(ai, 'get_secret', lambda key: 'test-key')
    calls = []; real_client = httpx.AsyncClient
    def reply(request):
        assert request.url.host == 'api.deepseek.com', '模式不能自动触发网页访问'
        body = json.loads(request.content); calls.append(body)
        return httpx.Response(200, text='data: ' + j({'choices': [{'delta': {'content':
            '# 论证\n前提支持结论，类比不等于因果证明。[来源：论证.txt｜第 1 段]\n\n## 系统性总结\n区分证据与主张，保留来源不足的疑问。'},
            'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **k: real_client(transport=httpx.MockTransport(reply)))
    return calls


async def generate_and_wait(value):
    result = await server.generate(value)
    for _ in range(200):
        row = one('SELECT * FROM jobs WHERE id=?', (result['job_id'],))
        if row['status'] in ('completed', 'failed'):
            assert row['status'] == 'completed', row['error']
            return result, json.loads(row['payload_json'])
        await asyncio.sleep(.01)
    raise AssertionError('生成没有结束')


@pytest.mark.parametrize('mode', ['overview', 'deep', 'research'])
@pytest.mark.parametrize('level', [1, 5])
def test_deepseek_lecture_uses_shared_mode_full_original_and_independent_controls(tmp_path, monkeypatch, mode, level):
    project, source = material(tmp_path); calls = cloud(monkeypatch)
    result, payload = asyncio.run(generate_and_wait(server.GenerateIn(
        project_id=project, source_ids=[source], provider='deepseek', model='chosen-model', learning_mode=mode,
        summary_level=level, exercises=False, review_mode='express', instructions='只用原资料，用两段话说明主线。')))
    assert len(calls) == 1, '模式不得额外调用审查或自动出题'
    assert calls[0]['model'] == 'chosen-model'
    prompt = j(calls[0]['messages'])
    assert f'当前学习模式：{MODE_LABELS[mode]}' in prompt
    assert all(text in prompt for text in ['开头定义', '关键条件', '末尾限制', '只用原资料', '两段话'])
    assert '不能代替全文的摘要' not in prompt
    assert '模式控制教学目标' in prompt and '模式不授权新的联网' in prompt
    request = calls[0]['messages'][-1]['content']
    assert mode_structure(mode) in request, '三种模式须实际改变默认组织，不能只改标题'
    assert f'本次{MODE_LABELS[mode]}教学重点' in request
    assert request.index(f'本次{MODE_LABELS[mode]}教学重点') > request.index('末尾限制')
    assert '本次只需读懂并了解原文' not in request, '未勾选出题不能将精学和研究降为概览'
    assert '不生成习题；讲解深度仍遵循当前学习模式' in request
    assert payload['learning_mode'] == mode and payload['summary_level'] == level and payload['exercises'] is False
    assert payload['review_mode'] == 'express' and payload['dialogue_snapshot']['mentor']['learning_mode'] == mode
    metadata = json.loads(one("SELECT metadata_json FROM artifacts WHERE kind='explanation'")['metadata_json'])
    assert metadata['learning_mode'] == mode and metadata['summary_level'] == level
    assert resolve_mode(conversation_id=result['conversation_id']) == mode
    assert len(many('SELECT * FROM artifacts')) == 1 and many('SELECT * FROM exercise_sets') == []


@pytest.mark.parametrize('provider', ['codex', 'deepseek'])
def test_chat_mode_changes_keep_same_conversation_and_omitted_mode_inherits(tmp_path, monkeypatch, provider):
    project, source = material(tmp_path); calls = cloud(monkeypatch)
    codex_calls = []
    async def stream(prompt, remote=None, model=None, effort=None, **kwargs):
        codex_calls.append((prompt, remote, model, kwargs['fallback_history']))
        yield 'thread', 'same-private-thread'
        yield 'final', '已解释当前材料。'
    monkeypatch.setattr('studyforge.codex_bridge.CodexBridge.stream_turn',lambda self,*args,**kwargs:stream(*args,**kwargs))
    api = TestClient(server.app); conversation = None
    for mode, expected in [('overview', '概览'), ('research', '研究'), (None, '研究')]:
        body = dict(project_id=project, source_ids=[source], provider=provider, model='chosen-model',
                    conversation_id=conversation, text='只用原资料简短说明，不要出题。')
        if mode: body['learning_mode'] = mode
        response = api.post('/api/chat/stream', json=body)
        assert response.status_code == 200 and '"error"' not in response.text
        events = [json.loads(line) for line in response.text.splitlines()]
        next_id = next(row['value'] for row in events if row['type'] == 'conversation')
        if conversation: assert next_id == conversation
        conversation = next_id
        prompt = codex_calls[-1][0] if provider == 'codex' else j(calls[-1]['messages'])
        assert f'当前学习模式：{expected}' in prompt and '末尾限制' in prompt
        current_request = codex_calls[-1][0] if provider == 'codex' else calls[-1]['messages'][-1]['content']
        assert f'当前学习模式：{expected}' in prompt
        assert f'本次{expected}教学重点' not in current_request
        assert current_request.endswith('只用原资料简短说明，不要出题。')
    assert len(many('SELECT * FROM conversations')) == 1 and len(many('SELECT * FROM messages')) == 6
    assert many('SELECT * FROM exercise_sets') == []
    if provider == 'codex':
        assert codex_calls[1][1] == 'same-private-thread' and codex_calls[1][2] == 'chosen-model'
        assert '只用原资料' in codex_calls[1][3]


def test_questionnaire_supplement_restores_original_lecture_mode(tmp_path, monkeypatch):
    project, source = material(tmp_path); calls = cloud(monkeypatch)
    result, _ = asyncio.run(generate_and_wait(server.GenerateIn(
        project_id=project, source_ids=[source], provider='deepseek', learning_mode='overview')))
    save_conversation_mode(result['conversation_id'], 'research')
    api = TestClient(server.app)
    q = api.get('/api/lesson-feedback/by-job/' + result['job_id']).json()
    assert api.get(f"/api/lesson-feedback/{q['id']}/dialogue").json()['learning_mode'] == 'overview'
    api.post(f"/api/lesson-feedback/{q['id']}/submit", json={'difficulties': ['motivation'], 'other_text': '请详细讲这个构造，不要出题。'})
    response = api.post(f"/api/lesson-feedback/{q['id']}/followup")
    assert response.status_code == 200 and '"error"' not in response.text
    prompt = j(calls[-1]['messages'])
    assert '当前学习模式：概览' in prompt and '请详细讲这个构造' in prompt
    assert '学生本次明确的篇幅' in prompt and len(calls) == 2
    assert many('SELECT * FROM exercise_sets') == [] and many('SELECT * FROM mastery') == []


def test_restart_resume_keeps_job_mode_and_reuses_finished_model_step(tmp_path, monkeypatch):
    project, source = material(tmp_path)
    conversation = uid()
    execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)', (conversation, project, 'deepseek', None, now(), j([source]), 'chosen-model', None))
    value = server.GenerateIn(project_id=project, source_ids=[source], provider='deepseek', model='chosen-model',
                              conversation_id=conversation, learning_mode='overview')
    job = create_job(project, 'generate', value.model_dump()); calls = []
    class Client:
        model = 'chosen-model'
        async def complete(self, system, user, **kwargs):
            calls.append((system, user)); control_for(job).pause()
            return '# 论证\n前提支持结论。\n\n## 系统性总结\n保留条件。'
    monkeypatch.setattr(server, 'client_for', lambda *a, **k: Client())
    async def run():
        task = asyncio.create_task(server._generate_job(job, value))
        for _ in range(200):
            if one('SELECT status FROM jobs WHERE id=?', (job,))['status'] == 'paused': break
            await asyncio.sleep(.01)
        else: raise AssertionError('未进入暂停')
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        save_conversation_mode(conversation, 'research')
        # A process restart reloads only the saved payload. Changing the current
        # conversation must not change that task or its cached model signature.
        restored = server.GenerateIn(**json.loads(one('SELECT payload_json FROM jobs WHERE id=?', (job,))['payload_json']))
        control_for(job).resume(); await server._generate_job(job, restored)
    asyncio.run(run())
    assert one('SELECT status FROM jobs WHERE id=?', (job,))['status'] == 'completed'
    assert len(calls) == 1 and '当前学习模式：概览' in calls[0][0]
    assert json.loads(one('SELECT metadata_json FROM artifacts')['metadata_json'])['learning_mode'] == 'overview'


def test_revision_and_missing_summary_keep_mode_without_expanding_review_count():
    calls = []
    class Client:
        async def complete(self, system, user, **kwargs):
            calls.append((system, user))
            if kwargs.get('json_mode'): return j({'passed': False, 'issues': [{'location': '定义', 'problem': '需纠正', 'evidence': '原文'}]})
            if '只补写整篇文章' in system: return '## 系统性总结\n原文的条件与结论。'
            return '# 简明概览\n保留关键定义。'
    async def run():
        doc, reports = await review_explanation(Client(), '完整原文', '原讲解', mode='balanced', learning_mode='overview')
        assert len(reports) == 2
        return await finish_explanation(Client(), doc, learning_mode='overview')
    assert '系统性总结' in asyncio.run(run()) and len(calls) == 3
    assert all('当前学习模式：概览' in system for system, _ in calls)


def test_default_mode_invalid_input_and_legacy_conversation_compatibility():
    project = create_project('旧对话'); cid = uid()
    execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)', (cid, project['id'], 'deepseek', None, now(), '[]', None, None))
    assert resolve_mode(conversation_id=cid) == 'deep'
    ai.save_settings({'learning_mode': 'overview'})
    assert resolve_mode() == 'overview'
    api = TestClient(server.app)
    for endpoint, body in [('/api/chat/stream', {'text': '你好'}), ('/api/generate', {'source_ids': []})]:
        response = api.post(endpoint, json={'project_id': project['id'], 'provider': 'deepseek', 'learning_mode': 'invalid', **body})
        assert response.status_code == 422
    assert many('SELECT * FROM jobs') == [] and many('SELECT * FROM messages') == []


def test_readonly_mode_guide_uses_actual_policy_without_model_calls(monkeypatch):
    def unexpected(*args, **kwargs): raise AssertionError('模式说明不需要调用模型或改变设置')
    monkeypatch.setattr(server, 'client_for', unexpected)
    before = ai.settings()
    response = TestClient(server.app).get('/api/learning-modes')
    assert response.status_code == 200
    values = response.json()['modes']
    assert set(values) == set(MODE_LABELS)
    for mode, feature in values.items():
        assert feature['label'] == MODE_LABELS[mode] and feature['structure'] == mode_structure(mode)
        assert feature['checks'] == MODE_FEATURES[mode]['checks']
    assert len({feature['aim'] for feature in values.values()}) == 3
    assert ai.settings() == before and many('SELECT * FROM jobs') == []
