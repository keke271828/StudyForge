"""Synthetic historical attribution, actual desktop/paired-phone gateway, no cloud."""
import asyncio
import json
import os

from scripts import smoke_library_ui as fixture
from studyforge import learning_memory as memory,server
from studyforge.db import execute,j,many,one,now,uid

fixture.enable_semantic(False)
project=fixture.p['id'];chat=fixture.c['id'];message=uid()
external='我认为高斯定律说明没有净电荷时电场一定为零。'
own='我不理解高斯定律里的净通量与局部电场有什么区别。'
raw='> '+external+'\n\n我的问题：'+own
execute('INSERT INTO messages VALUES (?,?,?,?,?)',(message,chat,'user',raw,now()))
event=memory.record_event('legacy-voice','chat',{'message_id':message,'student_text':external+'\n'+own},project,chat,analyzed=True)
memory._save_insight(event,'引用造成的误判','gap','concepts','COPIED_CLAIM_NO_TEACHING',external,'暂定',anchors=['高斯定律'])
memory._save_insight(event,'高斯定律','gap','concepts','OWN_QUESTION：需要解释净通量与局部电场的区别。',own,'暂定',anchors=['高斯定律'])
wrong=one('SELECT id FROM learning_insights WHERE topic=?',('引用造成的误判',))['id']
execute('INSERT OR REPLACE INTO learning_event_filters VALUES (?,1,1)',(event,))
fixture.case.update(profile_wrong_id=wrong,profile_message_id=message,external_quote=external,own_question=own)


@server.app.get('/__voice_test__/snapshot')
def snapshot():
    return {'messages':many('SELECT id,content FROM messages WHERE id=?',(message,)),
            'insights':many('SELECT id,observation,quote FROM learning_insights WHERE event_id=?',(event,)),
            'mastery':many('SELECT * FROM mastery'),'submissions':many('SELECT * FROM submissions')}


async def response(request):
    if request.method=='GET':return fixture.httpx.Response(200,json={'data':[{'id':'deepseek-flash'}]})
    body=json.loads(request.content);fixture.calls.append(body)
    (fixture.case_path.parent/'private-model-requests.json').write_text(j(fixture.calls),encoding='utf-8')
    answer='净通量是整体有符号求和，局部电场是各点的矢量；需要区分它们。'
    if body.get('stream'):return fixture.httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    return fixture.httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':answer},'finish_reason':'stop'}]})


mount=next(route for route in server.app.routes if getattr(route,'name',None)=='web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
fixture.httpx.AsyncClient=lambda *a,**kw:fixture.original(transport=fixture.httpx.MockTransport(response))
if __name__=='__main__':asyncio.run(fixture.main())
