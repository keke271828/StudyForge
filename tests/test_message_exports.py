"""A public answer becomes an exact local snapshot, never a new AI lesson."""
import asyncio
import hashlib
from pathlib import Path
import threading
import zipfile

import pytest
from fastapi.testclient import TestClient

from studyforge import conversations,document_exports, message_exports,server,mobile_access
from studyforge.ai import save_settings
from studyforge.db import create_project,execute,j,many,now,one,uid,unj
from tests.test_document_exports import BODY


def fixture(content=BODY,role='assistant'):
    save_settings({'background_learning_enabled':False,'agent_tools_enabled':False})
    project=create_project('保存满意的解释');chat=conversations.create(project['id'],'deepseek','later-model','high')
    ident=uid();execute('INSERT INTO messages VALUES (?,?,?,?,?)',(ident,chat['id'],role,content,now()))
    return project,chat,ident,hashlib.sha256(content.encode()).hexdigest()


def launch(values,fmt='docx',request=None,title='学习笔记'):
    p,c,mid,digest=values
    return message_exports.launch(p['id'],c['id'],mid,fmt,request or uid(),digest,title)


@pytest.mark.parametrize('fmt',document_exports.FORMATS)
def test_answer_reuses_exact_body_and_project_without_model_or_rereading_selected_files(monkeypatch,fmt):
    values=fixture();p,c,mid,digest=values
    monkeypatch.setattr(server,'client_for',lambda *a,**k:pytest.fail('Saving is local'))
    monkeypatch.setattr('studyforge.materials.read_original_sources',lambda *a,**k:pytest.fail('No rereading current materials'))
    job,reused=launch(values,fmt);assert not reused
    snapshot=one('SELECT * FROM document_snapshots WHERE job_id=?',(job,))
    assert snapshot['content']==BODY and snapshot['content_sha256']==digest
    asyncio.run(document_exports.run_job(job))
    saved=one('SELECT * FROM jobs WHERE id=?',(job,));assert saved['status']=='completed',saved['error']
    artifact=one('SELECT * FROM artifacts');meta=unj(artifact['metadata_json'])
    assert meta['chat_export']['message_id']==mid and meta['chat_export']['content_sha256']==digest
    assert meta['chat_export']['reviewed_again'] is False and meta['conversation_id']==c['id']
    assert meta['model']!='later-model' and meta['source_reading']==[] and unj(artifact['source_ids_json'])==[]
    assert 'generation_job_id' not in meta and not meta.get('reviews')
    assert artifact['project_id']==p['id'] and Path(artifact['path']).stat().st_size>0
    assert len(many('SELECT * FROM messages'))==1 and not many('SELECT * FROM lesson_questionnaires')
    assert not many('SELECT * FROM mastery') and not many('SELECT * FROM learning_events') and not many('SELECT * FROM exercise_sets')
    sources=server.sources(p['id']);assert any(r.get('artifact_id')==artifact['id'] for r in sources)
    assert document_exports.available([artifact],True,p['id'])[artifact['id']]
    if fmt in ('md','txt'):assert Path(artifact['path']).read_text(encoding='utf-8')==BODY
    if fmt=='docx':
        with zipfile.ZipFile(artifact['path']) as z:xml=z.read('word/document.xml').decode()
        assert '严格小于号' in xml and '<m:rad>' in xml and '$' not in xml


def test_idempotence_active_double_click_and_request_intent_are_pinned():
    values=fixture();request=uid();first,reused=launch(values,request=request)
    assert not reused and launch(values,request=request)==(first,True) and launch(values)==(first,True)
    with pytest.raises(ValueError,match='同一次'):launch(values,'pdf',request)
    assert len(many('SELECT * FROM jobs'))==1 and len(many('SELECT * FROM document_snapshots'))==1


def test_frozen_body_survives_chat_edits_and_deletion_after_authorized_export():
    values=fixture();_,c,mid,_=values;job,_=launch(values,'md')
    execute('UPDATE messages SET content=? WHERE id=?',('更改后的另一版回答',mid))
    with pytest.raises(ValueError,match='已变化'):launch(values)
    execute('DELETE FROM messages WHERE id=?',(mid,))
    asyncio.run(document_exports.run_job(job));artifact=one('SELECT * FROM artifacts')
    assert Path(artifact['path']).read_text(encoding='utf-8')==BODY
    assert not many('SELECT * FROM messages') and not many('SELECT * FROM lesson_questionnaires')
    with pytest.raises(LookupError):launch(values)


def test_cross_project_cross_chat_and_deleted_chat_do_not_create_snapshots():
    p,c,mid,digest=fixture();other=create_project('其他项目');chat=conversations.create(p['id'],'deepseek')
    for project,convo in [(other['id'],c['id']),(p['id'],chat['id'])]:
        with pytest.raises(LookupError):message_exports.launch(project,convo,mid,'docx',uid(),digest)
    execute('INSERT INTO deleted_conversations VALUES (?,?)',(c['id'],now()))
    with pytest.raises(LookupError):message_exports.launch(p['id'],c['id'],mid,'docx',uid(),digest)
    assert not many('SELECT * FROM jobs') and not many('SELECT * FROM document_snapshots')


@pytest.mark.parametrize('content,role',[('', 'assistant'),('只写了一半\n'+message_exports.STOPPED,'assistant'),('我的作答','user')])
def test_empty_stopped_and_user_messages_are_not_treated_as_completed_ai_lessons(content,role):
    values=fixture(content,role)
    with pytest.raises(ValueError):launch(values)
    assert not many('SELECT * FROM jobs') and not many('SELECT * FROM document_snapshots')


def test_saved_answer_can_reexport_again_without_duplicate_chat_or_questionnaire():
    values=fixture();p,_,_,_=values;job,_=launch(values,'md');asyncio.run(document_exports.run_job(job))
    artifact=one('SELECT * FROM artifacts');second,_=document_exports.launch(p['id'],artifact['id'],'docx',uid(),True)
    asyncio.run(document_exports.run_job(second))
    assert one('SELECT status FROM jobs WHERE id=?',(second,))['status']=='completed'
    assert len(many('SELECT * FROM artifacts'))==2 and len(many('SELECT * FROM messages'))==1
    assert not many('SELECT * FROM lesson_questionnaires') and not many('SELECT * FROM generation_dialogue_outputs')


@pytest.mark.parametrize('restart',[False,True])
def test_answer_export_can_pause_or_restart_without_rewriting_or_publishing_a_second_reply(monkeypatch,restart):
    from studyforge.generation_control import control_for
    from studyforge.job_control import start_job,active_jobs
    values=fixture();job,_=launch(values,'txt');entered=threading.Event();release=threading.Event()
    original=document_exports.write_file;calls=[]
    def blocked(*args):
        calls.append(args);entered.set();assert release.wait(12);return original(*args)
    monkeypatch.setattr(document_exports,'write_file',blocked)
    async def run():
        control=control_for(job);task=start_job(job,document_exports.run_job(job))
        try:
            async with asyncio.timeout(10):
                while not entered.is_set():await asyncio.sleep(.01)
                await server.pause_generation(job);release.set()
                while one('SELECT status FROM jobs WHERE id=?',(job,))['status']!='paused' or control.in_flight:
                    await asyncio.sleep(.01)
                assert not many('SELECT * FROM artifacts')
                if restart:
                    task.cancel();await asyncio.gather(task,return_exceptions=True)
                    from studyforge.desktop_lifecycle import recover_interrupted_jobs
                    recover_interrupted_jobs();await server.resume_generation(job);task=active_jobs[job]
                else:await server.resume_generation(job)
                await task
        finally:release.set()
    asyncio.run(run())
    assert one('SELECT status FROM jobs WHERE id=?',(job,))['status']=='completed'
    assert len(calls)==1 and len(many('SELECT * FROM artifacts'))==1 and len(many('SELECT * FROM messages'))==1
    assert not many('SELECT * FROM lesson_questionnaires')


def test_api_validation_and_mobile_route_only_allow_public_message_export(monkeypatch):
    values=fixture();p,c,mid,digest=values;api=TestClient(server.app);started=[]
    def start(job,operation):started.append(job);operation.close()
    monkeypatch.setattr(server,'start_job',start)
    body={'project_id':p['id'],'conversation_id':c['id'],'content_sha256':digest,'request_id':uid(),'format':'docx','title':'极限学习笔记'}
    result=api.post('/api/messages/'+mid+'/export',json=body)
    assert result.status_code==200 and result.json()['model_requests']==0 and len(started)==1
    assert api.post('/api/messages/'+mid+'/export',json=body).json()['reused'] and len(started)==1
    assert api.post('/api/messages/'+mid+'/export',json=body|{'content_sha256':'wrong'}).status_code==422
    assert api.post('/api/messages/'+uid()+'/export',json=body).status_code==404
    assert mobile_access.allowed('POST','/api/messages/'+mid+'/export')
    assert not mobile_access.allowed('GET','/api/messages/'+mid) and not mobile_access.allowed('POST','/api/messages/'+mid+'/delete')
