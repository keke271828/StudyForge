"""The submitted recovery choice is durable, visible and actually used."""
import asyncio

import pytest

from studyforge import homework,server
from studyforge.db import execute,j,many,now,one,unj
from tests.test_homework import fixture,finish


@pytest.mark.parametrize('mode,expected',[('adaptive','repair_required'),('strict','feynman_required')])
def test_default_policy_is_frozen_before_queued_grading(monkeypatch,mode,expected):
    project,chat,ident,teacher,value=fixture(monkeypatch,scores=(79,79),unknown=False)
    execute('INSERT INTO practice_options VALUES (?,?,?)',(ident,mode,now()))
    teacher.hold=True
    async def scenario():
        result=await server.submit_answers(ident,value)
        saved=unj(homework.get_attempt(result['id'])['options_json'])
        # A different frontend changes the worksheet default while this attempt
        # is queued. The accepted attempt must retain its original choice.
        execute('UPDATE practice_options SET recovery_mode=? WHERE exercise_set_id=?',
                ('strict' if mode=='adaptive' else 'adaptive',ident))
        await asyncio.wait_for(teacher.entered.wait(),3)
        teacher.release.set()
        assert (await finish(result))['status']=='completed'
        assert one('SELECT status FROM exercise_sets WHERE id=?',(ident,))['status']==expected
        assert saved['recovery_mode']==mode and result['recovery_mode']==mode
        attempt=homework.public_attempt(homework.get_attempt(result['id']))
        assert attempt['recovery_mode']==mode and attempt['score']==79
        assert len(many('SELECT * FROM submissions'))==1
        assert len(many('SELECT * FROM exercise_sets'))==1
    asyncio.run(scenario())


@pytest.mark.parametrize('mode,expected',[('adaptive','repair_required'),('strict','feynman_required')])
def test_explicit_choice_overrides_worksheet_default_and_is_reported(monkeypatch,mode,expected):
    project,chat,ident,teacher,value=fixture(monkeypatch,scores=(79,79),unknown=False)
    other='strict' if mode=='adaptive' else 'adaptive'
    execute('INSERT INTO practice_options VALUES (?,?,?)',(ident,other,now()))
    value=value.model_copy(update={'recovery_mode':mode,'used_notes':False})
    async def scenario():
        result=await server.submit_answers(ident,value)
        assert result['recovery_mode']==mode
        assert (await finish(result))['status']=='completed'
        assert one('SELECT status FROM exercise_sets WHERE id=?',(ident,))['status']==expected
        grade=unj(one('SELECT grade_json FROM submissions WHERE exercise_set_id=?',(ident,))['grade_json'])
        assert grade['recovery_mode']==mode
        assert grade['requires_feynman'] is (mode=='strict')
        assert grade['requires_repair'] is (mode=='adaptive')
    asyncio.run(scenario())
