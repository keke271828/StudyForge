"""Real desktop and paired HTTPS phone with synthetic completed followups."""
import asyncio
import json
import os
from pathlib import Path
import sys

folder=Path(__file__).resolve().parents[1]/'build'/sys.argv[1]
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
from scripts import smoke_library_ui as fixture
from scripts.lesson_check_fixture import seed
from studyforge import conversations
from studyforge.db import j

fixture.enable_semantic(False)
fixture.ai.save_settings({'generation_parallel':False})
pc=seed(folder/'pc','math',fixture.p['id'],fixture.c['id'])
second=conversations.create(fixture.p['id'],'deepseek','deepseek-flash')
phone=seed(folder/'phone','causal',fixture.p['id'],second['id'])
conversations.update(fixture.c['id'],fixture.p['id'],{'source_ids':[phone['source_id']]})
conversations.activate(fixture.c['id'])
fixture.case.update(pc=pc,phone=phone,phone_conversation_id=second['id'],process_id=os.getpid())
audit_active={'math':0,'causal':0}
audit_peak={'math':0,'causal':0}


@fixture.server.app.get('/__lesson_review__/state')
def audit_state():return {'active':dict(audit_active),'peak':dict(audit_peak)}


# Test routes must precede the production static-file mount.
mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)


async def respond(request):
    if request.method=='GET':return await fixture.respond(request)
    body=json.loads(request.content);fixture.calls.append(body);system=body['messages'][0]['content']
    if '严谨的习题设计者' in system:
        spec,_=json.JSONDecoder().raw_decode(body['messages'][-1]['content'].split('补讲检查目标：',1)[1])
        if len(fixture.calls)==1:await asyncio.sleep(2)
        question=('UI_CHECK_MATH：数轴上两点为2和8，分别取半径3的开区间，判断有无共同点并说明理由；再比较半径4的情况。' if '极限' in spec['topic'] else
                  'UI_CHECK_CAUSAL：同校学生自选是否记笔记，记笔记组平均分更高。若人数从200增到20000，哪些不确定性可能减小，哪些替代解释仍需排除？请说明理由。')
        answer={'questions':[{'question':question,'topic':spec['topic'],'solution':'PRIVATE_CHECK_SOLUTION：完整参考解。',
            'rubric':[{'criterion':'PRIVATE_CHECK_RUBRIC：概念与条件','points':50},{'criterion':'关键理由','points':50}],'source_url':'',
            'lesson_check_focus':'PRIVATE_CHECK_FOCUS：通过改变一个条件检查原补讲的推理缺口，而不直接复述原答案。'}]}
    elif '独立解题员' in system:answer={'answers':[{'index':0,'solution':'独立核对完成。','issues':[]}]}
    else:
        case='math' if 'UI_CHECK_MATH' in body['messages'][-1]['content'] else 'causal'
        audit_active[case]+=1;audit_peak[case]=max(audit_peak[case],audit_active[case])
        try:await asyncio.sleep(.4)
        finally:audit_active[case]-=1
        answer={'passed':True,'issues':[]}
    if body.get('stream'):return fixture.httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':j(answer)},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    return fixture.httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':j(answer)},'finish_reason':'stop'}]})


fixture.httpx.AsyncClient=lambda *a,**kw:fixture.original(transport=fixture.httpx.MockTransport(respond))
if __name__=='__main__':asyncio.run(fixture.main())
