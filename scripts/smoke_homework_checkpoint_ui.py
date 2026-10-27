"""Actual failed grading boundary, followed by desktop retry and phone delivery."""
import asyncio
import json
from unittest.mock import patch
from scripts import smoke_homework_reader_ui as base
from studyforge import server,workflows,homework
from studyforge.db import execute,j,many,now,one,uid,unj
from tests.test_homework import Teacher,finish

fixture=base.fixture
set_id=uid();worksheet=base.source.worksheet
execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
    (set_id,base.source.project['id'],'[]','中断后继续补讲验收',worksheet['questions_json'],worksheet['solutions_json'],2,'assigned',now()))
teacher=Teacher(unknown=False)
real_phase=workflows.phase

async def interrupted(name,operation):
    if name=='homework:grade':await operation();raise PermissionError('controlled interruption after committed grade')
    return await real_phase(name,operation)

async def choose(*a,**kw):pass

async def seed():
    value=server.SubmitIn(answers=['内电荷为零所以场为零，我不知道怎样区分','2+3=4'],provider='deepseek',
        model='deepseek-flash',conversation_id=base.source.chat['id'],detailed_feedback=True,background=True)
    with patch.object(server,'client_for',lambda *a,**kw:teacher),patch.object(server,'choose_generation_model',choose),patch.object(workflows,'phase',interrupted):
        accepted=await server.submit_answers(set_id,value)
        assert (await finish(accepted))['status']=='failed'
    assert len(teacher.calls)==2
    return accepted

accepted=asyncio.run(seed())
before_mastery=j(many('SELECT * FROM mastery ORDER BY topic'))
before_events=one("SELECT COUNT(*) AS n FROM learning_events WHERE kind='做题'")['n']
submission=one('SELECT id FROM submissions WHERE exercise_set_id=?',(set_id,))['id']
seed_evidence={'grade_model_requests':len(teacher.calls),'submission':submission,'attempt':accepted['id'],
    'phase_cache_present':bool(one("SELECT 1 FROM generation_steps WHERE job_id=? AND step_key='phase:homework:grade'",(accepted['job_id'],)))}
(base.source.folder/'seed-evidence.json').write_text(j(seed_evidence),encoding='utf-8')
teacher=Teacher(unknown=False)

async def respond(request):
    if request.method=='GET':return fixture.httpx.Response(200,json={'data':[{'id':'deepseek-flash'}]})
    body=json.loads(request.content);fixture.calls.append(body)
    result=await teacher.complete(body['messages'][0]['content'],body['messages'][-1]['content'])
    return fixture.httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':result},'finish_reason':'stop'}]})

fixture.respond=respond
fixture.case.update(checkpoint_attempt=accepted['id'],checkpoint_worksheet=set_id)

@server.app.get('/__checkpoint__/evidence')
def evidence():
    row=homework.get_attempt(accepted['id'])
    return {'job':one('SELECT status,error FROM jobs WHERE id=?',(accepted['job_id'],)),
        'submissions':one('SELECT COUNT(*) AS n FROM submissions WHERE exercise_set_id=?',(set_id,))['n'],
        'submission_unchanged':one('SELECT id FROM submissions WHERE exercise_set_id=?',(set_id,))['id']==submission,
        'mastery_unchanged':j(many('SELECT * FROM mastery ORDER BY topic'))==before_mastery,
        'assessment_events_unchanged':one("SELECT COUNT(*) AS n FROM learning_events WHERE kind='做题'")['n']==before_events,
        'feedback_registered':bool(row['feedback_artifact_id']),'model_requests':len(fixture.calls)}

mount=next(route for route in server.app.routes if getattr(route,'name',None)=='web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)

if __name__=='__main__':asyncio.run(fixture.main())
