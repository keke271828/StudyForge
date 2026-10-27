"""Resume after a committed grade but before the outer phase cache is saved."""
import asyncio
import copy
import pytest
from studyforge import homework,server,workflows,coding,exercises,learning_memory,homework_checkpoint
from studyforge.db import execute,j,many,one,unj
from tests.test_homework import fixture,finish


@pytest.mark.parametrize('language',[None,'javascript'])
def test_committed_grade_survives_missing_phase_cache_without_grading_again(monkeypatch,language):
    project,_,set_id,teacher,value=fixture(monkeypatch,unknown=False,language=language)
    if language:monkeypatch.setattr(coding,'_run_assignment_tests',lambda *a:{'ran':True,'score':50,'output':'controlled'})
    real=workflows.phase;broken=True
    async def interrupted(name,operation):
        nonlocal broken
        if name=='homework:grade' and broken:
            broken=False
            await operation()  # Database commits, process stops before phase saves its return value.
            raise OSError('simulated interruption after committed grade')
        return await real(name,operation)
    monkeypatch.setattr(workflows,'phase',interrupted)
    async def scenario():
        accepted=await homework.enqueue(set_id,value,code='function add(a,b){return a-b;}') if language else await server.submit_answers(set_id,value)
        assert (await finish(accepted))['status']=='failed'
        assert not one("SELECT 1 FROM generation_steps WHERE job_id=? AND step_key='phase:homework:grade'",(accepted['job_id'],))
        original=copy.deepcopy(many('SELECT * FROM mastery'))
        calls=len(teacher.calls)
        resumed=await server.homework_retry(accepted['id'],project['id'])
        task=await finish(resumed)
        assert task['status']=='completed',task['error']
        assert len(teacher.calls)==calls+1  # Only the missing targeted teaching, no grading.
        assert len(many('SELECT * FROM submissions'))==1
        assert many('SELECT * FROM mastery')==original
        assert homework.get_attempt(accepted['id'])['feedback_artifact_id']
    asyncio.run(scenario())


@pytest.mark.parametrize('language',[None,'javascript'])
def test_learning_evidence_failure_rolls_back_grade_and_checkpoint_together(monkeypatch,language):
    project,_,set_id,teacher,value=fixture(monkeypatch,unknown=False,language=language)
    if language:monkeypatch.setattr(coding,'_run_assignment_tests',lambda *a:{'ran':True,'score':50,'output':'controlled'})
    owner=learning_memory if language else exercises
    original=owner.assessment_record
    def broken(*args,**kwargs):
        original(*args,**kwargs)
        raise PermissionError('controlled learning evidence failure')
    monkeypatch.setattr(owner,'assessment_record',broken)
    async def scenario():
        accepted=await homework.enqueue(set_id,value,code='function add(a,b){return a-b;}') if language else await server.submit_answers(set_id,value)
        assert (await finish(accepted))['status']=='failed'
        assert not many('SELECT * FROM submissions') and not many('SELECT * FROM mastery')
        assert not many('SELECT * FROM learning_events') and not many('SELECT * FROM learning_insights')
        assert unj(homework.get_attempt(accepted['id'])['grade_json'])=={}
        assert one('SELECT status FROM exercise_sets WHERE id=?',(set_id,))['status']=='assigned'
        monkeypatch.setattr(owner,'assessment_record',original)
        resumed=await server.homework_retry(accepted['id'],project['id'])
        assert (await finish(resumed))['status']=='completed'
        assert len(many('SELECT * FROM submissions'))==1
        assert all(row['evidence_count']==1 for row in many('SELECT * FROM mastery'))
    asyncio.run(scenario())


@pytest.mark.parametrize('damage',['missing_marker','missing_field','grade_json','empty_list','missing_submission','student_answer','submission_answer','grade_value','numeric_score','version'])
def test_recovery_rejects_missing_or_mismatched_proof_without_guessing_latest(monkeypatch,damage):
    _,_,set_id,teacher,value=fixture(monkeypatch,unknown=False)
    real=workflows.phase
    async def interrupted(name,operation):
        if name=='homework:grade':await operation();raise PermissionError('controlled stop before cache')
        return await real(name,operation)
    monkeypatch.setattr(workflows,'phase',interrupted)
    async def scenario():
        accepted=await server.submit_answers(set_id,value);await finish(accepted)
        row=homework.get_attempt(accepted['id']);grade=unj(row['grade_json']);submission=grade['submission_id']
        if damage=='missing_marker':
            grade.pop('homework_attempt_id');execute('UPDATE homework_attempts SET grade_json=? WHERE id=?',(j(grade),row['id']))
        elif damage=='missing_field':
            grade.pop('scores');execute('UPDATE homework_attempts SET grade_json=? WHERE id=?',(j(grade),row['id']))
        elif damage in ('grade_json','empty_list'):
            execute('UPDATE homework_attempts SET grade_json=? WHERE id=?',('broken' if damage=='grade_json' else '[]',row['id']))
        elif damage=='missing_submission':execute('DELETE FROM submissions WHERE id=?',(submission,))
        elif damage=='student_answer':execute('UPDATE homework_attempts SET answers_json=? WHERE id=?',(j(['changed','2+3=4']),row['id']))
        elif damage=='submission_answer':execute('UPDATE submissions SET answers_json=? WHERE id=?',(j(['changed','2+3=4']),submission))
        elif damage=='grade_value':execute("UPDATE submissions SET grade_json=json_set(grade_json,'$.scores[0]',100) WHERE id=?",(submission,))
        elif damage=='numeric_score':execute('UPDATE submissions SET score=100 WHERE id=?',(submission,))
        elif damage=='version':execute('UPDATE exercise_sets SET difficulty=4 WHERE id=?',(set_id,))
        calls=len(teacher.calls);mastery=copy.deepcopy(many('SELECT * FROM mastery'))
        from studyforge.review_versions import ReviewVersionConflict
        with pytest.raises(ReviewVersionConflict):homework_checkpoint.restore(row['id'],one('SELECT * FROM exercise_sets WHERE id=?',(set_id,)))
        assert len(teacher.calls)==calls and many('SELECT * FROM mastery')==mastery
    asyncio.run(scenario())


def test_fresh_python_process_restores_persisted_score_without_grading_again(monkeypatch):
    import os,subprocess,sys,json
    from pathlib import Path
    project,_,set_id,teacher,value=fixture(monkeypatch,unknown=False)
    real=workflows.phase
    async def interrupted(name,operation):
        if name=='homework:grade':await operation();raise PermissionError('controlled stop before cache')
        return await real(name,operation)
    monkeypatch.setattr(workflows,'phase',interrupted)
    async def seed():
        accepted=await server.submit_answers(set_id,value)
        assert (await finish(accepted))['status']=='failed'
        return accepted
    accepted=asyncio.run(seed())
    env=dict(os.environ);env['PYTHONIOENCODING']='utf-8'
    result=subprocess.run([sys.executable,'-X','utf8','-m','scripts.resume_homework_checkpoint',accepted['id'],project['id']],
        cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
    proof=json.loads(result.stdout)
    assert proof['status']=='completed' and proof['mastery_unchanged'] and proof['submissions']==1
    assert proof['model_calls']==1 and proof['grading_calls']==0
