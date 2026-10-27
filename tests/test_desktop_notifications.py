import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from studyforge import ai, conversations, server
from studyforge.db import connect, create_job, create_project, execute, j, many, now, uid, update_job
from studyforge.desktop_notifications import DEFAULTS, acknowledge, enqueue, feed


def workspace(name='通知项目'):
    project = create_project(name)
    chat = conversations.create(project['id'], 'deepseek')
    return project['id'], chat['id']


def artifact(tmp_path, project, chat, job=None):
    file = tmp_path / (uid()+'.docx'); file.write_bytes(b'saved deliverable')
    return server.add_artifact(project, [], 'explanation', 'docx', '守恒律讲解', file,
                               {'conversation_id':chat, 'generation_job_id':job})


def approval(project, chat, job=None):
    ident=uid()
    execute('INSERT INTO agent_approvals VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (ident,project,chat,job,'sf_write_text',uid(),j({'paths':[]}), 'pending',None,now(),None))
    return ident


def test_completed_outputs_in_other_projects_are_durable_and_not_repeated(tmp_path, monkeypatch):
    monkeypatch.setattr(ai,'client_for',lambda *a,**k:pytest.fail('Notifications must not call a model'))
    p1,c1=workspace('当前项目');p2,c2=workspace('后台项目')
    job=create_job(p2,'generate',{'conversation_id':c2})
    output=artifact(tmp_path,p2,c2,job)
    update_job(job,'completed',100,{'artifacts':[output]})
    events=feed()['events']
    assert len(events)==1 and events[0]['category']=='complete'
    assert events[0]['target']=={'view':'artifacts','project_id':p2,'conversation_id':c2,'artifact_id':output['id'],'job_id':job}
    assert '后台项目' in events[0]['body']
    acknowledge([events[0]['id']],'sent')
    assert feed()['events']==[]
    assert feed()['recent'][0]['status']=='sent'
    # A new collector/main process sees the same durable delivery receipt.
    assert len(many('SELECT * FROM desktop_notices'))==1


def test_approval_is_not_consumed_by_delivery_and_disappears_after_decision():
    project,chat=workspace();ident=approval(project,chat)
    first=feed();event=first['events'][0]
    assert first['active_actions']==['approval:'+ident]
    assert event['target']['approval_id']==ident
    assert feed()['events']==first['events']
    assert many('SELECT status FROM agent_approvals')[0]['status']=='pending'
    execute("UPDATE agent_approvals SET status='denied' WHERE id=?",(ident,))
    assert feed()['events']==[] and feed()['active_actions']==[]
    assert many('SELECT status FROM desktop_notices')[0]['status']=='dismissed'


def test_questionnaire_stays_pending_until_student_answers():
    project,chat=workspace();job=create_job(project,'homework_grade',{'conversation_id':chat})
    worksheet,attempt=uid(),uid()
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(worksheet,project,'[]','题单','[]','[]',1,'assigned',now()))
    execute('INSERT INTO homework_attempts(id,exercise_set_id,project_id,conversation_id,job_id,source_version,answers_json,options_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (attempt,worksheet,project,chat,job,'v1','[]','{}','awaiting_causes',now(),now()))
    update_job(job,'paused',70,{'waiting_for_causes':True})
    event=feed()['events'][0]
    assert event['category']=='questionnaire' and event['target']['homework_attempt_id']==attempt
    acknowledge([event['id']],'sent')
    assert feed()['active_actions']==['causes:'+attempt] and feed()['events']==[]
    execute("UPDATE homework_attempts SET status='clarified' WHERE id=?",(attempt,))
    assert feed()['active_actions']==[]


def test_partial_output_and_failed_followup_both_have_notifications(tmp_path):
    project,chat=workspace();job=create_job(project,'generate',{'conversation_id':chat})
    artifact(tmp_path,project,chat,job)
    update_job(job,'failed',80,error='secret answer must not appear in OS notification')
    events=feed()['events']
    assert {event['category'] for event in events}=={'complete','failure'}
    assert 'secret answer' not in json.dumps(events)
    for event in events:acknowledge([event['id']],'sent')
    assert feed()['events']==[]


@pytest.mark.parametrize('kind,view',[('import','sources'),('import_url','sources'),('import_video','sources'),('read','study'),('knowledge','study')])
def test_completed_non_document_work(kind,view):
    project,chat=workspace();job=create_job(project,kind,{'conversation_id':chat})
    update_job(job,'completed',100)
    assert feed()['events'][0]['target']['view']==view


def test_upgrade_does_not_notify_old_finished_work_but_pending_actions_are_relevant(tmp_path):
    project,chat=workspace();job=create_job(project,'read',{'conversation_id':chat})
    update_job(job,'completed',100);artifact(tmp_path,project,chat)
    execute("UPDATE workspace_state SET value=? WHERE key='desktop_notices_since'",(now(),))
    ident=approval(project,chat)
    assert [event['notice_key'] for event in feed()['events']]==['approval:'+ident]


@pytest.mark.parametrize('removal',['project','chat','job','artifact'])
def test_removed_targets_do_not_deliver_stale_notifications(tmp_path,removal):
    project,chat=workspace();job=create_job(project,'generate',{'conversation_id':chat})
    output=artifact(tmp_path,project,chat,job);assert len(feed()['events'])==1
    if removal=='project':execute('INSERT INTO removed_projects VALUES (?,?)',(project,now()))
    elif removal=='chat':execute('INSERT INTO deleted_conversations VALUES (?,?)',(chat,now()))
    elif removal=='job':execute('INSERT INTO deleted_job_records VALUES (?,?)',(job,now()))
    else:
        # Artifact sources refer back to their output; use the public deletion route.
        response=TestClient(server.app).delete('/api/artifacts/'+output['id'])
        assert response.status_code==200
    assert feed()['events']==[] and feed()['recent']==[]


def test_expired_completion_is_not_replayed_after_long_offline():
    project,chat=workspace()
    old=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
    with connect() as db:
        enqueue(db,'old-output','complete','旧成果','已完成',{'project_id':project,'conversation_id':chat,'view':'artifacts'},old)
    assert feed()['events']==[]
    assert feed()['recent'][0]['status']=='dismissed'


def test_chats_notify_without_exposing_the_reply_text():
    project,chat=workspace()
    with connect() as db:
        enqueue(db,'chat:reply','chat','导师已回复','点击继续当前学习对话。',{'project_id':project,'conversation_id':chat,'view':'study'})
    assert feed()['events'][0]['category']=='chat'
    assert feed()['events'][0]['target']['conversation_id']==chat


def test_disabled_notification_settings_keep_history_available():
    project,chat=workspace();approval(project,chat)
    ai.save_settings({'desktop_notifications_enabled':False,'desktop_notifications_sound':False})
    result=feed()
    assert len(result['events'])==1 and result['settings']['desktop_notifications_enabled'] is False
    acknowledge([result['events'][0]['id']],'skipped')
    assert feed()['events']==[] and feed()['recent'][0]['status']=='skipped'
    ai.save_settings({'desktop_notifications_enabled':True})
    assert feed()['events']==[]


@pytest.mark.parametrize('key',list(DEFAULTS))
def test_notification_settings_require_actual_booleans(key):
    with pytest.raises(ValueError):ai.save_settings({key:'false'})
    assert ai.save_settings({key:False})[key] is False


def test_async_os_failure_may_correct_an_accepted_receipt():
    project,chat=workspace();approval(project,chat)
    ident=feed()['events'][0]['id']
    acknowledge([ident],'sent');acknowledge([ident],'failed')
    assert feed()['recent'][0]['status']=='failed'


def test_desktop_feed_and_receipts_only_accept_own_desktop(monkeypatch):
    monkeypatch.setenv('STUDYFORGE_DESKTOP_TOKEN','notice-owner')
    monkeypatch.setattr(server.app.state,'desktop_shutdown',False)
    api=TestClient(server.app)
    for headers in ({},{'X-StudyForge-Desktop-Token':'wrong'}):
        assert api.get('/api/desktop/notifications',headers=headers).status_code==403
        assert api.post('/api/desktop/notifications/ack',headers=headers,json={'ids':[],'status':'sent'}).status_code==403
    headers={'X-StudyForge-Desktop-Token':'notice-owner'}
    assert api.get('/api/desktop/notifications',headers=headers).status_code==200
    assert api.post('/api/desktop/notifications/ack',headers=headers,json={'ids':[True],'status':'sent'}).status_code==422
    assert api.post('/api/desktop/notifications/ack',headers=headers,json={'ids':[-1],'status':'sent'}).status_code==400
    assert api.post('/api/desktop/notifications/ack',headers=headers,json={'ids':[],'status':'sent'}).status_code==200
    assert api.get('/api/desktop/notifications',headers=headers|{'Origin':'https://foreign.example'}).status_code==403


def test_waiting_actions_are_prioritized_over_a_completion_backlog():
    project,chat=workspace()
    with connect() as db:
        for number in range(65):
            enqueue(db,'output:'+str(number),'complete','成果已完成','已保存',{'view':'artifacts','project_id':project,'conversation_id':chat})
    ident=approval(project,chat);result=feed()
    assert len(result['events'])==40
    assert result['events'][0]['target']['approval_id']==ident
    assert result['recent'][0]['action_pending'] is True
    acknowledge([result['events'][0]['id']],'sent')
    assert feed()['recent'][0]['target']['approval_id']==ident


def test_repeated_idle_poll_does_not_advance_database_sequence():
    project,chat=workspace();approval(project,chat);feed()
    before=many("SELECT seq FROM sqlite_sequence WHERE name='desktop_notices'")[0]['seq']
    feed();feed()
    assert many("SELECT seq FROM sqlite_sequence WHERE name='desktop_notices'")[0]['seq']==before
