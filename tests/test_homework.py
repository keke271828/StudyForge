import asyncio
import json

import pytest
from docx import Document
from fastapi import HTTPException
from fastapi.testclient import TestClient

from studyforge import ai, coding, conversations, exercises, homework, learning_memory, learning_profile, server
from studyforge.db import create_project, execute, j, many, now, one, uid, unj
from studyforge.job_control import active_jobs, remove_job


class Teacher:
    model='homework-model'
    effort=None
    def __init__(self, scores=(30,50), unknown=True):
        self.scores=list(scores);self.unknown=unknown;self.calls=[];self.hold=False;self.broken=False
        self.entered=asyncio.Event();self.release=asyncio.Event()
    async def close(self):pass
    async def complete(self,system,user,**kwargs):
        self.calls.append((system,user))
        if self.hold:
            self.hold=False;self.entered.set();await self.release.wait()
        if '逐题诊断错因并补讲' in system:
            if self.broken:return ''
            data=json.JSONDecoder().raw_decode(user)[0];items=[]
            for index in data['wrong_indices']:
                causes=[x for x in data['student_causes'] if x['index']==index]
                uncertain=index==0 and self.unknown and not causes
                confidence='uncertain' if uncertain else 'self_report' if causes else 'supported'
                quote=causes[0]['text'] or causes[0]['labels'][0] if causes else data['student_answers'][index]
                explanation=('高斯定律中的积分是对封闭面的电通量求和。电场与外法向决定每小块面的通量；Q是面内总电荷，外部电荷不进入Q，但会影响各处电场。先区分电场、面积和电荷，再代入公式。' if index==0 else
                             '你把2+3写成4，错误出现在加法计算。先从2开始依次加三个1：3、4、5，所以应为5。用逆运算检查：5−3=2，而4−3=1，后者不等于原来的2。')
                items.append({'index':index,'kind':'terminology' if index==0 else 'implementation','confidence':confidence,
                    'cause':'封闭面通量概念需要进一步确认' if uncertain else '学生自报把通量与电场混淆' if causes else '作答中可核对的计算或实现错误',
                    'evidence':[{'source':'questionnaire' if causes else 'answer','quote':quote}],
                    'clarification':'你当时怎样理解封闭面的电通量？具体卡在哪个量的含义？',
                    'explanation':explanation,'check':'逐个核对量的含义或用逆运算检查结果。'})
            return j({'items':items})
        if '编程教师' in system:return j({'score':50,'feedback':'相加写成相减','issues':['return a-b 应为 a+b']})
        return j({'scores':self.scores,'feedback':['需要区分概念','加法算错'][:len(self.scores)],'uncertainties':[],'overall_feedback':'逐题核对'})


def fixture(monkeypatch, *, scores=(30,50),unknown=True,language=None):
    ai.save_settings({'deepseek_model':'homework-model','background_learning_enabled':False})
    project=create_project('提交作业测试');chat=conversations.create(project['id'],'deepseek','homework-model')
    questions=[{'index':0,'topic':'高斯定律','question':'说明封闭面电通量与面内电荷的关系，并解释各个量。'},
               {'index':1,'topic':'加法','question':'计算2+3并说明步骤。'}]
    solutions=[{'index':0,'solution':'REFERENCE_GAUSS：封闭面电通量等于面内电荷除以真空介电常数。','rubric':'明确封闭面、通量、内电荷'},
               {'index':1,'solution':'REFERENCE_ADD：2+3=5。','rubric':'加法步骤正确'}]
    if language:
        questions=[{'index':0,'topic':'函数加法','question':'实现 add(a,b)，返回两数之和。','language':language}]
        solutions=[{'index':0,'solution':'function add(a,b){return a+b;}','rubric':'正确相加','test_code':'测试 add(2,3)===5'}]
    ident=uid();execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
        (ident,project['id'],'[]','概念与计算题单',j(questions),j(solutions),2,'assigned',now()))
    teacher=Teacher(scores,unknown);monkeypatch.setattr(server,'client_for',lambda *a,**kw:teacher)
    async def choose(*a,**kw):pass
    monkeypatch.setattr(server,'choose_generation_model',choose)
    value=server.SubmitIn(answers=['不知道封闭面通量是什么','2+3=4'],provider='deepseek',model=teacher.model,
                          conversation_id=chat['id'],detailed_feedback=True,background=True)
    return project,chat,ident,teacher,value


async def finish(result):
    task=active_jobs.get(result['job_id'])
    if task:await task
    await asyncio.sleep(0)
    row=one('SELECT * FROM jobs WHERE id=?',(result['job_id'],))
    return row


def paragraphs(artifact_id):
    return '\n'.join(p.text for p in Document(one('SELECT path FROM artifacts WHERE id=?',(artifact_id,))['path']).paragraphs)


def test_answers_immediately_export_without_waiting_for_grader(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch)
    async def scenario():
        model.hold=True
        assert 'solutions' not in exercises.public_set(s,True)
        result=await server.submit_answers(s,value)
        assert result['solution_artifact'] and result['feedback_artifact'] is None
        assert model.calls==[],'Local reference export should finish before model work starts'
        assert 'REFERENCE_GAUSS' in paragraphs(result['solution_artifact']['id'])
        await asyncio.wait_for(model.entered.wait(),3)
        assert many("SELECT id FROM artifacts WHERE kind='grading'")==[]
        assert exercises.public_set(s,True)['solutions'][1]['solution'].startswith('REFERENCE_ADD')
        again=await server.submit_answers(s,value)
        assert again['id']==result['id'] and again['reused']
        assert len(many('SELECT * FROM homework_attempts'))==1
        model.release.set();row=await finish(result)
        assert row['status']=='paused',row['error']
        return result
    result=asyncio.run(scenario())
    assert len(many('SELECT * FROM submissions'))==1
    assert homework.public_attempt(homework.get_attempt(result['id']))['waiting_for_causes']


def test_unknown_cause_questionnaire_gates_feedback_and_resume_does_not_regrade(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch)
    async def scenario():
        result=await server.submit_answers(s,value);row=await finish(result)
        assert row['status']=='paused',row['error']
        attempt=homework.public_attempt(homework.get_attempt(result['id']))
        assert len(attempt['questions'])==1 and attempt['questions'][0]['index']==0
        assert many("SELECT id FROM artifacts WHERE kind='grading'")==[]
        with pytest.raises(HTTPException,match='问卷'):await server.resume_generation(result['job_id'])
        with pytest.raises(HTTPException):await server.homework_causes(result['id'],server.HomeworkCausesIn(responses=[{'index':1,'kinds':['implementation'],'text':''}]),p['id'])
        before={x['topic']:x['evidence_count'] for x in many('SELECT * FROM mastery')}
        response=server.HomeworkCausesIn(responses=[{'index':0,'kinds':['terminology'],'text':'我把通量当作电场，不知道面积为什么出现'}])
        updated=await server.homework_causes(result['id'],response,p['id'])
        assert (await finish(updated))['status']=='completed'
        await server.homework_causes(result['id'],response,p['id']) # Repeated click must be idempotent.
        assert len(many('SELECT * FROM submissions'))==1
        assert before=={x['topic']:x['evidence_count'] for x in many('SELECT * FROM mastery')}
        assert len([x for x in model.calls if '批改者' in x[0]])==2
        return homework.public_attempt(homework.get_attempt(result['id']))
    result=asyncio.run(scenario())
    assert result['status']=='completed'
    report=paragraphs(result['feedback_artifact']['id'])
    assert '错因分析' in report and '针对性讲解' in report and '学生自报' in report
    assert 'Q是面内总电荷' in report and '先从2开始' in report and '4−3=1' in report
    assert report.index('错因分析')<report.index('针对性讲解')<report.index('参考解析')
    assert {x['kind'] for x in many('SELECT * FROM artifacts')}=={'solutions','grading'}
    assert all(x['origin']['conversation_id']==c['id'] for x in server.artifacts(p['id']))
    assert any(x['kind']=='gap' and x['topic']=='加法' for x in many('SELECT * FROM learning_insights'))


@pytest.mark.parametrize('answers',[[''],['知道封闭面',''],['只完成第一题']])
def test_partial_submission_keeps_answers_private(monkeypatch,answers):
    p,c,s,model,value=fixture(monkeypatch);value.answers=answers
    with pytest.raises(HTTPException):asyncio.run(server.submit_answers(s,value))
    assert many('SELECT * FROM homework_attempts')==[] and many('SELECT * FROM artifacts')==[]
    assert model.calls==[] and 'solutions' not in exercises.public_set(s,True)


def test_correct_answers_skip_cause_ai_and_still_export_two_documents(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch,scores=(100,100))
    async def scenario():
        result=await server.submit_answers(s,value);assert (await finish(result))['status']=='completed';return result
    result=asyncio.run(scenario())
    assert len(model.calls)==2
    assert homework.public_attempt(homework.get_attempt(result['id']))['score']==100
    assert len(many('SELECT * FROM artifacts'))==2


def test_profile_only_hypothesis_cannot_publish_as_verified_cause(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch,unknown=False)
    original=model.complete
    async def profile_only(system,user,**kwargs):
        raw=await original(system,user,**kwargs)
        if '逐题诊断错因并补讲' in system:
            data=unj(raw);data['items'][0]['evidence']=[{'source':'profile','quote':'不存在的画像内容'}];return j(data)
        return raw
    model.complete=profile_only
    async def scenario():
        result=await server.submit_answers(s,value);assert (await finish(result))['status']=='paused';return result
    result=asyncio.run(scenario());row=homework.get_attempt(result['id'])
    assert unj(row['analysis_json'])['items'][0]['confidence']=='uncertain'
    assert row['feedback_artifact_id'] is None


def test_failed_analysis_can_retry_fresh_model_reply_without_regrading(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch,unknown=False);model.broken=True
    async def scenario():
        result=await server.submit_answers(s,value);assert (await finish(result))['status']=='failed'
        assert result['solution_artifact']
        model.broken=False;retry=await server.homework_retry(result['id'],p['id'])
        row=await finish(retry);assert row['status']=='completed',row['error']
    asyncio.run(scenario())
    assert len(many('SELECT * FROM submissions'))==1
    assert len([x for x in model.calls if '批改者' in x[0]])==2
    assert len(many('SELECT * FROM artifacts'))==2


def test_cancelled_questionnaire_cannot_publish_late_report(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch)
    async def scenario():
        result=await server.submit_answers(s,value);await finish(result);await remove_job(result['job_id'])
        with pytest.raises(HTTPException):await server.homework_causes(result['id'],server.HomeworkCausesIn(responses=[{'index':0,'kinds':['terminology'],'text':''}]),p['id'])
        with pytest.raises(HTTPException):await server.homework_retry(result['id'],p['id'])
        assert homework.public_attempt(homework.get_attempt(result['id']))['status']=='cancelled'
    asyncio.run(scenario());assert many("SELECT * FROM artifacts WHERE kind='grading'")==[]


def test_wrong_project_and_changed_worksheet_rejected(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch)
    async def scenario():
        result=await server.submit_answers(s,value);await finish(result)
        with pytest.raises(HTTPException):server.homework_detail(result['id'],create_project('其他项目')['id'])
        execute('UPDATE exercise_sets SET difficulty=4 WHERE id=?',(s,))
        with pytest.raises(HTTPException):await server.homework_causes(result['id'],server.HomeworkCausesIn(responses=[{'index':0,'kinds':['terminology'],'text':''}]),p['id'])
    asyncio.run(scenario())


def test_javascript_static_feedback_has_no_fabricated_final_grade(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch,language='javascript',unknown=False)
    monkeypatch.setattr(coding,'_run_assignment_tests',lambda *args:{'ran':False,'score':0,'reason':'Docker未启动'})
    async def scenario():
        result=await homework.enqueue(s,value,code='function add(a,b){return a-b;}')
        row=await finish(result);assert row['status']=='completed',row['error']
        return homework.public_attempt(homework.get_attempt(result['id']))
    result=asyncio.run(scenario());assert result['score'] is None and result['provisional']
    assert '没有最终分数' in paragraphs(result['feedback_artifact']['id'])
    assert 'REFERENCE' not in result['title']
    assert any('JavaScript' in text for _,text in model.calls)


def test_definition_doubt_is_immediate_tentative_and_unrelated_chat_not_profiled(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch);ai.save_settings({'background_learning_enabled':True})
    msg=uid();execute('INSERT INTO messages VALUES (?,?,?,?,?)',(msg,c['id'],'user','高斯定律是什么？',now()))
    learning_memory.discussion_completed(c['id'],msg);learning_memory.discussion_completed(c['id'],msg)
    assert len(many('SELECT * FROM learning_insights'))==1
    profile=learning_profile.mentor_profile('高斯定律')
    assert '不能仅凭提问认定不会' in j(profile) and '高斯定律' in j(profile)
    assert many('SELECT * FROM mastery')==[]
    other=uid();execute('INSERT INTO messages VALUES (?,?,?,?,?)',(other,c['id'],'user','删除项目文件夹按钮为什么报错？',now()))
    learning_memory.discussion_completed(c['id'],other)
    assert len(many('SELECT * FROM learning_events'))==1


def test_homework_read_api_does_not_leak_solutions_before_submission(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch)
    api=TestClient(server.app)
    assert api.get(f'/api/projects/{p["id"]}/homework').json()==[]
    assert 'REFERENCE' not in api.get(f'/api/exercises/{s}').text
    assert api.get('/api/homework/missing',params={'project_id':p['id']}).status_code==404


def test_questionnaire_draft_is_saved_without_releasing_grade_or_updating_profile(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch)
    async def scenario():
        result=await server.submit_answers(s,value);await finish(result)
        original=unj(homework.get_attempt(result['id'])['options_json'])['profile']
        draft=server.HomeworkCausesIn(responses=[{'index':0,'kinds':[],'text':'尚未提交的思路'}])
        before=len(many('SELECT * FROM learning_insights'))
        assert server.homework_draft(result['id'],draft,p['id'])['saved']
        restored=server.homework_detail(result['id'],p['id'])
        assert restored['cause_draft'][0]['text']=='尚未提交的思路'
        assert restored['waiting_for_causes'] and restored['feedback_artifact'] is None
        assert unj(homework.get_attempt(result['id'])['options_json'])['profile']==original
        assert len(many('SELECT * FROM learning_insights'))==before
        with pytest.raises(HTTPException):server.homework_draft(result['id'],draft,create_project('别的项目')['id'])
        await server.homework_causes(result['id'],server.HomeworkCausesIn(responses=[{'index':0,'kinds':['unknown'],'text':'我仍不清楚为什么要积分'}]),p['id'])
        await finish(result)
        assert server.homework_detail(result['id'],p['id'])['cause_draft']==[]
    asyncio.run(scenario())


def test_bare_final_answer_cannot_establish_cause_even_if_model_claims_certainty(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch,unknown=False);value.answers=['4','2+3=4']
    async def scenario():
        result=await server.submit_answers(s,value);assert (await finish(result))['status']=='paused';return result
    result=asyncio.run(scenario());assert homework.public_attempt(homework.get_attempt(result['id']))['questions'][0]['index']==0


def test_generic_advice_is_rejected_before_publishing_report(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch,unknown=False);original=model.complete
    async def vague(system,user,**kwargs):
        raw=await original(system,user,**kwargs)
        if '逐题诊断错因并补讲' in system:
            data=unj(raw);data['items'][0]['explanation']='请复习一下这个概念';return j(data)
        return raw
    model.complete=vague
    async def scenario():
        result=await server.submit_answers(s,value);row=await finish(result)
        assert row['status']=='failed' and row['progress']<100
        assert '仍不符合任务要求' in row['error'] and many("SELECT * FROM artifacts WHERE kind='grading'")==[]
    asyncio.run(scenario());assert len([x for x in model.calls if '逐题诊断错因并补讲' in x[0]])==2


def test_solution_export_failure_preserves_submission_and_can_retry_locally(monkeypatch):
    from studyforge import exporters
    p,c,s,model,value=fixture(monkeypatch,unknown=False);real=exporters.export_document
    def broken(*a,**kw):raise RuntimeError('临时导出失败')
    monkeypatch.setattr(exporters,'export_document',broken)
    async def scenario():
        with pytest.raises(HTTPException):await server.submit_answers(s,value)
        row=one('SELECT * FROM homework_attempts');assert unj(row['answers_json'])==value.answers
        assert model.calls==[]
        monkeypatch.setattr(exporters,'export_document',real)
        retry=await server.homework_retry(row['id'],p['id']);done=await finish(retry)
        assert done['status']=='completed',done['error']
        assert len(many('SELECT * FROM artifacts'))==2
    asyncio.run(scenario())


def test_solution_rubric_is_readable_not_a_python_dictionary(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch,scores=(100,100))
    solutions=unj(one('SELECT solutions_json FROM exercise_sets WHERE id=?',(s,))['solutions_json'])
    solutions[0]['rubric']=[{'criterion':'区分封闭面与面内电荷','points':100}]
    execute('UPDATE exercise_sets SET solutions_json=? WHERE id=?',(j(solutions),s))
    async def scenario():
        result=await server.submit_answers(s,value);await finish(result);return result
    result=asyncio.run(scenario());content=paragraphs(result['solution_artifact']['id'])
    assert '区分封闭面与面内电荷（100分）' in content and "{'criterion'" not in content


@pytest.mark.parametrize('encoding',['utf-8','utf-16','gb18030'])
def test_code_file_preview_preserves_chinese_and_does_not_submit(monkeypatch,encoding):
    p,c,s,model,value=fixture(monkeypatch,language='javascript')
    text='// 中文注释\nfunction add(a,b){return a+b;}'
    api=TestClient(server.app)
    response=api.post(f'/api/coding/{s}/preview',files={'file':('作业.js',text.encode(encoding),'text/plain')})
    assert response.status_code==200,response.text
    assert response.json()['code']==text and '\ufffd' not in response.json()['code']
    assert many('SELECT * FROM homework_attempts')==[] and model.calls==[]


def test_code_preview_rejects_wrong_language_file(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch,language='javascript')
    response=TestClient(server.app).post(f'/api/coding/{s}/preview',files={'file':('错误.py',b'print(1)','text/plain')})
    assert response.status_code==400 and model.calls==[]


def test_submission_without_chat_creates_independent_home_for_questionnaire(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch);value.conversation_id=None
    async def scenario():
        result=await server.submit_answers(s,value);row=await finish(result)
        assert row['status']=='paused',row['error']
        created=conversations.detail(result['conversation_id'],p['id'])
        assert created['id']!=c['id'] and created['source_ids']==[]
        assert created['title']=='概念与计算题单 · 作业反馈'
        assert any('错因问卷' in x['content'] for x in created['messages'])
        await server.homework_causes(result['id'],server.HomeworkCausesIn(responses=[{'index':0,'kinds':['terminology'],'text':'我看不懂公式的各个量'}]),p['id'])
        assert (await finish(result))['status']=='completed'
    asyncio.run(scenario())


def test_legacy_analysis_still_gates_each_new_uncertain_question_and_preserves_literal_quotes(monkeypatch):
    p,c,s,model,value=fixture(monkeypatch);original=model.complete
    async def cross_question(system,user,**kwargs):
        raw=await original(system,user,**kwargs)
        if '逐题诊断错因并补讲' in system:
            inputs=json.JSONDecoder().raw_decode(user)[0]
            if len(inputs['student_causes'])==1:
                data=unj(raw);data['items'][1]['confidence']='self_report'
                data['items'][1]['evidence']=[{'source':'questionnaire','quote':inputs['student_causes'][0]['text']}]
                return j(data) # A real quote from Q1 is not valid evidence of Q2's cause.
        return raw
    model.complete=cross_question
    async def scenario():
        result=await server.submit_answers(s,value);await finish(result)
        # Pre-upgrade attempts have no per-question evidence receipt. They must
        # still revalidate every result, including a newly returned foreign quote.
        attempt=homework.get_attempt(result['id']);legacy=unj(attempt['analysis_json'])
        legacy.pop('analysis_reuse',None)
        execute('UPDATE homework_attempts SET analysis_json=? WHERE id=?',(j(legacy),result['id']))
        first=server.HomeworkCausesIn(responses=[{'index':0,'kinds':['terminology'],'text':'我不理解"通量"与电场的区别'}])
        await server.homework_causes(result['id'],first,p['id']);row=await finish(result)
        assert row['status']=='paused',row['error']
        pending=homework.public_attempt(homework.get_attempt(result['id']))
        assert [q['index'] for q in pending['questions']]==[1]
        analysis=unj(homework.get_attempt(result['id'])['analysis_json'])
        assert analysis['items'][0]['confidence']=='self_report' # Literal quotes survive JSON escaping.
        assert analysis['items'][1]['confidence']=='uncertain'
        assert pending['feedback_artifact'] is None
        await server.homework_causes(result['id'],first,p['id']) # A duplicate old response cannot bypass Q2.
        assert one('SELECT status FROM jobs WHERE id=?',(result['job_id'],))['status']=='paused'
        second=server.HomeworkCausesIn(responses=[{'index':1,'kinds':['implementation'],'text':'我把3抄成了2，导致算成4'}])
        await server.homework_causes(result['id'],second,p['id']);row=await finish(result)
        assert row['status']=='completed',row['error']
        assert len(unj(homework.get_attempt(result['id'])['causes_json']))==2
        assert len(many('SELECT * FROM submissions'))==1
    asyncio.run(scenario())
