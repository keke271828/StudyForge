import asyncio
import json
import time

import httpx
import pytest

from studyforge.ai import CodexClient, DeepSeekClient, save_settings
from studyforge.agent_tools import AgentRuntime
from studyforge.codex_bridge import CodexBridge
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid, unj
from studyforge.generation_control import PausableClient, control_for
from studyforge.job_control import start_job, cancel_job
from studyforge.scheduling import execution_scope, model_slot, resource_slot, scheduler, wake_schedulers, run_local


@pytest.mark.parametrize('parallel,limit,expected', [(True,2,2),(True,3,3),(False,3,1)])
def test_real_request_limit_and_span_evidence(parallel,limit,expected):
    save_settings({'task_parallel_enabled':parallel,'model_concurrency':limit})
    async def scenario():
        count=maximum=0
        async def request(index):
            nonlocal count,maximum
            async with execution_scope(label=f'request-{index}'), model_slot('test'):
                count+=1;maximum=max(count,maximum);await asyncio.sleep(.025);count-=1
        await asyncio.gather(*(request(i) for i in range(7)))
        assert maximum==expected
        assert scheduler().snapshot()['model']['active']==scheduler().snapshot()['model']['queued']==0
    asyncio.run(scenario())
    rows=many('SELECT * FROM execution_spans')
    assert len(rows)==7 and all(row['started_at'] and row['ended_at'] and row['status']=='completed' for row in rows)


def test_foreground_priority_resize_and_cancel_queue():
    save_settings({'model_concurrency':1})
    async def scenario():
        entered,release=asyncio.Event(),asyncio.Event();order=[]
        async def blocking():
            async with model_slot('test'): entered.set();await release.wait()
        first=asyncio.create_task(blocking());await entered.wait()
        async def waiting(label,priority=0):
            async with execution_scope(priority=priority,label=label), model_slot('test'):
                order.append(label);await asyncio.sleep(.01)
        background=asyncio.create_task(waiting('background',10));await asyncio.sleep(0)
        cancelled=asyncio.create_task(waiting('cancelled'));await asyncio.sleep(0)
        foreground=asyncio.create_task(waiting('foreground'));await asyncio.sleep(0)
        cancelled.cancel();await asyncio.gather(cancelled,return_exceptions=True)
        save_settings({'model_concurrency':2});wake_schedulers();await asyncio.sleep(.02)
        assert order[0]=='foreground' and 'cancelled' not in order
        release.set();await asyncio.gather(first,foreground,background)
        assert scheduler().snapshot()['model']['queued']==0
    asyncio.run(scenario())


def test_pausing_queued_request_frees_idle_boundary_and_never_sends_before_resume():
    project=create_project('queued pause');job=create_job(project['id'],'generate',{})
    save_settings({'model_concurrency':1})
    async def scenario():
        release,entered=asyncio.Event(),asyncio.Event();calls=[]
        async def blocker():
            async with model_slot('test'):entered.set();await release.wait()
        busy=asyncio.create_task(blocker());await entered.wait()
        class Client:
            async def complete(self,*args,**kwargs):
                async with model_slot('test'):calls.append('sent');return 'reply'
        control=control_for(job);client=PausableClient(Client(),control)
        task=start_job(job,client.complete('system','user'));await asyncio.sleep(.01)
        control.pause();await asyncio.sleep(.01)
        assert one('SELECT status FROM jobs WHERE id=?',(job,))['status']=='paused'
        release.set();await busy;await asyncio.sleep(.01)
        assert not calls and not task.done()
        control.resume();assert await asyncio.wait_for(task,1)=='reply'
        assert calls==['sent'];control.finish()
    asyncio.run(scenario())


def test_cancelling_job_does_not_cancel_other_model_work():
    project=create_project('cancel');job=create_job(project['id'],'generate',{})
    save_settings({'model_concurrency':1})
    async def scenario():
        entered,release=asyncio.Event(),asyncio.Event();calls=[]
        async def other():
            async with model_slot('test'):entered.set();await release.wait();calls.append('other')
        original=asyncio.create_task(other());await entered.wait()
        async def operation():
            async with model_slot('test'):calls.append('cancelled-job')
        task=start_job(job,operation());await asyncio.sleep(.01)
        await cancel_job(job);release.set();await original
        assert task.cancelled() and calls==['other'] and scheduler().snapshot()['model']['queued']==0
    asyncio.run(scenario())


def test_nested_tool_request_releases_and_reacquires_single_model_slot():
    save_settings({'model_concurrency':1})
    async def scenario():
        async with model_slot('codex') as parent:
            await parent.suspend()
            async with model_slot('deepseek'): assert scheduler().snapshot()['model']['active']==1
            await parent.resume();assert scheduler().snapshot()['model']['active']==1
        assert scheduler().snapshot()['model']['active']==0
    asyncio.run(asyncio.wait_for(scenario(),1))
    rows=many('SELECT status FROM execution_spans ORDER BY queued_at,rowid')
    assert rows==[{'status':'tool_wait'},{'status':'completed'},{'status':'completed'}]


def test_codex_dynamic_tool_can_call_model_with_single_global_slot(monkeypatch):
    save_settings({'model_concurrency':1})
    bridge=CodexBridge();sent=[]
    async def send(value):sent.append(value)
    monkeypatch.setattr(bridge,'_send',send)
    class Runtime:
        async def execute(self,name,arguments):
            async with model_slot('deepseek'):
                return {'text':'工具内的独立模型已完成'}
    async def scenario():
        async with bridge.scheduled_turn(None):
            await bridge._handle_tool({'id':1,'params':{'threadId':'test','tool':'nested_model','arguments':{}}},Runtime())
            assert scheduler().snapshot()['model']['active']==1
        assert scheduler().snapshot()['model']['active']==0
    asyncio.run(asyncio.wait_for(scenario(),1))
    assert sent[0]['result']['success'] is True
    assert '工具内的独立模型已完成' in sent[0]['result']['contentItems'][0]['text']


def test_reading_dependency_is_saved_without_blocking_unrelated_model_work(tmp_path,monkeypatch):
    from studyforge import server
    from studyforge.db import update_job
    pid,cid,sid=chat_material(tmp_path)
    reading_job=create_job(pid,'read',{'conversation_id':cid,'source_ids':[sid]})
    reading_id=uid();events=[]
    class Client:
        model='model';effort=None
        async def complete(self,system,user,**kwargs):
            async with model_slot('test'):
                events.append('generation');return '# 讲解\n解释概念。\n\n## 系统性总结\n总结。'
        async def close(self):pass
    monkeypatch.setattr(server,'client_for',lambda *a,**kw:Client())
    monkeypatch.setattr(server.lesson_feedback,'ensure_questionnaire',lambda _:None)
    records=server.read_original_sources(server.source_records([sid],pid))
    execute('INSERT INTO reading_sessions VALUES (?,?,?,?,?,?,?,?,?,?)',
            (reading_id,pid,j([sid]),server.source_fingerprint(records),'deepseek',None,None,'[]',j([r['read_manifest'] for r in records]),now()))
    value=server.GenerateIn(project_id=pid,source_ids=[sid],conversation_id=cid,provider='deepseek',reading_job_id=reading_job)
    job=create_job(pid,'generate',value.model_dump())
    async def scenario():
        generation=asyncio.create_task(server._generate_job(job,value))
        await asyncio.sleep(.03)
        async with model_slot('test'):events.append('unrelated')
        assert events==['unrelated'] and not generation.done()
        update_job(reading_job,'completed',100,{'reading_id':reading_id})
        # This assertion concerns dependency scheduling. Cold DOCX/font imports
        # share no model slot and can exceed two seconds on a loaded Windows PC.
        await asyncio.wait_for(generation,10)
    asyncio.run(scenario())
    row=one('SELECT * FROM jobs WHERE id=?',(job,))
    assert row['status']=='completed',row['error']
    assert unj(row['payload_json'])['reading_id']==reading_id
    assert events[0]=='unrelated' and 'generation' in events


def test_cancelled_local_thread_keeps_resource_occupied_until_thread_exits():
    import threading
    async def scenario():
        entered,release=threading.Event(),threading.Event()
        def work():entered.set();release.wait(timeout=2)
        task=asyncio.create_task(run_local('container',work))
        while not entered.is_set():await asyncio.sleep(.005)
        task.cancel();await asyncio.gather(task,return_exceptions=True)
        assert scheduler().snapshot()['container']['active']==1
        release.set()
        for _ in range(100):
            if not scheduler().snapshot()['container']['active']:break
            await asyncio.sleep(.005)
        assert scheduler().snapshot()['container']['active']==0
    asyncio.run(scenario())


def chat_material(tmp_path,provider='deepseek'):
    project=create_project('isolated task');cid=uid();sid=uid()
    path=tmp_path/'source.txt';path.write_text('相关不等于因果，变量和证据需要区分。',encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (sid,project['id'],path.name,'.txt',str(path),'[]','ready',now()))
    execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)',(cid,project['id'],provider,'public-thread',now(),j([sid]),'model',None))
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),cid,'user','原来的学习要求',now()))
    return project['id'],cid,sid


def test_deepseek_generation_uses_frozen_public_messages_and_never_changes_chat_protocol(tmp_path,monkeypatch):
    pid,cid,sid=chat_material(tmp_path);job=create_job(pid,'generate',{'conversation_id':cid})
    monkeypatch.setattr('studyforge.ai.get_secret',lambda _: 'test-key')
    captured=[];original=httpx.AsyncClient
    async def respond(request):
        captured.append(json.loads(request.content));await asyncio.sleep(.01)
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':'可靠讲解'},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:original(transport=httpx.MockTransport(respond)))
    snapshot={'id':cid,'project_id':pid,'messages':[{'role':'user','content':'冻结要求'}]}
    runtime=AgentRuntime(pid,[sid],'deepseek','model',conversation_id=cid,job_id=job,publishing=False)
    client=DeepSeekClient('model',runtime,snapshot)
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),cid,'user','启动后新增要求',now()))
    execute('INSERT INTO agent_dialogue_state VALUES (?,?,?,?,?)',(cid,1,j([{'role':'assistant','content':'不要继承的工具内容'}]),now(),1))
    before=one('SELECT * FROM agent_dialogue_state WHERE conversation_id=?',(cid,))
    assert asyncio.run(client.complete('system','current'))=='可靠讲解'
    text=j(captured[0]['messages'])
    assert '冻结要求' in text and '启动后新增要求' not in text and '不要继承的工具内容' not in text
    assert one('SELECT * FROM agent_dialogue_state WHERE conversation_id=?',(cid,))==before
    fork=client.fork();assert fork.agent_runtime.workspace!=runtime.workspace and fork.conversation is not snapshot


def test_codex_job_and_forks_own_connections_and_dont_publish_remote_ids(tmp_path,monkeypatch):
    pid,cid,sid=chat_material(tmp_path,'codex');job=create_job(pid,'generate',{})
    bridges=[]
    async def stream(connection,prompt,**options):
        bridges.append((connection,options));yield 'thread','private-thread';yield 'final','讲解'
    monkeypatch.setattr(CodexBridge,'stream_turn',stream)
    runtime=AgentRuntime(pid,[sid],'codex','model',conversation_id=cid,job_id=job,publishing=False)
    original={'id':cid,'messages':[{'role':'user','content':'冻结原话'}],'remote_thread_id':'public-thread'}
    client=CodexClient(model='model',agent_runtime=runtime,conversation=original);fork=client.fork()
    async def scenario():
        assert await asyncio.gather(client.complete('s','u'),fork.complete('s','u'))==['讲解','讲解']
        await client.close();await fork.close()
    asyncio.run(scenario())
    assert bridges[0][0] is not bridges[1][0] and all(options['remote_thread_id'] is None for _,options in bridges)
    assert all('冻结原话' in options['fallback_history'] for _,options in bridges)
    assert one('SELECT remote_thread_id FROM conversations WHERE id=?',(cid,))['remote_thread_id']=='public-thread'
    assert client.agent_runtime.workspace!=fork.agent_runtime.workspace


@pytest.mark.parametrize('parallel',[False,True])
def test_internal_checkbox_changes_chapter_and_worksheet_execution(tmp_path,monkeypatch,parallel):
    from studyforge import server
    pid,cid,sid=chat_material(tmp_path);events=[]
    class Client:
        model='model';effort=None
        def __init__(self,runtime):self.agent_runtime=runtime
        def fork(self):return Client(self.agent_runtime.fork())
        async def close(self):pass
        async def complete(self,system,user,**kwargs):
            label='worksheet' if system=='worksheet' else 'summary' if '只补写整篇文章的系统性总结' in system else 'chapter-1' if '第 1/2' in user else 'chapter-2' if '第 2/2' in user else 'summary'
            async with model_slot('test',self.agent_runtime):
                events.append((label,'start',time.monotonic()));await asyncio.sleep(.08 if label=='chapter-1' else .02);events.append((label,'end',time.monotonic()))
            return '# 清楚讲解\n术语和前提。 [source.txt｜文本]\n\n## 系统性总结\n总结概念。'
    monkeypatch.setattr(server,'client_for',lambda *a,**kw:Client(kw['agent_runtime']))
    monkeypatch.setattr(server,'explanation_batches',lambda digest:[digest,digest])
    async def worksheet(client,*args,**kwargs):await client.complete('worksheet','题目');return uid(),[]
    monkeypatch.setattr(server,'generate_set',worksheet)
    monkeypatch.setattr(server,'student_document',lambda _: '# 题单\n1. 请论证条件。')
    value=server.GenerateIn(project_id=pid,source_ids=[sid],conversation_id=cid,provider='deepseek',model='model',exercises=True,parallel=parallel)
    job=create_job(pid,'generate',value.model_dump())
    asyncio.run(server._generate_job(job,value))
    row=one('SELECT * FROM jobs WHERE id=?',(job,));assert row['status']=='completed',row['error']
    def stamp(label,kind):return next(t for name,event,t in events if name==label and event==kind)
    if parallel:
        assert stamp('worksheet','start')<stamp('chapter-1','end')
        assert stamp('chapter-2','start')<stamp('chapter-1','end') or stamp('chapter-1','start')<stamp('chapter-2','end')
    else:
        assert stamp('chapter-2','start')>=stamp('chapter-1','end')
        assert stamp('worksheet','start')>=stamp('summary','end')
    artifacts=many('SELECT * FROM artifacts');assert len(artifacts)==2 and {a['kind'] for a in artifacts}=={'explanation','exercise'}
    assert all(unj(a['metadata_json'])['conversation_id']==cid for a in artifacts)
    from docx import Document
    student=next(a for a in artifacts if a['kind']=='exercise')
    assert '答案' not in '\n'.join(p.text for p in Document(student['path']).paragraphs)
    assert unj(row['result_json'])['parallel'] is parallel


def test_continuation_dependencies_and_no_extra_practice_when_unchecked():
    from studyforge.lesson_quality import chapter_dependencies
    plan=chapter_dependencies(['\n[来源 A｜1]\n定义。','\n[来源 A｜2]\n[原文续接]\n继续推导。','\n[来源 B｜1]\n独立介绍。'])
    assert [item['after'] for item in plan]==[None,0,None]
    assert plan[1]['reason']


@pytest.mark.parametrize('values',[{'model_concurrency':0},{'model_concurrency':9},{'model_concurrency':True},{'generation_parallel':'yes'},{'task_parallel_enabled':1}])
def test_invalid_settings_do_not_silently_change_concurrency(values):
    with pytest.raises(ValueError):save_settings(values)
