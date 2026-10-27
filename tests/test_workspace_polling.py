"""Polling must not load originals or repeatedly ship private task snapshots."""
from contextlib import contextmanager
import sqlite3
import tracemalloc

import pytest
from fastapi.testclient import TestClient

from studyforge import db as storage,server,workflows
from studyforge.db import create_job,create_project,execute,j,one,now,uid,update_job


def material(project):
    ident=uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
        (ident,project['id'],'长原文.txt','.txt','not-read-for-listing',j([{'locator':'原文位置','text':'ORIGINAL_BODY '*300000}]),'ready',now()))
    return ident


def test_source_listing_never_selects_the_original_text_column(monkeypatch):
    p=create_project('元数据');ident=material(p);native=storage.connect
    @contextmanager
    def protected():
        with native() as database:
            database.set_authorizer(lambda action,table,column,*a:sqlite3.SQLITE_DENY
                if action==sqlite3.SQLITE_READ and table=='sources' and column=='segments_json' else sqlite3.SQLITE_OK)
            yield database
    monkeypatch.setattr(storage,'connect',protected)
    result=server.sources(p['id'])
    assert result[0]['id']==ident and result[0]['parse_type']=='document'
    assert 'ORIGINAL_BODY' not in j(result) and 'segments' not in result[0]


def test_generated_file_linking_does_not_load_its_large_private_metadata(monkeypatch):
    from studyforge.config import artifacts_dir
    p=create_project('成果链接');path=artifacts_dir()/'讲解.txt';path.write_text('完整成果正文。',encoding='utf-8')
    artifact=server.add_artifact(p['id'],[],'explanation','txt','讲解',path,{'private':'PRIVATE_METADATA '*10000})
    from studyforge.artifact_sources import remove_link
    with storage.connect() as database:remove_link(database,artifact['id'])
    assert not one('SELECT source_id FROM artifact_sources WHERE artifact_id=?',(artifact['id'],))
    native=storage.connect
    @contextmanager
    def protected():
        with native() as database:
            database.set_authorizer(lambda action,table,column,*a:sqlite3.SQLITE_DENY
                if action==sqlite3.SQLITE_READ and table=='artifacts' and column=='metadata_json' else sqlite3.SQLITE_OK)
            yield database
    monkeypatch.setattr(storage,'connect',protected)
    sources=server.sources(p['id'])
    assert sources[0]['artifact_id']==artifact['id'] and sources[0]['status']=='ready'


@pytest.mark.parametrize('value',['{ }','[ ]'])
def test_legacy_whitespace_in_empty_workflow_values_keeps_pause_disabled(value):
    p=create_project('旧任务');ident=create_job(p['id'],'repair',{})
    execute('UPDATE jobs SET payload_json=? WHERE id=?',('{"workflow_version":1,"values":'+value+'}',ident))
    assert not server.job(ident,view='progress')['can_pause'] and not server.jobs(p['id'])[0]['can_pause']


def test_progress_view_is_bounded_and_keeps_the_saved_task_intent():
    p=create_project('任务');payload={'project_id':p['id'],'source_ids':[uid()],'only_exercises':True,
        'conversation_id':uid(),'dialogue_snapshot':{'messages':['PRIVATE_DIALOGUE '*250000]},
        'library_context':'PRIVATE_REFERENCE '*200000}
    ident=create_job(p['id'],'generate',payload)
    update_job(ident,'running',48,{'stage':'撰写讲解','request_status':'running',
        'artifacts':[{'metadata':{'lecture':'PRIVATE_RESULT '*100000}}]})
    before=one('SELECT payload_json FROM jobs WHERE id=?',(ident,))['payload_json']
    with TestClient(server.app) as client:
        response=client.get('/api/jobs/'+ident+'?view=progress')
        assert response.status_code==200,response.text
        progress=response.json()
        assert progress['result']['stage']=='撰写讲解' and progress['progress']==48 and progress['can_pause']
        assert progress['payload']['only_exercises'] and progress['payload']['conversation_id']==payload['conversation_id']
        assert len(response.content)<6000 and 'PRIVATE_' not in response.text
        detail=client.get('/api/jobs/'+ident).json()
        assert detail['payload']==payload and detail['result']['artifacts']
    assert one('SELECT payload_json FROM jobs WHERE id=?',(ident,))['payload_json']==before


@pytest.mark.parametrize('kind,payload',[
    ('generate',{}),('read',{}),('read',{'project_id':'p','source_ids':['s']}),
    ('knowledge',{'project_id':'p','source_ids':['s']}),('knowledge',{'project_id':'p','source_ids':['s'],'reading_id':'r'}),
    ('homework_grade',{'workflow_version':1,'values':{'set_id':'s'}}),
    ('quiz_grade',{'workflow_version':1,'values':{}}),('export',{'workflow_version':1,'values':[]}),
    ('coding_grade',{'workflow_version':1,'values':False}),('repair',{'workflow_version':1,'values':'{}'}),
    ('feynman',{'workflow_version':1,'values':'[]'}),('advance',{'workflow_version':1,'values':0}),
    ('advance',{'workflow_version':1,'values':1}),('other',{'workflow_version':1,'values':{'id':'x'}}),
])
def test_compact_views_keep_the_existing_pause_rules(kind,payload):
    p=create_project('任务规则');ident=create_job(p['id'],kind,payload)
    expected=workflows.resumable(one('SELECT * FROM jobs WHERE id=?',(ident,)))
    result=server.job(ident,view='progress')
    assert result['can_pause']==expected
    assert server.jobs(p['id'])[0]['can_pause']==expected


def test_project_task_list_has_bounded_python_allocation_for_large_snapshots():
    p=create_project('大任务列表')
    for _ in range(8):
        ident=create_job(p['id'],'generate',{'dialogue_snapshot':'PRIVATE_CONTEXT '*120000})
        update_job(ident,'running',35,{'stage':'已完成第一部分','private_document':'PRIVATE_OUTPUT '*100000})
    tracemalloc.start()
    try:
        result=server.jobs(p['id']);peak=tracemalloc.get_traced_memory()[1]
    finally:tracemalloc.stop()
    assert len(result)==8 and all(row['stage']=='已完成第一部分' for row in result)
    assert peak<2_000_000,peak


def test_paired_mobile_can_poll_the_same_lightweight_progress():
    from test_mobile_access import mobile_client,pair
    p=create_project('手机');ident=create_job(p['id'],'read',{'project_id':p['id'],'source_ids':[uid()]})
    update_job(ident,'paused',60,{'stage':'等待继续','reading_id':'saved-reading'})
    manager,client=mobile_client()
    with client:
        pair(manager,client)
        result=client.get('/api/jobs/'+ident+'?view=progress')
        assert result.status_code==200,result.text
        assert result.json()['can_pause'] and result.json()['result']['reading_id']=='saved-reading'


def test_phone_bootstrap_can_load_the_shared_refresh_script_without_private_data():
    from test_mobile_access import mobile_client
    _,client=mobile_client()
    with client:
        script=client.get('/refresh_state.js')
        assert script.status_code==200 and 'javascript' in script.headers['content-type']
        assert 'window.studyforgeRefresh' in script.text
        assert client.get('/api/projects').status_code==401
