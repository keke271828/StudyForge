import asyncio
import json

from fastapi.testclient import TestClient

from studyforge import server
from studyforge.ai import CodexClient
from studyforge.codex_bridge import CodexBridge
from studyforge.agent_tools import AgentRuntime
from studyforge.teaching import REASONING_TEACHING_RULES, TEACHING_TASK_REMINDER
from studyforge.learning_modes import mode_task_reminder
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid


def setup_dialogue(tmp_path, provider='codex'):
    project = create_project('统一导师'); source, conversation = uid(), uid()
    path = tmp_path/'original.txt'; path.write_text('相关不能推出因果。尾部论据：实验也有外部效度限制。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (source, project['id'], path.name, '.txt', str(path), '[]', 'ready', now()))
    execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)',
            (conversation, project['id'], provider, 'same-thread' if provider=='codex' else None, now(), j([source]), 'same-model', 'high' if provider=='codex' else None))
    execute('INSERT INTO messages VALUES (?,?,?,?,?)', (uid(), conversation, 'user', '请用概念对照表，指出我把同时变化理解为因果的错误。', now()))
    return server.GenerateIn(project_id=project['id'], source_ids=[source], conversation_id=conversation, model='old-writer', provider=provider)


def test_chat_document_followup_share_public_history_model_with_isolated_task_thread(tmp_path, monkeypatch):
    value = setup_dialogue(tmp_path); calls = []
    async def stream(prompt, remote_thread_id=None, model=None, effort=None, **kwargs):
        calls.append((prompt, remote_thread_id, model, effort, kwargs))
        assert prompt.count(REASONING_TEACHING_RULES) == 1
        role = 'lecture' if '完整阅读所选资料' in prompt else 'tutor'
        if role == 'lecture':
            assert '【本次表达重点：' in prompt
            assert prompt.endswith(TEACHING_TASK_REMINDER + mode_task_reminder('deep', role=role))
        else:
            assert '当前讲解风格：' in prompt and '当前学习模式：精学' in prompt
            assert '【本次表达重点：' not in prompt
            assert prompt.endswith('用户：解释生成文档中的共同原因。')
        yield 'thread', 'same-thread'
        if '完整阅读所选资料' in prompt:
            context = prompt + kwargs.get('fallback_history', '')
            assert '概念对照表' in context and '尾部论据' in prompt
            yield 'final', '# 相关与因果\n共同原因不是因果结论。\n\n## 系统性总结\n排除共同原因。'
        else:
            assert '共同原因不是因果结论' in prompt
            yield 'tool', {'tool':'sf_list_files','status':'completed'}
            yield 'final', '继续解释刚刚生成的讲解。'
    async def validate(*args): pass
    monkeypatch.setattr(CodexBridge, 'stream_turn', lambda self,*args,**kwargs:stream(*args,**kwargs))
    monkeypatch.setattr(server.model_catalog, 'validate_effort', validate)
    job_id = create_job(value.project_id, 'generate', value.model_dump())
    asyncio.run(server._generate_job(job_id, value))
    job = one('SELECT * FROM jobs WHERE id=?', (job_id,))
    assert job['status']=='completed', job['error']
    assert many('SELECT * FROM mentor_handoffs') == []
    assert len(many('SELECT * FROM generation_dialogue_outputs'))==1
    meta = json.loads(one("SELECT * FROM artifacts WHERE kind='explanation'")['metadata_json'])
    assert meta['session_mode']=='shared_dialogue' and meta['dialogue_model']=='same-model'
    response = TestClient(server.app).post('/api/chat/stream', json={'project_id':value.project_id, 'source_ids':value.source_ids,
        'conversation_id':value.conversation_id, 'text':'解释生成文档中的共同原因。', 'model':'same-model', 'reasoning_effort':'high'})
    assert response.status_code==200 and '"error"' not in response.text and '"tool"' in response.text
    assert calls[0][1:4] == (None, 'same-model', 'high')
    assert calls[1][1:4] == ('same-thread', 'same-model', 'high')
    assert len(calls)==2, 'No teacher handoff request should occur'


def test_no_dialogue_creates_one_session_and_uses_current_choice(tmp_path, monkeypatch):
    value=setup_dialogue(tmp_path); value.conversation_id=None; value.mentor_model='chosen-model'; value.reasoning_effort=None
    async def noop(*args): pass
    monkeypatch.setattr(server, '_generate_job', noop)
    result=TestClient(server.app).post('/api/generate', json=value.model_dump())
    assert result.status_code==200, result.text
    row=one('SELECT * FROM conversations WHERE id=?', (result.json()['conversation_id'],))
    assert row['model']=='chosen-model'
    payload=json.loads(one('SELECT payload_json FROM jobs')['payload_json'])
    assert payload['generation_quality']=='custom' and payload['dialogue_snapshot']['mentor']['id']==row['id']
    server.active_generations.pop(result.json()['job_id'], None)


def test_codex_tools_share_live_private_thread_and_old_threads_restore_saved_history(monkeypatch):
    bridge=CodexBridge(); calls=[]
    async def start(): pass
    async def request(method, params):
        calls.append((method,params))
        if method=='thread/start': return {'thread':{'id':'tool-thread', 'ephemeral':True}}
        if method=='turn/start':
            await bridge.events.put({'method':'turn/completed','params':{'threadId':'tool-thread','turn':{'status':'completed'}}})
        return {}
    monkeypatch.setattr(bridge,'start',start); monkeypatch.setattr(bridge,'request',request)
    async def run():
        runtime=AgentRuntime()
        _=[event async for event in bridge.stream_turn('任务','old-thread', agent_runtime=runtime, fallback_history='保留原始要求')]
        _=[event async for event in bridge.stream_turn('下一步','tool-thread', agent_runtime=runtime)]
    asyncio.run(run())
    assert len([m for m,p in calls if m=='thread/start'])==1
    assert '保留原始要求' in next(p for m,p in calls if m=='turn/start')['input'][0]['text']
    assert not any(m == 'thread/resume' for m, p in calls)
    started = next(p for m,p in calls if m=='thread/start')
    assert started['dynamicTools'] and started['ephemeral'] is True
    from pathlib import Path
    assert Path(started['cwd']).parent.name=='agent-workspace' and Path(started['cwd']).name!='general'


def test_private_codex_restart_restores_app_history_without_resuming_a_stored_thread(monkeypatch):
    calls = []
    async def start(): pass
    async def run(bridge, remote, text):
        async def request(method, params):
            calls.append((method, params))
            if method == 'thread/start': return {'thread': {'id': 'private-' + str(len(calls)), 'ephemeral': True}}
            if method == 'turn/start':
                await bridge.events.put({'method': 'turn/completed', 'params': {'threadId': params['threadId'], 'turn': {'status': 'completed'}}})
            return {}
        monkeypatch.setattr(bridge, 'start', start); monkeypatch.setattr(bridge, 'request', request)
        return [event async for event in bridge.stream_turn('继续学习', remote, agent_runtime=AgentRuntime(), fallback_history=text)]
    first = asyncio.run(run(CodexBridge(), None, '原学习记录'))
    remote = next(value for kind,value in first if kind == 'thread')
    later = asyncio.run(run(CodexBridge(), remote, '已保存的完整问答与生成讲解'))
    assert next(value for kind,value in later if kind == 'thread') != remote
    assert not any(method == 'thread/resume' for method,params in calls)
    assert '完整问答与生成讲解' in [params for method,params in calls if method=='turn/start'][-1]['input'][0]['text']


def test_codex_that_does_not_confirm_private_history_mode_stops_before_inference(monkeypatch):
    import pytest
    bridge = CodexBridge(); calls = []
    async def start(): pass
    async def request(method, params):
        calls.append(method)
        return {'thread': {'id': 'legacy', 'ephemeral': False}}
    monkeypatch.setattr(bridge, 'start', start); monkeypatch.setattr(bridge, 'request', request)
    async def run(): return [event async for event in bridge.stream_turn('学习请求', agent_runtime=AgentRuntime())]
    with pytest.raises(RuntimeError, match='未确认临时会话'):
        asyncio.run(run())
    assert calls == ['thread/start']


def test_review_fork_copies_public_history_and_owns_a_connection():
    conversation={'id':'local', 'remote_thread_id':'remote', 'messages':[]}
    client=CodexClient(model='model',effort='high',conversation=conversation)
    fork=client.fork()
    assert fork.conversation is not conversation and fork.conversation['id']==conversation['id']
    assert fork.private_bridge is not None and fork.detached and fork.conversation['remote_thread_id'] is None


def test_deepseek_chat_generation_and_followup_retain_tools_and_reasoning(tmp_path,monkeypatch):
    import httpx
    value=setup_dialogue(tmp_path,'deepseek'); requests=[]; original=httpx.AsyncClient
    monkeypatch.setattr('studyforge.ai.get_secret',lambda key:'test-key')
    def respond(request):
        body=json.loads(request.content); requests.append(body)
        text='# 因果分析\n解释共同原因。\n\n## 系统性总结\n相关不能推出因果。' if len(requests)==2 else '继续解释共同原因。'
        content={'choices':[{'delta':{'reasoning_content':f'private-{len(requests)}','content':text},'finish_reason':'stop'}]}
        return httpx.Response(200,text='data: '+j(content)+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:original(transport=httpx.MockTransport(respond)))
    args={'project_id':value.project_id,'source_ids':value.source_ids,'conversation_id':value.conversation_id,'provider':'deepseek','model':'same-model','text':'我需要概念表。'}
    first=TestClient(server.app).post('/api/chat/stream',json=args)
    assert '"error"' not in first.text
    job=create_job(value.project_id,'generate',value.model_dump()); asyncio.run(server._generate_job(job,value))
    assert one('SELECT * FROM jobs WHERE id=?',(job,))['status']=='completed'
    final=TestClient(server.app).post('/api/chat/stream',json=args | {'text':'继续解释刚刚文档的共同原因。'})
    assert '"error"' not in final.text and 'private-' not in final.text
    assert len(requests)==3 and all(row['model']=='same-model' for row in requests)
    for request in requests:
        current_policy = next(row['content'] for row in request['messages'] if row['role']=='system')
        assert current_policy.count(REASONING_TEACHING_RULES) == 1
        role = 'lecture' if '详略要求：' in request['messages'][-1]['content'] else 'tutor'
        if role == 'lecture':
            assert '【本次表达重点：' in request['messages'][-1]['content']
            assert request['messages'][-1]['content'].endswith(TEACHING_TASK_REMINDER + mode_task_reminder('deep', role=role))
        else:
            assert request['messages'][-1]['content'] in ('我需要概念表。', '继续解释刚刚文档的共同原因。')
            assert '当前讲解风格：' in current_policy and '当前学习模式：精学' in current_policy
    assert not any(row.get('reasoning_content')=='private-1' for row in requests[1]['messages'])
    assert any(row.get('reasoning_content')=='private-1' for row in requests[2]['messages'])
    assert not any(row.get('reasoning_content')=='private-2' for row in requests[2]['messages'])
    assert any('已生成讲解文档' in str(row.get('content')) for row in requests[2]['messages'])


def test_failed_generation_never_adds_fake_completed_lecture(tmp_path,monkeypatch):
    value=setup_dialogue(tmp_path)
    class Client:
        async def complete(self,*args,**kwargs): raise RuntimeError('网络中断')
    monkeypatch.setattr(server,'client_for',lambda *a,**kw:Client())
    job=create_job(value.project_id,'generate',value.model_dump()); asyncio.run(server._generate_job(job,value))
    assert one('SELECT status FROM jobs WHERE id=?',(job,))['status']=='failed'
    assert many('SELECT * FROM generation_dialogue_outputs')==[]


def test_exercise_solutions_stay_outside_shared_student_dialogue(tmp_path,monkeypatch):
    value=setup_dialogue(tmp_path);value.exercises=True;contexts=[];runtimes=[]
    class Client:
        async def complete(self,system,user,**kwargs): return '# 因果\n讲解。\n\n## 系统性总结\n相关不能证明因果。'
    def clients(*args,**kwargs):
        contexts.append(kwargs.get('conversation')); runtimes.append(kwargs.get('agent_runtime')); return Client()
    async def exercises(client,*args,**kwargs): return uid(),[]
    monkeypatch.setattr(server,'client_for',clients)
    monkeypatch.setattr(server,'generate_set',exercises)
    monkeypatch.setattr(server,'student_document',lambda *args:'# 习题\n请分析共同原因。')
    job=create_job(value.project_id,'generate',value.model_dump());asyncio.run(server._generate_job(job,value))
    assert one('SELECT * FROM jobs WHERE id=?',(job,))['status']=='completed'
    assert contexts[0]['id']==value.conversation_id and contexts[1] is None
    assert runtimes[1].private_context and runtimes[1].conversation_id is None
    assert runtimes[1].workspace != runtimes[0].workspace


def test_saved_long_lecture_can_be_used_again_and_resumed(tmp_path,monkeypatch):
    value=setup_dialogue(tmp_path); text='已有讲解。'*40000+'文末关键条件'
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),value.conversation_id,'assistant',text,now()))
    async def noop(*args): pass
    monkeypatch.setattr(server,'_generate_job',noop)
    response=TestClient(server.app).post('/api/generate',json=value.model_dump())
    assert response.status_code==200,response.text
    stored=json.loads(one('SELECT payload_json FROM jobs')['payload_json'])
    resumed=server.GenerateIn.model_validate(stored)
    assert len(resumed.resolved_requirements)>200000 and '文末关键条件' in resumed.resolved_requirements
    server.active_generations.pop(response.json()['job_id'],None)
