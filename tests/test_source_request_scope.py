"""Effective source selection survives task branches and provider replay."""
import asyncio
import json

import httpx
import pytest

from studyforge import conversations
from studyforge.agent_tools import AgentRuntime, ReadSource
from studyforge.ai import DeepSeekClient, save_settings
from studyforge.db import create_project, execute, j, now, uid


def runtime(tmp_path):
    import fitz
    save_settings({'agent_permission_mode':'read_only','agent_tools_enabled':False,'background_learning_enabled':False})
    project = create_project('读取范围验证')
    chat = conversations.create(project['id'],'deepseek','fixture-model')
    path = tmp_path / 'original.pdf'
    with fitz.open() as document:
        for label in ('FIRST_PAGE_ONLY','SECOND_PAGE_ONLY'):
            page = document.new_page()
            page.insert_text((50,80),label + ': enough original text to read without optical recognition.')
        document.save(path)
    sid = uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
        (sid,project['id'],path.name,'.pdf',str(path),'ready',now()))
    return AgentRuntime(project['id'],[sid],provider='deepseek',model='fixture-model',conversation_id=chat['id']),sid


def test_fork_preserves_exact_read_request_without_sharing_mutable_tool_cache(tmp_path):
    parent, sid = runtime(tmp_path)
    parent.source_read_request = '只读原PDF第1页'
    child = parent.fork()
    assert child.source_read_request == parent.source_read_request
    child.source_read_request = '只读第2页'
    assert parent.source_read_request == '只读原PDF第1页' and child.cache is not parent.cache


def test_state_key_changes_when_effective_read_scope_changes_not_for_rewording(tmp_path):
    agent, _ = runtime(tmp_path)
    keys = []
    for question in ('只读第1页','请帮我核对原PDF第1页','只读第2页','只读第1-2页','只讲解第1章','请完整阅读全文'):
        agent.source_read_request = question
        keys.append(agent.state_key())
    assert keys[0] == keys[1]
    assert len(set(keys)) == 5


def test_fork_cannot_broaden_selected_pdf_page_even_if_file_was_already_parsed(tmp_path):
    parent, sid = runtime(tmp_path)
    parent.source_read_request = '只读第1页'
    child = parent.fork()
    with pytest.raises(PermissionError, match='超出'):
        asyncio.run(child.sf_read_source(ReadSource(source_id=sid,page_spec='2')))
    result = asyncio.run(child.sf_read_source(ReadSource(source_id=sid,page_spec='1')))
    assert 'FIRST_PAGE_ONLY' in result['text'] and 'SECOND_PAGE_ONLY' not in result['text']


@pytest.mark.parametrize('same', [False,True])
def test_native_replay_keeps_only_compatible_internal_source_history(tmp_path, monkeypatch, same):
    agent, sid = runtime(tmp_path)
    monkeypatch.setattr('studyforge.ai.get_secret',lambda name:'fixture-only')
    client = DeepSeekClient(model='fixture-model',agent_runtime=agent)
    agent.source_read_request = '只读第1页'
    key = agent.state_key()
    execute('INSERT INTO agent_dialogue_scopes VALUES (?,?,?)',(agent.conversation_id,agent.project_id,key))
    execute('INSERT INTO agent_dialogue_state VALUES (?,?,?,?,?)',
        (agent.conversation_id,0,j([{'role':'assistant','content':'INTERNAL_FIRST_PAGE_RESULT'}]),now(),client.protocol_version))
    agent.source_read_request = '帮我解释原PDF第1页' if same else '只读第2页'
    captured = []
    native = httpx.AsyncClient
    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':'受控回复'},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:native(transport=httpx.MockTransport(respond)))
    async def run():
        try:
            return [event async for event in client.agent_stream([{'role':'system','content':'核对明确选中的资料'},
                {'role':'user','content':'PUBLIC_SAME_CHAT_MESSAGE'},{'role':'user','content':agent.source_read_request}])]
        finally: await client.close()
    assert asyncio.run(run())
    body = j(captured[0])
    assert ('INTERNAL_FIRST_PAGE_RESULT' in body) is same
    assert 'PUBLIC_SAME_CHAT_MESSAGE' in body


@pytest.mark.parametrize('same', [False, True])
def test_codex_restarts_native_thread_for_changed_read_scope_only(tmp_path, monkeypatch, same):
    from studyforge.codex_bridge import CodexBridge
    agent, _ = runtime(tmp_path)
    agent.provider = 'codex'
    bridge, requests = CodexBridge(), []
    async def start(): pass
    async def request(method, params):
        requests.append((method, params))
        if method == 'thread/start': return {'thread':{'id':'scoped-' + str(len(requests)), 'ephemeral':True}}
        if method == 'turn/start':
            await bridge.events.put({'method':'turn/completed','params':{'threadId':params['threadId'], 'turn':{'status':'completed'}}})
        return {}
    monkeypatch.setattr(bridge, 'start', start)
    monkeypatch.setattr(bridge, 'request', request)
    async def run():
        agent.source_read_request = '只读第1页'
        first = [event async for event in bridge.stream_turn('问题一', agent_runtime=agent)]
        remote = next(value for kind, value in first if kind == 'thread')
        await asyncio.sleep(0)
        agent.source_read_request = '核对原PDF第1页' if same else '只读第2页'
        second = [event async for event in bridge.stream_turn('问题二', remote, agent_runtime=agent,
            fallback_history='PUBLIC_SAME_CHAT_HISTORY')]
        assert (next(value for kind, value in second if kind == 'thread') == remote) is same
    asyncio.run(run())
    assert len([p for method, p in requests if method == 'thread/start']) == (1 if same else 2)
    if not same:
        assert 'PUBLIC_SAME_CHAT_HISTORY' in [p for method, p in requests if method == 'turn/start'][-1]['input'][0]['text']
