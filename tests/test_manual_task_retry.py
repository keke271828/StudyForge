"""Manual retry reuses the original task, cache and scope without replaying grades."""
import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException

from studyforge import ai,server,task_recovery,task_retry,workflows
from studyforge.db import create_job,execute,j,many,now,one,uid,unj,update_job
from studyforge.generation_control import control_for,PausableClient,active_generations
from studyforge.job_control import start_job,active_jobs
from tests.test_generation_control import material


@pytest.fixture(autouse=True)
def no_auto_retries():
    ai.save_settings({'task_auto_retry':False,'background_learning_enabled':False})
    yield
    active_generations.clear()


def failure(value,kind='generate',reason='网络连接中断或超时'):
    ident=create_job(value.project_id,kind,value.model_dump())
    execute("UPDATE jobs SET status='failed',progress=100,error='ConnectError: interrupted' WHERE id=?",(ident,))
    execute("UPDATE task_retries SET state='disabled',reason=? WHERE job_id=?",(reason,ident))
    return ident


def request(value,nonce=None):return server.TaskRetryIn(project_id=value.project_id,request_id=nonce or uid())


async def finish(ident):
    task=active_jobs.get(ident)
    if task:await task
    await asyncio.sleep(0)


def test_manual_retry_reuses_successful_step_and_frozen_requirements(tmp_path,monkeypatch):
    value=material(tmp_path);value.instructions='原要求';calls={'good':0,'bad':0};seen=[]
    class Client:
        model='writer';effort='high'
        async def complete(self,system,user,**kw):
            calls[user]+=1
            if user=='bad' and calls[user]==1:raise httpx.ConnectError('interrupted')
            return '已核对的章节' if user=='good' else '后来完成的章节'
    async def worker(ident,saved):
        seen.append(saved.model_dump())
        records=await server.generation_input_records(saved);workflows.pin_originals(ident,records)
        client=PausableClient(Client(),control_for(ident),'manual-fixture')
        a=await client.complete('教师','good');b=await client.complete('教师','bad')
        update_job(ident,'completed',100,{'text':a+b})
    monkeypatch.setattr(server,'_generate_job',worker)
    async def scenario():
        ident=create_job(value.project_id,'generate',value.model_dump())
        await start_job(ident,lambda:worker(ident,value));assert server.job(ident)['status']=='failed'
        before=one('SELECT payload_json FROM jobs WHERE id=?',(ident,))['payload_json']
        ai.save_settings({'deepseek_model':'later-model'})
        nonce=uid();answer=await server.retry_saved_task(ident,request(value,nonce));await finish(ident)
        repeated=await server.retry_saved_task(ident,request(value,nonce))
        assert answer['job_id']==ident and not answer['reused'] and repeated['reused']
        assert server.job(ident)['status']=='completed' and calls=={'good':1,'bad':2}
        assert seen[0]==seen[1] and seen[1]['instructions']=='原要求' and seen[1]['model']=='writer'
        assert one('SELECT payload_json FROM jobs WHERE id=?',(ident,))['payload_json']==before
        assert len(many('SELECT * FROM task_manual_retries'))==1
        assert not many('SELECT * FROM learning_events') and not many('SELECT * FROM mastery')
    asyncio.run(scenario())


def test_double_request_has_one_source_check_one_worker_and_one_receipt(tmp_path,monkeypatch):
    value=material(tmp_path);ident=failure(value);calls=[];checks=[]
    async def validate(*args):checks.append(1);await asyncio.sleep(.03)
    async def worker(job,saved):calls.append(1);await asyncio.sleep(.02);update_job(job,'completed',100)
    monkeypatch.setattr(task_recovery,'validate_originals',validate);monkeypatch.setattr(server,'_generate_job',worker)
    async def scenario():
        nonce=uid();results=await asyncio.gather(*(server.retry_saved_task(ident,request(value,nonce)) for _ in range(8)))
        await finish(ident)
        assert sum(not row['reused'] for row in results)==1 and len(calls)==len(checks)==1
        assert len(many('SELECT * FROM task_manual_retries'))==1
        assert len(task_recovery.locks)==0
    asyncio.run(scenario())


@pytest.mark.parametrize('kind',['quiz_grade','homework_grade','coding_grade','feynman','repair','advance','coding_generate','import'])
def test_generic_recovery_never_replays_assessments_or_untracked_imports(tmp_path,kind):
    value=material(tmp_path);ident=failure(value,kind)
    before=one('SELECT * FROM jobs WHERE id=?',(ident,))
    assert not server.job(ident)['recovery']['available']
    with pytest.raises(HTTPException) as rejected:asyncio.run(server.retry_saved_task(ident,request(value)))
    assert rejected.value.status_code==409 and one('SELECT * FROM jobs WHERE id=?',(ident,))==before
    assert not many('SELECT * FROM task_manual_retries')


@pytest.mark.parametrize('reason',['教学内容仍有实质质量问题，需要修订','需要修正输入、配置或内容问题',
    '本次未完成步骤可能已修改文件，需核对后继续，避免重复操作','题目版本或复习依据需要核对，重复模型请求无法修复'])
def test_content_version_and_external_effect_blocks_are_not_bypassed(tmp_path,reason):
    value=material(tmp_path);ident=failure(value,reason=reason)
    with pytest.raises(HTTPException):asyncio.run(server.retry_saved_task(ident,request(value)))
    assert server.job(ident)['status']=='failed' and not many('SELECT * FROM task_manual_retries')


def test_source_changes_are_rejected_before_changing_task_or_retry_allowance(tmp_path):
    value=material(tmp_path);ident=failure(value)
    records=asyncio.run(server.generation_input_records(value));workflows.pin_originals(ident,records)
    source=one('SELECT original_path FROM sources WHERE id=?',(value.source_ids[0],))
    from pathlib import Path
    Path(source['original_path']).write_text('这是另一个版本。',encoding='utf-8')
    before=one('SELECT * FROM jobs WHERE id=?',(ident,));retry=task_retry.public('project',ident)
    with pytest.raises(HTTPException) as error:asyncio.run(server.retry_saved_task(ident,request(value)))
    assert error.value.status_code==409 and '改变' in error.value.detail
    assert one('SELECT * FROM jobs WHERE id=?',(ident,))==before and task_retry.public('project',ident)==retry


@pytest.mark.parametrize('mutation',['delete','project','intent','cancel'])
def test_changes_during_validation_cannot_resurrect_or_repurpose_task(tmp_path,monkeypatch,mutation):
    value=material(tmp_path);ident=failure(value)
    async def scenario():
        entered=asyncio.Event();release=asyncio.Event()
        async def validate(*args):entered.set();await release.wait()
        monkeypatch.setattr(task_recovery,'validate_originals',validate)
        work=asyncio.create_task(server.retry_saved_task(ident,request(value)));await entered.wait()
        if mutation=='delete':execute('INSERT INTO deleted_job_records VALUES (?,?)',(ident,now()))
        elif mutation=='project':execute('INSERT INTO removed_projects VALUES (?,?)',(value.project_id,now()))
        elif mutation=='intent':execute("UPDATE jobs SET payload_json=json_set(payload_json,'$.instructions','后来改过') WHERE id=?",(ident,))
        else:execute("UPDATE jobs SET status='cancelled' WHERE id=?",(ident,))
        release.set()
        with pytest.raises(HTTPException) as rejected:await work
        assert rejected.value.status_code==409 and not many('SELECT * FROM task_manual_retries')
        assert ident not in active_jobs
    asyncio.run(scenario())


def test_wrong_project_and_existing_cancelled_completed_tasks_are_not_reopened(tmp_path):
    value=material(tmp_path);ident=failure(value)
    with pytest.raises(HTTPException) as other:asyncio.run(server.retry_saved_task(ident,server.TaskRetryIn(project_id=uid(),request_id=uid())))
    assert other.value.status_code==404
    for status in ['completed','cancelled','running','paused']:
        execute('UPDATE jobs SET status=? WHERE id=?',(status,ident))
        with pytest.raises(HTTPException):asyncio.run(server.retry_saved_task(ident,request(value)))
        assert server.job(ident)['status']==status


def test_list_capability_projects_small_fields_not_a_large_dialogue(tmp_path):
    value=material(tmp_path);ident=failure(value)
    payload=value.model_dump()|{'dialogue_snapshot':{'messages':[{'content':'PRIVATE_DIALOGUE_'+'x'*2000000}]}}
    execute('UPDATE jobs SET payload_json=? WHERE id=?',(j(payload),ident))
    result=server.jobs(value.project_id)
    assert result[0]['recovery']['available'] and len(j(result))<12000
    assert 'PRIVATE_DIALOGUE' not in j(result) and 'dialogue_snapshot' not in j(result)
    assert server.job(ident,'progress')['recovery']['available']


def test_library_primary_inputs_are_used_for_both_retry_and_pause_resume(tmp_path,monkeypatch):
    value=material(tmp_path);records=asyncio.run(server.generation_input_records(value))
    value.source_ids=[];value.library_snapshot={'references':[{'purpose':'primary','node_id':'original-scope'}]}
    seen=[]
    async def library_records(saved):seen.append(saved.library_snapshot);return records
    async def worker(ident,saved):update_job(ident,'completed',100)
    monkeypatch.setattr(server,'generation_input_records',library_records);monkeypatch.setattr(server,'_generate_job',worker)
    async def scenario():
        for paused in [False,True]:
            ident=failure(value);workflows.pin_originals(ident,records)
            if paused:
                execute("UPDATE jobs SET status='paused' WHERE id=?",(ident,));await server.resume_generation(ident)
            else:await server.retry_saved_task(ident,request(value))
            await finish(ident);assert server.job(ident)['status']=='completed'
    asyncio.run(scenario());assert seen==[value.library_snapshot,value.library_snapshot]


def test_uncached_file_effect_is_blocked_but_committed_step_can_be_reused(tmp_path):
    value=material(tmp_path);ident=failure(value)
    records=asyncio.run(server.generation_input_records(value));workflows.pin_originals(ident,records)
    key='a'*64
    execute('INSERT INTO generation_steps VALUES (?,?,?,?)',(ident,'external-effect:'+key,j(True),now()))
    assert not server.job(ident)['recovery']['available']
    execute('INSERT INTO generation_steps VALUES (?,?,?,?)',(ident,key,j('已成功保存的步骤'),now()))
    assert server.job(ident)['recovery']['available']


def test_export_recovery_keeps_the_saved_body_and_needs_no_model(tmp_path,monkeypatch):
    from tests.test_document_exports import snapshot,BODY
    from studyforge import document_exports
    from docx import Document
    project,chat,root,source,artifact=snapshot(tmp_path)
    ai.save_settings({'task_auto_retry':False})
    ident,reused=document_exports.launch(project['id'],artifact['id'],'docx',uid(),True)
    original=document_exports.write_file;calls=[]
    def flaky(*args,**kwargs):
        calls.append(1)
        if len(calls)==1:raise TimeoutError('local layout timeout')
        return original(*args,**kwargs)
    monkeypatch.setattr(document_exports,'write_file',flaky)
    monkeypatch.setattr(server,'client_for',lambda *a,**k:pytest.fail('纯排版恢复不应请求模型'))
    async def scenario():
        await start_job(ident,lambda:document_exports.run_job(ident));assert server.job(ident)['status']=='failed'
        await server.retry_saved_task(ident,server.TaskRetryIn(project_id=project['id'],request_id=uid()));await finish(ident)
        result=server.job(ident);assert result['status']=='completed' and result['result']['model_requests']==0
        delivered=one("SELECT * FROM artifacts WHERE json_extract(metadata_json,'$.reexport_job_id')=?",(ident,))
        assert '严格小于号' in '\n'.join(p.text for p in Document(delivered['path']).paragraphs)
        assert len(many('SELECT * FROM generation_dialogue_outputs'))==1 and len(calls)==2
    asyncio.run(scenario())


@pytest.mark.parametrize('kind',['read','knowledge'])
def test_actual_reading_and_knowledge_workers_recover_the_same_task(tmp_path,monkeypatch,kind):
    from tests.test_knowledge import case
    project,source,path,reading,graph,calls=case(tmp_path,monkeypatch)
    value=server.ReadIn(project_id=project,source_ids=[source],provider='deepseek',model='structure-model') if kind=='read' else server.KnowledgeIn(project_id=project,source_ids=[source],provider='deepseek',model='structure-model',reading_id=reading)
    if kind=='read':execute('DELETE FROM reading_sessions WHERE id=?',(reading,))
    factory=server.client_for;failed=[]
    class Client:
        def __init__(self,wrapped):self.wrapped=wrapped
        def __getattr__(self,name):return getattr(self.wrapped,name)
        async def complete(self,*args,**kwargs):
            if not failed:failed.append(1);raise httpx.ConnectError('one controlled interruption')
            return await self.wrapped.complete(*args,**kwargs)
    monkeypatch.setattr(server,'client_for',lambda *a,**kw:Client(factory(*a,**kw)))
    async def scenario():
        ident=create_job(project,kind,value.model_dump())
        worker=server._read_job if kind=='read' else server._knowledge_job
        await start_job(ident,lambda:worker(ident,value));assert server.job(ident)['status']=='failed'
        await server.retry_saved_task(ident,server.TaskRetryIn(project_id=project,request_id=uid()));await finish(ident)
        result=server.job(ident);assert result['status']=='completed' and len(calls)==2
        assert many('SELECT * FROM mastery')==[] and many('SELECT * FROM exercise_sets')==[]
        if kind=='read':assert result['result']['reading_id'] and len(many('SELECT * FROM reading_sessions'))==1
        else:assert result['result']['map_id'] and len(many('SELECT * FROM knowledge_maps'))==1
    asyncio.run(scenario())
