import asyncio

import pytest
from fastapi.testclient import TestClient
from docx import Document

from studyforge import assessment, exercises, practice, server
from studyforge.db import create_project, execute, j, many, now, one, uid


class Replies:
    def __init__(self, replies):self.replies=list(replies);self.calls=[]
    async def complete(self,system,user,**kwargs):
        self.calls.append((system,user));return j(self.replies.pop(0))


def response(scores, feedback=None, doubts=None):
    return {'scores':scores,'feedback':feedback or ['明确评分点与作答步骤']*len(scores),'uncertainties':doubts or []}


def worksheet():
    p=create_project('批改教学质量');ident=uid()
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
        (ident,p['id'],'[]','不同解法',j([{'index':0,'question':'求2+3，说明计算步骤。','topic':'加法'}]),
         j([{'index':0,'solution':'2+3=5','rubric':'正确计算100分'}]),1,'assigned',now()))
    return ident,p


@pytest.mark.parametrize('left,right,final',[(79,81,79),(100,99,100),(78,82,80),(85,92,87)])
def test_consequential_disagreement_is_decided_not_averaged(left,right,final):
    ident,_=worksheet();client=Replies([response([left],['第一份依据']),response([right],['第二份依据']),response([final],['裁决依据'])])
    result=asyncio.run(exercises.grade_submission(client,ident,['从2加三个1，得到5']))
    assert len(client.calls)==3
    assert result['score']==final and result['feedback']==['裁决依据']
    assert result['requires_feynman']==(final<80)
    assert one('SELECT status FROM exercise_sets WHERE id=?',(ident,))['status']==('feynman_required' if final<80 else 'passed')


def test_small_nonconsequential_difference_keeps_matching_score_and_feedback():
    ident,_=worksheet();client=Replies([response([86],['86分对应的评分点']),response([88],['88分对应的评分点'])])
    result=asyncio.run(exercises.grade_submission(client,ident,['2+3=5']))
    assert len(client.calls)==2 and result['score']==86 and result['feedback']==['86分对应的评分点']


def test_full_credit_has_no_invented_error_diagnosis_even_with_model_extras():
    ident,_=worksheet()
    item=response([100]);item['provisional']=True
    item['diagnostics']=[{'index':0,'kind':'implementation','quote':'2+3=5','reason':'没有明确证据的失误判断'}]
    result=asyncio.run(exercises.grade_submission(Replies([item,response([100])]),ident,['2+3=5']))
    assert result['diagnostics']==[] and result['provisional'] is False and result['score']==100


def test_total_threshold_disagreement_is_not_hidden_by_per_question_checks():
    assert assessment.requires_reconciliation(response([77,82]),response([79,84]))


def test_unresolved_grading_doubt_never_becomes_mastery_or_punishment_then_can_recheck(monkeypatch):
    ident,p=worksheet();doubt='参考解与题意冲突，需核实第1题'
    client=Replies([response([20],doubts=[doubt]),response([20]),response([20],doubts=[doubt])])
    result=asyncio.run(exercises.grade_submission(client,ident,['从2加三个1，得到5']))
    assert result['score'] is None and result['scores']==[None] and result['tentative_scores']==[20]
    assert not result['requires_feynman'] and not result['requires_repair']
    assert many('SELECT * FROM mastery')==[] and many('SELECT * FROM learning_insights')==[]
    assert 'solutions' in exercises.public_set(ident,reveal=True)
    with pytest.raises(ValueError,match='评分尚待核实'):practice.schedule_review(ident)
    with pytest.raises(ValueError,match='不覆盖'):asyncio.run(exercises.grade_submission(client,ident,['更换了答案']))
    good=Replies([response([100]),response([100])])
    async def factory(*args,**kwargs):return good
    monkeypatch.setattr(server,'assessment_client',factory)
    api=TestClient(server.app)
    checked=api.post(f'/api/exercises/{ident}/regrade',json={'provider':'codex'})
    assert checked.status_code==200,checked.text
    assert checked.json()['score']==100 and checked.json()['submission_id']==result['submission_id']
    assert len(many('SELECT * FROM submissions'))==1 and many('SELECT * FROM mastery')[0]['quiz_score']==100
    assert len(many("SELECT * FROM learning_events WHERE kind='做题'"))==1
    assert api.post(f'/api/exercises/{ident}/regrade',json={}).status_code==409


def test_graders_start_in_separate_branches_and_close_them():
    calls=[];closed=[]
    class Branch:
        async def complete(self,system,user,**kwargs):
            assert not self.__dict__.get('used');self.used=True
            calls.append((system,user));return j(response([100]))
        async def close(self):closed.append(self)
    class Root:
        def fork(self):return Branch()
        async def complete(self,*a,**kw):pytest.fail('评分不得累积在原导师会话')
    result=asyncio.run(assessment.verified_grade(Root(),['题目'],['参考解'],['学生答案']))
    assert result['scores']==[100] and len(closed)==2
    assert '第一份批改' not in calls[1][1]


def test_missing_feedback_gets_one_bounded_repair_before_recording():
    ident,_=worksheet();client=Replies([{'scores':[80],'feedback':[]},response([80]),response([80])])
    result=asyncio.run(exercises.grade_submission(client,ident,['2+3=5']))
    assert result['score']==80 and len(client.calls)==3 and '上次格式错误' in client.calls[1][1]


@pytest.mark.parametrize('score',[0,79,80,100])
def test_single_question_rubric_points_keep_all_feedback_and_original_score_without_repair(score):
    ident,_=worksheet()
    points=['积分写法和提出常数属于本题已满足的评分点。','有向面积和不能换成总面积；后续结论须在这一步修正。']
    client=Replies([response([score],points),response([score],points)])
    result=asyncio.run(exercises.grade_submission(client,ident,['给出本题的完整作答。']))
    assert len(client.calls)==2, '明确定归一道题的评分点不应再耗一次格式修复'
    assert result['score']==score and result['scores']==[score]
    assert result['feedback']==['\n\n'.join(points)]
    assert result['feedback_normalization']=={'kind':'single_question_points','point_count':2}
    assert result['first_review']['feedback']==result['second_review']['feedback']==result['feedback']
    assert result['requires_feynman']==(score<80)
    assert one('SELECT score FROM submissions')['score']==score


def test_multiple_questions_with_ungrouped_points_require_explicit_repair_not_guessed_regrouping():
    questions=[{'index':0,'question':'第一题','topic':'甲'},{'index':1,'question':'第二题','topic':'乙'}]
    first=response([70,100],['某个评分点甲','某个评分点乙','某个评分点丙','某个评分点丁'])
    fixed=response([70,100],['明确归属第一题的全部反馈','明确归属第二题的全部反馈'])
    client=Replies([first,fixed,fixed])
    result=asyncio.run(assessment.verified_grade(client,questions,['参考甲','参考乙'],['作答甲','作答乙']))
    assert len(client.calls)==3
    assert result['feedback']==fixed['feedback'] and 'feedback_normalization' not in result
    assert 'feedback必须恰有2个' in client.calls[1][1] and '目前为4条' in client.calls[1][1]
    assert '作答甲' in client.calls[1][1] and '作答乙' in client.calls[1][1]
    assert '第一份批改' not in client.calls[-1][1]


@pytest.mark.parametrize('points',[['有效反馈',''],['有效反馈',None],[],{'0':'反馈'},'反馈'])
def test_unusable_single_question_feedback_is_not_silently_pruned_or_invented(points):
    client=Replies([{'scores':[80],'feedback':points},response([80]),response([80])])
    result=asyncio.run(assessment.verified_grade(client,['题目'],['参考'],['作答']))
    assert len(client.calls)==3 and result['feedback']==['明确评分点与作答步骤']
    assert 'feedback_normalization' not in result and '上次格式错误' in client.calls[1][1]


def test_single_question_split_feedback_reaches_homework_docx_and_keeps_answer_release(monkeypatch):
    from tests.test_homework import fixture,finish,paragraphs
    from studyforge import homework
    p,c,ident,teacher,value=fixture(monkeypatch,scores=(40,),unknown=False)
    import json
    worksheet=one('SELECT * FROM exercise_sets WHERE id=?',(ident,))
    execute('UPDATE exercise_sets SET questions_json=?,solutions_json=? WHERE id=?',
        (j(json.loads(worksheet['questions_json'])[:1]),j(json.loads(worksheet['solutions_json'])[:1]),ident))
    value=value.model_copy(update={'answers':['我写出有向通量积分并提出常数，随后把有向面积和当成总面积，所以推断E为零。']})
    points=['积分和提出常数正确，保留40分。','将有向面积和当成总面积是错误步骤。','零净通量不能推出电场为零，修正时保留第一步。']
    normal=teacher.complete
    async def split(system,user,**kwargs):
        if '逐题诊断错因并补讲' in system:return await normal(system,user,**kwargs)
        teacher.calls.append((system,user));return j(response([40],points))
    teacher.complete=split
    async def scenario():
        assert 'solutions' not in exercises.public_set(ident,reveal=True)
        result=await server.submit_answers(ident,value)
        assert result['solution_artifact'] and result['feedback_artifact'] is None
        assert (await finish(result))['status']=='completed'
        attempt=homework.public_attempt(homework.get_attempt(result['id']))
        assert attempt['status']=='completed' and attempt['score']==40
        text=paragraphs(attempt['feedback_artifact']['id'])
        assert all(point in text for point in points)
        assert '第 1 题' in text and '第 2 题' not in text
        assert '错因分析' in text and '针对性讲解' in text
        assert len(teacher.calls)==3,'两次独立批改加一次补讲，不为拆分评分点追加格式修复'
        assert len(many('SELECT * FROM submissions'))==1
        assert 'solutions' in exercises.public_set(ident,reveal=True)
    asyncio.run(scenario())


def test_eloquent_but_critically_wrong_feynman_explanation_cannot_pass():
    ident,_=worksheet();execute("UPDATE exercise_sets SET status='feynman_required' WHERE id=?",(ident,))
    text='我认为2+3等于4，以下只是流畅地复述我的想法。'*6
    error={'quote':'2+3等于4','problem':'加法计算错误'}
    client=Replies([{'score':95,'feedback':'措辞流畅','gaps':['加法'],'critical_errors':[error]},
                    {'score':60,'feedback':'你说2+3等于4，但逐个加1得到3、4、5。应更正结果，用5减3核对。','gaps':['加法计算'],'critical_errors':[error]}])
    result=asyncio.run(exercises.grade_feynman(client,ident,text))
    assert not result['passed'] and result['score']==60 and len(client.calls)==2
    assert one('SELECT status FROM exercise_sets WHERE id=?',(ident,))['status']=='feynman_retry'


def test_sufficient_short_explanation_is_not_rejected_for_character_count():
    ident,_=worksheet();execute("UPDATE exercise_sets SET status='feynman_required' WHERE id=?",(ident,))
    client=Replies([{'score':100,'feedback':'加法步骤与检查都正确。','gaps':[]}])
    result=asyncio.run(exercises.grade_feynman(client,ident,'从2开始连续加三个1得到3、4、5，所以2+3=5；5减3等于2，可核对。'))
    assert result['passed'] and len(client.calls)==1


def test_pending_homework_recheck_reuses_submission_and_does_not_guess_causes(monkeypatch):
    from tests.test_homework import fixture,finish,paragraphs
    from studyforge import homework
    p,c,ident,teacher,value=fixture(monkeypatch,scores=(100,100),unknown=False)
    normal=teacher.complete
    pending=True
    async def complete(system,user,**kwargs):
        if pending:
            assert '逐题诊断错因并补讲' not in system
            teacher.calls.append((system,user))
            return j(response([40,40],doubts=['第1题的评分依据尚未确认']))
        return await normal(system,user,**kwargs)
    teacher.complete=complete
    async def scenario():
        nonlocal pending
        result=await server.submit_answers(ident,value)
        task=await finish(result)
        assert task['status']=='completed',task['error']
        attempt=homework.public_attempt(homework.get_attempt(result['id']))
        assert attempt['status']=='awaiting_grade_review' and attempt['questions']==[]
        assert many('SELECT * FROM mastery')==[]
        assert '暂不定分' in paragraphs(attempt['feedback_artifact']['id'])
        original_submission=one('SELECT id FROM submissions')['id']
        pending=False
        retried=await server.homework_retry(result['id'],p['id'])
        assert (await finish(retried))['status']=='completed'
        attempt=homework.public_attempt(homework.get_attempt(result['id']))
        assert attempt['status']=='completed' and attempt['score']==100
        assert len(many('SELECT * FROM submissions'))==1 and one('SELECT id FROM submissions')['id']==original_submission
        assert len(many("SELECT * FROM learning_events WHERE kind='做题'"))==2
        assert '本次得分：100.0' in paragraphs(attempt['feedback_artifact']['id'])
    asyncio.run(scenario())


def test_real_model_calculation_category_does_not_discard_valid_remediation(monkeypatch):
    from tests.test_homework import fixture,finish,paragraphs
    from studyforge import homework
    p,c,ident,teacher,value=fixture(monkeypatch,unknown=False);normal=teacher.complete
    async def calculation(system,user,**kwargs):
        raw=await normal(system,user,**kwargs)
        if '逐题诊断错因并补讲' in system:
            import json
            data=json.loads(raw);data['items'][1]['kind']='calculation';return j(data)
        return raw
    teacher.complete=calculation
    async def scenario():
        result=await server.submit_answers(ident,value);task=await finish(result)
        assert task['status']=='completed',task['error']
        attempt=homework.public_attempt(homework.get_attempt(result['id']))
        assert '先从2开始' in paragraphs(attempt['feedback_artifact']['id'])
        assert len([x for x in teacher.calls if '逐题诊断错因并补讲' in x[0]])==1
    asyncio.run(scenario())
