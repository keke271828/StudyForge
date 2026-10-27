"""Isolated persisted passage references, desktop and paired HTTPS mobile."""
import asyncio
import json
import os
from pathlib import Path
import sys

folder=Path(__file__).resolve().parents[1]/'build'/sys.argv[1]
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
from scripts import smoke_library_ui as fixture
from studyforge.db import execute,j,many,now,uid

fixture.enable_semantic(False)
fixture.case['process_id']=os.getpid()
text='# 第一段\n'+('已有解释只是用于定位。'*540)+'\n🔎 为何“任意正数”允许选择 ε=(b−a)/2？\r\n因为 a<b，所选值为正，可以将全称命题用于这一特例。\n\n## 后续内容\n最后还讲过如何取最大阈值。'
mid=uid();execute('INSERT INTO messages VALUES (?,?,?,?,?)',(mid,fixture.c['id'],'assistant',text,now()))
short=uid();execute('INSERT INTO messages VALUES (?,?,?,?,?)',(short,fixture.c['id'],'assistant','偏导和沿轨迹的时间导数不同，沿轨迹还需应用链式法则。',now()))
other=fixture.conversations.create(fixture.p['id'],'deepseek')
fixture.case.update(target_message_id=mid,short_message_id=short,same_project_other_chat=other['id'],target_quote='🔎 为何“任意正数”允许选择 ε=(b−a)/2？\r\n因为 a<b，所选值为正，可以将全称命题用于这一特例。')


async def respond(request):
    if request.method=='GET':return await fixture.respond(request)
    body=json.loads(request.content);fixture.calls.append(body)
    assert '明确引用范围' in body['messages'][-1]['content']
    answer='针对所选原句：已知定义对任意正数成立，而所取数为正，因此可以使用这个特例。这没有把定义改成仅对该值成立。'
    return fixture.httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')


@fixture.server.app.get('/__focus_test__/state')
def state():
    return {'calls':fixture.calls,'references':many('SELECT * FROM message_focus_references'),
        'users':many("SELECT content FROM messages WHERE role='user'"),'scores':many('SELECT * FROM mastery'),
        'insights':many('SELECT * FROM learning_insights')}


mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)
fixture.httpx.AsyncClient=lambda *a,**kw:fixture.original(transport=fixture.httpx.MockTransport(respond))
if __name__=='__main__':asyncio.run(fixture.main())
