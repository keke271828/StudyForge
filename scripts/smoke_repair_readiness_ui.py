"""Real submitted work, interrupted diagnosis, project restore and phone recovery."""
import asyncio
import json

from scripts import smoke_library_ui as fixture
from studyforge import server
from studyforge.db import execute,j,many,now,one,uid,unj

fixture.enable_semantic(False)
ident=uid();legacy=uid()
questions=[{'index':0,'topic':'高斯定律','question':'内部净电荷为零能否推出内部电场处处为零？说明理由。'},
    {'index':1,'topic':'加法','question':'计算2+3并说明步骤。'}]
solutions=[{'index':0,'solution':'净通量为零可以来自穿入穿出抵消，不能确定各点场为零。','rubric':'区分净和与局部。'},
    {'index':1,'solution':'2+3=5。','rubric':'结果与步骤。'}]
execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(ident,fixture.p['id'],'[]','先补讲后再练验收',j(questions),j(solutions),2,'assigned',now()))
execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(legacy,fixture.p['id'],'[]','满分普通练习',j([questions[1]|{'index':0}]),j([solutions[1]|{'index':0}]),2,'passed',now()))
execute('INSERT INTO submissions VALUES (?,?,?,?,?,?,?)',(uid(),legacy,j(['2+3=5。']),j({'scores':[100],'score':100,'feedback':['合成满分记录。']}),100,'{}',now()))


class Teacher:
    model='fixture-readiness';effort='none'
    def __init__(self):self.calls=[];self.hold=True;self.waiting=False
    async def close(self):pass
    async def complete(self,system,user,**kwargs):
        phase='analysis' if '逐题诊断错因并补讲' in system else 'grade'
        self.calls.append(phase)
        if phase=='analysis':
            if self.hold:
                self.hold=False;self.waiting=True
                try:await asyncio.Event().wait()
                finally:self.waiting=False
            packet=json.JSONDecoder().raw_decode(user)[0];causes=packet['student_causes'];known=bool(causes)
            quote=causes[0]['text'] if known else packet['student_answers'][0]
            return j({'items':[{'index':0,'kind':'terminology','confidence':'self_report' if known else 'uncertain',
                'cause':'学生自报混淆净通量和各点电场。' if known else '原作答不足以确定具体混淆的环节。',
                'evidence':[{'source':'questionnaire' if known else 'answer','quote':quote}],
                'clarification':'你当时怎样理解净通量和各点电场的关系？',
                'explanation':'净通量是对闭合面上有正负的穿入、穿出贡献求和，合计为零可以来自抵消。电场描述各个位置的局部作用，所以一个整体积分为零不能决定每个位置的场为零。',
                'check':'先区分整体净和与局部量，再检验条件。'}]})
        return j({'scores':[90,100],'feedback':['净和为零不能确定各点场为零。','加法步骤正确。'],
            'uncertainties':[],'overall_feedback':'验收桩固定分数，仅核对流程。',
            'diagnostics':[{'index':0,'kind':'terminology','quote':'我认为内部净电荷为零就能推出里面每个点的电场为零。',
                'reason':'暂定需要区分整体净和与局部场。'}]})


teacher=Teacher()
async def client(*args,**kwargs):return teacher
async def choose(*args,**kwargs):pass
server.assessment_client=client;server.choose_generation_model=choose
fixture.case.update(exercise_id=ident,legacy_set_id=legacy)


@server.app.get('/__readiness_test__/state')
def state():
    attempt=one('SELECT id,job_id,status,feedback_artifact_id,grade_json FROM homework_attempts WHERE exercise_set_id=?',(ident,))
    return {'calls':teacher.calls,'waiting':teacher.waiting,'attempt':attempt,
        'job':one('SELECT status FROM jobs WHERE id=?',(attempt['job_id'],)) if attempt else None,
        'submissions':many('SELECT id,score FROM submissions WHERE exercise_set_id=?',(ident,)),
        'sets':many('SELECT id FROM exercise_sets'),
        'new_practice_jobs':many("SELECT id FROM jobs WHERE kind IN ('repair','advance')")}


mount=next(route for route in server.app.routes if getattr(route,'name',None)=='web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
if __name__=='__main__':asyncio.run(fixture.main())
