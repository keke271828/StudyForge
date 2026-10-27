"""Exercise the real chat entry, provider tool protocol and permission decision."""
import asyncio
import json

import httpx
import pytest

from studyforge import ai, conversations, server
from studyforge.agent_events import relay_tool_events
from studyforge.agent_permissions import decide, list_requests
from studyforge.agent_tools import AgentRuntime
from studyforge.codex_bridge import CodexBridge
from studyforge.db import create_project, j, many, one, uid


def setup_chat(provider='deepseek'):
    ai.save_settings({'chat_provider':provider,'agent_permission_mode':'approval',
                      'agent_tools_enabled':True,'agent_file_write_enabled':True,
                      'background_learning_enabled':False})
    project = create_project('聊天审批的完整流程')
    chat = conversations.create(project['id'], provider, 'approval-test-model')
    return project['id'], chat['id']


async def pending(pid, cid, after=None):
    for _ in range(150):
        rows = list_requests(pid, cid)
        if rows and rows[0]['id'] != after:
            return rows[0]
        await asyncio.sleep(.01)
    raise AssertionError('No pending approval')


def mock_deepseek(monkeypatch, operations):
    requests = []
    original = httpx.AsyncClient
    monkeypatch.setattr(ai, 'get_secret', lambda name:'test-key')
    monkeypatch.setattr('studyforge.agent_tools.get_secret', lambda name: None)

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        index = len(requests) - 1
        if index < len(operations):
            tool, arguments = operations[index]
            delta = {'content':'我会请求本次操作的审批，然后继续。',
                     'tool_calls':[{'index':0,'id':f'call-{index}', 'type':'function',
                                    'function':{'name':tool,'arguments':j(arguments)}}]}
            reason = 'tool_calls'
        else:
            last = json.loads(next(row['content'] for row in reversed(body['messages']) if row['role']=='tool'))
            delta = {'content':'你拒绝了本次操作，文件保持原样。' if 'error' in last else '已按原指令完成文件操作。'}
            reason = 'stop'
        return httpx.Response(200, text='data: '+j({'choices':[{'delta':delta,'finish_reason':reason}]})+'\n\ndata: [DONE]\n\n')

    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(*a, **(kw|{'transport':httpx.MockTransport(respond)})))
    return requests


async def start_reply(pid, cid, provider='deepseek'):
    response = await server.chat_stream(server.ChatIn(project_id=pid, conversation_id=cid, source_ids=[],
        provider=provider, model='approval-test-model', text='请按指令修改指定文件，并说明实际结果。'))
    events = []

    async def consume():
        async for data in response.body_iterator:
            events.append(json.loads(data))

    return asyncio.create_task(consume()), events


@pytest.mark.parametrize('approved', [True, False])
def test_deepseek_chat_suspends_before_decision_and_resumes_same_reply(tmp_path, monkeypatch, approved):
    pid, cid = setup_chat()
    target = tmp_path/'outside.txt'
    target.write_text('before', encoding='utf-8')
    requests = mock_deepseek(monkeypatch, [('sf_write_text', {'path':str(target),'text':'after','overwrite':True})])

    async def check():
        task, events = await start_reply(pid, cid)
        row = await pending(pid, cid)
        await asyncio.sleep(.25)
        assert not task.done(), 'The chat must stay live while approval is pending'
        assert len(requests) == 1 and target.read_text() == 'before'
        assert any(event['type']=='tool' and event['value']['status']=='waiting_approval' for event in events)
        assert not any(event['type'] in ('done','error') for event in events)
        assert not many("SELECT * FROM messages WHERE conversation_id=? AND role='assistant'", (cid,))
        decide(row['id'], pid, cid, approved)
        await asyncio.wait_for(task, 3)
        assert len(requests) == 2
        assert target.read_text() == ('after' if approved else 'before')
        assert one('SELECT status FROM agent_approvals WHERE id=?', (row['id'],))['status'] == ('consumed' if approved else 'denied')
        assert events[-1] == {'type':'done','value':True}
        assert cid not in server.active_chat_conversations
        assert len(many("SELECT * FROM messages WHERE conversation_id=? AND role='user'", (cid,))) == 1
        replies = many("SELECT * FROM messages WHERE conversation_id=? AND role='assistant'", (cid,))
        assert len(replies)==1 and ('已按原指令' if approved else '你拒绝了') in replies[0]['content']

    asyncio.run(check())


def test_sequential_operations_each_wait_for_their_own_decision(tmp_path, monkeypatch):
    # The install tree is implicitly readable. Put this fixture outside it even
    # when pytest's basetemp happens to be under the source checkout.
    monkeypatch.setenv('STUDYFORGE_APPLICATION_ROOT', str(tmp_path / 'installed-app'))
    pid, cid = setup_chat()
    source = tmp_path/'input.txt'
    source.write_text('原文', encoding='utf-8')
    target = tmp_path/'output.txt'
    requests = mock_deepseek(monkeypatch, [('sf_read_file', {'path':str(source)}),
        ('sf_write_text', {'path':str(target),'text':'已阅读后的结果'})])

    async def check():
        task, events = await start_reply(pid, cid)
        first = await pending(pid, cid)
        decide(first['id'], pid, cid, True)
        second = await pending(pid, cid, first['id'])
        await asyncio.sleep(.15)
        assert not task.done() and not target.exists() and len(requests)==2
        decide(second['id'], pid, cid, True)
        await asyncio.wait_for(task, 3)
        assert target.read_text(encoding='utf-8') == '已阅读后的结果' and len(requests)==3
        assert len([event for event in events if event['type']=='tool' and event['value']['status']=='waiting_approval'])==2

    asyncio.run(check())


@pytest.mark.parametrize('approved', [True, False])
def test_codex_chat_does_not_acknowledge_tool_or_time_out_during_approval(tmp_path, monkeypatch, approved):
    pid, cid = setup_chat('codex')
    target = tmp_path/'codex-target.txt'
    target.write_text('before', encoding='utf-8')
    bridge = CodexBridge()
    sent = []
    monkeypatch.setattr(server, 'bridge_for', lambda _:bridge)
    monkeypatch.setattr('studyforge.codex_bridge.FOREGROUND_EVENT_TIMEOUT', .08)

    async def start():
        pass

    async def request(method, params):
        if method=='thread/start':
            return {'thread':{'id':'private-approval-thread','ephemeral':True}}
        if method=='turn/start':
            call = {'id':'codex-tool-call', 'params':{'threadId':params['threadId'],'tool':'sf_write_text',
                'arguments':{'path':str(target),'text':'after','overwrite':True}}}
            task = asyncio.create_task(bridge._handle_tool(call, bridge.agent_runtime))
            bridge.tool_tasks.add(task)
            task.add_done_callback(bridge.tool_tasks.discard)
        return {}

    async def send(message):
        sent.append(message)
        text = '已按原指令完成文件操作。' if message['result']['success'] else '你拒绝了本次操作，文件保持原样。'
        await bridge.events.put({'method':'item/completed', 'params':{'threadId':'private-approval-thread',
            'item':{'type':'agentMessage','text':text}}})
        await bridge.events.put({'method':'turn/completed','params':{'threadId':'private-approval-thread','turn':{'status':'completed'}}})

    monkeypatch.setattr(bridge, 'start', start)
    monkeypatch.setattr(bridge, 'request', request)
    monkeypatch.setattr(bridge, '_send', send)

    async def check():
        task, events = await start_reply(pid, cid, 'codex')
        row = await pending(pid, cid)
        await asyncio.sleep(.3)  # Several times the model timeout, with no approval decision.
        assert not task.done() and not sent and target.read_text()=='before'
        assert bridge.agent_runtime.waiting_approvals == {row['id']}
        assert not any(event['type'] in ('done','error') for event in events)
        decide(row['id'], pid, cid, approved)
        await asyncio.wait_for(task, 3)
        assert len(sent)==1 and sent[0]['result']['success'] is approved
        assert not bridge.agent_runtime.waiting_approvals
        assert bridge.agent_runtime.approval_wait_seconds() >= .3
        assert target.read_text()==('after' if approved else 'before')
        assert events[-1] == {'type':'done','value':True}
        await bridge.close()

    asyncio.run(check())


def test_cancelling_waiting_chat_invalidates_approval_and_never_writes(tmp_path, monkeypatch):
    pid, cid = setup_chat()
    target = tmp_path/'never.txt'
    mock_deepseek(monkeypatch, [('sf_write_text', {'path':str(target),'text':'never'})])

    async def check():
        task, _ = await start_reply(pid, cid)
        row = await pending(pid, cid)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        assert not target.exists() and cid not in server.active_chat_conversations
        assert one('SELECT status FROM agent_approvals WHERE id=?', (row['id'],))['status']=='cancelled'
        with pytest.raises(ValueError):
            decide(row['id'], pid, cid, True)

    asyncio.run(check())


def test_noninteractive_caller_cannot_leave_a_dead_approval_card(tmp_path):
    pid, cid = setup_chat()
    runtime = AgentRuntime(pid, conversation_id=cid)
    result = asyncio.run(runtime.execute('sf_write_text', {'path':str(tmp_path/'not-written.txt'),'text':'never'}))
    assert result['type']=='PermissionError' and not many('SELECT * FROM agent_approvals')


def test_codex_model_timeout_still_applies_after_approval_wait(monkeypatch):
    monkeypatch.setattr('studyforge.codex_bridge.FOREGROUND_EVENT_TIMEOUT', .06)

    async def check():
        runtime = AgentRuntime()
        bridge = CodexBridge()
        task = asyncio.create_task(bridge.next_turn_event(runtime))
        await asyncio.sleep(.01)
        runtime.begin_approval_wait('approval')
        await asyncio.sleep(.18)
        assert not task.done()
        runtime.end_approval_wait('approval')
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(task, .3)

    asyncio.run(check())


def test_relay_cancels_producer_even_when_notification_queue_is_full():
    async def check():
        runtime = AgentRuntime(on_event=lambda _:None)
        previous = runtime.on_event
        stopped = asyncio.Event()

        async def source():
            try:
                while True:
                    yield b'packet'
            finally:
                stopped.set()

        stream = relay_tool_events(source(), runtime, lambda _:b'tool')
        assert await anext(stream) == b'packet'
        await asyncio.sleep(.01)
        await asyncio.wait_for(stream.aclose(), 1)
        assert stopped.is_set() and runtime.on_event is previous

    asyncio.run(check())
