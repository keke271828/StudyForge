"""Real UI submits a synthetic worksheet which changes during its mocked lesson."""
import asyncio
import json
from scripts import smoke_homework_reader_ui as base
from studyforge import homework,server
from studyforge.db import execute,j,many,now,one,uid,unj
from tests.test_homework import Teacher

fixture=base.fixture
set_id=uid();worksheet=base.source.worksheet
execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
    (set_id,base.source.project['id'],'[]','处理中改题验收',worksheet['questions_json'],worksheet['solutions_json'],2,'assigned',now()))
teacher=Teacher(unknown=False)

async def respond(request):
    if request.method=='GET':return fixture.httpx.Response(200,json={'data':[{'id':'deepseek-flash'}]})
    body=json.loads(request.content);fixture.calls.append(body)
    system=body['messages'][0]['content'];user=body['messages'][-1]['content']
    result=await teacher.complete(system,user)
    if '逐题诊断错因并补讲' in system:
        execute('UPDATE exercise_sets SET difficulty=4 WHERE id=?',(set_id,))
    return fixture.httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':result},'finish_reason':'stop'}]})

fixture.respond=respond
fixture.case.update(inflight_worksheet=set_id)

@server.app.get('/__inflight__/evidence')
def evidence():
    row=one('SELECT * FROM homework_attempts WHERE exercise_set_id=?',(set_id,))
    if not row:return {'accepted':False}
    task=one('SELECT status,error FROM jobs WHERE id=?',(row['job_id'],))
    return {'accepted':True,'attempt':row['id'],'job':task,
        'analysis_saved':bool(unj(row['analysis_json'],{})),
        'score_count':len(many('SELECT id FROM submissions WHERE exercise_set_id=?',(set_id,))),
        'feedback_registered':bool(row['feedback_artifact_id']),
        'calls':len(fixture.calls)}

mount=next(route for route in server.app.routes if getattr(route,'name',None)=='web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)

if __name__=='__main__':asyncio.run(fixture.main())
