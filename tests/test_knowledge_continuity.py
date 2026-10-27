import json
from fastapi.testclient import TestClient
from studyforge import knowledge,server
from studyforge.db import create_job,one,unj,update_job
from tests.test_knowledge import case

def test_map_view_respects_exact_model_effort_and_service_without_extra_calls(tmp_path,monkeypatch):
    project,source,path,reading,graph,calls=case(tmp_path,monkeypatch)
    saved=one('SELECT * FROM reading_sessions WHERE id=?',(reading,));ids={}
    for service,model,effort in [('deepseek','first','high'),('deepseek','second','high'),('deepseek','first',None),('codex','first','high')]:
        ids[service,model,effort]=knowledge.save_map(saved,graph,service,model,effort)['id']
    client=TestClient(server.app)
    for (service,model,effort),ident in ids.items():
        result=client.get(f'/api/knowledge/reading/{reading}',params={'project_id':project,'provider':service,'model':model,'reasoning_effort':effort or ''})
        assert result.status_code==200,result.text
        assert result.json()['id']==ident
    missing=client.get(f'/api/knowledge/reading/{reading}',params={'project_id':project,'provider':'deepseek','model':'not-built','reasoning_effort':'high'}).json()
    assert missing['structure'] is None
    assert client.get(f'/api/knowledge/reading/{reading}',params={'project_id':project}).json()['id']==ids['codex','first','high']
    assert len(calls)==1

def test_small_task_views_keep_model_scope_without_copying_private_context(tmp_path,monkeypatch):
    project,source,path,reading,graph,calls=case(tmp_path,monkeypatch)
    payload={'project_id':project,'source_ids':[source],'reading_id':reading,'provider':'deepseek','model':'first',
        'reasoning_effort':'high','conversation_id':'origin-chat','dialogue_snapshot':'PRIVATE_CONTENT_'*100000}
    ident=create_job(project,'knowledge',payload);update_job(ident,'paused',42,{'stage':'已保存','notes':'PRIVATE_NOTES_'*100000})
    client=TestClient(server.app)
    listing=client.get(f'/api/projects/{project}/jobs').json();row=next(item for item in listing if item['id']==ident)
    progress=client.get(f'/api/jobs/{ident}?view=progress')
    for field in ('provider','model','reasoning_effort','conversation_id','reading_id'):
        assert row[field]==payload[field] and progress.json()['payload'][field]==payload[field]
    assert len(progress.content)<6000 and 'PRIVATE_' not in progress.text and 'PRIVATE_' not in json.dumps(listing)
    assert unj(one('SELECT payload_json FROM jobs WHERE id=?',(ident,))['payload_json'])==payload
    assert len(calls)==1
