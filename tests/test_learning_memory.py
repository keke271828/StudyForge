import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from studyforge import learning_memory as memory
from studyforge.ai import DeepSeekClient, save_settings
from studyforge.db import create_project, execute, j, many, now, one, uid, update_mastery


def chat_event(text='我能说出概念，但不明白为什么引入辅助函数。', topic='柯西不等式', model='deepseek-flash'):
    project = create_project('学习')
    conversation, message = uid(), uid()
    execute('INSERT INTO conversations(id,project_id,provider,created_at,source_ids_json,model) VALUES (?,?,?,?,?,?)',
            (conversation, project['id'], 'deepseek', now(), '[]', model))
    execute('INSERT INTO messages VALUES (?,?,?,?,?)', (message, conversation, 'user', text, now()))
    memory.discussion_completed(conversation, message)
    return one('SELECT * FROM learning_events ORDER BY id DESC LIMIT 1'), topic, conversation, message


class SmallClient:
    def __init__(self): self.calls = []; self.closed = False

    async def complete(self, system, user, **kwargs):
        self.calls.append((system, user, kwargs))
        events = json.loads(user)['events']
        return j({'insights': [{'event_id': e['id'], 'topic': '柯西不等式', 'kind': 'gap', 'dimension': 'reasoning',
                               'quote': e.get('student_text', ''), 'observation': '需要解释辅助函数的构造动机；理解程度待测验。',
                               'anchors':['辅助函数','这一步']}
                              for e in events if e['kind'] == 'chat']})

    async def close(self): self.closed = True


def test_discussion_deduplicated_and_no_mastery_inflation():
    event, _, conversation, message = chat_event()
    memory.discussion_completed(conversation, message)
    assert len(many('SELECT * FROM learning_events')) == 1
    assert many('SELECT * FROM mastery') == []
    client = SmallClient()
    assert asyncio.run(memory.MemoryWorker(lambda _: client).run_once(ignore_idle=True))
    assert len(client.calls) == 1 and client.closed
    assert client.calls[0][2] == {'json_mode': True, 'max_tokens': 1200}
    assert one('SELECT * FROM learning_events')['status'] == 'completed'
    assert many('SELECT * FROM mastery') == []
    assert one('SELECT * FROM learning_insights')['confidence'] == '暂定'
    assert not asyncio.run(memory.MemoryWorker(lambda _: client).run_once(ignore_idle=True))


def test_reading_only_exposure_and_literal_evidence_required():
    events = [{'id': 1, 'kind': 'reading', 'payload': {'reading_text': '资料介绍了规训权力和规范化。'}},
              {'id': 2, 'kind': 'chat', 'payload': {'student_text': '请讲慢一些，证明部分我没有看懂。', 'mentor_context': '我已经完全掌握'}}]
    base = dict(event_id=1, topic='规训权力', dimension='', quote='规训权力', observation='接触了规训权力。')
    result = memory.validate_insights({'insights': [dict(base, kind='understanding'), dict(base, kind='exposure'),
        dict(base, event_id=999, kind='exposure'), dict(base, quote='福柯的全部著作', kind='exposure'),
        dict(base, event_id=2, quote='我已经完全掌握', kind='ability'),
        dict(base, event_id=2, quote='请讲慢一些', kind='preference')]}, events)
    assert [r['kind'] for r in result] == ['exposure','preference']
    assert memory.validate_insights({'insights': []}, events) == []


def test_cross_project_memory_filtered_and_scores_unchanged():
    event, _, _, _ = chat_event()
    memory._save_insight(event['id'], '柯西不等式', 'gap', 'reasoning', '需要辅助函数动机。', '引入辅助函数', '暂定')
    memory._save_insight(event['id'], '教学偏好', 'preference', '', '希望慢一些。', '请慢一些', '暂定')
    memory._save_insight(event['id'], '经典力学', 'gap', '', '单位检查不足。', '单位是什么', '暂定')
    create_project('哲学项目')
    assert '辅助函数动机' in memory.profile_context('柯西不等式的证明')
    assert '经典力学' not in memory.profile_context('福柯与规训权力')
    assert '希望慢一些' in memory.profile_context('福柯与规训权力')
    assert len(memory.memory_snapshot()['insights']) == 3
    assert many('SELECT * FROM mastery') == []


def test_long_heading_anchors_and_domain_specific_preferences():
    event, _, _, _ = chat_event()
    memory._save_insight(event['id'], '对辅助构造动机的理解不足', 'gap', 'reasoning', '需要解释函数构造。',
                         '不知道为什么构造函数', '暂定', anchors=['柯西不等式','二次函数'])
    memory._save_insight(event['id'], '只在哲学课简略讲解', 'preference', '', '哲学内容希望简略。',
                         '只在哲学课简略讲解', '暂定', anchors=['哲学'])
    assert '函数构造' in memory.profile_context('柯西不等式如何证明')
    assert '哲学内容希望简略' not in memory.profile_context('柯西不等式如何证明')
    assert '函数构造' not in memory.profile_context('哲学中的规训权力')
    assert '哲学内容希望简略' in memory.profile_context('哲学中的规训权力')
    for index in range(160):
        memory._save_insight(event['id'], f'无关主题{index}', 'exposure', '', '接触记录', '已有记录', '接触记录')
    assert '函数构造' in memory.profile_context('柯西不等式如何证明')


@pytest.mark.parametrize('value', [0,25,True,2.5])
def test_budget_validation(value):
    with pytest.raises(ValueError): save_settings({'background_learning_daily_limit': value})


def test_disabled_busy_interval_and_daily_quota():
    chat_event()
    client = SmallClient(); worker = memory.MemoryWorker(lambda _: client)
    save_settings({'background_learning_enabled': False})
    assert not asyncio.run(worker.run_once(ignore_idle=True))
    save_settings({'background_learning_enabled': True, 'background_learning_daily_limit': 1, 'task_parallel_enabled':False})
    with memory.foreground_activity(): assert not asyncio.run(worker.run_once(ignore_idle=True))
    assert not asyncio.run(worker.run_once())  # Idle threshold.
    assert asyncio.run(worker.run_once(ignore_idle=True))
    chat_event(text='这一步还是不懂为什么。')
    assert not asyncio.run(worker.run_once(ignore_idle=True))
    assert memory.memory_snapshot()['today_calls'] == 1
    assert len(client.calls) == 1


def test_background_learning_can_finish_with_foreground_work_and_keeps_budget():
    from studyforge.scheduling import execution_context, model_slot
    chat_event()
    save_settings({'task_parallel_enabled':True,'model_concurrency':2,'background_learning_daily_limit':1})
    class ConcurrentClient(SmallClient):
        async def complete(self,*args,**kwargs):
            assert execution_context.get()['priority']==10
            async with model_slot('test'):return await super().complete(*args,**kwargs)
    client=ConcurrentClient();worker=memory.MemoryWorker(lambda _:client)
    async def scenario():
        with memory.foreground_activity():
            async with model_slot('foreground'):
                assert await worker.run_once(ignore_idle=True)
        assert memory.memory_snapshot()['today_calls']==1
        chat_event(text='柯西不等式的证明仍然不懂。')
        assert not await worker.run_once(ignore_idle=True)
    asyncio.run(scenario())
    assert len(client.calls)==1 and client.closed
    assert one('SELECT * FROM learning_insights')['confidence']=='暂定'


def test_failures_bounded_and_do_not_block_foreground():
    chat_event()
    class Broken(SmallClient):
        async def complete(self, *args, **kwargs): raise RuntimeError('密钥错误，不能打印到画像')
    worker = memory.MemoryWorker(lambda _: Broken())
    assert not asyncio.run(worker.run_once(ignore_idle=True))
    assert one('SELECT * FROM learning_runs')['error'] == 'RuntimeError'
    assert not asyncio.run(worker.run_once(ignore_idle=True))  # No immediate retry.
    execute('UPDATE learning_runs SET created_at=?', ('2000-01-01T00:00:00+00:00',))
    assert not asyncio.run(worker.run_once(ignore_idle=True))
    assert one('SELECT * FROM learning_events')['status'] == 'failed'
    execute('UPDATE learning_runs SET created_at=?', ('2000-01-01T00:00:00+00:00',))
    assert not asyncio.run(worker.run_once(ignore_idle=True))
    assert len(many('SELECT * FROM learning_runs')) == 2


def test_foreground_preempts_and_restart_recovers():
    save_settings({'task_parallel_enabled':False})
    chat_event()
    class Waiting(SmallClient):
        async def complete(self, *args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
    async def scenario():
        nonlocal entered
        entered = asyncio.Event()
        worker = memory.MemoryWorker(lambda _: Waiting())
        await worker.start()
        worker.task.cancel(); await asyncio.gather(worker.task, return_exceptions=True)
        worker.inflight = asyncio.create_task(worker.run_once(ignore_idle=True))
        await entered.wait()
        with memory.foreground_activity():
            result = await asyncio.gather(worker.inflight, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert one('SELECT * FROM learning_events')['status'] == 'pending'
        assert one('SELECT * FROM learning_events')['attempts'] == 0
        assert one('SELECT * FROM learning_runs')['status'] == 'interrupted'
        assert memory.memory_snapshot()['today_calls'] == 1
        await worker.close()
        execute("UPDATE learning_events SET status='running'")
        execute("UPDATE learning_runs SET status='running'")
        restored = memory.MemoryWorker()
        await restored.start(); await restored.close()
        assert one('SELECT * FROM learning_events')['status'] == 'pending'
        assert one('SELECT * FROM learning_runs')['status'] == 'interrupted'
    entered = None
    asyncio.run(scenario())


def test_switch_off_during_response_does_not_commit():
    chat_event()
    class SwitchOff(SmallClient):
        async def complete(self, *args, **kwargs):
            answer = await super().complete(*args, **kwargs)
            save_settings({'background_learning_enabled': False})
            return answer
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(memory.MemoryWorker(lambda _: SwitchOff()).run_once(ignore_idle=True))
    assert many('SELECT * FROM learning_insights') == []
    assert one('SELECT * FROM learning_events')['status'] == 'pending'


def test_separate_models_not_coalesced():
    chat_event(model='deepseek-flash'); chat_event(model='other-model')
    captured = []
    def factory(event): captured.append(event['model']); return SmallClient()
    worker = memory.MemoryWorker(factory)
    assert asyncio.run(worker.run_once(ignore_idle=True))
    assert captured == ['deepseek-flash']
    assert one("SELECT count(*) AS n FROM learning_events WHERE status='pending'")['n'] == 1


def test_assessment_records_not_regraded_and_api_compatible():
    update_mastery('电磁感应', quiz=79)
    before = one('SELECT * FROM mastery')
    memory.assessment_record('quiz:1', '电磁感应', '做题', 79, '我用楞次定律判断方向。', '缺少单位检查。')
    memory.assessment_record('quiz:1', '电磁感应', '做题', 79, '同一回调', '')
    assert len(many('SELECT * FROM learning_events')) == 1
    assert one('SELECT * FROM mastery') == before
    assert '单位检查' in memory.profile_context('电磁感应')
    from studyforge.server import app
    client = TestClient(app)
    assert isinstance(client.get('/api/profile').json(), list)
    assert client.get('/api/profile/memory').json()['insights'][0]['confidence'] == '评估记录'


def test_deepseek_background_has_no_tools_history_retry_or_uncapped_output(monkeypatch):
    monkeypatch.setattr('studyforge.ai.get_secret', lambda _: 'fake-test-key')
    seen = []
    async def post(self, body, timeout=240, retry=True):
        seen.append((body, timeout, retry))
        return {'choices':[{'message': {'role':'assistant','content':'{"insights":[]}'}, 'finish_reason':'stop'}]}
    monkeypatch.setattr(DeepSeekClient, '_post', post)
    client = memory.background_client({'provider':'deepseek','model':'deepseek-flash','effort':None})
    asyncio.run(client.complete(memory.MEMORY_RULES, '{}', json_mode=True, max_tokens=1200))
    body, timeout, retry = seen[0]
    assert not client.agent_runtime and not client.conversation
    assert 'tools' not in body and len(body['messages']) == 2
    assert body['max_tokens'] == 1200 and body['thinking'] == {'type':'disabled'}
    assert timeout == 90 and retry is False


def test_production_chat_receives_memory_and_only_successful_reply_queued(monkeypatch):
    from studyforge import server
    event, _, conversation, _ = chat_event()
    memory._save_insight(event['id'], '教学偏好', 'preference', '', '先解释构造的动机。', '先讲动机', '暂定')
    captured = []
    class Tutor:
        def __init__(self, model=None, effort=None):
            self.model = model or 'deepseek-flash'
            self.effort = effort
        async def agent_stream(self, messages):
            captured.append(messages)
            yield 'final', '这里解释构造的动机。'
    monkeypatch.setattr(server, 'DeepSeekClient', Tutor)
    project = one('SELECT project_id FROM conversations WHERE id=?', (conversation,))['project_id']
    async def send():
        result = await server.chat_stream(server.ChatIn(project_id=project, source_ids=[], conversation_id=conversation,
                                                        provider='deepseek', text='再讲一下柯西不等式。'))
        return b''.join([packet async for packet in result.body_iterator])
    assert b'error' not in asyncio.run(send())
    assert '先解释构造的动机' in captured[0][0]['content']
    assert len(many('SELECT * FROM learning_events')) == 2
    class Failed(Tutor):
        async def agent_stream(self, messages):
            if False: yield None
            raise RuntimeError('模拟断网')
    monkeypatch.setattr(server, 'DeepSeekClient', Failed)
    assert b'error' in asyncio.run(send())
    assert len(many('SELECT * FROM learning_events')) == 2


def test_long_student_message_keeps_last_requirements_and_bounded_source_refs():
    event, _, _, _ = chat_event(text='这里是资料。' * 600 + '最后要求：请详细解释证明的动机。')
    assert '最后要求' in json.loads(event['payload_json'])['student_text']
    event_id = memory.record_event('large-scope', 'reading', {'source_ids':[str(i) for i in range(1000)], 'reading_text':'笔记'},
                                    provider='deepseek', model='test-model')
    payload = json.loads(one('SELECT payload_json FROM learning_events WHERE id=?', (event_id,))['payload_json'])
    assert len(payload['source_ids']) == 20 and payload['source_count'] == 1000


def test_codex_memory_uses_ephemeral_private_bridge_without_any_tools(monkeypatch):
    from studyforge.codex_bridge import CodexBridge
    calls = []
    async def start(self): pass
    async def close(self): pass
    async def request(self, method, params):
        calls.append((method,params))
        if method == 'thread/start': return {'thread':{'id':'memory-only','ephemeral':True}}
        if method == 'turn/start':
            await self.events.put({'method':'item/completed','params':{'threadId':'memory-only','item':{'type':'agentMessage','text':'{"insights":[]}'}}})
            await self.events.put({'method':'turn/completed','params':{'threadId':'memory-only','turn':{'status':'completed'}}})
        return {}
    monkeypatch.setattr(CodexBridge, 'start', start)
    monkeypatch.setattr(CodexBridge, 'close', close)
    monkeypatch.setattr(CodexBridge, 'request', request)
    client = memory.background_client({'provider':'codex','model':'test-model','effort':'high'})
    assert client.private_bridge and not client.agent_runtime and not client.conversation
    assert asyncio.run(client.complete(memory.MEMORY_RULES, '{}', json_mode=True)) == '{"insights":[]}'
    started, turn = calls[0][1], calls[1][1]
    assert started['ephemeral'] is True and started['sandbox'] == 'read-only'
    assert 'dynamicTools' not in started and started['config']['web_search'] == 'disabled'
    assert all(value is False for key,value in started['config'].items() if key.startswith('features.'))
    assert turn['model'] == 'test-model' and turn['effort'] == 'high'
