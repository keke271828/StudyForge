"""Run real task dispatch and desktop/phone controls on synthetic goal checks."""
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];CASE=ROOT/'build'/sys.argv[1]
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(CASE/'isolated-model')
from scripts import smoke_library_ui as fixture
from studyforge import conversations,learning_goals as goals,server
from studyforge.db import execute,j,now,uid

fixture.enable_semantic(False)
source=uid();original=fixture.case_path.parent/'理解检查原材料.txt'
original.write_text('收敛定义对任意正半径成立，序列的尾部落在极限的开邻域。若a<b，选择半距离得到两个不相交的开邻域，统一两个门槛后出现矛盾。更小的正半径也适用。',encoding='utf-8')
execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
        (source,fixture.p['id'],original.name,'.txt',str(original),'ready',now()))
goal=goals.save(fixture.p['id'],{'name':'极限的条件与构造','domain':'数学','intent':'deep','source_ids':[source]})
baseline=uid();old=[{'index':i,'question':f'BASE_{i}：解释收敛定义与邻域构造第{i+1}处的条件。','topic':goal['name']} for i in range(3)]
execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(baseline,fixture.p['id'],j([source]),'已完成的参考检查',j(old),
        j([{'index':i,'solution':f'BASE_PRIVATE_{i}','rubric':'基准评分'} for i in range(3)]),2,'passed',now()))
goals.register_check(baseline,fixture.p['id'],goals.check_spec(goals.get(goal['id'],fixture.p['id'])))
execute('INSERT INTO submissions VALUES (?,?,?,?,?,?,?)',(uid(),baseline,j(['BASE_STUDENT_PRIVATE']*3),
        j({'scores':[85]*3,'grading_verification_required':False,'practice_context':{'used_notes':False}}),85,'{}',now()))
goals.focus(fixture.p['id'],fixture.c['id'],goal['id'])
other_chat=conversations.create(fixture.p['id'],'deepseek','deepseek-flash')
execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),other_chat['id'],'user','FOREIGN_DIALOGUE_PRIVATE',now()))
conversations.activate(fixture.c['id'])
release=asyncio.Event();waiting=False;design_number=0

async def response(request):
    global waiting,design_number
    if request.method=='GET':return await fixture.respond(request)
    body=json.loads(request.content);fixture.calls.append(body)
    system=body['messages'][0]['content'];user=body['messages'][-1]['content']
    if '严谨的习题设计者' in system:
        spec,_=json.JSONDecoder().raw_decode(user.rsplit('目标数据：',1)[1].lstrip())
        if spec.get('kind','standard')=='standard' and not release.is_set():
            waiting=True
            await asyncio.wait_for(release.wait(),90)
        design_number+=1
        prefix='CONTEXT' if spec.get('kind')=='new_context' else 'STANDARD'
        answer={'questions':[{'question':f'{prefix}_{design_number}_{i}：在改变的条件中解释第{i+1}处构造与门槛的作用。',
            'solution':f'ANSWER_PRIVATE_{design_number}_{i}：完整推导。','rubric':'依据与条件分别计分。','topic':spec['profile_topic'],
            'assessment_dimension':dim,'source_url':'',
            'context_change':f'CHANGE_PRIVATE_{design_number}_{i}：改为不同的边界条件，重新检验邻域能否分离。'} for i,dim in enumerate(spec['dimensions'])]}
    elif '独立解题员' in system:
        answer={'answers':[{'index':i,'solution':'INDEPENDENT_PRIVATE_'+str(i),'issues':[]} for i in range(3)]}
    else:answer={'passed':True,'issues':[]}
    if body.get('stream'):
        return fixture.httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':j(answer)},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    return fixture.httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':j(answer)},'finish_reason':'stop'}]})

fixture.httpx.AsyncClient=lambda *a,**kw:fixture.original(transport=fixture.httpx.MockTransport(response))

@server.app.get('/__transfer_test__/state')
def test_state():return {'standard_waiting':waiting,'released':release.is_set(),'model_requests':len(fixture.calls)}

@server.app.post('/__transfer_test__/release')
def end_wait():release.set();return test_state()

mount=next(route for route in server.app.routes if getattr(route,'name',None)=='web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
fixture.case.update(goal_id=goal['id'],baseline_set_id=baseline,source_id=source,second_conversation_id=other_chat['id'],process_id=os.getpid())
if __name__=='__main__':asyncio.run(fixture.main())
