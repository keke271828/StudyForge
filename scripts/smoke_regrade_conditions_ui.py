"""Pending, fully submitted records rechecked through real desktop/phone UI."""
import asyncio

from scripts import smoke_library_ui as fixture
from studyforge import homework,server,learning_profile
from studyforge.db import create_job,execute,j,many,now,one,uid,unj,update_job

fixture.enable_semantic(False)
items={}
for name,context in [('supported',{'hint_levels':{},'used_notes':True,'is_review':False,'timing':[],
    'notice':'原始自报：参考过笔记。'}),('partial',{'used_notes':False})]:
    ident,attempt,submission=uid(),uid(),uid()
    title='评分复核 · '+('参考过笔记' if name=='supported' else '旧条件不完整')
    questions=[{'index':0,'topic':title,'question':'计算2+3并写出步骤。'}]
    solutions=[{'index':0,'solution':'2+3=5。','rubric':'按步骤和结论核对。'}]
    answers=['从2开始依次加三个1，得到3、4、5，所以2+3=5。']
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(ident,fixture.p['id'],'[]',title,
        j(questions),j(solutions),2,'grading_review_required',now()))
    row=one('SELECT * FROM exercise_sets WHERE id=?',(ident,))
    grade={'scores':[None],'score':None,'tentative_scores':[20],'feedback':['评分尚待核实。'],
        'grading_verification_required':True,'provisional':True,'uncertainties':['旧参考评分点尚待核实'],
        'practice_context':context,'recovery_mode':'adaptive','submission_id':submission}
    execute('INSERT INTO submissions VALUES (?,?,?,?,?,?,?)',(submission,ident,j(answers),j(grade),-1,'{}',now()))
    execute('INSERT INTO practice_options VALUES (?,?,?)',(ident,'strict',now()))
    options={'provider':'deepseek','model':'fixture-regrade','reasoning_effort':'none','coding':False,
        'conversation_id':fixture.c['id'],'used_notes':False,'recovery_mode':'strict','profile':{},
        'teaching':{'learning_mode':'deep','explanation_style':'clear','output_language':'zh'}}
    payload={'workflow_version':1,'project_id':fixture.p['id'],'set_id':ident,'attempt_id':attempt,
        'conversation_id':fixture.c['id'],'values':options,'exercise_version':homework.version(row)}
    job=create_job(fixture.p['id'],'homework_grade',payload)
    update_job(job,'completed',100,{'stage':'评分待核实，未定分'})
    execute('INSERT INTO homework_attempts(id,exercise_set_id,project_id,conversation_id,job_id,source_version,'
        'answers_json,options_json,grade_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        (attempt,ident,fixture.p['id'],fixture.c['id'],job,homework.version(row),j(answers),j(options),j(grade),'awaiting_grade_review',now(),now()))
    items[name]={'set_id':ident,'attempt_id':attempt,'submission_id':submission,'topic':title}


class Teacher:
    model='fixture-regrade';effort='none'
    def __init__(self):self.calls=[]
    async def close(self):pass
    async def complete(self,system,user,**kwargs):
        self.calls.append((system,user))
        return j({'scores':[100],'feedback':['验收桩接受所给加法步骤，固定100分用于检查复核记录。'],
            'uncertainties':[],'overall_feedback':'验收桩评分，不代表真实模型质量。'})


teacher=Teacher()
async def client(*args,**kwargs):return teacher
server.assessment_client=client
fixture.case.update(regrade_items=items)


@server.app.get('/__regrade_test__/state')
def state():
    return {'calls':len(teacher.calls),'submissions':[dict(row,grade=unj(row['grade_json'])) for row in many('SELECT * FROM submissions')],
        'sets':many('SELECT id,status FROM exercise_sets'),'attempts':many('SELECT id,status,feedback_artifact_id FROM homework_attempts'),
        'profile':learning_profile.effective_profile(),'events':many("SELECT event_key,payload_json FROM learning_events WHERE kind='做题'")}


mount=next(route for route in server.app.routes if getattr(route,'name',None)=='web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
if __name__=='__main__':asyncio.run(fixture.main())
