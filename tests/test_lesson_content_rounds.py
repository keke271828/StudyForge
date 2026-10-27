"""New content doubts retain all earlier feedback and original input scope."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from studyforge import conversations, db, lesson_feedback, navigation, server
from studyforge.db import connect, create_project, execute, j, many, one, unj
from tests.test_lesson_feedback import completed_lesson


def setup(tmp_path, monkeypatch):
    project, job, chat, calls, respond, original = completed_lesson(tmp_path, monkeypatch)
    api = TestClient(server.app)
    root = api.get('/api/lesson-feedback/by-job/' + job).json()
    scope = {'project_id': project['id'], 'conversation_id': chat}
    return api, root, scope, calls, respond, original


def new(api, root, scope):
    response = api.post('/api/lesson-feedback/' + root['id'] + '/content-check', json=scope)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('skip', [True, False])
def test_new_draft_retains_submitted_or_skipped_root_and_uses_no_ai(tmp_path, monkeypatch, skip):
    api, root, scope, calls, *_ = setup(tmp_path, monkeypatch)
    body = {'skip': True} if skip else {'difficulties':['motivation'], 'other_text':'看懂计算，不懂为什么这样构造。'}
    assert api.post(f"/api/lesson-feedback/{root['id']}/submit", json=body).status_code == 200
    old = one('SELECT * FROM lesson_questionnaires')
    events, insights = many('SELECT * FROM learning_events'), many('SELECT * FROM learning_insights')
    item = new(api, root, scope)
    assert item['kind'] == 'content_check' and item['status'] == 'pending' and item['content_check']
    assert item['parent_questionnaire_id'] == root['id'] and item['id'] != root['id']
    assert item['source_ids'] == root['source_ids'] and item['job_id'] == root['job_id']
    assert item['options'] == [{'id':'content_accuracy', 'label':lesson_feedback.CONTENT_CHECK['label']}]
    assert one('SELECT * FROM lesson_questionnaires') == old
    assert many('SELECT * FROM learning_events') == events and many('SELECT * FROM learning_insights') == insights
    assert len(calls) == 1 and len(many('SELECT * FROM jobs')) == 1
    rows = api.get(f"/api/projects/{scope['project_id']}/lesson-feedback").json()
    assert {row['id'] for row in rows} == {item['id'], root['id']}


def test_repeated_and_concurrent_opens_reuse_pending_draft_without_erasing_it(tmp_path, monkeypatch):
    api, root, scope, calls, *_ = setup(tmp_path, monkeypatch)
    with ThreadPoolExecutor(max_workers=3) as executor:
        rows = list(executor.map(lambda _: lesson_feedback.create_content_check(root['id'], **scope), range(3)))
    assert len({row['id'] for row in rows}) == 1
    ident = rows[0]['id']
    execute('UPDATE lesson_content_checks SET other_text=? WHERE id=?', ('已保存的记录', ident))
    assert new(api, root, scope)['other_text'] == '已保存的记录'
    assert len(many('SELECT * FROM lesson_content_checks')) == 1 and len(calls) == 1


def test_targeted_round_reaches_same_tutor_and_completed_round_is_immutable(tmp_path, monkeypatch):
    api, root, scope, calls, *_ = setup(tmp_path, monkeypatch)
    item = new(api, root, scope)
    sections = api.get(f"/api/lesson-feedback/{item['id']}/sections").json()['items']
    section = sections[0]
    window = api.get(f"/api/lesson-feedback/{item['id']}/passage", params={'section_id': section['id']}).json()
    selected = '福柯研究规训权力及其机制。'
    start = window['text'].index(selected)
    body = {'difficulties':['content_accuracy'], 'other_text':'这句是否有原文依据？只核对这一句，不出题。',
            'focus_section_id':section['id'], 'focus_selection':{'start':start, 'end':start+len(selected), 'text':selected}}
    before = one('SELECT * FROM lesson_questionnaires')
    for _ in range(2): assert api.post(f"/api/lesson-feedback/{item['id']}/submit", json=body).status_code == 200
    response = api.post(f"/api/lesson-feedback/{item['id']}/followup")
    assert response.status_code == 200 and '"error"' not in response.text
    done = one('SELECT * FROM lesson_content_checks WHERE id=?', (item['id'],))
    assert done['reply_status'] == 'completed' and done['reply_message_id'] and done['user_message_id']
    assert calls[-1]['model'] == 'lesson-model' and len(calls) == 2
    prompt = j(calls[-1]['messages'])
    assert selected in prompt and '只核对这一句' in prompt and '先处理内容疑点' in prompt
    assert '不能从别段借更强条件' in prompt
    assert not many('SELECT * FROM learning_events') and not many('SELECT * FROM learning_insights')
    assert not many('SELECT * FROM mastery') and not many('SELECT * FROM exercise_sets')
    assert one('SELECT * FROM lesson_questionnaires') == before
    assert api.post(f"/api/lesson-feedback/{item['id']}/followup").status_code == 409
    changed = dict(body, other_text='替换已提交的问题')
    assert api.post(f"/api/lesson-feedback/{item['id']}/submit", json=changed).status_code == 400
    later = new(api, item, scope)
    assert later['id'] != item['id'] and later['parent_questionnaire_id'] == root['id']
    assert one('SELECT * FROM lesson_content_checks WHERE id=?', (item['id'],)) == done
    assert api.get('/api/lesson-feedback/by-job/' + root['job_id']).json()['id'] == root['id']


def test_source_scope_does_not_follow_new_chat_selection_or_library_selection(tmp_path, monkeypatch):
    api, root, scope, calls, *_ = setup(tmp_path, monkeypatch)
    payload = unj(one('SELECT payload_json FROM jobs WHERE id=?', (root['job_id'],))['payload_json'])
    snapshot = {'mode':'manual','references':[], 'original_scope_marker':'ORIGINAL_BOOK_SELECTION'}
    payload['library_snapshot'] = snapshot
    execute('UPDATE jobs SET payload_json=? WHERE id=?', (j(payload), root['job_id']))
    conversations.update(scope['conversation_id'], scope['project_id'], {'source_ids': []})
    def forbidden(*args, **kwargs): raise AssertionError('不得重新检索当前聊天书库配置')
    monkeypatch.setattr('studyforge.library.reference_snapshot', forbidden)
    from studyforge import library
    original = library.reference_content
    seen = []
    def content(value, query, **kwargs):
        seen.append(value)
        return original(value, query, **kwargs)
    monkeypatch.setattr(library, 'reference_content', content)
    item = new(api, root, scope)
    assert api.post(f"/api/lesson-feedback/{item['id']}/submit", json={'difficulties':['content_accuracy'], 'other_text':'核对规训的含义'}).status_code == 200
    result = api.post(f"/api/lesson-feedback/{item['id']}/followup")
    assert '"error"' not in result.text and seen == [snapshot]
    assert '福柯研究规训权力。规训包括观察、记录、规范化判断。' in j(calls[-1]['messages'])
    assert unj(one('SELECT source_ids_json FROM conversations WHERE id=?', (scope['conversation_id'],))['source_ids_json']) == []


def test_scope_archival_and_missing_original_are_rejected_without_ai(tmp_path, monkeypatch):
    api, root, scope, calls, *_ = setup(tmp_path, monkeypatch)
    other = create_project('其他项目')
    chat = conversations.create(other['id'], 'deepseek')
    for wrong in ({'project_id':other['id'], 'conversation_id':chat['id']}, dict(scope, conversation_id=chat['id'])):
        assert api.post(f"/api/lesson-feedback/{root['id']}/content-check", json=wrong).status_code == 400
    item = new(api, root, scope)
    assert navigation.request_project_id(f"/api/lesson-feedback/{item['id']}/submit", {}) == scope['project_id']
    artifact = root['artifact_id']
    execute('DELETE FROM artifacts WHERE id=?', (artifact,))
    assert api.post(f"/api/lesson-feedback/{root['id']}/content-check", json=scope).status_code == 400
    assert api.get(f"/api/lesson-feedback/{item['id']}/dialogue").json()['questionnaire']['ready'] is False
    assert len(calls) == 1 and not many('SELECT * FROM learning_events')


def test_content_only_round_cannot_become_a_profile_assessment_or_check_question(tmp_path, monkeypatch):
    api, root, scope, calls, *_ = setup(tmp_path, monkeypatch)
    item = new(api, root, scope)
    for choices in (['motivation'], ['content_accuracy','prerequisites']):
        assert api.post(f"/api/lesson-feedback/{item['id']}/submit", json={'difficulties':choices}).status_code == 400
    response = api.post(f"/api/lesson-feedback/{item['id']}/submit", json={'difficulties':['content_accuracy']})
    assert response.status_code == 400 and '请写下需要核对' in response.text
    assert api.post(f"/api/lesson-feedback/{item['id']}/check", json=scope).status_code == 400
    assert not many('SELECT * FROM learning_events') and len(calls) == 1


def test_archived_round_routes_are_blocked_and_changed_library_is_not_replaced(tmp_path, monkeypatch):
    api, root, scope, calls, *_ = setup(tmp_path, monkeypatch)
    item = new(api, root, scope)
    from studyforge.db import now
    execute('INSERT INTO removed_projects VALUES (?,?)', (scope['project_id'], now()))
    for method, path, body in (
        ('GET', '/dialogue', None), ('POST', '/submit', {'difficulties':['content_accuracy']}),
        ('POST', '/content-check', scope)):
        response = api.request(method, f"/api/lesson-feedback/{item['id']}" + path, **({'json':body} if body else {}))
        assert response.status_code == 404 and '回收站' in response.text, response.text
    navigation.restore(scope['project_id'])
    api.post(f"/api/lesson-feedback/{item['id']}/submit", json={'difficulties':['content_accuracy'], 'other_text':'核对原范围'}).raise_for_status()
    def changed(*args, **kwargs): raise ValueError('书库节点范围在任务启动后改变；没有混用新的范围')
    monkeypatch.setattr('studyforge.library.reference_content', changed)
    response = api.post(f"/api/lesson-feedback/{item['id']}/followup")
    assert response.status_code == 400 and '没有混用新的范围' in response.text
    assert one('SELECT reply_status FROM lesson_content_checks')['reply_status'] == 'failed' and len(calls) == 1


def test_paired_phone_round_survives_background_run_and_isolates_wrong_chat(monkeypatch):
    from tests.test_mobile_lesson_feedback import phone_lesson, mobile_client, pair, feedback_payload, wait_run
    project, chat, another, root, artifact, tutor, *_ = phone_lesson(monkeypatch)
    manager, client = mobile_client()
    with client:
        pair(manager, client)
        scope = {'project_id':project['id'], 'conversation_id':chat['id']}
        created = client.post(f"/api/lesson-feedback/{root['id']}/content-check", json=scope)
        assert created.status_code == 200, created.text
        item = created.json()
        assert client.post(f"/api/lesson-feedback/{item['id']}/submit", json={'difficulties':['content_accuracy'], 'other_text':'核对原文的条件，不出题。'}).status_code == 200
        route = '/api/mobile/lesson-feedback/' + item['id'] + '/followup'
        wrong = dict(feedback_payload(project, chat), conversation_id=another['id'])
        assert client.post(route, json=wrong).status_code == 400
        payload = feedback_payload(project, chat)
        run = client.post(route, json=payload)
        assert run.status_code == 200, run.text
        assert client.post(route, json=payload).json()['reused']
        wait_run(client, run.json()['run_id'], 'running')
        tutor.release.set()
        done = wait_run(client, run.json()['run_id'], 'completed')
        assert 'PHONE_SUPPLEMENT' in done['content'] and len(tutor.requests) == 1
        assert one('SELECT reply_status FROM lesson_content_checks')['reply_status'] == 'completed'
        assert one('SELECT status FROM lesson_questionnaires')['status'] == 'pending'
        assert not many('SELECT * FROM learning_events') and not many('SELECT * FROM mastery')


def test_failed_round_can_retry_without_duplicate_student_message_and_restart_recovers(tmp_path, monkeypatch):
    api, root, scope, calls, respond, original = setup(tmp_path, monkeypatch)
    item = new(api, root, scope)
    api.post(f"/api/lesson-feedback/{item['id']}/submit", json={'difficulties':['content_accuracy'], 'other_text':'请核对这份讲解'}).raise_for_status()
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(transport=httpx.MockTransport(lambda request:httpx.Response(503, json={'error':{'message':'unavailable'}}))))
    response = api.post(f"/api/lesson-feedback/{item['id']}/followup")
    assert '"error"' in response.text
    failed = one('SELECT * FROM lesson_content_checks')
    assert failed['reply_status'] == 'failed' and failed['user_message_id']
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(transport=httpx.MockTransport(respond)))
    assert '"error"' not in api.post(f"/api/lesson-feedback/{item['id']}/followup").text
    assert one('SELECT user_message_id FROM lesson_content_checks')['user_message_id'] == failed['user_message_id']
    execute("UPDATE lesson_content_checks SET reply_status='running'")
    from studyforge.desktop_lifecycle import recover_interrupted_jobs
    recover_interrupted_jobs()
    assert one('SELECT reply_status FROM lesson_content_checks')['reply_status'] == 'failed'
    assert len(many("SELECT * FROM messages WHERE role='user' AND conversation_id=?", (scope['conversation_id'],))) == 2
    assert not many('SELECT * FROM learning_events')


def test_additive_schema_upgrade_preserves_legacy_questionnaire_and_delete_cascades(tmp_path, monkeypatch):
    api, root, scope, calls, *_ = setup(tmp_path, monkeypatch)
    before = one('SELECT * FROM lesson_questionnaires')
    execute('DROP TABLE lesson_content_checks')
    from studyforge.config import data_dir
    db._initialized_databases.pop(data_dir() / 'studyforge.sqlite3', None)
    assert one('SELECT * FROM lesson_questionnaires') == before
    item = new(api, root, scope)
    conversations.delete_history(scope['conversation_id'], scope['project_id'])
    assert not many('SELECT * FROM lesson_content_checks') and not many('SELECT * FROM lesson_questionnaires')
    with connect() as database: assert not database.execute('PRAGMA foreign_key_check').fetchall()


def test_all_seven_original_choices_are_supported(tmp_path, monkeypatch):
    api, root, scope, calls, *_ = setup(tmp_path, monkeypatch)
    response = api.post(f"/api/lesson-feedback/{root['id']}/submit", json={'difficulties':[item['id'] for item in root['options']]})
    assert response.status_code == 200
    assert len(many('SELECT * FROM learning_insights')) == 6 and len(calls) == 1


def test_content_round_survives_format_replacement_but_rejects_inexact_focus(tmp_path, monkeypatch):
    api, root, scope, calls, *_ = setup(tmp_path, monkeypatch)
    item = new(api, root, scope)
    artifact = one('SELECT * FROM artifacts WHERE id=?', (root['artifact_id'],))
    from pathlib import Path
    replacement = server.add_artifact(scope['project_id'], root['source_ids'], 'explanation', artifact['format'],
        '同一讲解另存格式', Path(artifact['path']), unj(artifact['metadata_json']))
    execute('DELETE FROM artifacts WHERE id=?', (artifact['id'],))
    restored = api.get(f"/api/lesson-feedback/{item['id']}/dialogue").json()
    assert restored['questionnaire']['ready'] and restored['questionnaire']['artifact_id'] == replacement['id']
    section = restored['sections']['items'][0]['id']
    response = api.post(f"/api/lesson-feedback/{item['id']}/submit", json={'difficulties':['content_accuracy'],
        'focus_section_id':section, 'focus_selection':{'start':0, 'end':1, 'text':'伪'}})
    assert response.status_code == 400
    assert one('SELECT status,focus_json FROM lesson_content_checks') == {'status':'pending','focus_json':'{}'}
    assert len(calls) == 1


def test_permanent_project_delete_removes_completed_round_without_orphans(tmp_path, monkeypatch):
    api, root, scope, calls, *_ = setup(tmp_path, monkeypatch)
    item = new(api, root, scope)
    api.post(f"/api/lesson-feedback/{item['id']}/submit", json={'difficulties':['content_accuracy'], 'other_text':'核对这个概念'}).raise_for_status()
    response = api.post(f"/api/lesson-feedback/{item['id']}/followup")
    assert '"error"' not in response.text
    api.delete('/api/projects/' + scope['project_id']).raise_for_status()
    from studyforge.project_purge import purge
    assert purge(scope['project_id'], '哲学')['deleted']
    assert not many('SELECT * FROM lesson_content_checks')
    with connect() as database: assert not database.execute('PRAGMA foreign_key_check').fetchall()
