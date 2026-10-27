import asyncio

import pytest

from studyforge import exercises
from studyforge.ai import complete_json
from studyforge.db import create_project, j, many
from studyforge.review import review_explanation, review_exercises


PRIVATE='PRIVATE_ANSWER_NEVER_IN_JOB_ERROR'
QUESTION={'question':'在实数范围，说明一个反例。','solution':PRIVATE,'rubric':'正确反例且说明条件','topic':'推理','source_url':''}


class RepairModel:
    def __init__(self,never_pass=False):self.calls=[];self.repaired=False;self.never_pass=never_pass
    async def complete(self,system,user,**kwargs):
        self.calls.append((system,user,kwargs))
        if '正在修订' in system:
            self.repaired=True
            return j({'questions':[QUESTION]})
        if '习题设计者' in system:return j({'questions':[dict(QUESTION,question='说明一个反例。')]})
        if '独立解题员' in system:return j({'answers':[{'index':0,'solution':PRIVATE,'issues':[]}]})
        if '习题审查员' in system:
            passed=self.repaired and not self.never_pass
            return j({'passed':passed,'issues':[] if passed else [{'index':0,'category':'statement','problem':'缺少实数范围。'+PRIVATE}],
                      'corrected_questions':[] if passed else [QUESTION]})
        raise AssertionError(system)


def test_repaired_questions_solved_again_and_initial_failure_does_not_veto():
    model=RepairModel()
    questions,reports=asyncio.run(review_exercises(model,'资料说明了反例和实数范围。',[dict(QUESTION,question='说明一个反例。')]))
    assert questions==[QUESTION]
    assert len([s for s,u,k in model.calls if '独立解题员' in s])==2
    assert len([s for s,u,k in model.calls if '正在修订' in s])==1
    assert len(reports)==7 and reports[-1]['passed'] is True and reports[1]['passed'] is False
    second_solver=[u for s,u,k in model.calls if '独立解题员' in s][-1]
    assert '在实数范围' in second_solver and PRIVATE not in second_solver


def test_generation_repair_commits_only_verified_private_answers(monkeypatch):
    async def no_network(title):return []
    monkeypatch.setattr(exercises,'search_exercises',no_network)
    project=create_project('生成恢复');model=RepairModel()
    set_id,reports=asyncio.run(exercises.generate_set(model,project['id'],[],'实数反例。','练习'))
    assert PRIVATE not in j(exercises.public_set(set_id,reveal=True))
    assert PRIVATE in many('SELECT solutions_json FROM exercise_sets')[0]['solutions_json']
    assert reports[-1]['attempt']==2


def test_unresolved_failure_is_bounded_specific_and_does_not_leak_answers(monkeypatch):
    async def no_network(title):return []
    monkeypatch.setattr(exercises,'search_exercises',no_network)
    project=create_project('失败保留');model=RepairModel(never_pass=True)
    with pytest.raises(RuntimeError,match='第1题：题意或条件有歧义') as error:
        asyncio.run(exercises.generate_set(model,project['id'],[],'原文。','练习'))
    assert PRIVATE not in str(error.value)
    assert len(model.calls)==8 and many('SELECT * FROM exercise_sets')==[]


@pytest.mark.parametrize('malformed',['','说明文字','{"passed":"true","issues":[]}'])
def test_lecture_review_repairs_empty_nonjson_and_wrong_shape_once(malformed):
    class Model:
        calls=[]
        async def complete(self,system,user,**kwargs):
            self.calls.append((system,user,kwargs))
            return malformed if len(self.calls)==1 else j({'passed':True,'issues':[]})
    model=Model()
    text,reports=asyncio.run(review_explanation(model,'原文。','# 正文\n\n## 系统性总结\n概念关系。',mode='fast'))
    assert len(model.calls)==2 and reports[0]['passed'] is True
    assert '上一次返回格式无效' in model.calls[-1][0] and 'JSON' in model.calls[-1][0]
    assert '待核实' not in text


def test_repeated_malformed_review_has_readable_error_and_retains_no_fake_pass():
    class Bad:
        calls=0
        async def complete(self,*a,**k):self.calls+=1;return '没有发现问题'
    model=Bad()
    with pytest.raises(RuntimeError,match='JSON') as exc:
        asyncio.run(review_explanation(model,'原文。','待审文档',mode='fast'))
    assert 'JSONDecodeError' not in str(exc.value) and model.calls==2


def test_independent_solution_missing_questions_is_repaired_then_rejected():
    class Bad:
        calls=0
        async def complete(self,*a,**k):self.calls+=1;return j({'answers':[]})
    model=Bad()
    with pytest.raises(RuntimeError,match='JSON'):asyncio.run(review_exercises(model,'资料',[QUESTION]))
    assert model.calls==2


class ConcernModel:
    def __init__(self,blocking=False):self.blocking=blocking
    async def complete(self,system,user,**kw):
        if '独立解题员' in system:return j({'answers':[{'index':0,'solution':PRIVATE,'issues':['可以给出另一种证明；当前题目条件已经足够。']}]})
        if '习题审查员' in system:return j({'passed':True,'issues':[], 'independent_issue_decisions':[{'concern_id':0,'blocking':self.blocking,'reason':'所给实数条件保证可以求解，替代证明只是可选优化。' if not self.blocking else '必要前提缺失，无法唯一评分。'}]})
        if '正在修订' in system:return j({'questions':[QUESTION]})
        raise AssertionError(system)


def test_solver_advice_is_adjudicated_and_real_docx_has_no_private_answers(monkeypatch,tmp_path):
    from docx import Document
    from studyforge.exporters import export_document
    async def no_network(title):return []
    monkeypatch.setattr(exercises,'search_exercises',no_network)
    class Model(ConcernModel):
        async def complete(self,system,user,**kw):
            if '习题设计者' in system:return j({'questions':[QUESTION]})
            return await super().complete(system,user,**kw)
    project=create_project('建议不拦截导出')
    set_id,reports=asyncio.run(exercises.generate_set(Model(),project['id'],[],'实数反例。','练习'))
    assert len(reports)==3 and all(report['independent_issue_decisions'][0]['blocking'] is False for report in reports[1:])
    path=export_document(exercises.student_document(set_id),'docx','练习','concern-test.docx')
    text='\n'.join(p.text for p in Document(path).paragraphs)
    assert '在实数范围' in text and PRIVATE not in text and '参考解析' not in text


def test_confirmed_independent_defect_still_blocks_without_leaking_answers():
    with pytest.raises(RuntimeError,match='题意或条件有歧义') as exc:asyncio.run(review_exercises(ConcernModel(True),'资料',[QUESTION]))
    assert PRIVATE not in str(exc.value)


def test_missing_independent_adjudication_is_not_accepted_as_pass():
    class Model(ConcernModel):
        async def complete(self,system,user,**kw):
            if '习题审查员' in system:return j({'passed':True,'issues':[]})
            return await super().complete(system,user,**kw)
    with pytest.raises(RuntimeError,match='JSON'):asyncio.run(review_exercises(Model(),'资料',[QUESTION]))
