"""Real public history refresh during a gated provider stream; isolated data."""
import asyncio
import json
import httpx
from scripts import smoke_library_ui as fixture
from studyforge.db import execute, j, many, now, uid

identifiers=[]
for i in range(30):
    ident=uid();identifiers.append(ident)
    content=(f'第 {i+1} 个具体问题。' if i%2==0 else
             '# 已有讲解\n\nPUBLIC_HISTORY_'+str(i)+'：先解释目标与条件，保留构造的动机。\n\n'
             r'$$\varepsilon=\frac{b-a}{2},\quad N=\max\{N_1,N_2\}$$'+'\n\n这是独立测试材料。')
    execute('INSERT INTO messages(id,conversation_id,role,content,created_at) VALUES (?,?,?,?,?)',
        (ident,fixture.c['id'],'user' if i%2==0 else 'assistant',content,now()))
gate=asyncio.Event();original_response=fixture.respond
class ControlledStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield ('data: '+j({'choices':[{'delta':{'content':'LIVE_CHUNK_ONE：回复仍在继续。\n\n'},'finish_reason':None}]})+'\n\n').encode()
        await gate.wait()
        yield ('data: '+j({'choices':[{'delta':{'content':r'LIVE_CHUNK_TWO：条件 $x>0$ 需要一起保留。'},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n').encode()
async def respond(request):
    if request.method=='POST':
        body=json.loads(request.content)
        if 'HISTORY_LIVE_TEST' in str(body['messages'][-1]['content']):
            fixture.calls.append(body)
            gate.clear()
            return httpx.Response(200,stream=ControlledStream(),headers={'Content-Type':'text/event-stream'})
    return await original_response(request)
fixture.respond=respond
@fixture.server.app.post('/__history_test__/append')
def append():
    ident=uid()
    execute('INSERT INTO messages(id,conversation_id,role,content,created_at) VALUES (?,?,?,?,?)',
        (ident,fixture.c['id'],'assistant','BACKGROUND_RESULT：一项独立任务已经保存。',now()))
    return {'id':ident}
@fixture.server.app.post('/__history_test__/release')
async def release():gate.set();return {'ok':True}
@fixture.server.app.post('/__history_test__/amend')
def amend():
    execute('UPDATE messages SET content=? WHERE id=?',('AMENDED_SAME_ID：同一条消息的更正。',identifiers[1]))
    return {'id':identifiers[1]}
mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)
fixture.case.update(message_ids=identifiers)
if __name__=='__main__':asyncio.run(fixture.main())
