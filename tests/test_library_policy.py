"""Real admission boundaries, persisted accounting, and resumable native calls."""
import asyncio
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from studyforge import ai, library_policy as policy, library_worker, server
from studyforge.db import execute, many, one
from studyforge.scheduling import execution_scope
from test_global_library import setup_book, scoped_node


MOMENT=datetime(2026,10,12,23,30,tzinfo=timezone(timedelta(hours=8)))  # Monday
BODY={'model':'fixture','messages':[{'content':'定义和条件'}]}


def job(tmp_path, count=1):
    b,_=setup_book(tmp_path,count=count)
    nodes=[scoped_node(b,'节点 '+str(page),page,page) for page in range(1,count+1)]
    return library_worker.new_read_job(b['id'],[n['id'] for n in nodes],'deepseek','fixture','none'),b,nodes


def fixed_clock(monkeypatch):
    clock={'now':MOMENT};monkeypatch.setattr(policy,'local_now',lambda:clock['now']);return clock


@pytest.mark.parametrize('moment,expected',[(MOMENT,True),(MOMENT+timedelta(hours=2),True),
    (MOMENT+timedelta(hours=3),False),(MOMENT-timedelta(hours=2),False),
    (MOMENT+timedelta(days=1),False)])
def test_overnight_window_uses_starting_weekday_and_exclusive_end(moment,expected):
    prefs=policy.DEFAULTS|{'window_enabled':True,'start':'23:00','end':'02:00','weekdays':[0]}
    assert policy.window_allowed(prefs,moment)==expected


def test_all_day_and_next_opening_are_local_calendar_values():
    prefs=policy.DEFAULTS|{'window_enabled':True,'start':'00:00','end':'00:00','weekdays':[1]}
    assert not policy.window_allowed(prefs,MOMENT)
    assert policy.next_opening(prefs,MOMENT)==(MOMENT+timedelta(days=1)).replace(hour=0,minute=0).isoformat()
    prefs.update(start='23:00',end='02:00',weekdays=[0])
    closed=MOMENT+timedelta(hours=3)
    assert datetime.fromisoformat(policy.next_opening(prefs,closed)).weekday()==0


@pytest.mark.parametrize('change',[{'daily_tokens':True},{'daily_tokens':-1},{'start':'24:00'},
    {'end':'1:00'},{'weekdays':[]},{'weekdays':[True]},{'window_enabled':1},{'unknown':0}])
def test_invalid_policy_does_not_replace_saved_configuration(change):
    old=policy.configuration()
    with pytest.raises(ValueError):policy.save(change)
    assert policy.configuration()==old


def test_parallel_reservations_share_one_transactional_balance(tmp_path,monkeypatch):
    fixed_clock(monkeypatch);row,_,_=job(tmp_path);amount=policy.estimate(BODY)
    policy.save({'daily_tokens':amount})
    async def hold():
        async with execution_scope(library_reading=True,job_id=row['id']):
            with policy.model_request(BODY,'fixture'):
                assert policy.status()['usage']['reserved']==amount
                with pytest.raises(policy.ReadingDeferred):
                    with policy.model_request(BODY,'fixture'):pytest.fail('same balance spent twice')
    asyncio.run(hold())
    assert policy.status()['usage']['estimated']==amount and policy.status()['usage']['reserved']==0


def test_two_threads_cannot_reserve_the_same_remaining_balance(tmp_path,monkeypatch):
    import threading
    fixed_clock(monkeypatch);row,_,_=job(tmp_path);amount=policy.estimate(BODY)
    policy.save({'daily_tokens':amount});entered=threading.Event();release=threading.Event()
    async def reserve_once():
        async with execution_scope(library_reading=True,job_id=row['id']):
            with policy.model_request(BODY,'fixture'):
                entered.set();await asyncio.to_thread(release.wait,3)
    async def competing():
        async with execution_scope(library_reading=True,job_id=row['id']):
            with pytest.raises(policy.ReadingDeferred):
                with policy.model_request(BODY,'fixture'):pytest.fail('overbooked')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(asyncio.run,reserve_once());assert entered.wait(3)
        second=pool.submit(asyncio.run,competing());second.result(3);release.set();first.result(3)
    assert len(many('SELECT * FROM library_model_usage'))==1


def test_reported_and_unknown_usage_survive_midnight_restart_and_job_removal(tmp_path,monkeypatch):
    clock=fixed_clock(monkeypatch);row,_,_=job(tmp_path);amount=policy.estimate(BODY)
    async def calls():
        async with execution_scope(library_reading=True,job_id=row['id']):
            with policy.model_request(BODY,'fixture') as meter:
                meter.accept({'usage':{'total_tokens':123}});clock['now']+=timedelta(hours=1)
            with pytest.raises(RuntimeError):
                with policy.model_request(BODY,'fixture'):raise RuntimeError('unknown completion')
    asyncio.run(calls())
    entries=many('SELECT * FROM library_model_usage ORDER BY rowid')
    assert entries[0]['day']==MOMENT.date().isoformat() and entries[0]['charged_tokens']==123
    assert entries[1]['day']==clock['now'].date().isoformat() and entries[1]['charged_tokens']==amount
    execute("UPDATE library_model_usage SET status='inflight',charged_tokens=0 WHERE id=?",(entries[1]['id'],))
    policy.recover_requests()
    assert policy.status()['usage']['uncertain']==1 and policy.status()['usage']['charged']==amount
    execute('DELETE FROM library_jobs WHERE id=?',(row['id'],))
    assert len(many('SELECT * FROM library_model_usage'))==2
    assert policy.status()['usage']['charged']==amount


def test_usage_validation_and_foreground_exclusion(tmp_path,monkeypatch):
    fixed_clock(monkeypatch);row,_,_=job(tmp_path)
    policy.save({'daily_tokens':1})
    assert policy.reported_total({'usageMetadata':{'totalTokenCount':321,'thoughtsTokenCount':100}})==321
    for value in [True,-1,'123',None]:assert policy.reported_total({'usage':{'total_tokens':value}}) is None
    async def foreground():
        async with execution_scope(job_id=row['id']):
            with policy.model_request(BODY,'fixture') as meter:meter.accept({'usage':{'total_tokens':9000}})
    asyncio.run(foreground());assert not many('SELECT * FROM library_model_usage')
    image=BODY|{'messages':[{'content':[{'type':'image_url','image_url':{'url':'data:'+'x'*100_000}}]}]}
    assert policy.estimate(image)<20_000


def native_transport(monkeypatch,totals):
    monkeypatch.setattr(ai,'get_secret',lambda key:'fixture-only')
    calls=[];original=httpx.AsyncClient
    async def respond(request):
        body=json.loads(request.content);calls.append(body)
        return httpx.Response(200,json={'choices':[{'message':{'content':'本页的定义、条件与来源已整理。'},'finish_reason':'stop'}],
            'usage':{'total_tokens':totals[len(calls)-1] if len(calls)<=len(totals) else 100}})
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda *a,**kw:original(transport=httpx.MockTransport(respond)))
    return calls


def test_native_budget_wait_resumes_from_cache_without_duplicate_requests(tmp_path,monkeypatch):
    fixed_clock(monkeypatch);row,_,nodes=job(tmp_path,count=2)
    calls=native_transport(monkeypatch,[200_000,100]);policy.save({'daily_tokens':100_000})
    async def scenario():
        worker=library_worker.LibraryWorker(lambda payload:ai.DeepSeekClient('fixture',effort='none'))
        worker.launch(row['id']);await worker.tasks[row['id']];await asyncio.sleep(0)
        saved=one('SELECT * FROM library_jobs WHERE id=?',(row['id'],))
        assert saved['status']=='queued' and not saved['error']
        assert policy.wait_for_job(saved)['kind']=='daily_budget'
        assert len(calls)==1 and len(many("SELECT * FROM library_readings WHERE status='completed'"))==1
        # Raising the budget admits exactly the unfinished chapter.
        policy.save({'daily_tokens':300_000})
        worker.launch(row['id']);await worker.tasks[row['id']]
        assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='completed'
        assert len(calls)==2 and len(many("SELECT * FROM library_readings WHERE status='completed'"))==2
        assert len(many('SELECT * FROM library_model_usage'))==2
        assert calls[0]['thinking']=={'type':'disabled'}  # selected strength preserved
        assert all('max_tokens' not in body for body in calls)
    asyncio.run(scenario())


def test_window_wait_auto_continues_but_user_pause_stays_paused(tmp_path,monkeypatch):
    clock=fixed_clock(monkeypatch);row,_,_=job(tmp_path)
    calls=native_transport(monkeypatch,[100]);policy.save({'window_enabled':True,'start':'01:00','end':'02:00'})
    async def scenario():
        worker=library_worker.LibraryWorker(lambda payload:ai.DeepSeekClient('fixture',effort='none'))
        await worker.start()
        try:
            await asyncio.sleep(.1);assert not calls
            assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='queued'
            await worker.action(row['id'],'pause');clock['now']+=timedelta(hours=2)
            await asyncio.sleep(.45);assert not calls
            assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='paused'
            await worker.action(row['id'],'resume')
            for _ in range(30):
                if one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='completed':break
                await asyncio.sleep(.1)
            assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='completed'
            assert len(calls)==1
        finally:await worker.close()
    asyncio.run(scenario())


def test_native_retry_requires_new_reservation_and_cannot_bypass_quota(tmp_path,monkeypatch):
    fixed_clock(monkeypatch);row,_,_=job(tmp_path);policy.save({'daily_tokens':policy.estimate(BODY)})
    monkeypatch.setattr(ai,'get_secret',lambda key:'fixture-only');calls=[];original=httpx.AsyncClient
    async def fail(request):calls.append(request);raise httpx.ConnectError('fixture',request=request)
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda *a,**kw:original(transport=httpx.MockTransport(fail)))
    async def scenario():
        client=ai.DeepSeekClient('fixture')
        try:
            async with execution_scope(library_reading=True,job_id=row['id']):
                with pytest.raises(policy.ReadingDeferred):await client._post(BODY)
        finally:await client.close()
    asyncio.run(scenario());assert len(calls)==1
    assert policy.status()['usage']['uncertain']==1


def test_codex_attempt_is_budgeted_before_model_work(tmp_path,monkeypatch):
    from studyforge.codex_bridge import CodexBridge
    fixed_clock(monkeypatch);row,_,_=job(tmp_path);policy.save({'daily_tokens':1})
    async def scenario():
        async with execution_scope(library_reading=True,job_id=row['id']):
            with pytest.raises(policy.ReadingDeferred):
                async with CodexBridge().scheduled_turn(None,BODY):pytest.fail('Codex entered model work')
    asyncio.run(scenario());assert not many('SELECT * FROM library_model_usage')


def test_policy_routes_validate_and_are_available_to_paired_gateway():
    from studyforge.mobile_access import MobileManager
    with TestClient(server.app) as client:
        original=client.get('/api/library/policy').json()['settings']
        assert original==policy.DEFAULTS
        saved=client.put('/api/library/policy',json=original|{'daily_tokens':100_000})
        assert saved.status_code==200 and saved.json()['settings']['daily_tokens']==100_000
        assert client.put('/api/library/policy',json=original|{'daily_tokens':True}).status_code==422
        assert client.put('/api/library/policy',json=original|{'weekdays':[9]}).status_code==400
    from studyforge.mobile_access import SAFE_ROUTES
    import re
    for method in ('GET','PUT'):
        assert any(verb==method and re.fullmatch(pattern,'/api/library/policy') for verb,pattern in SAFE_ROUTES)
    manager=MobileManager(server.app);manager.addresses=['127.0.0.1']
    with TestClient(manager.gateway,base_url='https://127.0.0.1',client=('127.0.0.1',14000)) as client:
        assert client.get('/library_policy.js').status_code==200
        assert client.get('/api/library/policy').status_code==401


@pytest.mark.parametrize('protocol', ['openai', 'gemini'])
def test_native_third_party_accounting_uses_response_before_normalization(tmp_path,monkeypatch,protocol):
    from studyforge import providers, provider_clients
    fixed_clock(monkeypatch);row,_,_=job(tmp_path)
    monkeypatch.setattr(provider_clients,'get_secret',lambda key:'fixture-only')
    monkeypatch.setattr(providers,'get_secret',lambda key:'fixture-only')
    service=providers.save_service({'name':'Budget fixture','protocol':protocol,
        'base_url':'https://fixture.example/v1','default_model':'fixture','requires_key':False})
    original=httpx.AsyncClient;calls=[]
    def respond(request):
        calls.append(request)
        packet=({'candidates':[{'content':{'parts':[{'text':'概念与条件'}]},'finishReason':'STOP'}],
            'usageMetadata':{'totalTokenCount':123,'thoughtsTokenCount':80}} if protocol=='gemini' else
            {'choices':[{'message':{'content':'概念与条件'},'finish_reason':'stop'}],'usage':{'total_tokens':123}})
        return httpx.Response(200,json=packet)
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:original(transport=httpx.MockTransport(respond)))
    body=BODY|{'messages':[{'role':'user','content':'概念和条件'}]}
    async def scenario():
        async with execution_scope(library_reading=True,job_id=row['id']):
            client=provider_clients.service_client(service['id'])
            await client._post(body)
            policy.save({'daily_tokens':123})
            with pytest.raises(policy.ReadingDeferred):await client._post(body)
    asyncio.run(scenario())
    assert len(calls)==1 and policy.status()['usage']['reported']==123


def test_codex_missing_report_stays_explicitly_estimated(tmp_path,monkeypatch):
    from studyforge.codex_bridge import CodexBridge
    fixed_clock(monkeypatch);row,_,_=job(tmp_path)
    async def scenario():
        async with execution_scope(library_reading=True,job_id=row['id']):
            async with CodexBridge().scheduled_turn(None,BODY):pass
    asyncio.run(scenario())
    assert policy.status()['usage']['estimated']==policy.estimate(BODY)
    assert policy.status()['usage']['reported']==0


def test_local_new_day_auto_resumes_budget_wait(tmp_path,monkeypatch):
    clock=fixed_clock(monkeypatch);row,_,_=job(tmp_path,count=2)
    calls=native_transport(monkeypatch,[200_000,100]);policy.save({'daily_tokens':100_000})
    async def scenario():
        worker=library_worker.LibraryWorker(lambda payload:ai.DeepSeekClient('fixture',effort='none'))
        await worker.start()
        try:
            for _ in range(60):
                saved=one('SELECT * FROM library_jobs WHERE id=?',(row['id'],))
                if saved['status']=='queued' and library_worker.unj(saved['result_json'],{}).get('policy_wait'):break
                await asyncio.sleep(.1)
            assert len(calls)==1 and saved['status']=='queued'
            clock['now']+=timedelta(days=1)
            for _ in range(60):
                if one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='completed':break
                await asyncio.sleep(.1)
            assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='completed'
            assert len(calls)==2 and policy.status()['usage']['reported']==100
        finally:await worker.close()
    asyncio.run(scenario())


def test_window_closing_during_sent_request_saves_result_before_wait(tmp_path,monkeypatch):
    clock=fixed_clock(monkeypatch);row,_,_=job(tmp_path)
    policy.save({'window_enabled':True,'start':'23:00','end':'23:59'})
    monkeypatch.setattr(ai,'get_secret',lambda key:'fixture-only');calls=[];original=httpx.AsyncClient
    async def respond(request):
        calls.append(request);clock['now']+=timedelta(hours=1)
        return httpx.Response(200,json={'choices':[{'message':{'content':'定义、条件与本页来源。'},'finish_reason':'stop'}],
            'usage':{'total_tokens':123}})
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:original(transport=httpx.MockTransport(respond)))
    async def scenario():
        worker=library_worker.LibraryWorker(lambda payload:ai.DeepSeekClient('fixture',effort='none'))
        worker.launch(row['id']);await worker.tasks[row['id']];await asyncio.sleep(0)
        saved=one('SELECT * FROM library_jobs WHERE id=?',(row['id'],))
        assert saved['status']=='queued' and not saved['error'] and len(calls)==1
        assert many('SELECT * FROM library_steps')
        policy.save({'window_enabled':False})
        worker.launch(row['id']);await worker.tasks[row['id']]
        assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='completed'
        assert len(calls)==1  # the already-sent result is reused
    asyncio.run(scenario())
