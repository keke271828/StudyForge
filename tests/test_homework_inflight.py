"""Change the worksheet during real suspended assessment steps, not after completion."""
import asyncio
import pytest

from studyforge import coding,homework,server,workflows,scheduling
from studyforge.db import execute,many,one,unj
from tests.test_homework import fixture,finish


def change(set_id):
    execute('UPDATE exercise_sets SET difficulty=4 WHERE id=?',(set_id,))


@pytest.mark.parametrize('point',['analysis','export'])
def test_changed_during_teaching_or_export_does_not_publish_a_mixed_report(monkeypatch,point):
    project,chat,set_id,teacher,value=fixture(monkeypatch,unknown=False)
    original=teacher.complete
    async def respond(system,user,**kwargs):
        result=await original(system,user,**kwargs)
        if point=='analysis' and '逐题诊断错因并补讲' in system:change(set_id)
        return result
    teacher.complete=respond
    original_export=workflows.export
    async def export(*args,**kwargs):
        path=await original_export(*args,**kwargs)
        if point=='export':change(set_id)
        return path
    monkeypatch.setattr(workflows,'export',export)
    async def scenario():
        accepted=await server.submit_answers(set_id,value)
        task=await finish(accepted)
        assert task['status']=='failed',task
        row=homework.get_attempt(accepted['id'])
        assert row['feedback_artifact_id'] is None
        assert not many("SELECT * FROM artifacts WHERE kind='grading'")
        assert len(many('SELECT * FROM submissions'))==1  # Already committed original grade remains evidence.
        assert not many("SELECT * FROM learning_insights WHERE kind='gap'")
        if point=='analysis':assert unj(row['analysis_json'],{})=={}
        assert '变更' in task['error']
    asyncio.run(scenario())


@pytest.mark.parametrize('phase',['homework:grade','homework:analysis'])
def test_changed_while_waiting_to_start_a_phase_stops_before_another_model_request(monkeypatch,phase):
    _,_,set_id,teacher,value=fixture(monkeypatch,unknown=False)
    original=workflows.phase
    async def waiting(name,operation):
        if name.startswith(phase):change(set_id)
        return await original(name,operation)
    monkeypatch.setattr(workflows,'phase',waiting)
    async def scenario():
        result=await server.submit_answers(set_id,value)
        task=await finish(result)
        assert task['status']=='failed' and '变更' in task['error']
        assert len(teacher.calls)==(0 if phase=='homework:grade' else 2)
        assert not many("SELECT * FROM artifacts WHERE kind='grading'")
    asyncio.run(scenario())


def test_changed_while_creating_client_closes_it_without_grading(monkeypatch):
    _,_,set_id,teacher,value=fixture(monkeypatch)
    closed=[]
    async def client(*args,**kwargs):change(set_id);return teacher
    async def close():closed.append(True)
    monkeypatch.setattr(server,'assessment_client',client);teacher.close=close
    async def scenario():
        accepted=await server.submit_answers(set_id,value)
        assert (await finish(accepted))['status']=='failed'
        assert not teacher.calls and closed==[True] and not many('SELECT * FROM submissions')
    asyncio.run(scenario())


def test_changed_during_reference_export_keeps_submission_but_does_not_publish(monkeypatch):
    _,_,set_id,teacher,value=fixture(monkeypatch)
    original=scheduling.run_local
    async def export(kind,operation,*args,**kwargs):
        path=await original(kind,operation,*args,**kwargs)
        if kwargs.get('label')=='答案解析本机排版':change(set_id)
        return path
    monkeypatch.setattr(scheduling,'run_local',export)
    async def scenario():
        with pytest.raises(Exception,match='变更'):await server.submit_answers(set_id,value)
        row=many('SELECT * FROM homework_attempts')[0]
        assert unj(row['answers_json'])==value.answers and row['solution_artifact_id'] is None
        assert not many('SELECT * FROM artifacts') and not many('SELECT * FROM submissions') and not teacher.calls
    asyncio.run(scenario())


def test_code_changed_during_container_run_never_starts_review(monkeypatch):
    _,_,set_id,teacher,value=fixture(monkeypatch,language='javascript',unknown=False)
    def tests(*args):change(set_id);return {'ran':True,'score':50,'output':'controlled'}
    monkeypatch.setattr(coding,'_run_assignment_tests',tests)
    async def scenario():
        accepted=await homework.enqueue(set_id,value,code='function add(a,b){return a-b;}')
        assert (await finish(accepted))['status']=='failed'
        assert not teacher.calls and not many('SELECT * FROM submissions')
    asyncio.run(scenario())


def test_unchanged_flow_still_produces_two_documents_without_extra_model_calls(monkeypatch):
    _,_,set_id,teacher,value=fixture(monkeypatch,unknown=False)
    async def scenario():
        accepted=await server.submit_answers(set_id,value)
        assert (await finish(accepted))['status']=='completed'
        assert len(teacher.calls)==3 and len(many('SELECT * FROM artifacts'))==2
        assert len(many('SELECT * FROM submissions'))==1
    asyncio.run(scenario())


@pytest.mark.parametrize('field',['difficulty','questions_json','solutions_json','test_code'])
def test_code_changed_during_review_does_not_save_a_grade_or_profile(monkeypatch,field):
    project,chat,set_id,teacher,value=fixture(monkeypatch,language='javascript',unknown=False)
    monkeypatch.setattr(coding,'_run_assignment_tests',lambda *args:{'ran':True,'score':50,'output':'controlled test'})
    original=teacher.complete
    async def respond(system,user,**kwargs):
        result=await original(system,user,**kwargs)
        if '编程教师' in system:
            if field=='difficulty':change(set_id)
            else:
                column='questions_json' if field=='questions_json' else 'solutions_json'
                from studyforge.db import j
                saved=unj(one('SELECT '+column+' FROM exercise_sets WHERE id=?',(set_id,))[column])
                key='question' if field=='questions_json' else 'solution' if field=='solutions_json' else 'test_code'
                saved[0][key]+=' CHANGED'
                execute('UPDATE exercise_sets SET '+column+'=? WHERE id=?',(j(saved),set_id))
        return result
    teacher.complete=respond
    async def scenario():
        accepted=await homework.enqueue(set_id,value,code='function add(a,b){return a-b;}')
        task=await finish(accepted)
        assert task['status']=='failed',task
        assert not many('SELECT * FROM submissions') and not many('SELECT * FROM mastery')
        assert not many('SELECT * FROM learning_events')
        assert one('SELECT status FROM exercise_sets WHERE id=?',(set_id,))['status']=='assigned'
        assert not many("SELECT * FROM artifacts WHERE kind='grading'")
    asyncio.run(scenario())


def test_version_conflict_is_not_retried_as_a_model_or_network_failure():
    from studyforge.review_versions import ReviewVersionConflict
    from studyforge.task_retry import classify
    assert classify(ReviewVersionConflict('版本变化'))[0] is False
