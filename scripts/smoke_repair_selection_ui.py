"""Native desktop/paired HTTPS selection, mocked model, isolated synthetic work."""
import asyncio
import json
import os
from pathlib import Path
import sys

folder=Path(__file__).resolve().parents[1]/'build'/sys.argv[1]
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
from scripts import smoke_library_ui as fixture
from tests.test_repair_selection import two_errors
from studyforge import homework,server
from studyforge.db import execute,j,many,one,unj
from studyforge.exporters import export_document

fixture.enable_semantic(False)
case,worksheet,submission=two_errors(folder)
row=homework.get_attempt(case['attempt_id'])
file=export_document(homework.report_document(row,worksheet,unj(submission['grade_json']),unj(row['analysis_json'])),
    'docx','合成错题反馈','selection-feedback.docx')
artifact=server.add_artifact(case['project_id'],[],'grading','docx','合成错题反馈',file,
    {'homework_attempt_id':case['attempt_id'],'exercise_set_id':case['set_id'],'conversation_id':case['conversation_id']})
execute('UPDATE homework_attempts SET feedback_artifact_id=? WHERE id=?',(artifact['id'],case['attempt_id']))
homework.notify(row,'本次合成作业已批改，可按题回看或主动选择卡点再练。')
fixture.case.update(case,process_id=os.getpid())
current=[]


async def response(request):
    if request.method=='GET':return fixture.httpx.Response(200,json={'data':[{'id':'deepseek-flash'}]})
    body=json.loads(request.content);fixture.calls.append(body);system=body['messages'][0]['content']
    if '严谨的习题设计者' in system:
        spec,_=json.JSONDecoder().raw_decode(body['messages'][-1]['content'].split('修复目标数据：',1)[1])
        current[:]=spec['targets']
        answer={'questions':[{'question':f'SELECTED_NEW_{target["index"]}：在不同条件下说明这个知识点的适用范围，并逐步写出判断理由。',
            'topic':target['topic'],'solution':'PRIVATE_SOLUTION：这是隔离夹具的完整参考解析。',
            'rubric':'区分条件、结论和理由。','source_url':'','repair_target_index':target['index'],
            'repair_focus':'PRIVATE_FOCUS：检查对应卡点并观察学生当前的推理步骤。'} for target in current]}
    elif '独立解题员' in system:answer={'answers':[{'index':index,'solution':'独立求解完成。','issues':[]} for index in range(len(current))]}
    else:answer={'passed':True,'issues':[]}
    if body.get('stream'):return fixture.httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':j(answer)},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    return fixture.httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':j(answer)},'finish_reason':'stop'}]})


@server.app.get('/__repair_test__/snapshot')
def snapshot():
    return {'submissions':len(many('SELECT * FROM submissions')),'learning_events':len(many('SELECT * FROM learning_events')),
            'mastery':len(many('SELECT * FROM mastery')),'parent_score':one('SELECT score FROM submissions WHERE id=?',(case['submission_id'],))['score']}


mount=next(route for route in server.app.routes if getattr(route,'name',None)=='web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
fixture.httpx.AsyncClient=lambda *args,**kwargs:fixture.original(transport=fixture.httpx.MockTransport(response))
if __name__=='__main__':asyncio.run(fixture.main())
