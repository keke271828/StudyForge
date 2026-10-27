"""Controlled structure and tutor requests; no external model traffic."""
import asyncio,json
from scripts import smoke_knowledge_continuity as base
from studyforge.learning_signals import learning_excerpt
from studyforge.db import many
f=base.f
base.graph['relations'][0]['reason']+=' AI_REFERENCE_ONLY：这只是 AI 的整理，不是学生的理解陈述。'
original=f.respond
tutor_requests=[]
async def respond(request):
    if request.method=='GET':return await original(request)
    payload=json.loads(request.content)
    if '【资料知识结构整理】' in payload['messages'][0]['content']:return await original(request)
    assert payload.get('stream'),'Only explicit tutor streaming is expected'
    f.calls.append(payload);tutor_requests.append(payload)
    answer='先把目标写成 $a=F/m$。已知 $F=ma$，因为 $m>0$，两边同除以 $m$ 才是合法的。这个变形保留了质量恒定与非零的条件。'
    return f.httpx.Response(200,text='data: '+f.j({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
f.respond=respond
@f.server.app.get('/__questions_ui__/state')
def state():return {**base.state(),'tutor_requests':tutor_requests,
    'profile_candidates':[learning_excerpt(row['content'],'当前在讲解数学推导的条件。') for row in many("SELECT content FROM messages WHERE role='user'")]}
mount=next(r for r in f.server.app.routes if getattr(r,'name',None)=='web');f.server.app.router.routes.remove(mount);f.server.app.router.routes.append(mount)
if __name__=='__main__':asyncio.run(f.main())
