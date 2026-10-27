"""Saved versions and legacy boundaries through native paired homework."""
import asyncio
import json
from datetime import timedelta

from scripts import smoke_library_ui as fixture
from studyforge import ai,practice,server
from studyforge.db import execute,j,many,one,uid,unj
from studyforge.review_versions import assessment_basis

fixture.enable_semantic(False)
ai.save_settings({'library_reference_mode':'off','background_learning_enabled':False})
stamp=practice.clock_now()-timedelta(days=3)
cases=[];calls=[]
for verified,project,topic,question,solution,rubric in [
    (True,fixture.p,'高斯定律','净电通量为零能否推出电场处处为零？说明理由。',
        '不能。净通量是带符号求和，穿入与穿出可抵消，均匀非零电场就是反例。',
        'SAVED_GAUSS_RUBRIC：区分整体净通量和局部电场，并提供反例。'),
    (False,fixture.q,'相关与因果','两万人的调查有显著相关，能否因此证明因果？说明理由。',
        '不能。大样本减少抽样误差，不能自动排除混杂和反向因果。',
        'LEGACY_CAUSAL_RUBRIC：区分随机误差与系统偏差。')]:
    ident=uid();questions=[{'index':0,'topic':topic,'question':question}]
    private=[{'index':0,'solution':solution,'rubric':rubric}]
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(ident,project['id'],'[]',topic+'原题',
        j(questions),j(private),2,'passed',stamp.isoformat()))
    grade={'score':80,'scores':[80],'feedback':['隔离验收的合成原始评分。']}
    if verified:grade['assessment_version']=assessment_basis(one('SELECT * FROM exercise_sets WHERE id=?',(ident,)))
    execute('INSERT INTO submissions VALUES (?,?,?,?,?,?,?)',(uid(),ident,j(['不能仅凭这个条件推论，具体理由仍需核对。']),
        j(grade),80,'{}',stamp.isoformat()))
    practice.schedule_review(ident,1)
    execute('UPDATE review_items SET due_at=?,created_at=?,updated_at=? WHERE origin_set_id=?',
        ((stamp+timedelta(days=1)).isoformat(),stamp.isoformat(),stamp.isoformat(),ident))
    cases.append({'origin':ident,'item_id':one('SELECT id FROM review_items WHERE origin_set_id=?',(ident,))['id'],
        'verified':verified,'topic':topic,'question':question,'rubric':rubric})
fixture.case.update(version_cases=cases)


class Teacher:
    model='fixture-review-versions';effort='none'
    async def close(self):pass
    async def complete(self,system,user,**kwargs):
        analysis='逐题诊断错因并补讲' in system
        calls.append({'kind':'analysis' if analysis else 'grade','saved_question':cases[0]['question'] in user,
            'saved_rubric':cases[0]['rubric'] in user,'changed_parent':'NEW_PARENT' in user})
        if not analysis:
            return j({'scores':[90],'feedback':['验收固定90分，理由仍需补全。'],
                'uncertainties':[],'overall_feedback':'受控评分只验证版本与交付流程。'})
        data=json.JSONDecoder().raw_decode(user)[0]
        gauss='高斯定律' in user
        return j({'items':[{'index':index,'kind':'argumentation','confidence':'supported',
            'cause':'作答明确自述尚不确定完整论证，需要补足关键理由。',
            'evidence':[{'source':'answer','quote':data['student_answers'][index]}],
            'explanation':('净通量是对闭合曲面上带正负号的通量求和。均匀电场从一侧穿入、另一侧穿出，贡献可以抵消，净通量为零并不要求各点电场为零。要先区分整体约束与局部量，再用满足条件的反例核对推论。' if gauss else
                '显著相关说明观察到共同变化，但大样本只能减小随机抽样误差。若学习动机同时影响记笔记和成绩，关联仍可能来自混杂。要论证因果，需要合适的研究设计及可检查的假设，不能省略替代解释。'),
            'check':'明确结论后，逐步说明为什么现有条件不能排除另一种情况。'} for index in data['wrong_indices']]})


async def client(*args,**kwargs):return Teacher()
async def choose(*args,**kwargs):pass
server.assessment_client=client;server.choose_generation_model=choose


@server.app.post('/__review_versions_test__/change')
def change():
    execute('UPDATE exercise_sets SET questions_json=?,solutions_json=?,difficulty=5 WHERE id=?',
        (j([{'index':0,'topic':'NEW_PARENT_TOPIC','question':'NEW_PARENT_QUESTION：已修改的另一道题。'}]),
         j([{'index':0,'solution':'NEW_PARENT_SOLUTION','rubric':'NEW_PARENT_RUBRIC'}]),cases[0]['origin']))
    return {'changed':True}


@server.app.get('/__review_versions_test__/state')
def state():
    from studyforge.learning_profile import effective_profile
    return {'calls':calls,'sets':many('SELECT id,project_id,status FROM exercise_sets'),
        'queue':many('SELECT * FROM review_items'),'sessions':many('SELECT * FROM review_sessions'),
        'submissions':many('SELECT id,exercise_set_id,score,grade_json FROM submissions'),
        'profile':effective_profile(),'events':many("SELECT id,event_key FROM learning_events WHERE kind='做题'"),
        'attempts':many('SELECT id,exercise_set_id,status,job_id,feedback_artifact_id FROM homework_attempts'),
        'jobs':many('SELECT id,status,error FROM jobs')}


mount=next(route for route in server.app.routes if getattr(route,'name',None)=='web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
if __name__=='__main__':asyncio.run(fixture.main())
