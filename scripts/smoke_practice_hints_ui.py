"""Fresh ordinary worksheet, fixed no-model hints, and an intentionally held grader."""
import asyncio
from pathlib import Path

from scripts import smoke_library_ui as fixture
from studyforge import server
from studyforge.db import execute,j,many,now,one,uid,unj
from tests.test_homework import Teacher as BaseTeacher


class Teacher(BaseTeacher):
    async def complete(self,system,user,**kwargs):
        result=await super().complete(system,user,**kwargs)
        value=unj(result)
        if 'scores' in value:
            value['feedback']=['本验收桩接受此概念区分，用于核对提示记录。','本验收桩接受2+3=5，用于核对提示记录。']
            value['overall_feedback']='固定验收评分，不是实际模型的质量或掌握度评价。'
            return j(value)
        return result

fixture.enable_semantic(False)
ident=uid();questions=[{'index':0,'topic':'高斯定律','question':'说明封闭面电通量与面内电荷的关系，并解释各个量。'},
    {'index':1,'topic':'加法','question':'计算2+3并说明步骤。'}]
execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(ident,fixture.p['id'],'[]','按题提示验收',j(questions),
    j([{'index':0,'solution':'PRIVATE_REFERENCE_GAUSS：净通量与内部净电荷有关。','rubric':'正确概念。'},
       {'index':1,'solution':'PRIVATE_REFERENCE_ADD：2+3=5。','rubric':'正确计算。'}]),2,'assigned',now()))
teacher=Teacher(scores=(100,100),unknown=False);teacher.hold=True
async def client(*args,**kwargs):return teacher
async def choose(*args,**kwargs):pass
server.assessment_client=client;server.choose_generation_model=choose
fixture.case.update(exercise_id=ident)


@server.app.get('/__hint_test__/snapshot')
def snapshot():
    attempt=one('SELECT * FROM homework_attempts WHERE exercise_set_id=?',(ident,))
    return {'hints':many('SELECT question_index,kind,level FROM practice_hints WHERE exercise_set_id=?',(ident,)),
        'submissions':many('SELECT grade_json FROM submissions WHERE exercise_set_id=?',(ident,)),
        'mastery':many('SELECT * FROM mastery'),'teacher_calls':len(teacher.calls),
        'worksheet_status':one('SELECT status FROM exercise_sets WHERE id=?',(ident,))['status'],
        'attempt':({key:attempt[key] for key in ('id','status','solution_artifact_id','feedback_artifact_id')} if attempt else None)}


@server.app.post('/__hint_test__/release')
def release():teacher.release.set();return {'ok':True}


mount=next(route for route in server.app.routes if getattr(route,'name',None)=='web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
if __name__=='__main__':asyncio.run(fixture.main())
