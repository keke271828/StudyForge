"""Real desktop review queue with recycle/restore and native phone submission."""
import asyncio
import json
from datetime import timedelta

from scripts import smoke_library_ui as fixture
from studyforge import ai,conversations,practice,server
from studyforge.db import create_project,execute,j,many,now,one,uid

fixture.enable_semantic(False)
ai.save_settings({'library_reference_mode':'off','background_learning_enabled':False})
target=create_project('混合复习工作区');chat=conversations.create(target['id'],'deepseek')
conversations.activate(fixture.c['id'])
stamp=practice.clock_now()-timedelta(days=3);origins=[]
for project,topic,question,solution in [
    (fixture.p,'相关与因果','统计相关能否单独证明因果？请说明理由。','不能；还需排除混杂、反向因果等替代解释。'),
    (fixture.q,'高斯定律','净电通量为零能否说明各点电场为零？请说明理由。','不能；净和可由正负抵消，不能决定各点局部量。')]:
    ident=uid();questions=[{'index':0,'topic':topic,'question':question}]
    private=[{'index':0,'solution':solution,'rubric':'结论和理由。'}]
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(ident,project['id'],'[]',topic+'原题',j(questions),j(private),2,'passed',stamp.isoformat()))
    execute('INSERT INTO submissions VALUES (?,?,?,?,?,?,?)',(uid(),ident,j(['不能单凭这个条件下结论，理由仍需核对。']),
        j({'score':80,'scores':[80],'feedback':['原始合成评分80。']}),80,'{}',stamp.isoformat()))
    practice.schedule_review(ident,1)
    execute('UPDATE review_items SET due_at=?,created_at=?,updated_at=? WHERE origin_set_id=?',
        ((stamp+timedelta(days=1)).isoformat(),stamp.isoformat(),stamp.isoformat(),ident))
    origins.append(ident)
fixture.case.update(review_target=target['id'],review_chat=chat['id'],review_origins=origins,
    review_item_ids=[one('SELECT id FROM review_items WHERE origin_set_id=?',(ident,))['id'] for ident in origins])
calls=[]


class Teacher:
    model='fixture-review-queue';effort='none'
    async def close(self):pass
    async def complete(self,system,user,**kwargs):
        analysis='逐题诊断错因并补讲' in system;calls.append('analysis' if analysis else 'grade')
        if analysis:
            data=json.JSONDecoder().raw_decode(user)[0]
            return j({'items':[{'index':index,'kind':'argumentation','confidence':'supported',
                'cause':'作答自述理由尚不完整，需继续核对具体论证。',
                'evidence':[{'source':'answer','quote':data['student_answers'][index]}],
                'explanation':('相关是共同变化的观察结果。若存在共同原因，两组变量可能一起改变而没有直接因果。要判断因果，应当明确干预、时间顺序与替代解释，不能仅凭一个关联结论省略这些环节。' if index==0 else
                    '净通量是对整个闭合曲面上带正负号的通量贡献求和。两侧穿入与穿出的贡献可以抵消，结果为零时各点电场仍可不为零。先明确积分的整体约束，再判断是否还有决定局部场的其他条件。'),
                'check':'先说明已有条件，再列出还不能排除的其他可能。'} for index in data['wrong_indices']]})
        return j({'scores':[90,90],'feedback':['验收固定90分：理由需继续核对。']*2,'uncertainties':[],
            'overall_feedback':'受控评分只验证流程与记录。'})


async def client(*args,**kwargs):return Teacher()
async def choose(*args,**kwargs):pass
server.assessment_client=client;server.choose_generation_model=choose


@server.app.get('/__review_test__/state')
def state():
    from studyforge.learning_profile import effective_profile
    attempt=one('SELECT id,status,job_id,feedback_artifact_id FROM homework_attempts ORDER BY rowid DESC LIMIT 1')
    return {'calls':calls,'sets':many('SELECT id,project_id,status FROM exercise_sets'),
        'queue':many('SELECT * FROM review_items'),'sessions':many('SELECT * FROM review_sessions'),
        'submissions':many('SELECT id,exercise_set_id,score,grade_json FROM submissions'),
        'profile':effective_profile(),'events':many("SELECT id,event_key FROM learning_events WHERE kind='做题'"),
        'attempt':attempt,'job':one('SELECT status FROM jobs WHERE id=?',(attempt['job_id'],)) if attempt else None}


mount=next(route for route in server.app.routes if getattr(route,'name',None)=='web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
if __name__=='__main__':asyncio.run(fixture.main())
