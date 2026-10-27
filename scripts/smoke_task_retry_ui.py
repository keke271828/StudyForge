"""Real desktop/paired phone UI; transient HTTP faults, isolated data."""
import asyncio
import json

import httpx
from scripts import smoke_library_ui as fixture
from studyforge import library, library_worker, server, task_retry
from studyforge.db import execute, now, uid

fixture.enable_semantic(False)
node=fixture.nodes[1]
library.update_node(node['id'],{'start_page':1,'end_page':1,'end_y':.5,'confirmed':True})
fixture.case['node_id']=node['id']
failures={'retry-project':0,'retry-book':0}
task_retry.retry_delay=lambda *a:1.5
async def respond(request):
    if request.method=='POST':
        payload=json.loads(request.content);model=payload.get('model')
        if model in failures and failures[model]<5:
            failures[model]+=1
            fixture.calls.append(payload)
            return httpx.Response(503,request=request,json={'error':{'message':'controlled service interruption'}})
    return await fixture.respond(request)
httpx.AsyncClient=lambda *a,**kw:fixture.original(transport=httpx.MockTransport(respond))
source=uid();path=fixture.case_path.parent/'material.txt'
path.write_text('数域对加法、减法、乘法和除以非零元素的运算封闭。',encoding='utf-8')
execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
    (source,fixture.p['id'],path.name,'.txt',str(path),'[]','ready',now()))

@server.app.post('/__retry_test__/project')
async def launch_project():
    return await server.generate(server.GenerateIn(project_id=fixture.p['id'],conversation_id=fixture.c['id'],
        source_ids=[source],provider='deepseek',model='retry-project',format='docx',review_mode='express'))

@server.app.post('/__retry_test__/book')
def launch_book():
    return library_worker.new_read_job(fixture.b['id'],[node['id']],'deepseek','retry-book',foreground=True)

@server.app.get('/__retry_test__/state')
def state():return {'failures':failures,'calls':fixture.calls}

mount=next(route for route in server.app.routes if getattr(route,'name',None)=='web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
if __name__=='__main__':asyncio.run(fixture.main())
