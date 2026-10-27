"""Foreground must actually run under load, without bypassing the global cap."""
import asyncio
from datetime import datetime

import pytest

from studyforge import ai,library_policy as policy,library_worker
from studyforge.db import one,unj
from studyforge.scheduling import execution_scope,model_slot
from test_global_library import setup_book,scoped_node,Client,tracker


@pytest.mark.parametrize('cap', [1,2])
def test_foreground_request_shares_limit_with_live_chat(tmp_path,cap):
    b,_=setup_book(tmp_path);n=scoped_node(b);t=tracker()
    ai.save_settings({'model_concurrency':cap,'task_parallel_enabled':True})
    class Gated(Client):
        async def complete(self,system,user,**kw):
            async with model_slot('fixture'):
                t['inputs'].append(user)
                await asyncio.sleep(.025)
                return '保留条件和来源 PDF 第1页。'
    async def scenario():
        worker=library_worker.LibraryWorker(lambda p:Gated(t))
        row=library_worker.new_read_job(b['id'],[n['id']],'fixture','fixture','none',foreground=True)
        async with execution_scope(priority=0,conversation_id='live-chat'):
            async with model_slot('chat'):
                worker.launch(row['id']);task=worker.tasks[row['id']]
                for _ in range(40):
                    if t['inputs']:break
                    await asyncio.sleep(.025)
                assert bool(t['inputs'])==(cap==2)  # real client entry, not just a mode label
                if cap==2:
                    await asyncio.wait_for(task,3)
                    assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='completed'
        await asyncio.wait_for(task,4)
        assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='completed'
    asyncio.run(scenario())


def test_waiting_background_and_paused_foreground_do_not_block_new_foreground(tmp_path):
    from studyforge.learning_memory import foreground_activity
    b,_=setup_book(tmp_path);a=scoped_node(b,'A',1,1);c=scoped_node(b,'C',2,2);d=scoped_node(b,'D',3,3)
    t=tracker()
    async def scenario():
        worker=library_worker.LibraryWorker(lambda p:Client(t));await worker.start()
        try:
            with foreground_activity():
                bg=library_worker.new_read_job(b['id'],[a['id']],'fixture','fixture','none')
                worker.launch(bg['id'])  # running control, parked at its background checkpoint
                front=library_worker.new_read_job(b['id'],[c['id']],'fixture','fixture','none',foreground=True)
                paused=library_worker.new_read_job(b['id'],[d['id']],'fixture','fixture','none',foreground=True)
                await worker.action(paused['id'],'pause')
                for _ in range(60):
                    if one('SELECT status FROM library_jobs WHERE id=?',(front['id'],))['status']=='completed':break
                    await asyncio.sleep(.05)
                assert one('SELECT status FROM library_jobs WHERE id=?',(front['id'],))['status']=='completed'
                assert one('SELECT status FROM library_jobs WHERE id=?',(bg['id'],))['status']=='queued'
                assert one('SELECT status FROM library_jobs WHERE id=?',(paused['id'],))['status']=='paused'
            await worker.action(paused['id'],'resume')
            for _ in range(80):
                if all(one('SELECT status FROM library_jobs WHERE id=?',(r['id'],))['status']=='completed' for r in [bg,paused]):break
                await asyncio.sleep(.05)
            assert all(one('SELECT status FROM library_jobs WHERE id=?',(r['id'],))['status']=='completed' for r in [bg,paused])
        finally:await worker.close()
    asyncio.run(scenario())


def test_foreground_bypasses_background_window_but_keeps_budget_and_usage(tmp_path,monkeypatch):
    monkeypatch.setattr(policy,'local_now',lambda:datetime(2026,10,11,12,0).astimezone())
    b,_=setup_book(tmp_path);n=scoped_node(b)
    row=library_worker.new_read_job(b['id'],[n['id']],'fixture','fixture','none',foreground=True)
    policy.save({'window_enabled':True,'start':'23:00','end':'23:30','daily_tokens':20_000})
    assert not policy.wait_for_job(one('SELECT * FROM library_jobs WHERE id=?',(row['id'],)))
    body={'model':'fixture','messages':[{'content':'只读取所选范围'}]}
    async def scenario():
        async with execution_scope(library_foreground=True,library_reading=True,job_id=row['id']):
            policy.check_window()
            with policy.model_request(body,'fixture') as meter:meter.accept({'usage':{'total_tokens':500}})
            policy.save({'daily_tokens':100})
            with pytest.raises(policy.ReadingDeferred,match='预算'):
                with policy.model_request(body,'fixture'):pytest.fail('budget bypassed')
    asyncio.run(scenario())
    assert policy.status()['usage']['reported']==500
    assert policy.wait_for_job(one('SELECT * FROM library_jobs WHERE id=?',(row['id'],)))['kind']=='daily_budget'


def test_foreground_pause_restart_preserves_priority_and_saved_step(tmp_path):
    from studyforge.learning_memory import foreground_activity
    b,_=setup_book(tmp_path);n=scoped_node(b);t=tracker()
    async def scenario():
        t.update(started=asyncio.Event(),release=asyncio.Event())
        worker=library_worker.LibraryWorker(lambda p:Client(t))
        row=library_worker.new_read_job(b['id'],[n['id']],'fixture','fixture','none',foreground=True)
        worker.launch(row['id']);await asyncio.wait_for(t['started'].wait(),3)
        await worker.action(row['id'],'pause');t['release'].set();await asyncio.sleep(.15)
        await worker.close()
        restarted=library_worker.LibraryWorker(lambda p:Client(t));await restarted.start()
        try:
            with foreground_activity():
                await restarted.action(row['id'],'resume')
                for _ in range(60):
                    if one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='completed':break
                    await asyncio.sleep(.05)
                saved=one('SELECT * FROM library_jobs WHERE id=?',(row['id'],))
                assert saved['status']=='completed' and unj(saved['payload_json'])['foreground']
                assert len(t['inputs'])==1  # finished model step is not repeated
        finally:await restarted.close()
    asyncio.run(scenario())
