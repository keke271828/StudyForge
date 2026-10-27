import asyncio

import pytest

from studyforge import ai, conversations, server
from studyforge.db import create_project


@pytest.mark.parametrize('outcome',['complete','error','cancel'])
def test_chat_owned_client_closed_after_response_error_or_stop(monkeypatch,outcome):
    p=create_project('对话连接释放');c=conversations.create(p['id'],'deepseek')
    ai.save_settings({'background_learning_enabled':False,'agent_tools_enabled':False,'library_reference_mode':'off'})
    closed=[]
    class Client:
        model='fixture'
        async def close(self):closed.append(True)
        async def agent_stream(self,*a):
            yield 'delta','已生成片段'
            if outcome=='error':raise RuntimeError('fixture failure')
            if outcome=='cancel':raise asyncio.CancelledError()
            yield 'final','完整回答'
    monkeypatch.setattr(server,'DeepSeekClient',lambda *a,**kw:Client())
    async def run():
        response=await server._chat_response(server.ChatIn(project_id=p['id'],conversation_id=c['id'],provider='deepseek',text='解释一个概念。'))
        if outcome=='cancel':
            with pytest.raises(asyncio.CancelledError):_=[chunk async for chunk in response.body_iterator]
        else:
            lines=[chunk async for chunk in response.body_iterator]
            assert any(b'"error"' in chunk for chunk in lines)==(outcome=='error')
    asyncio.run(run());assert closed==[True]


def test_chat_preparation_failure_closes_created_client_and_keeps_primary_error(monkeypatch):
    p=create_project('预处理失败');other=create_project('其他项目');c=conversations.create(other['id'],'deepseek')
    closed=[]
    class Client:
        model='fixture'
        async def close(self):closed.append(True);raise RuntimeError('cleanup failure must not replace input error')
    monkeypatch.setattr(server,'DeepSeekClient',lambda *a,**k:Client())
    from fastapi import HTTPException
    with pytest.raises(HTTPException,match='不匹配'):
        asyncio.run(server._chat_response(server.ChatIn(project_id=p['id'],conversation_id=c['id'],provider='deepseek',text='问题。')))
    assert closed==[True] and c['id'] not in server.active_chat_conversations


def test_actual_deepseek_http_client_is_closed_after_chat(monkeypatch):
    import httpx
    from studyforge.db import j
    p=create_project('实际HTTP客户端释放');c=conversations.create(p['id'],'deepseek')
    ai.save_settings({'background_learning_enabled':False,'agent_tools_enabled':False,'library_reference_mode':'off'})
    monkeypatch.setenv('DEEPSEEK_API_KEY','fixture-key')
    owned=[]
    def respond(request):
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':'完整回答。'},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    native=ai.DeepSeekClient
    def make(*args,**kwargs):
        client=native(*args,**kwargs);http=httpx.AsyncClient(transport=httpx.MockTransport(respond));client._http=http;owned.append((client,http));return client
    monkeypatch.setattr(server,'DeepSeekClient',make)
    async def run():
        response=await server._chat_response(server.ChatIn(project_id=p['id'],conversation_id=c['id'],provider='deepseek',text='请解释。'))
        assert not any(b'"error"' in chunk for chunk in [chunk async for chunk in response.body_iterator])
    asyncio.run(run());assert len(owned)==1 and owned[0][0]._http is None and owned[0][1].is_closed
