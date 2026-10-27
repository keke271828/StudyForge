"""Native phone submission updates bounded profile recency in another project."""
import asyncio
import json

import httpx

from scripts import smoke_library_ui as fixture
from studyforge import ai,conversations,learning_memory as memory,learning_profile as profile,server
from studyforge.db import execute,j,many,now,one,uid

fixture.enable_semantic(False)
ai.save_settings({'library_reference_mode':'off','background_learning_enabled':False})
cross=conversations.create(fixture.q['id'],'deepseek')
execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),fixture.other['id'],'user','RAW_OTHER_CHAT',now()))
gap_event=memory.record_event('old-gap','chat',{'student_text':'我不理解高斯定律中净通量和电场的区别。RAW_OTHER_CHAT'},
    fixture.q['id'],fixture.other['id'],analyzed=True)
memory._save_insight(gap_event,'高斯定律','gap','concepts','先前自报分不清净通量和各点电场，需要核对理解。',
    '我不理解高斯定律中净通量和电场的区别。','自报困难（未测验）')
memory.assessment_record('old-grade','高斯定律','做题',40,'PRIVATE_OLD_ANSWER','旧评分摘要：未区分整体和局部。',fixture.q['id'])
execute("UPDATE learning_events SET created_at='2026-10-18T10:00:00+00:00' WHERE event_key='old-gap'")
execute("UPDATE learning_insights SET created_at='2026-10-18T10:00:00+00:00' WHERE event_id=?",(gap_event,))
execute("UPDATE learning_events SET created_at='2026-10-19T10:00:00+00:00' WHERE event_key='old-grade'")
execute("UPDATE learning_insights SET created_at='2026-10-19T10:00:00+00:00' WHERE event_id=(SELECT id FROM learning_events WHERE event_key='old-grade')")
ident=uid()
question={'index':0,'topic':'高斯定律','question':'内部净电荷为零是否意味着电场处处为零？请区分整体净和与局部量。'}
solution={'index':0,'solution':'不能。净通量为零可以来自正负贡献抵消；整体净和不决定每一点电场。','rubric':'结论、理由与条件。'}
execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(ident,fixture.p['id'],'[]','近期表现验收题单',j([question]),j([solution]),2,'assigned',now()))
fixture.case.update(exercise_id=ident,cross_conversation_id=cross['id'])
conversations.activate(fixture.c['id'])
calls=[];requests=[]


class Teacher:
    model='fixture-recency';effort='none'
    async def close(self):pass
    async def complete(self,system,user,**kwargs):
        analysis='逐题诊断错因并补讲' in system;calls.append('analysis' if analysis else 'grade')
        if analysis:
            data=json.JSONDecoder().raw_decode(user)[0]
            return j({'items':[{'index':0,'kind':'argumentation','confidence':'supported',
                'cause':'作答明确说明还不能独立解释抵消与局部量的关系；仍需核对理解。',
                'evidence':[{'source':'answer','quote':data['student_answers'][0]}],
                'explanation':'整体净通量把闭合面上每小块的正负贡献相加。总和为零可以由穿入和穿出抵消，例如均匀电场穿过一个盒子时，两侧的贡献相反，各处电场仍不为零。因此整体求和的结果不能直接代替每个位置的局部值。',
                'check':'分别列出整体求和与局部量，再检查有没有额外条件。'}]})
        return j({'scores':[90],'feedback':['验收固定90分；保留正确结论，检查理由。'],'uncertainties':[],
            'overall_feedback':'受控评分只验证记录流转，不评价模型质量。'})


async def client(*args,**kwargs):return Teacher()
async def choose(*args,**kwargs):pass
server.assessment_client=client;server.choose_generation_model=choose


async def respond(request):
    if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'deepseek-flash'}]})
    body=json.loads(request.content);requests.append(body)
    answer='近期评估里记录了90分，历史作答曾为40分；本次自报参考过笔记。旧疑问需要结合现在的思路核对，不能据一次高分认定稳定掌握。净通量是整体求和，各点电场是局部量。'
    return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
httpx.AsyncClient=lambda *a,**kw:fixture.original(transport=httpx.MockTransport(respond))


@server.app.get('/__recency_test__/state')
def state():
    attempt=one('SELECT id,status,feedback_artifact_id,job_id FROM homework_attempts WHERE exercise_set_id=?',(ident,))
    return {'profile':profile.effective_profile(),'packet':profile.mentor_profile('高斯定律'),
        'calls':calls,'requests':requests,'attempt':attempt,
        'job':one('SELECT status FROM jobs WHERE id=?',(attempt['job_id'],)) if attempt else None,
        'new_insight':one("SELECT i.id,COALESCE(c.version,0) AS version FROM learning_insights i LEFT JOIN learning_insight_controls c ON c.insight_id=i.id JOIN learning_events e ON e.id=i.event_id WHERE e.event_key LIKE 'quiz:%' ORDER BY e.id DESC LIMIT 1"),
        'submissions':many('SELECT id,score FROM submissions'),
        'events':many("SELECT id,event_key FROM learning_events WHERE kind='做题'")}


mount=next(route for route in server.app.routes if getattr(route,'name',None)=='web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
if __name__=='__main__':asyncio.run(fixture.main())
