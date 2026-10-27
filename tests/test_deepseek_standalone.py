import asyncio
import json

import httpx
import pytest
from docx import Document
from fastapi.testclient import TestClient

from studyforge import server
from studyforge.ai import DeepSeekClient, client_for, save_settings
from studyforge.agent_tools import AgentRuntime
from studyforge.codex_bridge import CodexBridge
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid, unj, update_job


def install_transport(monkeypatch, respond):
    original = httpx.AsyncClient
    monkeypatch.setattr('studyforge.ai.get_secret', lambda key: 'test-key')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(transport=httpx.MockTransport(respond)))


def sse(delta, finish='stop', *, space=True):
    packet = {'id': 'request-test', 'choices': [{'delta': delta, 'finish_reason': finish}]}
    return httpx.Response(200, text=('data: ' if space else 'data:') + j(packet) +
                          '\n\ndata: {"choices":[],"usage":{"total_tokens":2}}\n\ndata:[DONE]\n\n',
                          headers={'content-type': 'text/event-stream'})


def collect(client):
    async def run():
        return [event async for event in client.agent_stream([{'role': 'system', 'content': '导师'},
                                                             {'role': 'user', 'content': '解释原文'}])]
    return asyncio.run(run())


@pytest.mark.parametrize('first_finish', ['stop', 'aborted', 'insufficient_system_resource', None])
def test_stream_recovers_empty_or_interrupted_reply_once(monkeypatch, first_finish):
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return sse({'reasoning_content': 'private-thought', 'content': '半截文字' if first_finish != 'stop' else ''}, first_finish)
        return sse({'content': '完整讲解。'}, space=False)
    install_transport(monkeypatch, respond)
    events = collect(DeepSeekClient('same-deepseek'))
    assert events[-1] == ('final', '完整讲解。')
    assert ('replace', '') in events and any(kind == 'status' for kind, _ in events)
    assert len(requests) == 2 and requests[0] == requests[1]
    assert not any('private-thought' in str(value) for kind, value in events)


def test_nonstream_reasoning_only_response_retries_without_publishing_reasoning(monkeypatch):
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
            'reasoning_content': 'private-thought', 'content': '' if len(requests) == 1 else '有效正文'}}]})
    install_transport(monkeypatch, respond)
    assert asyncio.run(DeepSeekClient('same-deepseek').complete('规则', '原文')) == '有效正文'
    assert len(requests) == 2 and requests[0] == requests[1]


@pytest.mark.parametrize('status, expected', [(401, '密钥无效'), (402, '账户余额不足'), (404, '模型或接口不存在'), (429, '请求过于频繁')])
@pytest.mark.parametrize('streaming', [True, False])
def test_http_failure_identifies_cause_model_and_request_without_retry(monkeypatch, status, expected, streaming):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json={'error': {'message': 'service-error'}}, headers={'x-request-id': 'specific-request'})
    install_transport(monkeypatch, respond)
    with pytest.raises(RuntimeError, match='selected-model.*' + expected + '.*specific-request'):
        if streaming: collect(DeepSeekClient('selected-model'))
        else: asyncio.run(DeepSeekClient('selected-model').complete('规则', '问题'))
    assert len(requests) == 1


@pytest.mark.parametrize('exception', [httpx.ConnectError, httpx.ReadTimeout])
def test_empty_transport_error_reports_cause_instead_of_blank_network_failure(monkeypatch, exception):
    requests = []
    def respond(request):
        requests.append(request); raise exception('', request=request)
    install_transport(monkeypatch, respond)
    with pytest.raises(RuntimeError, match='selected-model.*(网络连接失败|请求超时).*自动重试一次.*没有生成空文档'):
        collect(DeepSeekClient('selected-model'))
    assert len(requests) == 2


@pytest.mark.parametrize('finish', ['length', 'content_filter'])
def test_truncation_and_service_refusal_are_not_retried_or_exported(monkeypatch, finish):
    requests = []
    def respond(request):
        requests.append(request)
        return sse({'content': '未完成正文'}, finish)
    install_transport(monkeypatch, respond)
    with pytest.raises(RuntimeError, match='长度上限|拒绝'):
        collect(DeepSeekClient('test'))
    assert len(requests) == 1 and many('SELECT * FROM artifacts') == []


def test_persistent_empty_response_reports_model_and_retry_without_blank_document(monkeypatch):
    requests = []
    def respond(request):
        requests.append(request)
        return sse({'reasoning_content': 'private-thought'})
    install_transport(monkeypatch, respond)
    with pytest.raises(RuntimeError, match='only-deepseek.*没有正文.*request-test.*自动重试一次'):
        collect(DeepSeekClient('only-deepseek'))
    assert len(requests) == 2 and many('SELECT * FROM artifacts') == []


def test_completed_tool_is_not_repeated_when_next_model_reply_is_empty(monkeypatch):
    requests = []
    def respond(request):
        body = json.loads(request.content); requests.append(body)
        if len(requests) == 1:
            assert 'tool_choice' not in body
            return sse({'reasoning_content': 'private-thought', 'tool_calls': [{'index': 0, 'id': 'write-1',
                'function': {'name': 'sf_write_text', 'arguments': j({'path': 'once.txt', 'text': '一次'})}}]}, 'tool_calls')
        if len(requests) == 2: return sse({'content': ''})
        return sse({'content': '文件已写入。'})
    install_transport(monkeypatch, respond)
    runtime = AgentRuntime(provider='deepseek')
    assert collect(DeepSeekClient('test', agent_runtime=runtime))[-1] == ('final', '文件已写入。')
    assert len(many('SELECT * FROM agent_tool_events')) == 1
    assert requests[1] == requests[2] and requests[2]['messages'][-1]['role'] == 'tool'
    assert requests[2]['messages'][-2]['content'] == ''
    assert (runtime.workspace / 'once.txt').read_text(encoding='utf-8') == '一次'


def test_interrupted_tool_call_never_executes_before_confirmed_completion(monkeypatch):
    requests = []
    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return sse({'tool_calls': [{'index': 0, 'id': 'unconfirmed', 'function': {
                'name': 'sf_write_text', 'arguments': j({'path': 'bad.txt', 'text': '不要写入'})}}]}, None)
        return sse({'content': '已重新生成正文。'})
    install_transport(monkeypatch, respond)
    runtime = AgentRuntime(provider='deepseek')
    collect(DeepSeekClient('test', agent_runtime=runtime))
    assert not (runtime.workspace / 'bad.txt').exists()
    assert many('SELECT * FROM agent_tool_events') == []


def test_stream_request_can_accept_json_reply_and_recover_broken_packet(monkeypatch):
    requests = []
    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, text='data: {invalid\n\n', headers={'content-type': 'text/event-stream'})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '有效正文'}}]})
    install_transport(monkeypatch, respond)
    assert collect(DeepSeekClient('test'))[-1] == ('final', '有效正文')
    assert len(requests) == 2


def test_provider_defaults_follow_settings_for_every_entry_and_mcp(monkeypatch):
    save_settings({'chat_provider': 'deepseek'})
    monkeypatch.setattr('studyforge.ai.get_secret', lambda key: 'test-key')
    for model, args in [(server.ChatIn, {'project_id': 'p', 'text': '提问'}),
                        (server.ReadIn, {'project_id': 'p', 'source_ids': ['s']}),
                        (server.GenerateIn, {'project_id': 'p', 'source_ids': ['s']}),
                        (server.CodingIn, {'project_id': 'p', 'source_ids': ['s']}),
                        (server.SubmitIn, {'answers': ['回答']}),
                        (server.FeynmanIn, {'explanation': '解释'})]:
        assert model(**args).provider == 'deepseek'
    from studyforge.mcp_server import grading_client
    assert isinstance(asyncio.run(grading_client()), DeepSeekClient)
    assert isinstance(client_for(), DeepSeekClient)
    save_settings({'chat_provider': 'codex'})
    monkeypatch.setattr('studyforge.ai.shutil.which', lambda name: None)
    assert server.ChatIn(project_id='p', text='提问').provider == 'deepseek'
    assert server.ChatIn(project_id='p', text='提问', provider='codex').provider == 'codex'


def test_deepseek_entire_learning_flow_never_calls_codex(tmp_path, monkeypatch):
    save_settings({'chat_provider': 'deepseek', 'deepseek_model': 'standalone-model'})
    codex_attempts = []
    async def forbidden(*args, **kwargs):
        codex_attempts.append(True)
        raise AssertionError('DeepSeek 模式不得请求 Codex')
    monkeypatch.setattr(CodexBridge, 'start', forbidden)
    monkeypatch.setattr(server.model_catalog, 'get_models', forbidden)
    monkeypatch.setattr(server.model_catalog, 'validate_effort', forbidden)
    monkeypatch.setattr('studyforge.ai.shutil.which', lambda name: None)
    requests = []
    def respond(request):
        body = json.loads(request.content); requests.append(body)
        assert body['model'] == 'standalone-model'
        return sse({'content': '# 相关与因果\n共同变化不足以证明因果。[资料｜原文]\n\n## 系统性总结\n要排除共同原因。'})
    install_transport(monkeypatch, respond)
    project = create_project('DeepSeek 独立学习'); source = uid(); original = tmp_path / '资料.txt'
    original.write_text('相关不能证明因果。共同原因可能导致二者一起变化。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (source, project['id'], original.name, '.txt', str(original), '[]', 'ready', now()))
    async def run():
        read = server.ReadIn(project_id=project['id'], source_ids=[source])
        await server.choose_generation_model(read)
        job = create_job(project['id'], 'read', read.model_dump())
        await server._read_job(job, read)
        assert one('SELECT status FROM jobs WHERE id=?', (job,))['status'] == 'completed'
        response = await server.chat_stream(server.ChatIn(project_id=project['id'], text='解释共同原因', source_ids=[source]))
        events = [json.loads(line) async for line in response.body_iterator]
        assert not [event for event in events if event['type'] == 'error']
        conversation = next(event['value'] for event in events if event['type'] == 'conversation')
        value = server.GenerateIn(project_id=project['id'], source_ids=[source], conversation_id=conversation)
        result = await server.generate(value)
        for _ in range(300):
            row = one('SELECT * FROM jobs WHERE id=?', (result['job_id'],))
            if row['status'] in ('completed', 'failed'): break
            await asyncio.sleep(.01)
        assert row['status'] == 'completed', row['error']
        assert row['error'] is None
        assert one('SELECT remote_thread_id FROM conversations WHERE id=?', (conversation,))['remote_thread_id'] is None
    asyncio.run(run())
    assert codex_attempts == [], '即使其他代码捕获了异常，也不允许尝试调用 Codex'
    doc = Document(one("SELECT path FROM artifacts WHERE kind='explanation'")['path'])
    assert '共同原因' in '\n'.join(paragraph.text for paragraph in doc.paragraphs)
    assert len(requests) == 3
    health = TestClient(server.app).get('/api/health').json()
    assert health['ok'] and not health['codex_required'] and not health['codex_available']


def test_default_media_tool_uses_deepseek_without_codex(monkeypatch):
    from PIL import Image
    save_settings({'chat_provider': 'deepseek', 'deepseek_vision_model': 'deepseek-vision-probe'})
    codex_attempts, requests = [], []
    async def forbidden(*args, **kwargs):
        codex_attempts.append(True)
        raise AssertionError('不得读取 Codex 图片模型')
    monkeypatch.setattr(CodexBridge, 'start', forbidden)
    def respond(request):
        body = json.loads(request.content); requests.append(body)
        assert body['model'] == 'deepseek-vision-probe'
        assert body['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '已读取原图。'}}]})
    install_transport(monkeypatch, respond)
    runtime = AgentRuntime()
    image = runtime.workspace / '原图.png'; Image.new('RGB', (20, 20), 'white').save(image)
    result = asyncio.run(runtime.execute('sf_inspect_media', {'path': str(image), 'question': '读取原图'}))
    assert runtime.provider == 'deepseek' and result['description'] == '已读取原图。'
    assert len(requests) == 1 and codex_attempts == []


def test_generation_retry_is_visible_without_resetting_stage_progress_or_pause(monkeypatch):
    project = create_project('重试进度'); job = create_job(project['id'], 'generate', {})
    update_job(job, 'pausing', 53, {'stage': '撰写系统讲解', 'pause_requested': True})
    requests, snapshots = [], []
    def respond(request):
        requests.append(request)
        return sse({'content': '' if len(requests) == 1 else '完整讲解。'})
    install_transport(monkeypatch, respond)
    runtime = AgentRuntime(provider='deepseek', job_id=job)
    client = DeepSeekClient('test', agent_runtime=runtime)
    async def run():
        async for kind, value in client.agent_stream([{'role': 'system', 'content': '讲解'}, {'role': 'user', 'content': '原文'}]):
            if kind == 'status':
                snapshots.append(TestClient(server.app).get(f"/api/projects/{project['id']}/jobs").json()[0])
    asyncio.run(run())
    assert len(snapshots) == 1 and '自动重试' in snapshots[0]['request_status']
    assert snapshots[0]['stage'] == '撰写系统讲解' and snapshots[0]['progress'] == 53
    assert snapshots[0]['status'] == 'pausing'
    row = one('SELECT * FROM jobs WHERE id=?', (job,))
    assert 'request_status' not in unj(row['result_json']) and unj(row['result_json'])['pause_requested']
    assert row['status'] == 'pausing' and row['progress'] == 53


def test_import_quiz_feynman_coding_and_mcp_work_without_codex(tmp_path, monkeypatch):
    from studyforge import exercises, mcp_server
    save_settings({'chat_provider': 'deepseek', 'deepseek_model': 'standalone-assessment'})
    codex_attempts, requests = [], []
    async def forbidden(*args, **kwargs):
        codex_attempts.append(True)
        raise AssertionError('独立批改流程不得尝试调用 Codex')
    monkeypatch.setattr(CodexBridge, 'start', forbidden)
    monkeypatch.setattr(server.model_catalog, 'get_models', forbidden)
    monkeypatch.setattr(server.model_catalog, 'validate_effort', forbidden)
    original_which = server.shutil.which
    monkeypatch.setattr(server.shutil, 'which', lambda name: None if name == 'codex' else original_which(name))
    # The external search can fail independently; original question generation
    # must still work. Docker is unnecessary for the JavaScript static review.
    async def no_sources(*args): return []
    monkeypatch.setattr(exercises, 'search_exercises', no_sources)
    questions = [{'question': f'第{i+1}题：相关为什么不能证明因果？', 'solution': '可能有共同原因',
                  'rubric': '指出共同原因', 'topic': '因果推理', 'source_url': ''} for i in range(4)]
    approved = {'passed': True, 'blocking_issues': [], 'issues': [], 'notes': []}
    sequence = iter([
        {'answers': ['可能有共同原因'], 'uncertainties': []},
        {'scores': [79], 'feedback': ['需补充证据'], 'uncertainties': []},
        {'scores': [79], 'feedback': ['复核需补充证据'], 'uncertainties': []},
        {'score': 80, 'passed': True, 'feedback': '概念解释清楚', 'gaps': []},
        {'questions': questions},
        {'answers': [{'index': i, 'solution': '可能有共同原因', 'issues': []} for i in range(4)]},
        {'passed': True, 'issues': []}, {'passed': True, 'issues': []},
        {'title': '加法函数', 'problem': '定义 add(a,b)，合法输入为有限实数，返回两数之和。',
         'starter_code': 'function add(a,b) {}', 'reference_code': 'function add(a,b) { return a+b; }',
             'test_code': 'const {test}=require("node:test"); const assert=require("node:assert/strict"); '
                          'const {add}=require("./solution"); test("positive",()=>assert.equal(add(2,3),5)); '
                          'test("zero",()=>assert.equal(add(0,0),0)); test("negative",()=>assert.equal(add(-2,3),1));', 'topic': '函数与参数'},
        {'approach': '相加后返回', 'edge_cases': [], **approved}, approved, approved,
        {'score': 90, 'feedback': '实现正确，尚未运行', 'issues': []},
        {'scores': [80] * 4, 'feedback': ['完整'] * 4, 'uncertainties': []},
        {'scores': [80] * 4, 'feedback': ['复核完整'] * 4, 'uncertainties': []},
    ])
    def respond(request):
        body = json.loads(request.content); requests.append(body)
        expected_models = ['extract-selected', 'quiz-selected', 'quiz-selected'] + ['feynman-selected'] * 5 + ['coding-selected'] * 4 + ['code-grade-selected'] + ['mcp-selected'] * 2
        assert body['model'] == expected_models[len(requests) - 1]
        return sse({'content': j(next(sequence))})
    install_transport(monkeypatch, respond)
    project = create_project('独立学习与批改'); set_id = uid()
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)', (set_id, project['id'], '[]', '因果推理',
        j([{'index': 0, 'question': '相关为什么不足以证明因果？', 'topic': '因果推理'}]),
        j([{'index': 0, 'solution': '可能有共同原因', 'rubric': '指出共同原因'}]), 1, 'assigned', now()))
    with TestClient(server.app) as api:
        imported = api.post('/api/import/file', data={'project_id': project['id'], 'parse_immediately': 'true'},
            files={'file': ('资料.txt', '相关不等于因果。共同原因可能导致一起变化。编程函数 add 返回参数之和。'.encode())})
        assert imported.status_code == 200
        source = imported.json()['source_id']
        for _ in range(100):
            if api.get(f'/api/sources/{source}').json()['status'] == 'ready': break
        assert one('SELECT status FROM sources WHERE id=?', (source,))['status'] == 'ready'
        execute('UPDATE exercise_sets SET source_ids_json=? WHERE id=?', (j([source]), set_id))
        assert 'solutions' not in api.get(f'/api/exercises/{set_id}').json()
        answers = api.post(f'/api/exercises/{set_id}/extract-answers', data={'model': 'extract-selected'}, files={'file': ('答案.txt', '可能有共同原因'.encode())})
        assert answers.status_code == 200, answers.text
        graded = api.post(f'/api/exercises/{set_id}/submit', json={'answers': answers.json()['answers'], 'model': 'quiz-selected'})
        assert graded.status_code == 200 and graded.json()['score'] == 79
        assert graded.json()['requires_feynman'] and 'solutions' in api.get(f'/api/exercises/{set_id}').json()
        feynman = api.post(f'/api/exercises/{set_id}/feynman', json={'explanation': '相关表示一起变化，可能存在影响二者的共同原因，需要证据排除其他解释。'*4, 'model': 'feynman-selected'})
        assert feynman.status_code == 200, feynman.text
        advanced = feynman.json()['next_set']
        assert feynman.json()['passed'] and advanced['difficulty'] == 2 and 'solutions' not in advanced
        coding = api.post('/api/coding/generate', json={'project_id': project['id'], 'source_ids': [source], 'language': 'javascript', 'model': 'coding-selected'})
        assert coding.status_code == 200, coding.text
        code = api.post(f"/api/coding/{coding.json()['id']}/submit", data={'model': 'code-grade-selected'}, files={'file': ('solution.js', b'function add(a,b) { return a+b; }')})
        assert code.status_code == 200 and code.json()['provisional'] and code.json()['static_score'] == 90
        assert code.json()['score'] is None
        mcp_grade = asyncio.run(mcp_server.submit_answers(advanced['id'], ['可能有共同原因']*4, model='mcp-selected'))
        assert mcp_grade['score'] == 80 and not mcp_grade['requires_feynman']
        assert api.get('/api/profile').json()
    assert codex_attempts == [] and len(requests) == 15
