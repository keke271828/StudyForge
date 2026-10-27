"""A submitted attempt freezes hint usage, even before its grader starts."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from studyforge import homework,practice,server
from studyforge.db import create_job,execute,j,many,now,one,uid
from tests.test_homework import fixture,finish


@pytest.mark.parametrize('status',['accepted','grading','awaiting_causes','clarified','awaiting_grade_review','failed','cancelled','completed'])
def test_durable_submission_blocks_late_hints_without_rewriting_usage(monkeypatch,status):
    project,chat,ident,teacher,value=fixture(monkeypatch)
    practice.get_hint(ident,0,'terminology',1)
    before=many('SELECT * FROM practice_hints');row=one('SELECT * FROM exercise_sets WHERE id=?',(ident,))
    job=create_job(project['id'],'homework_grade',{'set_id':ident,'workflow_version':1})
    execute('INSERT INTO homework_attempts(id,exercise_set_id,project_id,conversation_id,job_id,source_version,answers_json,options_json,status,created_at,updated_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?)',(uid(),ident,project['id'],chat['id'],job,homework.version(row),j(value.answers),'{}',status,now(),now()))
    response=TestClient(server.app).post('/api/exercises/'+ident+'/hint',json={'question_index':0,'kind':'terminology','level':2})
    assert response.status_code==400 and '完整提交' in response.text
    assert many('SELECT * FROM practice_hints')==before and teacher.calls==[]


def test_native_accepted_answer_release_and_grading_keep_pre_submission_hint_level(monkeypatch):
    project,chat,ident,teacher,value=fixture(monkeypatch,scores=(100,100),unknown=False)
    value=value.model_copy(update={'recovery_mode':'adaptive','used_notes':False})
    teacher.hold=True
    async def scenario():
        practice.get_hint(ident,0,'terminology',1)
        result=await server.submit_answers(ident,value)
        assert result['solution_artifact'] and result['status']=='accepted'
        with pytest.raises(ValueError,match='完整提交'):
            practice.get_hint(ident,0,'terminology',3)
        await asyncio.wait_for(teacher.entered.wait(),3)
        teacher.release.set()
        assert (await finish(result))['status']=='completed'
        submitted=one('SELECT grade_json FROM submissions WHERE exercise_set_id=?',(ident,))
        from studyforge.db import unj
        grade=unj(submitted['grade_json'])
        assert grade['practice_context']['hint_levels']=={'0':1}
        assert one('SELECT status FROM exercise_sets WHERE id=?',(ident,))['status']=='passed_with_support'
        assert len(many('SELECT * FROM submissions'))==1
        from tests.test_homework import paragraphs
        attempt=homework.get_attempt(result['id'])
        text=paragraphs(attempt['feedback_artifact_id'])
        assert '本软件记录请求过第1层通用思考提示' in text and '不证明独立完成' in text
        assert '本软件没有记录本题的提示请求' in text
    asyncio.run(scenario())
