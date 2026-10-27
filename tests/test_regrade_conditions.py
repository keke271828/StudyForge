"""Rechecking a score must not turn the same work into an unaided attempt."""
import asyncio
import copy

import pytest
from fastapi.testclient import TestClient

from studyforge import exercises,learning_profile,server
from studyforge.db import execute,j,many,now,one,unj
from tests.test_assessment_quality import Replies,response,worksheet


def pending(*,used_notes=True,mode='adaptive'):
    ident,project=worksheet();doubt='参考评分点仍需核实，不能据此定分。'
    client=Replies([response([20],doubts=[doubt]),response([20]),response([20],doubts=[doubt])])
    result=asyncio.run(exercises.grade_submission(client,ident,['从2依次加三个1，得到5。'],
        recovery_mode=mode,used_notes=used_notes))
    assert result['grading_verification_required'] and many('SELECT * FROM learning_events')==[]
    return ident,project,result


@pytest.mark.parametrize('notes',[True,False,None])
def test_api_recheck_preserves_original_conditions_and_single_attempt(monkeypatch,notes):
    ident,project,original=pending(used_notes=notes);before=copy.deepcopy(original['practice_context'])
    client=Replies([response([100]),response([100])])
    async def factory(*args,**kwargs):return client
    monkeypatch.setattr(server,'assessment_client',factory)
    result=TestClient(server.app).post('/api/exercises/'+ident+'/regrade',json={'provider':'deepseek'})
    assert result.status_code==200,result.text
    value=result.json()
    assert value['practice_context']==before
    assert value['submission_id']==original['submission_id'] and value['regrade_basis']['same_answers']
    assert len(many('SELECT * FROM submissions'))==len(many("SELECT * FROM learning_events WHERE kind='做题'"))==1
    assert len(client.calls)==2
    profile=learning_profile.effective_profile()[0]
    assert profile['quiz_score']==100 and profile['assisted_count']==int(notes is True)
    assert profile['unaided_quiz_score']==(100 if notes is False else None)
    assert one('SELECT status FROM exercise_sets WHERE id=?',(ident,))['status']==('passed_with_support' if notes is True else 'passed')


@pytest.mark.parametrize('mode,status',[('adaptive','repair_required'),('strict','feynman_required')])
def test_recheck_keeps_original_recovery_mode_after_default_changes(mode,status):
    ident,project,original=pending(mode=mode)
    changed='strict' if mode=='adaptive' else 'adaptive'
    execute('UPDATE practice_options SET recovery_mode=?,updated_at=? WHERE exercise_set_id=?',(changed,now(),ident))
    client=Replies([response([79]),response([79])])
    result=asyncio.run(exercises.grade_submission(client,ident,['从2依次加三个1，得到5。'],recovery_mode=changed,used_notes=False))
    assert result['practice_context']==original['practice_context']
    assert result['recovery_mode']==mode
    assert one('SELECT status FROM exercise_sets WHERE id=?',(ident,))['status']==status
    assert result['requires_feynman'] is (mode=='strict')


@pytest.mark.parametrize('legacy',[None,{}, {'used_notes':False},{'used_notes':True}])
def test_legacy_missing_conditions_do_not_become_self_reported_no_help(legacy):
    ident,project,original=pending()
    saved=unj(one('SELECT grade_json FROM submissions WHERE exercise_set_id=?',(ident,))['grade_json'])
    if legacy is None:saved.pop('practice_context')
    else:saved['practice_context']=legacy
    saved.pop('recovery_mode')
    execute('UPDATE submissions SET grade_json=? WHERE exercise_set_id=?',(j(saved),ident))
    client=Replies([response([100]),response([100])])
    result=asyncio.run(exercises.grade_submission(client,ident,['从2依次加三个1，得到5。'],used_notes=False))
    state='not_recorded' if legacy is None else 'partial'
    assert result['practice_context']['recording_status']==state
    assert result['practice_context']['used_notes']==(legacy.get('used_notes') if isinstance(legacy,dict) else None)
    assert result['regrade_basis']['conditions']==state
    assert learning_profile.effective_profile()[0]['unaided_quiz_score'] is None
    observation=one('SELECT observation FROM learning_insights')['observation']
    assert '无法核实' in observation and '软件提示0层' not in observation


def test_first_grading_cannot_claim_a_recheck_from_model_output():
    ident,project=worksheet();value=response([100]);value['regrade_basis']={'same_answers':True}
    result=asyncio.run(exercises.grade_submission(Replies([value,response([100])]),ident,['从2依次加三个1，得到5。']))
    assert 'regrade_basis' not in result
