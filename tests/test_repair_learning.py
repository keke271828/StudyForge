import asyncio
import copy
import json

import httpx
import pytest
from docx import Document
from fastapi.testclient import TestClient

from studyforge import ai, exercises, homework, repair_learning as repair, server
from studyforge.db import create_project,execute,j,many,one,uid,unj
from test_homework import fixture,finish


def completed(monkeypatch,*,self_report=False):
    p,c,s,teacher,value=fixture(monkeypatch,scores=(90,100),unknown=self_report)
    async def run():
        result=await server.submit_answers(s,value);await finish(result)
        if self_report:
            await server.homework_causes(result['id'],server.HomeworkCausesIn(responses=[
                {'index':0,'kinds':['terminology'],'text':'我把电通量当成了每个点的电场。'}]),p['id'])
            await finish(result)
        return result
    result=asyncio.run(run())
    worksheet=one('SELECT * FROM exercise_sets WHERE id=?',(s,))
    submission=one('SELECT * FROM submissions WHERE exercise_set_id=?',(s,))
    return worksheet,submission,result


def new_questions(spec):
    return [{'question':f'NEW_{target["index"]}：比较封闭面上进入和离开的贡献，说明净和是否决定每个位置的场，并写出判断依据。',
        'topic':target['topic'],'solution':'PRIVATE_NEW_SOLUTION：保留完整推导。',
        'rubric':'按定义、条件和论证给分','source_url':'',
        'repair_target_index':target['index'],'repair_focus':'PRIVATE_FOCUS：检查是否能区分整体求和与各点电场，重新说明条件。'}
        for target in spec['targets']]


def test_current_graded_causes_and_teaching_reach_one_target_even_with_ninety_score(monkeypatch):
    worksheet,submission,result=completed(monkeypatch,self_report=True)
    spec=repair.build(worksheet,submission)
    assert len(spec['targets'])==1 and spec['targets'][0]['index']==0
    target=spec['targets'][0]
    assert target['basis']=='student_self_report' and '电通量' in target['teaching_excerpt']
    assert any('把电通量' in e['quote'] for e in target['evidence'])
    assert '自报' in repair.requirements(spec)
    public=homework.public_attempt(homework.get_attempt(result['id']))
    assert public['score']==95 and public['repair_available']
    assert 'exercise_version' not in spec and 'REFERENCE_GAUSS' not in j(spec)


@pytest.mark.parametrize('change',['source_version','answers','project','submission'])
def test_foreign_stale_or_incomplete_analysis_is_not_used_to_diagnose(monkeypatch,change):
    worksheet,submission,result=completed(monkeypatch)
    attempt=homework.get_attempt(result['id'])
    if change=='source_version':execute('UPDATE homework_attempts SET source_version=? WHERE id=?',('stale',attempt['id']))
    if change=='answers':execute('UPDATE homework_attempts SET answers_json=? WHERE id=?',(j(['FOREIGN_ANSWER','别的作答']),attempt['id']))
    if change=='project':execute('UPDATE homework_attempts SET project_id=? WHERE id=?',(create_project('其他项目')['id'],attempt['id']))
    if change=='submission':
        grade=unj(attempt['grade_json']);grade['submission_id']=uid()
        execute('UPDATE homework_attempts SET grade_json=? WHERE id=?',(j(grade),attempt['id']))
    spec=repair.build(worksheet,submission)
    assert spec['analysis_status']=='grade_only' and spec['targets'][0]['basis']=='unresolved'
    assert not spec['targets'][0]['evidence'] and not spec['targets'][0]['teaching_excerpt']


def test_awaiting_causes_and_unconfirmed_grades_do_not_generate_repair(monkeypatch):
    p,c,s,teacher,value=fixture(monkeypatch,scores=(90,100),unknown=True)
    async def run():
        result=await server.submit_answers(s,value);await finish(result);return result
    result=asyncio.run(run());worksheet=one('SELECT * FROM exercise_sets WHERE id=?',(s,))
    submission=one('SELECT * FROM submissions WHERE exercise_set_id=?',(s,))
    with pytest.raises(ValueError,match='问卷'):repair.build(worksheet,submission)
    grade=unj(submission['grade_json']);grade['grading_verification_required']=True;submission['grade_json']=j(grade)
    with pytest.raises(ValueError,match='核实'):repair.build(worksheet,submission)
    assert not homework.public_attempt(homework.get_attempt(result['id']))['repair_available']


def test_full_credit_is_not_repaired_or_marked_as_an_error(monkeypatch):
    worksheet,submission,_=completed(monkeypatch)
    grade=unj(submission['grade_json']);grade['scores']=[100,100];submission['grade_json']=j(grade)
    with pytest.raises(ValueError,match='没有失分'):repair.build(worksheet,submission)


def test_explicit_strict_feynman_choice_is_not_bypassed_by_new_repair_entry(monkeypatch):
    worksheet,submission,result=completed(monkeypatch)
    execute("UPDATE exercise_sets SET status='feynman_required' WHERE id=?",(worksheet['id'],))
    worksheet['status']='feynman_required'
    with pytest.raises(ValueError,match='费曼'):repair.build(worksheet,submission)
    assert not homework.public_attempt(homework.get_attempt(result['id']))['repair_available']


def test_legacy_generated_set_without_real_target_metadata_is_not_relabelled(monkeypatch):
    worksheet,submission,_=completed(monkeypatch);spec=repair.build(worksheet,submission)
    # A legacy cached question has no target/focus metadata; creating a new
    # context record must not make it masquerade as a validated targeted task.
    with pytest.raises(ValueError):
        repair.validate_saved(worksheet['id'],spec,worksheet['project_id'])
    assert not many('SELECT * FROM practice_repair_contexts')


def test_changed_current_scores_and_causes_invalidate_old_repair_reference(monkeypatch):
    worksheet,submission,_=completed(monkeypatch)
    first=repair.build(worksheet,submission)
    changed=copy.deepcopy(submission);grade=unj(changed['grade_json']);grade['feedback'][0]='新复核指出定义与结论的混淆'
    changed['grade_json']=j(grade)
    assert repair.build(worksheet,changed)['signature']!=first['signature']


@pytest.mark.parametrize('change',['missing','wrong_target','duplicate','topic'])
def test_generated_repairs_cannot_omit_swap_duplicate_or_mislabel_targets(monkeypatch,change):
    worksheet,submission,_=completed(monkeypatch);spec=repair.build(worksheet,submission);items=new_questions(spec)
    if change=='missing':items=[]
    if change=='wrong_target':items[0]['repair_target_index']=1
    if change=='duplicate':items[0]['question']=spec['targets'][0]['question']
    if change=='topic':items[0]['topic']='其他知识'
    with pytest.raises(ValueError):repair.validate(items,spec)


def test_actual_repair_request_uses_original_causes_exports_word_and_reuses_only_matching_reference(monkeypatch,tmp_path):
    worksheet,submission,_=completed(monkeypatch,self_report=True)
    spec=repair.build(worksheet,submission);calls=[];real=httpx.AsyncClient
    def respond(request):
        body=json.loads(request.content);calls.append(body);system=body['messages'][0]['content']
        if '严谨的习题设计者' in system:answer={'questions':new_questions(spec)}
        elif '独立解题员' in system:answer={'answers':[{'index':0,'solution':'独立求解完成。','issues':[]}]}
        elif '批改者' in system:answer={'scores':[100],'feedback':['区分了整体与局部，理由完整。'],'uncertainties':[]}
        else:answer={'passed':True,'issues':[]}
        if body.get('stream'):
            return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':j(answer)},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
        return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':j(answer)},'finish_reason':'stop'}]})
    monkeypatch.setattr(ai,'get_secret',lambda key:'fixture-only')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:real(transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(exercises,'search_exercises',lambda title:asyncio.sleep(0,result=[]))
    async def choose(*a,**kw):pass
    async def factory(*a,**kw):return ai.DeepSeekClient('repair-test-model')
    monkeypatch.setattr(server,'choose_generation_model',choose);monkeypatch.setattr(server,'assessment_client',factory)
    api=TestClient(server.app);url='/api/exercises/'+worksheet['id']+'/repair'
    first=api.post(url,json={'provider':'deepseek','model':'repair-test-model'})
    assert first.status_code==200,first.text
    data=first.json();fresh=data['exercise_set'];assert len(fresh['questions'])==1
    assert fresh['difficulty']==worksheet['difficulty'] and not fresh.get('solutions')
    assert fresh['repair']['targets'][0]['index']==0 and fresh['repair']['targets'][0]['basis']=='student_self_report'
    assert len(calls)==4
    user=calls[0]['messages'][-1]['content'];assert '我把电通量当成' in user and 'teaching_excerpt' in user
    assert user.count('修复目标数据：')==1
    artifact=one('SELECT * FROM artifacts WHERE id=?',(data['artifact']['id'],))
    text='\n'.join(p.text for p in Document(artifact['path']).paragraphs)
    assert 'NEW_0' in text and '原题' in text and 'PRIVATE_FOCUS' not in text and 'PRIVATE_NEW_SOLUTION' not in text
    again=api.post(url,json={'provider':'deepseek','model':'repair-test-model'}).json()
    assert again['cached'] and again['exercise_set']['id']==fresh['id'] and len(calls)==4
    assert 'PRIVATE_FOCUS' not in j(exercises.public_set(fresh['id']))
    assert 'PRIVATE_FOCUS' not in j(server.artifacts(worksheet['project_id']))
    assert not exercises.public_set(fresh['id'],True).get('solutions')
    grade=asyncio.run(exercises.grade_submission(ai.DeepSeekClient('repair-test-model'),fresh['id'],
        ['净和为零可以来自抵消；各点电场是局部量，不能由一个整体净和直接确定。'],recovery_mode='adaptive',used_notes=False))
    assert grade['score']==100
    assert 'PRIVATE_FOCUS' in exercises.student_document(fresh['id'],include_solutions=True)
    assert one('SELECT score FROM submissions WHERE id=?',(submission['id'],))['score']==95


@pytest.mark.parametrize('kind',['repair','new_context'])
@pytest.mark.parametrize('change_text',[True,False])
def test_real_revision_path_validates_target_fields_before_another_independent_solve(monkeypatch,tmp_path,kind,change_text):
    if kind=='repair':
        worksheet,submission,_=completed(monkeypatch);spec=repair.build(worksheet,submission)
        items=new_questions(spec);kwargs={'repair_spec':spec};field='repair_target_index'
        project=worksheet['project_id']
    else:
        from test_learning_transfer import seed,proposed
        from studyforge import learning_goals
        project,*_,goal,base,_=seed(tmp_path)
        spec=learning_goals.check_spec(learning_goals.get(goal['id'],project),'new_context')
        items=proposed(spec);kwargs={'check_spec':spec};field='context_change'
    events=[];solves=0;revisions=0
    class Model:
        async def complete(self,system,user,**kw):
            nonlocal solves,revisions
            if '正在修订当前题单' in system:
                revisions+=1;events.append('revision')
                assert field in user, 'The dedicated revision must receive the extra-field policy'
                changed=copy.deepcopy(items)
                if change_text:
                    for q in changed:q['question']+=' 请在明确的新条件下重新论证。'
                if revisions==1:
                    for q in changed:q.pop(field,None)
                return j({'questions':changed})
            if '严谨的习题设计者' in system:return j({'questions':items})
            if '独立解题员' in system:
                solves+=1;events.append('solve')
                return j({'answers':[{'index':i,'solution':'独立求解。','issues':[]} for i in range(len(items))]})
            if solves==1 and '阶段：解析核查' in user:
                return j({'passed':False,'issues':[{'index':0,'category':'solution','problem':'需更正实际算式。'}]})
            return j({'passed':True,'issues':[]})
    monkeypatch.setattr(exercises,'search_exercises',lambda title:asyncio.sleep(0,result=[]))
    ident,_=asyncio.run(exercises.generate_set(Model(),project,[],'合成原资料','修订验收',2,**kwargs))
    expected=['solve','revision','revision','solve'] if change_text else ['solve','revision','solve']
    assert events==expected, 'Changed questions need validated metadata; unchanged stems can reuse their original fields without an extra model request'
    data=exercises.public_set(ident);assert 'solutions' not in data
    private=unj(one('SELECT solutions_json FROM exercise_sets WHERE id=?',(ident,))['solutions_json'])
    assert all(field in q for q in private)
