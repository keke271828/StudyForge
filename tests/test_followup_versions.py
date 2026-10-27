"""Follow-up teaching must not pair an old grade with a changed question."""
import pytest
from fastapi.testclient import TestClient

from studyforge import learning_goals as goals,learning_memory as memory,learning_profile as profile,repair_learning,server
from studyforge.db import execute,j,many,one,unj
from studyforge.review_versions import assessment_basis
from tests.test_practice import make_set
from tests.test_learning_transfer import seed
from tests.test_profile_recency import record,row as profile_row


def mutate(ident,kind):
    row=one('SELECT * FROM exercise_sets WHERE id=?',(ident,))
    questions=unj(row['questions_json']);solutions=unj(row['solutions_json'])
    if kind=='question':questions[0]['question']='CHANGED_QUESTION：这是另一项知识要求。'
    elif kind=='topic':questions[0]['topic']='CHANGED_TOPIC'
    elif kind=='solution':solutions[0]['solution']='CHANGED_REFERENCE'
    elif kind=='rubric':solutions[0]['rubric']='CHANGED_RUBRIC'
    else:
        execute('UPDATE exercise_sets SET difficulty=5 WHERE id=?',(ident,));return
    execute('UPDATE exercise_sets SET questions_json=?,solutions_json=? WHERE id=?',(j(questions),j(solutions),ident))


def stored_state():
    return {table:many('SELECT * FROM '+table) for table in ('jobs','exercise_sets','submissions','learning_events','mastery')}


@pytest.mark.parametrize('kind',['question','topic','solution','rubric','difficulty'])
def test_changed_material_cannot_fall_back_to_score_only_repair(kind):
    ident,_=make_set(graded=True);mutate(ident,kind);before=stored_state()
    response=TestClient(server.app).get('/api/exercises/'+ident+'/repair-options')
    assert response.status_code==400,response.text
    assert '版本' in response.text and stored_state()==before


def test_matching_repair_and_legacy_unknown_have_explicit_version_basis():
    ident,_=make_set(graded=True);worksheet=one('SELECT * FROM exercise_sets WHERE id=?',(ident,))
    submission=one('SELECT * FROM submissions WHERE exercise_set_id=?',(ident,))
    assert repair_learning.build(worksheet,submission)['assessment_version_verified'] is True
    value=unj(submission['grade_json']);value.pop('assessment_version');submission['grade_json']=j(value)
    result=repair_learning.build(worksheet,submission)
    assert result['assessment_version_verified'] is False and '旧作答版本未核实' in result['notice']
    assert result['targets'][0]['basis']=='unresolved'


@pytest.mark.parametrize('kind',['question','topic','solution','rubric','difficulty'])
def test_changed_understanding_check_is_not_a_new_context_baseline(tmp_path,kind):
    project,*_,goal,base,submission_id=seed(tmp_path)
    worksheet=one('SELECT * FROM exercise_sets WHERE id=?',(base,))
    submission=one('SELECT * FROM submissions WHERE id=?',(submission_id,));grade=unj(submission['grade_json'])
    grade['assessment_version']=assessment_basis(worksheet)
    execute('UPDATE submissions SET grade_json=? WHERE id=?',(j(grade),submission_id))
    mutate(base,kind);before=stored_state()
    with pytest.raises(ValueError,match='版本'):goals.check_spec(goals.get(goal['id'],project),'new_context',base)
    assert goals.reviewable_check(goals.get(goal['id'],project)) is None
    assert stored_state()==before


def test_automatic_baseline_skips_changed_newer_check_and_uses_unchanged_older_one(tmp_path):
    from tests.test_learning_goals import linked_check,scored
    project,*_,goal,base,_=seed(tmp_path)
    newer=linked_check(goal,project);submission_id=scored(newer,[90]*3,created='2026-10-14T00:00:00+00:00')
    worksheet=one('SELECT * FROM exercise_sets WHERE id=?',(newer,))
    submission=one('SELECT * FROM submissions WHERE id=?',(submission_id,));grade=unj(submission['grade_json'])
    grade['assessment_version']=assessment_basis(worksheet)
    execute('UPDATE submissions SET grade_json=? WHERE id=?',(j(grade),submission_id));mutate(newer,'rubric')
    assert goals.reviewable_check(goals.get(goal['id'],project))==base
    packet=goals.check_spec(goals.get(goal['id'],project),'new_context')
    assert packet['baseline']['exercise_set_id']==base
    assert packet['baseline']['assessment_version_verified'] is False
    assert '未核实' in packet['baseline']['version_notice']


@pytest.mark.parametrize('verified',[True,False,None])
def test_tutor_recent_review_distinguishes_verified_from_unknown_spacing(verified):
    timing={'question_index':0,'delay_hours':25,'due_reached':True}
    if verified is not None:timing['same_question_verified']=verified
    record('review',90,context={'hint_levels':{},'used_notes':False,'is_review':True,'timing':[timing]})
    result=profile_row()['recent_assessments'][0]
    assert result['same_question_verified'] is (verified is True)
    context=memory.profile_context('高斯定律')
    assert ('同题版本已核实' if verified is True else '同题版本未核实') in context
    assert '间隔25小时' in context and 'PRIVATE_' not in j(result)
    packet=profile.mentor_profile('高斯定律')['topics'][0]['recent_assessments'][0]
    assert packet['same_question_verified'] is (verified is True)


def test_regular_assessment_is_not_labelled_as_a_review_version():
    record('normal',90,context={'hint_levels':{},'used_notes':False})
    assert profile_row()['recent_assessments'][0]['same_question_verified'] is None
    assert '同题版本' not in memory.profile_context('高斯定律')
