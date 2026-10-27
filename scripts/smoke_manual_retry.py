"""Full lesson generation interrupted once, recovered from UI with controlled models."""
import re
import httpx
from scripts import smoke_chapter_continuity_ui as base
from studyforge.db import execute,j,many,one,now,uid,unj
from studyforge.scheduling import current_step

f=base.fixture
f.ai.save_settings({'task_auto_retry':False,'generation_parallel':False})
original=f.server.client_for
failed=set()


class InterruptedClient:
    def __init__(self,client):self.client=client
    def __getattr__(self,name):return getattr(self.client,name)
    async def complete(self,system,user,**kwargs):
        step=current_step.get();ident=step.control.job_id if step else None
        if ident and '这是长资料第 2/' in user and ident not in failed:
            failed.add(ident);raise httpx.ConnectError('controlled interruption before second draft')
        return await self.client.complete(system,user,**kwargs)


f.server.client_for=lambda *args,**kwargs:InterruptedClient(original(*args,**kwargs))


@f.server.app.get('/__manual_ui__/state')
def state():
    result=base.state()
    result.update(receipts=many('SELECT * FROM task_manual_retries ORDER BY created_at'),failures=len(failed),
                  saved=[{'id':row['id'],'payload':unj(row['payload_json'])} for row in many("SELECT id,payload_json FROM jobs WHERE kind='generate'")])
    return result


@f.server.app.post('/__manual_ui__/later')
def later():
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),f.c['id'],'user','后来提出的要求：不应改写已启动的那份成果。',now()))
    return {'saved':True}


mount=next(r for r in f.server.app.routes if getattr(r,'name',None)=='web');f.server.app.router.routes.remove(mount);f.server.app.router.routes.append(mount)
if __name__=='__main__':f.asyncio.run(f.main())
