"""Review material must stay bound to the assessed question and rubric."""
import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from studyforge import exercises,practice,server
from studyforge.db import execute,j,many,one,unj
from tests.test_practice import make_set,grade,Grader


def prepared():
    ident,project=make_set()
    result,_=grade(ident,90,used_notes=False)
    return ident,project,result


def material(ident):return one('SELECT * FROM exercise_sets WHERE id=?',(ident,))


def mutate(ident,kind):
    row=material(ident);questions=unj(row['questions_json']);solutions=unj(row['solutions_json'])
    if kind=='question':questions[0]['question']='NEW_QUESTION：另一个完全不同的问题。'
    elif kind=='topic':questions[0]['topic']='NEW_TOPIC'
    elif kind=='solution':solutions[0]['solution']='NEW_PRIVATE_SOLUTION'
    elif kind=='rubric':solutions[0]['rubric']='NEW_PRIVATE_RUBRIC'
    elif kind=='removed':questions=[];solutions=[]
    else:execute('UPDATE exercise_sets SET difficulty=5 WHERE id=?',(ident,));return
    execute('UPDATE exercise_sets SET questions_json=?,solutions_json=? WHERE id=?',(j(questions),j(solutions),ident))


@pytest.mark.parametrize('kind',['question','topic','solution','rubric','difficulty','removed'])
def test_queued_review_uses_saved_material_after_origin_changes(kind):
    ident,project,_=prepared();original=material(ident);practice.schedule_review(ident,1)
    item=practice.review_queue()['items'][0];mutate(ident,kind)
    fresh,_=practice.start_review(project['id'],[item['id']]);copy=material(fresh)
    assert unj(copy['questions_json'])[0]['question']==unj(original['questions_json'])[0]['question']
    assert unj(copy['questions_json'])[0]['topic']==unj(original['questions_json'])[0]['topic']
    assert unj(copy['solutions_json'])[0]['solution']==unj(original['solutions_json'])[0]['solution']
    assert unj(copy['solutions_json'])[0]['rubric']==unj(original['solutions_json'])[0]['rubric']
    assert copy['difficulty']==original['difficulty']
    assert practice.attempt_context(fresh)['timing'][0]['same_question_verified'] is True


def test_queue_displays_saved_topic_and_version_notice_without_private_material():
    ident,_,_=prepared();practice.schedule_review(ident,1);mutate(ident,'topic')
    response=TestClient(server.app).get('/api/reviews');item=response.json()['items'][0]
    assert item['topic']=='论证' and item['source_changed'] is True
    assert '保存' in item['version_notice'] and 'PRIVATE' not in response.text and 'solution' not in response.text


def test_changed_unqueued_question_cannot_adopt_old_score_as_new_version():
    ident,_,_=prepared();mutate(ident,'rubric')
    before=many('SELECT * FROM submissions')
    with pytest.raises(ValueError,match='变更|更新|版本'):practice.schedule_review(ident,1)
    assert many('SELECT * FROM review_items')==[] and many('SELECT * FROM submissions')==before


def test_native_grade_has_server_owned_version_and_regrade_rejects_changed_material():
    ident,_,result=prepared()
    assert result['assessment_version']['version']==1 and result['assessment_version']['original_verified'] is True
    execute("UPDATE exercise_sets SET status='grading_review_required' WHERE id=?",(ident,));mutate(ident,'question')
    teacher=Grader(90);before=many('SELECT * FROM submissions')
    with pytest.raises(ValueError,match='变更|更新|版本'):
        asyncio.run(exercises.grade_submission(teacher,ident,['因为相似，因此机制相同。']))
    assert teacher.calls==[] and many('SELECT * FROM submissions')==before


def test_edit_during_grading_cannot_commit_score_for_another_question():
    ident,_=make_set()
    class Changing(Grader):
        async def complete(self,*args,**kwargs):
            response=await super().complete(*args,**kwargs);mutate(ident,'question');return response
    with pytest.raises(ValueError,match='变更|更新|版本'):
        asyncio.run(exercises.grade_submission(Changing(90),ident,['因为相似，因此机制相同。']))
    assert many('SELECT * FROM submissions')==many('SELECT * FROM learning_events')==[]


def test_original_change_does_not_rewrite_active_review_or_its_next_interval():
    ident,project,_=prepared();practice.schedule_review(ident,1);item=practice.review_queue()['items'][0]
    fresh,_=practice.start_review(project['id'],[item['id']]);mutate(ident,'question')
    assert practice.start_review(project['id'],[item['id']])==(fresh,True)
    grade(fresh,90,used_notes=False);practice.schedule_review(fresh,7)
    queued=practice.review_queue()['items'][0]
    assert queued['id']==item['id'] and queued['interval_days']==7 and queued['source_changed'] is True
    second,_=practice.start_review(project['id'],[item['id']])
    assert unj(material(second)['questions_json'])[0]['question']==unj(material(fresh)['questions_json'])[0]['question']


def test_edited_review_copy_cannot_use_old_score_to_reschedule_original():
    ident,project,_=prepared();practice.schedule_review(ident,1);item=practice.review_queue()['items'][0]
    fresh,_=practice.start_review(project['id'],[item['id']]);grade(fresh,90);mutate(fresh,'rubric')
    before=many('SELECT * FROM review_items')
    with pytest.raises(ValueError,match='变更|更新|版本'):practice.schedule_review(fresh,7)
    assert many('SELECT * FROM review_items')==before


def test_legacy_submission_can_practice_but_does_not_certify_same_question_spacing(monkeypatch):
    ident,project=make_set(graded=True)
    row=one('SELECT * FROM submissions WHERE exercise_set_id=?',(ident,));value=unj(row['grade_json']);value.pop('assessment_version',None)
    execute('UPDATE submissions SET grade_json=? WHERE id=?',(j(value),row['id']))
    practice.schedule_review(ident,1);item=practice.review_queue()['items'][0]
    assert item['version_verified'] is False and '旧' in item['version_notice']
    stamp=practice.clock_now()+timedelta(days=2);monkeypatch.setattr(practice,'clock_now',lambda:stamp)
    fresh,_=practice.start_review(project['id'],[item['id']]);grade(fresh,90,used_notes=False)
    from studyforge.learning_profile import effective_profile
    result=effective_profile()[0]
    assert result['review_count']==1 and result['delayed_count']==0 and result['quiz_score']==90
    assert practice.attempt_context(fresh)['timing'][0]['same_question_verified'] is False


def test_reformatting_json_and_renaming_title_do_not_change_material():
    ident,project,_=prepared();practice.schedule_review(ident,1);item=practice.review_queue()['items'][0]
    import json
    row=material(ident)
    execute('UPDATE exercise_sets SET title=?,questions_json=? WHERE id=?',('重命名原题',json.dumps(unj(row['questions_json']),ensure_ascii=True,indent=2),ident))
    assert practice.review_queue()['items'][0]['source_changed'] is False
    assert practice.start_review(project['id'],[item['id']])[0]


def test_editing_review_copy_before_submit_is_rejected_before_model_and_profile_changes():
    ident,project,_=prepared();practice.schedule_review(ident,1);item=practice.review_queue()['items'][0]
    fresh,_=practice.start_review(project['id'],[item['id']]);mutate(fresh,'question');teacher=Grader(90)
    before={table:many('SELECT * FROM '+table) for table in ('submissions','learning_events','review_items')}
    with pytest.raises(ValueError,match='版本|变更'):
        asyncio.run(exercises.grade_submission(teacher,fresh,['因为相似，因此机制相同。']))
    assert teacher.calls==[] and {table:many('SELECT * FROM '+table) for table in before}==before


@pytest.mark.parametrize('shape',[False,True])
def test_invalid_snapshot_is_not_replaced_with_current_source(shape):
    from studyforge.review_versions import fingerprint
    ident,project,_=prepared();practice.schedule_review(ident,1);item=practice.review_queue()['items'][0]
    value={'question':[],'solution':{},'difficulty':2}
    execute('UPDATE review_item_versions SET snapshot_json=?,fingerprint=? WHERE review_item_id=?',
        (j(value),fingerprint(value) if shape else 'wrong',item['id']))
    before=many('SELECT * FROM exercise_sets')
    assert '不完整' in practice.review_queue()['items'][0]['version_notice']
    with pytest.raises(ValueError,match='版本记录不完整'):practice.start_review(project['id'],[item['id']])
    assert many('SELECT * FROM exercise_sets')==before


def test_removing_review_plan_removes_private_snapshot():
    ident,_,_=prepared();practice.schedule_review(ident,1);item=practice.review_queue()['items'][0]
    assert len(many('SELECT * FROM review_item_versions'))==1
    practice.remove_review(item['id'])
    assert many('SELECT * FROM review_item_versions')==[]


def test_other_question_change_does_not_invalidate_an_unchanged_selected_question():
    ident,project=make_set();row=material(ident);questions=unj(row['questions_json']);solutions=unj(row['solutions_json'])
    questions.append(dict(questions[0],index=1,question='说明第二个不同的论证。'))
    solutions.append(dict(solutions[0],index=1))
    execute('UPDATE exercise_sets SET questions_json=?,solutions_json=? WHERE id=?',(j(questions),j(solutions),ident))
    class Two(Grader):
        async def complete(self,*a,**kw):return j({'scores':[90,90],'feedback':['明确理由','明确理由'],'uncertainties':[]})
    asyncio.run(exercises.grade_submission(Two(),ident,['给出第一个理由。','给出第二个理由。']))
    questions[1]['question']='修改第二题，不改变第一题。'
    execute('UPDATE exercise_sets SET questions_json=? WHERE id=?',(j(questions),ident))
    practice.schedule_review(ident,1,[0]);item=practice.review_queue()['items'][0]
    assert item['version_verified'] and item['source_changed'] is False


def test_model_cannot_supply_its_own_material_version():
    ident,_=make_set()
    class Forged(Grader):
        async def complete(self,*a,**kw):
            value=unj(await super().complete(*a,**kw));value['assessment_version']={'worksheet_sha256':'fake','original_verified':False};return j(value)
    result=asyncio.run(exercises.grade_submission(Forged(90),ident,['因为相似，因此机制相同。']))
    assert result['assessment_version']['worksheet_sha256']!='fake' and result['assessment_version']['original_verified'] is True


def test_mixed_reference_difficulties_keep_question_identity_and_rescheduling():
    first,project=make_set(difficulty=1);grade(first,90)
    second,_=make_set(project=project,difficulty=5);grade(second,90)
    practice.schedule_review(first,1);practice.schedule_review(second,1)
    ids=[item['id'] for item in practice.review_queue()['items']]
    fresh,_=practice.start_review(project['id'],ids)
    assert material(fresh)['difficulty']==3
    class Two(Grader):
        async def complete(self,*a,**kw):return j({'scores':[90,90],'feedback':['明确理由','明确理由'],'uncertainties':[]})
    asyncio.run(exercises.grade_submission(Two(),fresh,['因为相似，需要更多证据。']*2))
    practice.schedule_review(fresh,7)
    assert len(practice.review_queue()['items'])==2


def test_unknown_old_baseline_becomes_known_only_for_the_next_actual_attempt(monkeypatch):
    ident,project=make_set(graded=True);row=one('SELECT * FROM submissions WHERE exercise_set_id=?',(ident,))
    value=unj(row['grade_json']);value.pop('assessment_version')
    execute('UPDATE submissions SET grade_json=? WHERE id=?',(j(value),row['id']))
    practice.schedule_review(ident,1);item=practice.review_queue()['items'][0]
    stamp=practice.clock_now()+timedelta(days=2);monkeypatch.setattr(practice,'clock_now',lambda:stamp)
    first,_=practice.start_review(project['id'],[item['id']]);first_grade,_=grade(first,90,used_notes=False)
    assert first_grade['practice_context']['timing'][0]['same_question_verified'] is False
    assert practice.review_queue()['items'][0]['version_verified'] is True
    stamp+=timedelta(days=2)
    second,_=practice.start_review(project['id'],[item['id']]);second_grade,_=grade(second,90,used_notes=False)
    assert second_grade['practice_context']['timing'][0]['same_question_verified'] is True
    from studyforge.learning_profile import effective_profile
    assert effective_profile()[0]['delayed_count']==1


def test_old_database_upgrade_does_not_invent_missing_queue_version():
    from studyforge import db
    ident,project=make_set(graded=True);practice.schedule_review(ident,1);item=practice.review_queue()['items'][0]
    with db.connect() as database:database.execute('DROP TABLE review_item_versions')
    db._initialized_databases.clear()
    # Reopening an older DB adds an empty private snapshot table, without
    # changing grades or assuming a historical question version was saved.
    assert many('SELECT * FROM review_item_versions')==[]
    assert practice.review_queue()['items'][0]['version_verified'] is False
    fresh,_=practice.start_review(project['id'],[item['id']])
    assert fresh


def test_material_conflict_is_not_an_automatic_model_retry():
    from studyforge.review_versions import ReviewVersionConflict
    from studyforge.task_retry import classify
    assert classify(ReviewVersionConflict('复习版本记录不完整'))[0] is False


@pytest.mark.parametrize('mismatch',[None,'answers','submission'])
def test_old_detailed_attempt_establishes_version_only_for_the_matching_submission(mismatch):
    from studyforge import homework
    from studyforge.db import create_job,now,uid
    ident,project=make_set(graded=True);row=material(ident)
    submission=one('SELECT * FROM submissions WHERE exercise_set_id=?',(ident,))
    value=unj(submission['grade_json']);value.pop('assessment_version')
    execute('UPDATE submissions SET grade_json=? WHERE id=?',(j(value),submission['id']))
    job=create_job(project['id'],'homework_grade',{})
    execute('INSERT INTO homework_attempts(id,exercise_set_id,project_id,job_id,source_version,answers_json,'
        'options_json,grade_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
        (uid(),ident,project['id'],job,homework.version(row),
         j(['另一份作答']) if mismatch=='answers' else submission['answers_json'],'{}',
         j({'submission_id':'different' if mismatch=='submission' else submission['id']}),now(),now()))
    practice.schedule_review(ident,1)
    assert practice.review_queue()['items'][0]['version_verified'] is (mismatch is None)


def test_old_detailed_source_version_cannot_certify_changed_material():
    from studyforge import homework
    from studyforge.db import create_job,now,uid
    ident,project=make_set(graded=True);row=material(ident)
    submission=one('SELECT * FROM submissions WHERE exercise_set_id=?',(ident,))
    value=unj(submission['grade_json']);value.pop('assessment_version')
    execute('UPDATE submissions SET grade_json=? WHERE id=?',(j(value),submission['id']))
    job=create_job(project['id'],'homework_grade',{})
    execute('INSERT INTO homework_attempts(id,exercise_set_id,project_id,job_id,source_version,answers_json,'
        'options_json,grade_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
        (uid(),ident,project['id'],job,homework.version(row),submission['answers_json'],'{}',
         j({'submission_id':submission['id']}),now(),now()))
    mutate(ident,'rubric')
    with pytest.raises(ValueError,match='变更'):practice.schedule_review(ident,1)
    assert many('SELECT * FROM review_items')==[]
