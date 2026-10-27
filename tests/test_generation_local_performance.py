import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import sqlite3
import threading
import tracemalloc

import pytest

from studyforge import db, generation_control, materials, task_timing
from studyforge.db import create_job, create_project, execute, j, many, one, update_job
from studyforge.generation_control import GenerationControl
from studyforge.json_digest import sha256
from studyforge.scheduling import execution_scope, model_slot, run_owned_io


@pytest.mark.parametrize('ensure_ascii', [False, True])
@pytest.mark.parametrize('sort_keys', [False, True])
def test_streamed_hash_preserves_existing_json_keys(ensure_ascii, sort_keys):
    value = [{'中文': '\"\\\n\r\t\x00🙂', 'numbers': [1, -2.25, 1e30, float('inf')],
              'nest': {'empty': [], 'bool': True, 'null': None}}, ('t', 5)]
    expected = hashlib.sha256(json.dumps(value, ensure_ascii=ensure_ascii, sort_keys=sort_keys).encode()).hexdigest()
    assert sha256(value, ensure_ascii=ensure_ascii, sort_keys=sort_keys) == expected


def test_large_original_hash_has_bounded_temporary_allocations():
    parts = [{'locator': str(i), 'text': ('中文证明 %04d\n' % i) * 10000, 'meta': {}} for i in range(60)]
    expected = hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    tracemalloc.start()
    try:
        actual = sha256(parts, sort_keys=True)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert actual == expected
    assert peak < 2_000_000, 'Temporary JSON copies must not grow with the whole original'


def test_control_updates_do_not_reload_private_task_snapshot(monkeypatch):
    project = create_project('progress');ident = create_job(project['id'], 'generate', {'dialogue_snapshot': 'private' * 400000})
    real_connect = db.connect
    @contextmanager
    def limited():
        with real_connect() as connection:
            connection.set_authorizer(lambda action, table, column, *_:
                sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and table == 'jobs' and column == 'payload_json' else sqlite3.SQLITE_OK)
            yield connection
    monkeypatch.setattr(db, 'connect', limited)
    async def run():
        control = GenerationControl(ident)
        control.stage('读取', 5);control.pause();control.resume()
        await control.checkpoint()
        control.stage('撰写', 15, {'chapters_completed': [1]})
        return one('SELECT result_json,progress FROM jobs WHERE id=?', (ident,))
    result = asyncio.run(run())
    assert result['progress'] == 15 and json.loads(result['result_json'])['chapters_completed'] == [1]


def test_legacy_saved_step_resumes_without_another_model_request():
    project = create_project('resume');ident = create_job(project['id'], 'generate', {})
    signature = ['model', 'high', '原文' * 10000]
    key = hashlib.sha256(j(['writer', signature]).encode()).hexdigest()
    execute('INSERT INTO generation_steps VALUES (?,?,?,?)', (ident, key, j('已完成的讲解'), db.now()))
    async def unexpected():
        pytest.fail('A matching legacy step must not spend tokens again')
    result = asyncio.run(GenerationControl(ident).step('writer', signature, unexpected))
    assert result == '已完成的讲解'


def test_original_hash_and_body_stay_exact_without_stale_preview(tmp_path):
    path = tmp_path / 'source.txt';path.write_text('完整原文🙂\n末尾条件', encoding='utf-8')
    result = materials.read_original_sources([{'id': 's', 'name': 'source.txt', 'original_path': str(path),
        'segments_json': 'stale preview', 'segments': [], 'status': 'ready'}])[0]
    expected = hashlib.sha256(json.dumps([result['segments'], []], ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    assert result['read_manifest']['content_sha256'] == expected
    assert 'segments_json' not in result
    assert result['segments'][-1]['text'].endswith('末尾条件')


def test_cached_video_hash_does_not_lock_unrelated_book(tmp_path, monkeypatch):
    materials.clear_original_cache()
    paths = [tmp_path / name for name in ('large.txt', 'small.txt')]
    for path in paths:
        path.write_text(path.name, encoding='utf-8')
        materials.remember_parsed_original(path, materials.file_sha256(path), [{'locator': '位置', 'text': path.name, 'meta': {}}])
    entered, release = threading.Event(), threading.Event()
    real = materials.asset_fingerprints
    def slow(parts):
        if parts[0]['text'] == 'large.txt':
            entered.set();assert release.wait(3)
        return real(parts)
    monkeypatch.setattr(materials, 'asset_fingerprints', slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(materials.parsed_original, paths[0], materials.file_sha256(paths[0]))
        try:
            assert entered.wait(1)
            other = pool.submit(materials.parsed_original, paths[1], materials.file_sha256(paths[1]))
            assert other.result(timeout=1)[1] is True
        finally:
            release.set()
        assert first.result(timeout=1)[1] is True


def test_all_workflow_exports_share_one_slot_without_blocking_cloud(monkeypatch):
    from studyforge import exporters, workflows
    from docx import Document
    entered, release = threading.Event(), threading.Event()
    state = {'active': 0, 'peak': 0};real = exporters.EXPORTERS['docx']
    def write(content, title, path):
        state['active'] += 1;state['peak'] = max(state['peak'], state['active'])
        try:
            if title == 'first':entered.set();assert release.wait(3)
            return real(content, title, path)
        finally:
            state['active'] -= 1
    monkeypatch.setitem(exporters.EXPORTERS, 'docx', write)
    async def run():
        first = asyncio.create_task(workflows.export('# 原文\n正文保持完整', 'docx', 'first', 'first.docx'))
        try:
            while not entered.is_set():await asyncio.sleep(.003)
            second = asyncio.create_task(workflows.export('# 原文\n第二份正文', 'docx', 'second', 'second.docx'))
            await asyncio.sleep(.02)
            assert state['active'] == 1
            async with model_slot('fixture'):pass
        finally:
            release.set()
        return await first, await second
    outputs = asyncio.run(run())
    assert state['peak'] == 1
    assert all(Document(path).paragraphs[-1].text for path in outputs)
    assert [row['resource'] for row in many('SELECT resource FROM execution_spans')].count('document_export') == 2


def test_initial_document_export_pauses_and_resumes_without_rewriting(tmp_path, monkeypatch):
    from studyforge import exporters, server
    project = create_project('initial export');source_id = db.uid()
    path = tmp_path / 'original.txt';path.write_text('准确性依赖于前提条件。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (source_id,project['id'],'original.txt','.txt',str(path),'ready',db.now()))
    entered, release = threading.Event(), threading.Event();calls=[];writes=[]
    class Client:
        model='test-model';effort='high'
        async def complete(self, system, user):
            calls.append(user)
            return '# 条件与结论\n\n原文说明条件。[original.txt｜行 1-1]\n\n## 系统性总结\n要检查前提条件。'
    real = exporters.EXPORTERS['docx']
    def write(content,title,output):
        writes.append(content);entered.set();assert release.wait(4)
        return real(content,title,output)
    monkeypatch.setattr(server,'client_for',lambda *args,**kwargs:Client())
    monkeypatch.setitem(exporters.EXPORTERS,'docx',write)
    value=server.GenerateIn(project_id=project['id'],source_ids=[source_id],format='docx',provider='deepseek',review_mode='express')
    ident=create_job(project['id'],'generate',value.model_dump())
    async def run():
        task=asyncio.create_task(server._generate_job(ident,value))
        control=None
        try:
            async def started():
                while not entered.is_set():
                    if task.done():raise AssertionError(one('SELECT status,error FROM jobs WHERE id=?',(ident,)))
                    await asyncio.sleep(.003)
            await asyncio.wait_for(started(),4)
            control=generation_control.active_generations[ident];control.pause()
            assert one('SELECT status FROM jobs WHERE id=?',(ident,))['status']=='pausing'
            release.set()
            async def paused():
                while one('SELECT status FROM jobs WHERE id=?',(ident,))['status']!='paused':await asyncio.sleep(.005)
            await asyncio.wait_for(paused(),4)
            assert not many('SELECT id FROM artifacts WHERE project_id=?',(project['id'],))
            control.resume();await asyncio.wait_for(task,4)
        finally:
            release.set()
            if control and not task.done():control.resume()
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True)
    asyncio.run(run())
    assert one('SELECT status FROM jobs WHERE id=?',(ident,))['status']=='completed'
    assert len(writes)==1 and len(calls)==1


def test_timing_records_actual_thread_and_contains_no_private_input():
    project = create_project('timing');ident = create_job(project['id'], 'read', {'private': 'PRIVATE_ANSWER'})
    async def run():
        async with execution_scope(job_id=ident, project_id=project['id']):
            return await run_owned_io(task_timing.timed_call, 'original_read', '原文件读取', lambda: 'PRIVATE_SOURCE')
    assert asyncio.run(run()) == 'PRIVATE_SOURCE'
    result = task_timing.detail(ident)
    assert result['observed'] and result['resources'][0]['resource'] == 'original_read'
    assert 'PRIVATE_' not in j(result)


def test_timing_counts_queue_and_execution_separately_and_keeps_overlap():
    project = create_project('durations');ident = create_job(project['id'], 'generate', {})
    for resource in ('model', 'document_export'):
        execute('INSERT INTO execution_spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (db.uid(), 0, ident, project['id'], None, resource, None, 'label', 0, 'completed',
             '2026-10-11T01:00:00+00:00', '2026-10-11T01:00:02+00:00', '2026-10-11T01:00:07+00:00', 5000))
    update_job(ident, 'completed', 100)
    result = task_timing.detail(ident)
    assert result['overlapping'] and all(row['elapsed_ms'] == 5000 and row['queue_ms'] == 2000 for row in result['resources'])


def test_model_stage_labels_separate_writing_and_review():
    project=create_project('stages');ident=create_job(project['id'],'generate',{})
    async def run():
        async with execution_scope(job_id=ident,project_id=project['id'],label='writer'):
            for stage in ('讲解撰写','讲解审查','全文总结'):
                async with execution_scope(stage_label=stage):
                    async with model_slot('fixture'):pass
    asyncio.run(run())
    result=task_timing.detail(ident)
    assert [row['phase'] for row in result['resources']]==['讲解撰写','讲解审查','全文总结']
    assert all(row['calls']==1 for row in result['resources'])


def test_deleted_job_does_not_reappear_when_timing_finishes():
    project = create_project('deleted');ident = create_job(project['id'], 'generate', {})
    async def run():
        async with execution_scope(job_id=ident, project_id=project['id']):
            with task_timing.phase('original_read', 'read'):
                execute('INSERT INTO deleted_job_records VALUES (?,?)', (ident, db.now()))
                execute('DELETE FROM execution_spans WHERE job_id=?', (ident,))
    asyncio.run(run())
    assert task_timing.detail(ident) is None
    assert not many('SELECT * FROM execution_spans WHERE job_id=?', (ident,))


def test_timing_endpoint_and_mobile_allowlist():
    import re
    from fastapi.testclient import TestClient
    from studyforge import server
    from studyforge.mobile_access import SAFE_ROUTES
    project = create_project('API');ident = create_job(project['id'], 'generate', {})
    result = TestClient(server.app).get(f'/api/jobs/{ident}/timing')
    assert result.status_code == 200 and result.json()['observed'] is False
    assert any(method == 'GET' and re.fullmatch(pattern, f'/api/jobs/{ident}/timing') for method, pattern in SAFE_ROUTES)
    assert TestClient(server.app).get(f'/api/jobs/{db.uid()}/timing').status_code == 404
