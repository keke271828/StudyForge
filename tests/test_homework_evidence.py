"""A result alone cannot establish a learning diagnosis; quoted work stays quoted."""
import asyncio
import pytest
from studyforge import homework
from studyforge.db import j,unj
from tests.test_homework_analysis_reuse import data


class ConfidentTeacher:
    model='controlled-model'
    calls=0
    async def complete(self,system,user,**kwargs):
        import json
        self.calls+=1;request=json.JSONDecoder().raw_decode(user)[0]
        return j({'items':[{'index':i,'kind':'implementation','confidence':'supported',
            'cause':'因为计算粗心，所以算错。','evidence':[{'source':'answer','quote':request['student_answers'][i]}],
            'clarification':'你当时是怎样得到这个结果的？','explanation':'应先写出中间计算，再将每一步与题目条件核对，不能从最后数值推断错误发生的位置。需要区分计算、方法和概念。',
            'check':'用逆运算核对，并说明你原来的每一步。'} for i in request['wrong_indices']]})


@pytest.mark.parametrize('answer',['答案是 4','**答案：** $4$','结果：\\(4\\)','我选 B','Answer: B','最终结果：$x=4$'])
def test_wrapped_final_answer_stays_uncertain_without_reasoning(answer):
    row,worksheet,grade=data();row['answers_json']=j([answer,'2+3=4','由Q内为零推出电场为零'])
    teacher=ConfidentTeacher()
    result=asyncio.run(homework.analyze(teacher,row,worksheet,grade,[]))
    assert result['items'][0]['confidence']=='uncertain'
    assert '粗心' not in result['items'][0]['cause'] and '尚不能确定' in result['items'][0]['cause']
    assert teacher.calls==1


def test_multiline_evidence_never_becomes_teacher_heading_or_explanation():
    row,worksheet,grade=data()
    quote='2+3=4\n\n### 学生原文里的标题\n这段仍是学生作答，不是导师判断。'
    row['answers_json']=j([quote,'2+3=4','由Q内为零推出电场为零'])
    analysis={'items':[{'index':0,'kind':'implementation','confidence':'supported','cause':'仅作测试',
        'evidence':[{'source':'answer','quote':quote}],'explanation':'导师补讲在引用之外。','check':'逐步核对。'}]}
    document=homework.report_document(row,worksheet,grade,analysis,question_index=0)
    evidence=document.split('> 本次作答：',1)[1].split('### 针对性讲解',1)[0]
    assert '\n### 学生原文里的标题' not in evidence
    assert '\n> ### 学生原文里的标题' in evidence
    assert '\n> 这段仍是学生作答，不是导师判断。' in evidence


@pytest.mark.parametrize('answer',['4','-0.25','1/2','4 N/C','答案为 $\\frac{1}{2}$','结果：\n$x=4$','Answer is 4','B。','不知道','\\[x_{n}=4\\]'])
def test_obvious_results_are_recognized_without_modifying_the_answer(answer):
    from studyforge.homework_evidence import result_only
    original=answer
    assert result_only(answer) and answer==original


@pytest.mark.parametrize('answer',['2+3=4','x=2+3=4','因为把净通量当成电场，所以认为E=0。','从2开始依次加三个1得到3、4、4。','function add(a,b){return a-b;}','我把所有学生当成随机分组，因此认为能推出因果。'])
def test_observable_work_is_not_relabelled_as_a_bare_result(answer):
    from studyforge.homework_evidence import result_only
    assert not result_only(answer)


def test_programming_assignment_is_not_forced_into_a_questionnaire_for_short_code():
    row,worksheet,grade=data()
    questions=unj(worksheet['questions_json']);questions[0]['language']='matlab'
    worksheet['questions_json']=j(questions);row['answers_json']=j(['x=4','2+3=4','净通量为零所以场为零'])
    result=asyncio.run(homework.analyze(ConfidentTeacher(),row,worksheet,grade,[]))
    assert result['items'][0]['confidence']=='supported'


def test_actual_questionnaire_evidence_stays_self_report_even_with_a_bare_answer():
    row,worksheet,grade=data()
    class SelfReport(ConfidentTeacher):
        async def complete(self,system,user,**kwargs):
            result=unj(await super().complete(system,user,**kwargs))
            result['items'][0]['evidence'].append({'source':'questionnaire','quote':'我忘了最后除以2'})
            return j(result)
    result=asyncio.run(homework.analyze(SelfReport(),row,worksheet,grade,[{'index':0,'kinds':['implementation'],'text':'我忘了最后除以2'}]))
    assert result['items'][0]['confidence']=='self_report'


def test_multiline_quote_uses_source_style_in_real_word_export():
    from docx import Document
    from studyforge.exporters import export_document
    row,worksheet,grade=data();text='2+3=4\n\n### 学生原文里的标题\n这仍是学生作答。'
    row['answers_json']=j([text,'2+3=4','净通量为零所以场为零'])
    analysis={'items':[{'index':0,'kind':'implementation','confidence':'supported','cause':'测试原因',
        'evidence':[{'source':'answer','quote':text}],'explanation':'导师补讲在引用之外。','check':'逐步核对。'}]}
    path=export_document(homework.report_document(row,worksheet,grade,analysis,question_index=0),'docx','引用边界验收','evidence.docx')
    paragraphs=Document(path).paragraphs
    source=[p for p in paragraphs if '学生原文里的标题' in p.text or '这仍是学生作答' in p.text]
    assert source and all(p.style.name=='Source Quote' for p in source)
    assert next(p for p in paragraphs if '导师补讲在引用之外' in p.text).style.name=='Normal'


def test_wrapped_result_waits_for_student_cause_before_document_or_error_profile(monkeypatch):
    from tests.test_homework import fixture,finish
    from studyforge import server
    from studyforge.db import many
    project,chat,set_id,teacher,value=fixture(monkeypatch,unknown=False)
    value.answers=['答案是 4','2+3=4']
    async def scenario():
        accepted=await server.submit_answers(set_id,value)
        assert (await finish(accepted))['status']=='paused'
        row=homework.get_attempt(accepted['id']);analysis=unj(row['analysis_json'])
        assert analysis['items'][0]['confidence']=='uncertain'
        assert '尚不能确定' in analysis['items'][0]['cause']
        assert row['feedback_artifact_id'] is None
        assert not many("SELECT * FROM learning_insights WHERE kind='gap'")
        masteries=many('SELECT * FROM mastery ORDER BY topic')
        answer=server.HomeworkCausesIn(responses=[{'index':0,'kinds':['implementation'],'text':'我没有写步骤，只是猜了一个结果，原因还不确定'}])
        await server.homework_causes(accepted['id'],answer,project['id'])
        assert (await finish(accepted))['status']=='completed'
        assert unj(homework.get_attempt(accepted['id'])['analysis_json'])['items'][0]['confidence']=='self_report'
        assert many('SELECT * FROM mastery ORDER BY topic')==masteries
        assert len([call for call in teacher.calls if '批改者' in call[0]])==2
    asyncio.run(scenario())


def test_legacy_outer_phase_cannot_bypass_new_evidence_gate(monkeypatch):
    from tests.test_homework import fixture,finish
    from studyforge import server
    from studyforge.db import execute,now
    project,_,set_id,teacher,value=fixture(monkeypatch,unknown=False)
    value.answers=['答案是 4','2+3=4'];original=homework.analyze
    async def interrupted(*a,**kw):raise PermissionError('controlled stop before teaching')
    monkeypatch.setattr(homework,'analyze',interrupted)
    async def scenario():
        accepted=await server.submit_answers(set_id,value)
        assert (await finish(accepted))['status']=='failed'
        old={'items':[{'index':i,'kind':'implementation','confidence':'supported','cause':'OLD_UNSUPPORTED_DIAGNOSIS',
            'evidence':[{'source':'answer','quote':value.answers[i]}],'explanation':'旧规则缓存的讲解，不能据此认定本次错因。','check':'旧核对办法'} for i in range(2)]}
        execute('INSERT INTO generation_steps VALUES (?,?,?,?)',(accepted['job_id'],'phase:homework:analysis:[]',j(old),now()))
        monkeypatch.setattr(homework,'analyze',original)
        resumed=await server.homework_retry(accepted['id'],project['id'])
        assert (await finish(resumed))['status']=='paused'
        row=homework.get_attempt(accepted['id'])
        assert unj(row['analysis_json'])['items'][0]['confidence']=='uncertain'
        assert 'OLD_UNSUPPORTED_DIAGNOSIS' not in row['analysis_json'] and row['feedback_artifact_id'] is None
    asyncio.run(scenario())
