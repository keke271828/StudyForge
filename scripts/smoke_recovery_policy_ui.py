"""Isolated real UI, queued diagnosis and fixed grading; no cloud requests."""
import asyncio
import json

from scripts import smoke_library_ui as fixture
from studyforge import server
from studyforge.db import execute,j,many,now,uid,unj

fixture.enable_semantic(False)
ids={}
for name,policy in [('adaptive','strict'),('strict','adaptive'),('coding','strict')]:
    ident=uid();ids[name]=ident
    questions=[{'index':0,'topic':'加法','question':'计算2+3并写出步骤。'}]
    if name=='coding':questions[0].update(language='python',question='实现add(a,b)，返回两数之和。')
    solutions=[{'index':0,'solution':'PRIVATE_REFERENCE：2+3=5。','rubric':'按明确评分点核对。'}]
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(ident,fixture.p['id'],'[]',
        '低分流程验收 · '+name,j(questions),j(solutions),2,'assigned',now()))
    execute('INSERT INTO practice_options VALUES (?,?,?)',(ident,policy,now()))


class Teacher:
    model='fixture-recovery';effort='none'
    def __init__(self):self.calls=[];self.release=asyncio.Event();self.waiting=False
    async def close(self):pass
    async def complete(self,system,user,**kwargs):
        self.calls.append((system,user))
        if '逐题诊断错因并补讲' in system:
            self.waiting=True;await asyncio.wait_for(self.release.wait(),90)
            data=json.JSONDecoder().raw_decode(user)[0]
            return j({'items':[{'index':i,'kind':'implementation','confidence':'supported',
                'cause':'本验收桩按作答中的加法错误定位。','evidence':[{'source':'answer','quote':data['student_answers'][i]}],
                'clarification':'','explanation':'从2开始依次加三个1，得到3、4、5，因此2+3=5。再用5减3等于2核对，可定位本次加法错误；该示例不说明其他知识已经掌握。',
                'check':'用逆运算核对加法结果。'} for i in data['wrong_indices']]})
        return j({'scores':[79],'feedback':['验收桩固定79分，用于核对两条低分流程；不是实际模型评分。'],
            'uncertainties':[],'overall_feedback':'相同作答、相同固定评分，比较低分后的实际流程。'})


teacher=Teacher()
async def client(*args,**kwargs):return teacher
async def choose(*args,**kwargs):pass
server.assessment_client=client;server.choose_generation_model=choose
fixture.case.update(exercise_ids=ids)


@server.app.get('/__recovery_test__/state')
def state():
    return {'calls':len(teacher.calls),'waiting':teacher.waiting,'released':teacher.release.is_set(),
        'sets':many('SELECT id,status FROM exercise_sets'),
        'attempts':[dict(row,options=unj(row.pop('options_json')),grade=unj(row.pop('grade_json')))
            for row in many('SELECT id,exercise_set_id,status,options_json,grade_json,feedback_artifact_id FROM homework_attempts')],
        'submissions':many('SELECT exercise_set_id,score FROM submissions'),
        'feynman_jobs':many("SELECT id FROM jobs WHERE kind IN ('feynman','advance','repair')")}


@server.app.post('/__recovery_test__/release')
async def release():teacher.release.set();return {'ok':True}


mount=next(route for route in server.app.routes if getattr(route,'name',None)=='web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
if __name__=='__main__':asyncio.run(fixture.main())
