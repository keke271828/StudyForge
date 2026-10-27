"""Controlled failures through real task/step registries and persistence."""
import asyncio
from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest

from studyforge import ai, library, library_worker, server, task_retry
from studyforge.db import create_job, create_project, execute, j, many, now, one, unj, update_job
from studyforge.generation_control import PausableClient, active_generations, control_for
from studyforge.job_control import active_jobs, cancel_job, remove_job, start_job

REAL_RETRY_DELAY = task_retry.retry_delay


@pytest.fixture(autouse=True)
def immediate_retry(monkeypatch):
    ai.save_settings({'task_auto_retry':True,'task_retry_limit':5,'background_learning_enabled':False})
    monkeypatch.setattr(task_retry,'retry_delay',lambda count,error:0)
    yield
    active_generations.clear()


def job(kind='generate', **payload):
    project=create_project('故障恢复验收')
    return create_job(project['id'],kind,payload),project['id']


async def until(job_id, predicate):
    for _ in range(200):
        row=one('SELECT * FROM jobs WHERE id=?',(job_id,))
        if predicate(row):return row
        await asyncio.sleep(.005)
    pytest.fail(str(row))


@pytest.mark.parametrize('success',[True,False])
def test_five_retries_after_initial_attempt_and_successful_steps_are_reused(success):
    identifier,project=job(model='frozen-model',source_ids=['original'],instructions='原始要求')
    calls={'good':0,'bad':0};seen=[]
    class Model:
        model='frozen-model';effort='high'
        async def complete(self,system,user,**kw):
            if user=='good':calls['good']+=1;return '已完成的章节'
            calls['bad']+=1
            if not success or calls['bad']<6:raise httpx.ConnectError('connection reset')
            return '后来完成的章节'
    async def run():
        row=one('SELECT * FROM jobs WHERE id=?',(identifier,));seen.append(unj(row['payload_json']))
        client=PausableClient(Model(),control_for(identifier),'chapter')
        await client.complete('教师','good')
        await client.complete('教师','bad')
        update_job(identifier,'completed',100,{'result':'完整成果'})
    asyncio.run(start_scenario(identifier,run))
    row=server.job(identifier);retry=row['retry']
    assert calls=={'good':1,'bad':6} and len(seen)==6
    assert retry['retry_count']==5 and retry['limit_count']==5
    assert row['status']==('completed' if success else 'failed')
    assert retry['state']==('completed' if success else 'exhausted')
    assert all(item==seen[0] for item in seen)
    assert server.jobs(project)[0]['retry']==retry
    assert identifier not in active_jobs and identifier not in active_generations


async def start_scenario(identifier,factory):
    await start_job(identifier,factory)
    await asyncio.sleep(0)


@pytest.mark.parametrize('problem',[
    RuntimeError('DeepSeek API 返回 HTTP 401：密钥无效'),
    RuntimeError('HTTP 402 余额不足'),RuntimeError('HTTP 403 Forbidden'),
    FileNotFoundError('原文件未找到'),PermissionError('用户没有批准'),
    RuntimeError('习题修订后仍有实质问题：第1题独立解题未通过'),
    ValueError('原资料已变更'),TypeError("dict() got multiple values for keyword argument 'stage'"),
])
def test_permanent_errors_are_not_repeated_five_times(problem):
    identifier,_=job();calls=[]
    async def run():calls.append(1);raise problem
    asyncio.run(start_scenario(identifier,run))
    result=server.job(identifier)
    assert len(calls)==1 and result['status']=='failed'
    assert result['retry']['retry_count']==0 and result['retry']['state']=='blocked'


def test_actual_http_429_and_retry_after_are_recognized():
    request=httpx.Request('POST','https://example.com/v1/chat')
    response=httpx.Response(429,headers={'retry-after':'75'},request=request)
    error=httpx.HTTPStatusError('rate limited',request=request,response=response)
    assert task_retry.classify(error)[0]
    assert REAL_RETRY_DELAY(1,error)==75
    assert [REAL_RETRY_DELAY(n,RuntimeError('network')) for n in range(1,6)]==[3,6,12,24,48]


def test_explicit_billing_failure_is_not_mistaken_for_a_temporary_rate_limit():
    request=httpx.Request('POST','https://example.com/v1/chat')
    response=httpx.Response(429,json={'error':{'code':'insufficient_quota'}},request=request)
    error=httpx.HTTPStatusError('429 response',request=request,response=response)
    assert task_retry.classify(error)==(False,'账户额度或余额需要处理')


def test_empty_library_index_is_recoverable():
    assert task_retry.classify(ValueError('节点索引为空'))[0]


def test_schema_invalid_json_is_discarded_but_good_steps_stay_cached():
    identifier,_=job();calls=[]
    class Model:
        model='m';effort=None
        async def complete(self,system,user,**kw):
            calls.append((system,user))
            if user=='good':return 'success'
            return '{}' if len([c for c in calls if c[1]!='good'])<=2 else '{"questions":[1]}'
    async def run():
        client=PausableClient(Model(),control_for(identifier))
        await client.complete('s','good')
        def validate(value):
            if not value.get('questions'):raise ValueError('缺少 questions 数组')
        await ai.complete_json(client,'题目','原文',validate=validate)
        update_job(identifier,'completed',100)
    asyncio.run(start_scenario(identifier,run))
    assert server.job(identifier)['status']=='completed'
    assert calls.count(('s','good'))==1 and len(calls)==4
    assert len(many('SELECT * FROM generation_steps WHERE job_id=?',(identifier,)))==2


@pytest.mark.parametrize('action',['pause','cancel','delete'])
def test_waiting_retry_releases_model_slot_and_pause_cancel_delete_work(monkeypatch,action):
    monkeypatch.setattr(task_retry,'retry_delay',lambda *a:60)
    ai.save_settings({'model_concurrency':1})
    identifier,_=job();calls=[]
    async def run():
        from studyforge.scheduling import model_slot
        async with model_slot('mock'):calls.append(1);raise httpx.ReadTimeout('timeout')
    async def scenario():
        task=start_job(identifier,run)
        await until(identifier,lambda row:row['status']=='queued' and bool((task_retry.public('project',identifier) or {}).get('next_at')))
        from studyforge.scheduling import model_slot
        async with asyncio.timeout(1):
            async with model_slot('another-task'):pass  # Retry does not hold the only slot.
        if action=='pause':
            await server.pause_generation(identifier);await until(identifier,lambda row:row['status']=='paused')
            assert server.job(identifier)['retry']['state']=='waiting'
            execute("UPDATE task_retries SET next_at=? WHERE job_id=?",(now(),identifier))
            await asyncio.sleep(.3);assert calls==[1]
            await server.resume_generation(identifier)
            await until(identifier,lambda row:task_retry.public('project',identifier)['retry_count']==2)
            await cancel_job(identifier)
        elif action=='cancel':await cancel_job(identifier)
        else:await remove_job(identifier)
        await asyncio.gather(task,return_exceptions=True)
        assert one('SELECT status FROM jobs WHERE id=?',(identifier,))['status']=='cancelled'
        assert task_retry.public('project',identifier)['state']=='cancelled'
        assert len(calls)==(2 if action=='pause' else 1)
    asyncio.run(scenario())


def test_uncached_step_with_file_side_effect_is_not_replayed():
    identifier,_=job();calls=[]
    async def risky():
        task_retry.mark_external_effect();calls.append('wrote-file');raise httpx.ConnectError('lost reply after writing')
    async def run():await control_for(identifier).step('agent','same command',risky)
    asyncio.run(start_scenario(identifier,run))
    assert calls==['wrote-file'] and server.job(identifier)['retry']['state']=='blocked'
    assert '重复操作' in server.job(identifier)['retry']['reason']


def test_restart_keeps_retry_count_and_next_time(monkeypatch):
    identifier,_=job();task_retry.ensure('project',identifier)
    assert task_retry.schedule('project',identifier,httpx.ConnectError('retry'))
    before=task_retry.public('project',identifier)
    from studyforge.desktop_lifecycle import recover_interrupted_jobs
    assert recover_interrupted_jobs()['paused_generations']==1
    assert task_retry.public('project',identifier)==before
    assert server.job(identifier)['status']=='paused'


def test_real_generation_retries_broken_exercise_response_without_duplicate_lecture(tmp_path,monkeypatch):
    from test_task_exercise_workflows import fixture,PRIVATE
    from docx import Document
    value,model=fixture(tmp_path,monkeypatch,both=True,malformed=2)
    value.format='docx'
    identifier=create_job(value.project_id,'generate',value.model_dump())
    async def scenario():await start_job(identifier,server._generate_job(identifier,value))
    asyncio.run(scenario())
    assert server.job(identifier)['status']=='completed',server.job(identifier)['error']
    assert server.job(identifier)['retry']['retry_count']==1
    outputs=many('SELECT * FROM artifacts');assert len(outputs)==2
    assert len(many('SELECT * FROM exercise_sets'))==1
    assert len(many('SELECT * FROM generation_dialogue_outputs WHERE job_id=?',(identifier,)))==1
    assert len([call for call in model.calls if '习题设计者' in call[0]])==3
    exercise=next(item for item in outputs if item['kind']=='exercise')
    assert PRIVATE not in '\n'.join(p.text for p in Document(exercise['path']).paragraphs)
    assert PRIVATE not in str(server.job(identifier))


@pytest.mark.parametrize('failure',['network','empty'])
def test_book_worker_retries_only_failed_node_and_finishes_after_five_retries(tmp_path,failure):
    from test_global_library import setup_book,scoped_node,Client,tracker
    b,_=setup_book(tmp_path);a=scoped_node(b,'A',1,1);z=scoped_node(b,'B',2,2);t=tracker();counts={a['id']:0,z['id']:0}
    class Broken(Client):
        async def complete(self,system,user,**kw):
            key=z['id'] if 'PDF 第 2 页' in user else a['id'];counts[key]+=1
            if key==z['id'] and counts[key]<6:
                if failure=='empty':return ''
                raise httpx.ConnectError('temporary disconnect')
            return '阅读记录；原文来源 PDF 第1页。'
    async def scenario():
        worker=library_worker.LibraryWorker(lambda p:Broken(t))
        row=library_worker.new_read_job(b['id'],[a['id'],z['id']],'fixture','fixture','none',foreground=True,force=True)
        await worker.start()
        try:
            for _ in range(300):
                state=one('SELECT * FROM library_jobs WHERE id=?',(row['id'],))
                if state['status'] in ('completed','failed'):break
                await asyncio.sleep(.04)
            assert state['status']=='completed',state['error']
            assert library.public_job(state)['retry']['retry_count']==5
            assert counts=={a['id']:1,z['id']:6}
            assert len(many("SELECT * FROM library_readings WHERE status='completed'"))==2
            assert not many("SELECT * FROM desktop_notices WHERE category='failure'")
        finally:await worker.close()
    asyncio.run(scenario())


def test_grading_network_retry_keeps_one_grade_and_one_solution_document(monkeypatch):
    from test_homework import fixture,finish
    p,c,set_id,model,value=fixture(monkeypatch,unknown=False)
    original=model.complete;failed=[]
    async def broken(system,user,**kwargs):
        if '逐题诊断错因并补讲' in system and not failed:
            failed.append(1);raise httpx.ConnectError('disconnect during feedback')
        return await original(system,user,**kwargs)
    model.complete=broken
    async def scenario():
        submitted=await server.submit_answers(set_id,value)
        result=await finish(submitted)
        assert result['status']=='completed',result['error']
        assert server.job(submitted['job_id'])['retry']['retry_count']==1
    asyncio.run(scenario())
    assert len(many('SELECT * FROM submissions WHERE exercise_set_id=?',(set_id,)))==1
    assert len(many("SELECT * FROM artifacts WHERE kind='solutions'"))==1
    assert len(many("SELECT * FROM artifacts WHERE kind='grading'"))==1


def test_duplicate_start_cannot_launch_a_second_attempt_for_same_task():
    identifier,_=job();calls=[]
    async def scenario():
        release=asyncio.Event()
        async def run():calls.append(1);await release.wait();update_job(identifier,'completed',100)
        first=start_job(identifier,run)
        duplicate=run();second=start_job(identifier,duplicate)
        assert first is second
        release.set();await first
    asyncio.run(scenario())
    assert calls==[1]


def test_schema_discard_after_user_file_effect_cannot_replay_the_write():
    identifier,_=job();calls=[]
    class Model:
        model='m';effort=None
        async def complete(self,*args,**kwargs):task_retry.mark_external_effect();calls.append(1);return '{}'
    async def run():
        client=PausableClient(Model(),control_for(identifier))
        def reject(value):raise ValueError('结构不符合要求')
        await ai.complete_json(client,'任务','原文',validate=reject)
    asyncio.run(start_scenario(identifier,run))
    assert len(calls)==1  # Even format repair cannot automatically replay a file write.
    assert server.job(identifier)['retry']['retry_count']==0
    assert '重复操作' in server.job(identifier)['retry']['reason']


@pytest.mark.parametrize('value',[0,4,True,21,'5'])
def test_invalid_retry_limit_rejected(value):
    with pytest.raises(ValueError):ai.save_settings({'task_retry_limit':value})


def test_disabled_setting_and_limit_are_frozen_for_launched_task():
    ai.save_settings({'task_auto_retry':False,'task_retry_limit':8})
    identifier,_=job();task_retry.ensure('project',identifier)
    ai.save_settings({'task_auto_retry':True,'task_retry_limit':5})
    async def run():raise httpx.ConnectError('offline')
    asyncio.run(start_scenario(identifier,run))
    row=server.job(identifier)
    assert row['status']=='failed' and row['retry']['state']=='disabled'
    assert row['retry']['limit_count']==8 and row['retry']['retry_count']==0


@pytest.mark.parametrize('family',['project','library'])
def test_deleted_task_cannot_regain_retry_state_from_a_late_worker(tmp_path,family):
    if family=='project':identifier,_=job()
    else:
        from test_global_library import setup_book
        book,_=setup_book(tmp_path)
        identifier=library_worker.create_job(book['id'],'toc',{})['id']
    assert task_retry.public(family,identifier)
    execute(f'DELETE FROM {task_retry.TABLES[family]} WHERE id=?',(identifier,))
    assert task_retry.public(family,identifier) is None
    assert task_retry.ensure(family,identifier) is None
    assert not task_retry.schedule(family,identifier,httpx.ConnectError('late disconnect'))
    assert task_retry.public(family,identifier) is None


def test_failure_callback_keeps_partial_artifacts_in_the_retrying_task():
    identifier,_=job()
    update_job(identifier,'running',67,{'completed_chapters':['chapter-1']})
    attempt=task_retry.Attempt('project',identifier,error=httpx.ConnectError('disconnect'))
    token=task_retry.current_attempt.set(attempt)
    try:
        update_job(identifier,'failed',100,{'artifacts':['lecture-id'],'stage':'题单未完成'})
    finally:task_retry.current_attempt.reset(token)
    row=server.job(identifier)
    assert row['status']=='queued' and row['progress']==67
    assert row['result']['artifacts']==['lecture-id']
    assert row['result']['completed_chapters']==['chapter-1']
    assert '等待自动重试 1/5' in row['result']['stage']


def test_book_manual_retry_gets_new_allowance_but_pause_resume_keeps_it(tmp_path):
    from test_global_library import setup_book
    book,_=setup_book(tmp_path)
    ai.save_settings({'task_retry_limit':8})
    identifier=library_worker.create_job(book['id'],'toc',{})['id']
    assert task_retry.schedule('library',identifier,httpx.ConnectError('disconnect'))
    ai.save_settings({'task_retry_limit':5})
    async def scenario():
        worker=library_worker.LibraryWorker()
        await worker.action(identifier,'pause')
        await worker.action(identifier,'resume')
        assert task_retry.public('library',identifier)['retry_count']==1
        execute("UPDATE library_jobs SET status='failed' WHERE id=?",(identifier,))
        await worker.action(identifier,'resume')
    asyncio.run(scenario())
    row=task_retry.public('library',identifier)
    assert row['retry_count']==0 and row['limit_count']==8
    assert row['state']=='queued' and row['next_at'] is None
