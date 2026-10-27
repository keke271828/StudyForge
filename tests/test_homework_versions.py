"""Historical answers always refer to the worksheet accepted with that attempt."""
import asyncio
import pytest
from fastapi.testclient import TestClient

from studyforge import homework, homework_context, server
from studyforge.agent_tools import AgentRuntime
from studyforge.db import connect, execute, j, many, one, unj
from tests.test_homework_context import case, read
from tests.test_homework_reader import activity, url


def change(worksheet, *, shrink=False):
    questions=unj(worksheet['questions_json'])
    questions[0].update(topic='NEW_TOPIC',question='NEW_QUESTION')
    if shrink:questions=questions[:1]
    execute('UPDATE exercise_sets SET questions_json=?,solutions_json=?,difficulty=4 WHERE id=?',
        (j(questions),j([{'index':0,'solution':'NEW_REFERENCE','rubric':'NEW_RUBRIC'}]),worksheet['id']))


@pytest.mark.parametrize('shrink',[False,True])
def test_changed_pending_questionnaire_never_pairs_new_question_with_old_answer(tmp_path,shrink):
    project,_,attempt,worksheet,_=case(tmp_path,status='awaiting_causes',feedback=False)
    analysis=unj(homework.get_attempt(attempt)['analysis_json'])
    analysis['items'][1]['confidence']='uncertain'
    execute('UPDATE homework_attempts SET analysis_json=? WHERE id=?',(j(analysis),attempt))
    change(worksheet,shrink=shrink)
    response=TestClient(server.app).get(f'/api/homework/{attempt}?project_id={project["id"]}')
    assert response.status_code==200,response.text
    result=response.json()
    assert result['current_version_matches'] is False
    assert not result['questions'] and not result['waiting_for_causes']
    assert result['status']=='source_changed' and result['version_notice']
    assert not result['can_retry'] and not result['repair_available']
    assert 'NEW_QUESTION' not in j(result)


def test_original_catalog_reference_and_score_survive_a_shorter_current_worksheet(tmp_path):
    project,chat,attempt,worksheet,_=case(tmp_path)
    change(worksheet,shrink=True)
    before=activity()
    catalog=homework_context.reader(attempt,project['id'])
    assert catalog['questions']==[{'question_number':1,'topic':'高斯定律'},{'question_number':2,'topic':'加法'}]
    result=homework_context.reader(attempt,project['id'],question_number=2)
    assert '计算2+3' in result['text'] and 'REFERENCE_ADD' in result['text'] and '2+3=4' in result['text']
    assert '90/100' in result['text'] and 'NEW_' not in j(result)
    assert not result['current_version_matches'] and result['version_notice'] in result['text']
    assert result['repair_reference'] is None
    assert activity()==before
    listing=read(project,chat)
    assert listing['items'][0]['question_count']==2 and not listing['items'][0]['current_version_matches']
    current=one('SELECT * FROM exercise_sets WHERE id=?',(worksheet['id'],))
    assert not homework.answers_released(current)


def test_cache_invalidates_when_worksheet_changes_without_attempt_timestamp_update(tmp_path):
    project,chat,_,worksheet,_=case(tmp_path)
    before=AgentRuntime(project['id'],conversation_id=chat['id']).state_key()
    change(worksheet)
    assert AgentRuntime(project['id'],conversation_id=chat['id']).state_key()!=before


def test_new_version_warning_rejects_stale_window_continuation(tmp_path):
    project,_,attempt,worksheet,_=case(tmp_path)
    client=TestClient(server.app)
    first=client.get(url(attempt,project)+'&question_number=1&limit=200').json()
    change(worksheet)
    stale=client.get(url(attempt,project)+'&question_number=1&offset=200&record_sha256='+first['record_sha256'])
    assert stale.status_code==409 and '不会拼接' in stale.text
    fresh=client.get(url(attempt,project)+'&question_number=1').json()
    assert fresh['record_sha256']!=first['record_sha256']


@pytest.mark.parametrize('snapshot',[
    'not-json','[]','{}','null','["x","y"]','[1,2,3]',
    j(['not-json','[]',2]),j(['[]','[]',True]),j(['[]','[]',2]),
    j([j([{'index':0,'topic':'old','question':'ORIGINAL'}]),'[]',2]),
    j([j([{'index':4,'topic':'old','question':'ORIGINAL'}]),j([{'index':4,'solution':'PRIVATE'}]),2]),
])
def test_damaged_snapshot_does_not_fall_back_to_new_questions_or_break_listing(tmp_path,snapshot):
    project,chat,attempt,worksheet,_=case(tmp_path)
    change(worksheet)
    execute('UPDATE homework_attempts SET source_version=? WHERE id=?',(snapshot,attempt))
    result=homework.public_attempt(homework.get_attempt(attempt))
    assert result['status']=='source_unavailable' and not result['current_version_matches']
    assert result['solution_artifact'] and result['feedback_artifact']
    assert not result['questions'] and not result['can_retry'] and not result['repair_available']
    client=TestClient(server.app)
    assert client.get(f'/api/projects/{project["id"]}/homework').status_code==200
    assert client.get(url(attempt,project)).status_code==409
    failed=read(project,chat,attempt_id=attempt,question_number=1)
    assert 'error' in failed and 'NEW_' not in j(failed) and 'PRIVATE' not in j(failed)
    catalog=read(project,chat)
    assert 'error' not in catalog and 'REFERENCE_' not in j(catalog)


def test_pending_old_version_only_releases_published_reference(tmp_path):
    project,chat,attempt,worksheet,_=case(tmp_path,status='awaiting_causes',feedback=False)
    change(worksheet,shrink=True)
    result=read(project,chat,attempt_id=attempt,question_number=2)
    assert 'REFERENCE_ADD' in result['text'] and '2+3=4' in result['text']
    assert not result['feedback_available'] and 'FEEDBACK_' not in result['text'] and 'NEW_' not in j(result)


@pytest.mark.parametrize('incomplete',[False,True])
def test_original_snapshot_still_requires_submission_and_publication(tmp_path,incomplete):
    project,chat,attempt,worksheet,_=case(tmp_path,solutions=incomplete,feedback=incomplete)
    if incomplete:execute('UPDATE homework_attempts SET answers_json=? WHERE id=?',(j(['','2+3=4']),attempt))
    change(worksheet)
    result=read(project,chat,attempt_id=attempt,question_number=1)
    assert 'REFERENCE_' not in j(result) and 'FEEDBACK_' not in j(result) and not result.get('record_sha256')


def test_changed_questionnaire_cannot_write_or_grade_and_does_not_change_profile(tmp_path):
    _,_,attempt,worksheet,_=case(tmp_path,status='awaiting_causes',feedback=False)
    change(worksheet)
    row=homework.get_attempt(attempt);before=activity()
    responses=[{'index':0,'kinds':['terminology'],'text':'我不懂概念'}]
    for operation in (lambda:homework.save_draft(attempt,responses),lambda:homework.save_causes(attempt,responses),
        lambda:asyncio.run(homework.run(attempt))):
        with pytest.raises(ValueError,match='变更'):operation()
    assert homework.get_attempt(attempt)==row and activity()==before


def test_coding_snapshot_preserves_language_starter_and_test_metadata(tmp_path):
    _,_,attempt,worksheet,_=case(tmp_path)
    questions=[{'index':0,'topic':'JavaScript','question':'实现加法','language':'javascript','starter_code':'function add(a,b) {}'}]
    solutions=[{'index':0,'solution':'return a+b;','test_code':'assert.equal(add(2,3),5);','rubric':'运行与审查'}]
    original=worksheet|{'questions_json':j(questions),'solutions_json':j(solutions)}
    execute('UPDATE homework_attempts SET source_version=?,answers_json=? WHERE id=?',
        (homework.version(original),j(['return a-b;']),attempt))
    restored=homework.read_worksheet(homework.get_attempt(attempt),worksheet)
    assert restored['questions_json']==j(questions) and restored['solutions_json']==j(solutions)


def test_deleted_original_is_not_resurrected_from_snapshot(tmp_path):
    project,chat,attempt,worksheet,_=case(tmp_path)
    # Simulate an old damaged database; production correctly prevents this
    # deletion through its foreign key. Never disable it in application code.
    with connect() as database:
        database.execute('PRAGMA foreign_keys=OFF')
        database.execute('DELETE FROM exercise_sets WHERE id=?',(worksheet['id'],))
    assert read(project,chat)['items']==[]
    assert 'error' in read(project,chat,attempt_id=attempt,question_number=1)
    assert TestClient(server.app).get(url(attempt,project)).status_code==409

