"""First visible text must not wait for the next provider packet."""
import asyncio
import json

from starlette.responses import StreamingResponse

from studyforge import server
from studyforge.db import create_project, execute, j, now, one, uid
from studyforge.conversations import create
from studyforge.mobile_access import MobileManager


def test_first_delta_is_saved_during_the_throttle_window(monkeypatch):
    project=create_project('手机流式显示')
    chat=create(project['id'],'deepseek')
    ident,device=uid(),uid()
    execute('INSERT INTO mobile_devices(id,name,token_hash,status,created_at,last_seen,expires_at,address) VALUES (?,?,?,?,?,?,?,?)',
            (device,'隔离测试手机','fixture-token','approved',now(),now(),now(),'127.0.0.1'))
    execute('INSERT INTO mobile_chats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (ident,device,uid(),'fixture-request',project['id'],chat['id'],'queued','',j({}),None,now(),now(),0))
    manager=MobileManager(server.app)

    async def run():
        reached,release=asyncio.Event(),asyncio.Event()
        async def chunks():
            yield json.dumps({'type':'status','value':'导师正在回复'})+'\n'
            yield json.dumps({'type':'delta','value':'第一句已经讲清。'})+'\n'
            reached.set()
            await release.wait()
            yield json.dumps({'type':'done','value':True})+'\n'
        async def reply(request):return StreamingResponse(chunks())
        monkeypatch.setattr(server,'chat_stream',reply)
        task=asyncio.create_task(manager._chat(ident,device,object()))
        await asyncio.wait_for(reached.wait(),1)
        row=one('SELECT status,content FROM mobile_chats WHERE id=?',(ident,))
        assert row['status']=='running' and row['content']=='第一句已经讲清。'
        release.set()
        await task
        assert one('SELECT status FROM mobile_chats WHERE id=?',(ident,))['status']=='completed'

    asyncio.run(run())
