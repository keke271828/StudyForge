"""The human viewer reads public per-question feedback without another AI call."""
import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from studyforge import conversations, homework_context, server
from studyforge.agent_tools import AgentRuntime
from studyforge.db import create_project, execute, j, many
from tests.test_homework_context import case


def url(attempt, project):
    return f'/api/homework/{attempt}/reading?project_id={project["id"]}'


def activity():
    return {name: many('SELECT * FROM '+name) for name in
            ('messages', 'learning_events', 'mastery', 'submissions', 'agent_tool_events', 'jobs')}


def test_catalog_and_question_are_lazy_read_only_and_match_original_renderer(tmp_path):
    project, chat, attempt, *_ = case(tmp_path)
    before = activity()
    client = TestClient(server.app)
    listing = client.get(url(attempt, project)).json()
    assert listing['conversation_id'] == chat['id']
    assert [item['question_number'] for item in listing['questions']] == [1, 2]
    assert 'REFERENCE_' not in j(listing) and 'FEEDBACK_' not in j(listing) and '2+3=4' not in j(listing)
    response = client.get(url(attempt, project)+'&question_number=2')
    assert response.status_code == 200, response.text
    result = response.json()
    assert 'FEEDBACK_ADD' in result['text'] and 'REFERENCE_ADD' in result['text'] and '2+3=4' in result['text']
    assert 'FEEDBACK_GAUSS' not in result['text'] and 'REFERENCE_GAUSS' not in result['text']
    from studyforge.agent_tools import ReadHomeworkFeedback
    runtime = AgentRuntime(project['id'], conversation_id=chat['id'])
    original = homework_context.read(runtime, ReadHomeworkFeedback(attempt_id=attempt, question_number=2))
    assert original['text'] == result['text'] and original['record_sha256'] == result['record_sha256']
    assert activity() == before


def test_user_can_open_project_record_but_agent_cannot_cross_dialogues(tmp_path):
    project, chat, attempt, *_ = case(tmp_path)
    other = conversations.create(project['id'], 'deepseek')
    assert TestClient(server.app).get(url(attempt, project)+'&question_number=2').status_code == 200
    runtime = AgentRuntime(project['id'], conversation_id=other['id'])
    denied = asyncio.run(runtime.execute('sf_read_homework_feedback', {'attempt_id': attempt, 'question_number': 2}))
    assert 'error' in denied and 'FEEDBACK_ADD' not in j(denied)
    foreign = create_project('另一个项目')
    response = TestClient(server.app).get(url(attempt, foreign)+'&question_number=2')
    assert response.status_code == 409 and 'FEEDBACK_' not in response.text


@pytest.mark.parametrize('status', ['grading', 'awaiting_causes', 'clarified', 'failed'])
def test_unpublished_diagnosis_not_opened_even_if_private_analysis_exists(tmp_path, status):
    project, _, attempt, *_ = case(tmp_path, status=status, feedback=False)
    response = TestClient(server.app).get(url(attempt, project)+'&question_number=1')
    assert response.status_code == 200, response.text
    result = response.json()
    assert 'REFERENCE_GAUSS' in result['text'] and not result['feedback_available']
    assert 'FEEDBACK_GAUSS' not in response.text and '学生自报把净通量' not in response.text


def test_no_delivery_and_incomplete_answers_do_not_release_solutions(tmp_path):
    project, _, attempt, *_ = case(tmp_path, solutions=False, feedback=False)
    client = TestClient(server.app)
    result = client.get(url(attempt, project)+'&question_number=1').json()
    assert 'REFERENCE_' not in j(result) and 'FEEDBACK_' not in j(result) and not result.get('record_sha256')
    execute('UPDATE homework_attempts SET answers_json=? WHERE id=?', (j(['', '2+3=4']), attempt))
    response = client.get(url(attempt, project)+'&question_number=1')
    assert response.status_code == 409 and 'REFERENCE_' not in response.text


@pytest.mark.parametrize('query', ['question_number=0', 'question_number=-1', 'question_number=1.5',
    'offset=-1', 'limit=199', 'limit=16001', 'record_sha256=not-a-hash'])
def test_invalid_window_and_question_rejected_by_api(tmp_path, query):
    project, _, attempt, *_ = case(tmp_path)
    assert TestClient(server.app).get(url(attempt, project)+'&'+query).status_code == 422


def test_out_of_range_and_changed_worksheet_or_removed_chat_fail_without_fallback(tmp_path):
    project, chat, attempt, worksheet, _ = case(tmp_path)
    client = TestClient(server.app)
    assert client.get(url(attempt, project)+'&question_number=3').status_code == 409
    execute('UPDATE exercise_sets SET difficulty=4 WHERE id=?', (worksheet['id'],))
    original=client.get(url(attempt, project)+'&question_number=1')
    assert original.status_code == 200 and original.json()['current_version_matches'] is False
    assert 'REFERENCE_GAUSS' in original.json()['text'] and original.json()['version_notice']
    assert original.json()['repair_reference'] is None
    execute('INSERT INTO deleted_conversations VALUES (?,?)', (chat['id'], '2026-10-22'))
    assert client.get(url(attempt, project)).status_code == 409


def test_long_record_continues_exactly_and_changed_version_cannot_be_joined(tmp_path):
    project, _, attempt, *_ = case(tmp_path)
    long = '正确条件与原推理。'*3000
    execute("UPDATE homework_attempts SET analysis_json=json_set(analysis_json,'$.items[1].explanation',?) WHERE id=?", (long, attempt))
    client = TestClient(server.app)
    first = client.get(url(attempt, project)+'&question_number=2&limit=1000').json()
    assert len(first['text']) == 1000 and first['next_offset'] == 1000
    part = client.get(url(attempt, project)+'&question_number=2&offset=1000&limit=1000&record_sha256='+first['record_sha256'])
    assert part.status_code == 200 and part.json()['record_sha256'] == first['record_sha256']
    execute("UPDATE homework_attempts SET analysis_json=json_set(analysis_json,'$.items[1].explanation',?) WHERE id=?", ('新的讲解。'+long, attempt))
    stale = client.get(url(attempt, project)+'&question_number=2&offset=2000&record_sha256='+first['record_sha256'])
    assert stale.status_code == 409 and '不会拼接不同版本' in stale.text
    fresh = client.get(url(attempt, project)+'&question_number=2').json()
    assert fresh['record_sha256'] != first['record_sha256']


def test_authenticated_phone_reads_same_text_and_shell_assets(tmp_path):
    from tests.test_mobile_access import mobile_client, pair
    project, _, attempt, *_ = case(tmp_path)
    manager, phone = mobile_client()
    with phone:
        assert phone.get(url(attempt, project)).status_code == 401
        pair(manager, phone)
        before = activity()
        response = phone.get(url(attempt, project)+'&question_number=2')
        assert response.status_code == 200, response.text
        assert 'FEEDBACK_ADD' in response.json()['text'] and 'FEEDBACK_GAUSS' not in response.text
        assert phone.get('/homework_reader.js').status_code == 200
        assert phone.get('/homework_reader.css').status_code == 200
        assert phone.post(url(attempt, project)).status_code in (403, 405)
        assert activity() == before


def test_mobile_shell_only_caches_static_reader_assets_not_answers():
    root = Path(__file__).resolve().parents[1]
    worker = (root/'web/mobile/sw.js').read_text(encoding='utf-8')
    assert "'/homework_reader.js','/homework_reader.css'" in worker
    assert '/api/homework' not in worker


def test_unattributed_global_grading_doubts_are_not_attached_to_selected_question(tmp_path):
    from studyforge import homework
    from studyforge.db import one, unj
    project, _, attempt, worksheet, _ = case(tmp_path)
    execute("UPDATE homework_attempts SET grade_json=json_set(grade_json,'$.uncertainties',json(?)) WHERE id=?",
            (j(['OTHER_QUESTION_DOUBT：第一题参考条件待核对']), attempt))
    result = TestClient(server.app).get(url(attempt, project)+'&question_number=2').json()
    assert 'OTHER_QUESTION_DOUBT' not in result['text'] and '未标明题号的疑点不归因于本题' in result['text']
    row = homework.get_attempt(attempt)
    full = homework.report_document(row, worksheet, unj(row['grade_json']), unj(row['analysis_json']))
    assert 'OTHER_QUESTION_DOUBT' in full


def test_reader_representation_upgrade_changes_internal_model_state_key_only(tmp_path, monkeypatch):
    project, chat, *_ = case(tmp_path)
    before = activity()
    monkeypatch.setattr(homework_context, 'VERSION', 2)
    old = AgentRuntime(project['id'], conversation_id=chat['id']).state_key()
    monkeypatch.setattr(homework_context, 'VERSION', 3)
    new = AgentRuntime(project['id'], conversation_id=chat['id']).state_key()
    assert old != new
    assert activity() == before
