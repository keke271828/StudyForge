"""Reopening a chat restores its task, never reruns learning or exposes another chat."""
import json

import pytest
from fastapi.testclient import TestClient

from studyforge import conversations,server
from studyforge.db import create_job,execute,j,many,now,one,uid,update_job
from tests.test_project_conversations import setup_sources,new_chat,update


def case(tmp_path):
    project,other,ids=setup_sources(tmp_path)
    client=TestClient(server.app)
    a,b=new_chat(client,project),new_chat(client,project)
    update(client,a,source_ids=ids[:2],reasoning_effort='high')
    update(client,b,source_ids=ids[:2],reasoning_effort='high')
    value=server.ReadIn(project_id=project['id'],conversation_id=a['id'],source_ids=ids[:2],
        provider='deepseek',model='fixture',reasoning_effort='high')
    return client,project,other,a,b,ids,value


@pytest.mark.parametrize('status',['queued','running','pausing','paused','failed'])
def test_reopen_restores_each_unfinished_state_without_reading_or_model(tmp_path,monkeypatch,status):
    client,p,q,a,b,ids,value=case(tmp_path)
    ident=create_job(p['id'],'read',value.model_dump())
    update_job(ident,status,43,{'stage':'核对原文','private_notes':'私有笔记'*20000},error='ConnectError: interrupted' if status=='failed' else None)
    monkeypatch.setattr(conversations,'cached_reading',lambda *a: (_ for _ in ()).throw(AssertionError('正在处理时不重新读文件')))
    monkeypatch.setattr(server,'client_for',lambda *a,**k: (_ for _ in ()).throw(AssertionError('恢复不能调用模型')))
    before=one('SELECT * FROM jobs WHERE id=?',(ident,))
    for unused in range(3):
        response=client.get(f"/api/conversations/{a['id']}?project_id={p['id']}")
        assert response.status_code==200,response.text
        row=response.json()
        assert row['reading']=={'job_id':ident,'status':status,'progress':43,'stage':'核对原文','error':before['error']}
        assert row['reading_task']['id']==ident and row['reading_task']['can_pause']
        assert 'private_notes' not in j(row) and len(j(row))<9000
        if status=='failed':assert row['reading_task']['recovery']['available']
    assert one('SELECT * FROM jobs WHERE id=?',(ident,))==before
    assert len(many('SELECT id FROM jobs'))==1
    assert not many('SELECT * FROM learning_events') and not many('SELECT * FROM mastery')


@pytest.mark.parametrize('change',['conversation','project','sources','model','effort','provider','deleted','cancelled','completed'])
def test_task_from_another_scope_or_removed_state_is_not_restored(tmp_path,change):
    client,p,q,a,b,ids,value=case(tmp_path)
    payload=value.model_dump()
    if change=='conversation':payload['conversation_id']=b['id']
    if change=='project':payload['project_id']=q['id']
    if change=='sources':payload['source_ids']=[ids[0],ids[2]]
    if change=='model':payload['model']='other-model'
    if change=='effort':payload['reasoning_effort']='low'
    if change=='provider':payload['provider']='codex'
    ident=create_job(payload['project_id'],'read',payload)
    update_job(ident,change if change in ('completed','cancelled') else 'paused',42)
    if change=='deleted':execute('INSERT INTO deleted_job_records VALUES (?,?)',(ident,now()))
    row=client.get(f"/api/conversations/{a['id']}?project_id={p['id']}").json()
    assert row['reading_task'] is None and row['reading'] is None


def test_source_set_order_does_not_change_identity_and_latest_attempt_wins(tmp_path):
    client,p,q,a,b,ids,value=case(tmp_path)
    first=create_job(p['id'],'read',value.model_dump());update_job(first,'paused',20)
    value.source_ids.reverse()
    second=create_job(p['id'],'read',value.model_dump());update_job(second,'running',48)
    row=client.get(f"/api/conversations/{a['id']}?project_id={p['id']}").json()
    assert row['reading']['job_id']==second
    update_job(second,'cancelled',48)
    assert client.get(f"/api/conversations/{a['id']}?project_id={p['id']}").json()['reading_task'] is None
    assert server.job(first)['status']=='paused'


def test_task_restore_projection_does_not_copy_large_dialogue_or_results(tmp_path,monkeypatch):
    client,p,q,a,b,ids,value=case(tmp_path)
    payload=value.model_dump();payload['dialogue']='PRIVATE_DIALOGUE_'*100000
    ident=create_job(p['id'],'read',payload);update_job(ident,'running',28,{'notes':'LONG_NOTES_'*100000,'stage':'正在阅读'})
    original=conversations.one;fetched=[]
    def spy(sql,params=()):
        row=original(sql,params)
        if 'FROM jobs WHERE' in sql:fetched.append((sql,len(j(row))))
        return row
    monkeypatch.setattr(conversations,'one',spy)
    row=client.get(f"/api/conversations/{a['id']}?project_id={p['id']}").json()
    assert row['reading']['progress']==28
    assert fetched and all(size<3000 and 'SELECT *' not in sql for sql,size in fetched)
    assert 'PRIVATE_DIALOGUE' not in j(row) and 'LONG_NOTES' not in j(row)


def test_deleted_source_and_empty_new_chat_do_not_attach_reading_tasks(tmp_path):
    client,p,q,a,b,ids,value=case(tmp_path)
    ident=create_job(p['id'],'read',value.model_dump());update_job(ident,'paused',30)
    update(client,b,source_ids=[])
    assert client.get(f"/api/conversations/{b['id']}?project_id={p['id']}").json()['reading_task'] is None
    execute('DELETE FROM sources WHERE id=?',(ids[0],))
    row=client.get(f"/api/conversations/{a['id']}?project_id={p['id']}").json()
    assert row['removed_source_ids']==[ids[0]] and row['reading_task'] is None
