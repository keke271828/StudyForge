"""A dependent repair uses completed diagnosis, while legacy practice stays available."""
import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from scripts.repair_learning_fixture import seed
from studyforge import ai,homework,repair_learning as repair,server
from studyforge.db import create_project,execute,many,now,one
from tests.test_homework import fixture,finish
from tests.test_practice import make_set
from studyforge.job_control import cancel_job


def state():
    return {table:many('SELECT * FROM '+table) for table in ('jobs','exercise_sets','submissions','learning_events','mastery')}


@pytest.mark.parametrize('status',['accepted','grading','clarified','failed','cancelled','awaiting_grade_review'])
def test_incomplete_detailed_feedback_does_not_fall_back_to_generic_targets(tmp_path,status):
    data=seed(tmp_path)
    execute('UPDATE homework_attempts SET status=? WHERE id=?',(status,data['attempt_id']))
    before=state()
    response=TestClient(server.app).get('/api/exercises/'+data['set_id']+'/repair-options')
    assert response.status_code==400,response.text
    assert '补讲' in response.text or '批改' in response.text
    assert state()==before


@pytest.mark.parametrize('status',['queued','running','paused','failed','cancelled'])
def test_task_must_finish_even_if_its_feedback_row_was_saved(tmp_path,status):
    data=seed(tmp_path);attempt=homework.get_attempt(data['attempt_id'])
    execute('UPDATE jobs SET status=? WHERE id=?',(status,attempt['job_id']))
    assert not homework.public_attempt(homework.get_attempt(data['attempt_id']))['repair_available']
    response=TestClient(server.app).get('/api/exercises/'+data['set_id']+'/repair-options')
    assert response.status_code==400,response.text
    assert '任务' in response.text or '批改' in response.text


def test_native_failed_diagnosis_keeps_score_but_requires_finishing_feedback(monkeypatch):
    project,chat,ident,teacher,value=fixture(monkeypatch,scores=(90,100),unknown=False)
    ai.save_settings({'task_auto_retry':False})
    teacher.broken=True
    async def scenario():
        result=await server.submit_answers(ident,value)
        assert (await finish(result))['status']=='failed'
        return result
    result=asyncio.run(scenario())
    assert one('SELECT score FROM submissions WHERE exercise_set_id=?',(ident,))['score']==95
    assert homework.public_attempt(homework.get_attempt(result['id']))['repair_available'] is False
    before=len(teacher.calls)
    response=TestClient(server.app).get('/api/exercises/'+ident+'/repair-options')
    assert response.status_code==400 and ('补讲' in response.text or '批改' in response.text)
    assert len(teacher.calls)==before and len(many('SELECT * FROM exercise_sets'))==1


def test_grade_only_legacy_without_detailed_attempt_remains_usable():
    ident,project=make_set(graded=True)
    response=TestClient(server.app).get('/api/exercises/'+ident+'/repair-options')
    assert response.status_code==200,response.text
    assert response.json()['targets'][0]['basis']=='unresolved'


def test_completed_detailed_feedback_keeps_its_actual_teaching(tmp_path):
    data=seed(tmp_path)
    worksheet=one('SELECT * FROM exercise_sets WHERE id=?',(data['set_id'],))
    submission=one('SELECT * FROM submissions WHERE id=?',(data['submission_id'],))
    spec=repair.build(worksheet,submission)
    assert spec['analysis_status']=='completed' and spec['targets'][0]['basis']=='student_self_report'
    assert '净通量' in spec['targets'][0]['teaching_excerpt']


def test_cancelled_questionnaire_restores_original_feedback_without_regrading(monkeypatch):
    project,chat,ident,teacher,value=fixture(monkeypatch,scores=(90,100),unknown=True)
    async def scenario():
        result=await server.submit_answers(ident,value);await finish(result)
        assert homework.get_attempt(result['id'])['status']=='awaiting_causes'
        calls=len(teacher.calls);await cancel_job(result['job_id'])
        resumed=await server.homework_retry(result['id'],project['id'])
        assert resumed['waiting_for_causes'] and resumed['solution_artifact']['id']==result['solution_artifact']['id']
        assert one('SELECT status FROM jobs WHERE id=?',(result['job_id'],))['status']=='paused'
        assert len(teacher.calls)==calls
        await server.homework_causes(result['id'],server.HomeworkCausesIn(responses=[
            {'index':0,'kinds':['terminology'],'text':'我把电通量当成每个点的电场。'}]),project['id'])
        assert (await finish(result))['status']=='completed'
        assert len([x for x in teacher.calls if '批改者' in x[0]])==2
        assert len(many('SELECT * FROM submissions'))==1
        assert server.repair_options(ident)['targets'][0]['basis']=='student_self_report'
    asyncio.run(scenario())


def test_cancelled_inflight_grading_can_continue_original_submission(monkeypatch):
    project,chat,ident,teacher,value=fixture(monkeypatch,scores=(90,100),unknown=False)
    teacher.hold=True
    async def scenario():
        result=await server.submit_answers(ident,value)
        await asyncio.wait_for(teacher.entered.wait(),3)
        await cancel_job(result['job_id'])
        assert homework.public_attempt(homework.get_attempt(result['id']))['status']=='cancelled'
        await server.homework_retry(result['id'],project['id'])
        assert (await finish(result))['status']=='completed'
        assert len(many('SELECT * FROM submissions'))==len(many('SELECT * FROM homework_attempts'))==1
        assert len(many('SELECT * FROM exercise_sets'))==1
    asyncio.run(scenario())


@pytest.mark.parametrize('changed',['project','worksheet','deleted'])
def test_explicit_cancelled_recovery_keeps_scope_and_deletion_boundaries(tmp_path,changed):
    data=seed(tmp_path);attempt=homework.get_attempt(data['attempt_id']);project=data['project_id']
    execute("UPDATE jobs SET status='cancelled' WHERE id=?",(attempt['job_id'],))
    if changed=='project':project=create_project('其他项目')['id']
    elif changed=='worksheet':execute('UPDATE exercise_sets SET difficulty=5 WHERE id=?',(data['set_id'],))
    else:execute('INSERT INTO deleted_job_records VALUES (?,?)',(attempt['job_id'],now()))
    before=one('SELECT * FROM jobs WHERE id=?',(attempt['job_id'],))
    with pytest.raises(HTTPException):asyncio.run(server.homework_retry(attempt['id'],project))
    assert one('SELECT * FROM jobs WHERE id=?',(attempt['job_id'],))==before
    assert len(many('SELECT * FROM submissions'))==1
    if changed=='deleted':assert not homework.public_attempt(attempt)['can_retry']


def test_explicit_cancelled_recovery_waits_for_old_worker_cleanup(tmp_path):
    from studyforge.job_control import active_jobs
    data=seed(tmp_path);attempt=homework.get_attempt(data['attempt_id']);job=attempt['job_id']
    execute("UPDATE jobs SET status='cancelled' WHERE id=?",(job,))
    async def scenario():
        previous=asyncio.create_task(asyncio.Event().wait());active_jobs[job]=previous
        try:
            with pytest.raises(HTTPException,match='收尾'):
                await server.homework_retry(attempt['id'],data['project_id'])
            assert one('SELECT status FROM jobs WHERE id=?',(job,))['status']=='cancelled'
        finally:
            previous.cancel();await asyncio.gather(previous,return_exceptions=True);active_jobs.pop(job,None)
    asyncio.run(scenario())
