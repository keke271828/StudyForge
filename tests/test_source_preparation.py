import asyncio
import copy
from contextlib import contextmanager
import hashlib
from pathlib import Path
import random
import sqlite3
import threading

import pytest

from studyforge import ai, db, generation_control, materials, scheduling, server
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid


def source(tmp_path, project, suffix='.txt', status='ready', parts=None):
    ident = uid()
    path = tmp_path / (ident + suffix)
    path.write_text('完整原文件：必要条件与末尾结论。', encoding='utf-8')
    parts = parts if parts is not None else [dict(locator='旧预览', text='不应作为原文使用的预览' * 5000, meta={})]
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (ident, project, path.name, suffix, str(path), j(parts), status, now()))
    return ident, path


def forbid_previews(monkeypatch):
    real = db.connect
    @contextmanager
    def connection():
        with real() as database:
            database.set_authorizer(lambda action, table, column, *_:
                sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and table == 'sources' and column == 'segments_json'
                else sqlite3.SQLITE_OK)
            yield database
    monkeypatch.setattr(db, 'connect', connection)


def test_validation_and_original_nonmedia_never_read_cached_preview(tmp_path, monkeypatch):
    project = create_project('完整原文')['id']
    a, path = source(tmp_path, project)
    b, _ = source(tmp_path, project, '.sfvideo')
    stored, _ = source(tmp_path, project, '.pdf', 'stored')
    forbid_previews(monkeypatch)
    async def run():
        checked = await server.source_records_async([a, b], project, metadata_only=True)
        records = await server.source_records_async([a], project, for_original=True)
        capsule = await server.source_records_async([b], project, for_original=True)
        pending = await server.source_records_async([stored], project, allow_stored=True, for_original=True)
        original = await materials.read_original_sources_async(records)
        return checked, records, capsule, pending, original
    checked, records, capsule, pending, original = asyncio.run(run())
    assert [row['id'] for row in checked] == [a, b]
    assert all('segments' not in row and 'segments_json' not in row for row in checked + records + capsule + pending)
    assert original[0]['segments'][-1]['text'] == path.read_text(encoding='utf-8')
    assert original[0]['read_manifest']['method'] == 'original_file'
    assert not many("SELECT * FROM execution_spans WHERE resource='source_prepare'"), 'Unowned validations need no diagnostic writes'


def test_media_keeps_complete_transcript_checksum_and_frame_locations(tmp_path):
    project = create_project('视频原文')['id']
    ident, path = source(tmp_path, project, '.mp4')
    parts = [dict(locator='00:00:00-00:00:12', text='视频末尾的必要条件。',
                  meta={'original_media_sha256': materials.file_sha256(path), 'method': 'speech'}),
             dict(locator='画面 00:00:08', text='可读板书', meta={})]
    execute('UPDATE sources SET segments_json=? WHERE id=?', (j(parts), ident))
    async def run():
        records = await server.source_records_async([ident], project, for_original=True)
        assert records[0]['segments'] == parts and 'segments_json' not in records[0]
        return await materials.read_original_sources_async(records)
    original = asyncio.run(run())[0]
    assert original['segments'] == parts
    assert original['read_manifest']['method'] == 'full_transcript_and_frames'
    assert original['read_manifest']['sha256'] == materials.file_sha256(path)
    assert server.source_records([ident], project)[0]['segments_json'] == j(parts), 'The sync compatibility contract remains complete'


@pytest.mark.parametrize('status,allow_stored', [('pending', True), ('failed', True), ('stored', False)])
def test_projection_still_rejects_unready_sources(tmp_path, status, allow_stored):
    project = create_project('范围隔离')['id']
    ident, _ = source(tmp_path, project, status=status)
    with pytest.raises(ValueError, match='不存在或尚未解析完成'):
        asyncio.run(server.source_records_async([ident], project, metadata_only=True, allow_stored=allow_stored))


def test_projection_keeps_project_isolation_and_artifact_identity(tmp_path):
    project = create_project('项目 A')['id']; other = create_project('项目 B')['id']
    ident, path = source(tmp_path, project)
    artifact = server.add_artifact(project, [], 'explanation', 'docx', '已有讲解', path, {})
    execute('INSERT INTO artifact_sources VALUES (?,?)', (artifact['id'], ident))
    checked = asyncio.run(server.source_records_async([ident], project, for_original=True))
    assert checked[0]['artifact_id'] == artifact['id']
    assert checked[0]['project_id'] == project
    with pytest.raises(ValueError): asyncio.run(server.source_records_async([ident], other, metadata_only=True))
    with pytest.raises(ValueError): asyncio.run(server.source_records_async(['missing'], project, metadata_only=True))
    with pytest.raises(ValueError, match='至少选择'): asyncio.run(server.source_records_async([], project, metadata_only=True))


def legacy_chunks(sources, limit):
    # Frozen transport contract: continuation/source markers affect persisted
    # step keys. This intentionally compares the previous algorithm's output.
    chunks, current = [], ''
    for record in sources:
        for item in record['segments']:
            header = f"\n[来源 {record['name']}｜{item['locator']}]\n"
            value = header + str(item.get('text', '')) + '\n'
            while value:
                available = limit - len(current)
                if available < 1000:
                    chunks.append(current);current = '';available = limit
                current += value[:available];value = value[available:]
                if value:
                    chunks.append(current);current = '';value = header + '[原文续接]\n' + value
    if current: chunks.append(current)
    return chunks


@pytest.mark.parametrize('limit', [1600, 12000, 24000])
def test_offset_chunker_keeps_every_character_order_and_exact_legacy_markers(limit):
    rng = random.Random(43)
    records = [dict(name=f'原文 {i}🙂', segments=[dict(locator=f'第 {n + 1} 页', text=(f'唯一片段_{i}_{n} $x^2$。\n' * rng.randrange(0, 2400)))
               for n in range(24)]) for i in range(2)]
    before = copy.deepcopy(records)
    chunks = ai.source_chunks(records, limit)
    assert chunks == legacy_chunks(records, limit)
    assert all(len(chunk) <= limit for chunk in chunks)
    assert records == before


def test_invalid_locator_limit_stops_instead_of_repeatedly_copying_without_progress():
    with pytest.raises(ValueError, match='来源定位'):
        ai.source_chunks([dict(name='n' * 12000, segments=[dict(locator='页码', text='正文')])])


async def wait_until(predicate, task=None):
    async def wait():
        while not predicate():
            if task and task.done(): await task;raise AssertionError('Task ended before the expected boundary')
            await asyncio.sleep(.002)
    await asyncio.wait_for(wait(), 4)


def test_real_image_discovery_and_assembly_run_in_workers_callbacks_stay_on_loop(tmp_path, monkeypatch):
    path = tmp_path / 'frame.png';path.write_bytes(b'actual frame fixture')
    value = dict(id=uid(), name='选定范围', segments=[dict(locator='PDF 文件页 8', text='原始识别文字', meta={'image_path': str(path)})],
                 read_manifest=dict(method='explicit_selected_pages', limitations=[]))
    original = copy.deepcopy(value);threads = [];callbacks = []
    prepare, assemble = ai._prepare_digest_sources, ai._assemble_source_digest
    def prepared(*args):threads.append(threading.get_ident());return prepare(*args)
    def assembled(*args):threads.append(threading.get_ident());return assemble(*args)
    monkeypatch.setattr(ai, '_prepare_digest_sources', prepared);monkeypatch.setattr(ai, '_assemble_source_digest', assembled)
    class Client:
        model = 'native-fixture';effort = 'high'
        async def analyze_image(self, *args): return '画面上可读的公式，作为分析单独标注'
    def callback(*args): callbacks.append((threading.get_ident(), args))
    main = threading.get_ident()
    result, chunks = asyncio.run(ai.source_digest(Client(), [value], callback, True, callback, callback))
    assert threads and all(ident != main for ident in threads)
    assert len(callbacks) == 4 and all(ident == main for ident, _ in callbacks)
    assert '[资料ID:' + value['id'] + ']' in result and '[画面分析]' in result
    assert '未概括、未截断' in result and '不代表已经通读整本原文件' in result
    assert value == original and chunks


def test_cancelled_preparation_holds_single_slot_until_thread_stops_and_never_owns_originals(tmp_path):
    project = create_project('有界准备')['id'];job = create_job(project, 'generate', {})
    path = tmp_path / 'data' / 'original.txt';path.parent.mkdir(exist_ok=True);path.write_text('原文件', encoding='utf-8')
    entered, release = threading.Event(), threading.Event();second_started = threading.Event()
    def first():entered.set();assert release.wait(4);return dict(original_path=str(path))
    def second():second_started.set();return 'other source ready'
    async def run():
        async with scheduling.execution_scope(project_id=project, job_id=job):
            task = asyncio.create_task(scheduling.run_local('source_prepare', first, track_outputs=False))
            other = None
            try:
                await wait_until(entered.is_set, task)
                task.cancel();await asyncio.gather(task, return_exceptions=True)
                assert scheduling.local_work_pending(project)
                other = asyncio.create_task(scheduling.run_local('source_prepare', second, track_outputs=False))
                await asyncio.sleep(.025)
                assert not second_started.is_set() and scheduling.scheduler().snapshot()['source_prepare']['active'] == 1
                async with scheduling.model_slot('fixture'): pass
                release.set()
                assert await asyncio.wait_for(other, 4) == 'other source ready'
                await asyncio.sleep(0)
                assert not scheduling.local_work_pending(project)
            finally:
                release.set()
                if other and not other.done():other.cancel();await asyncio.gather(other, return_exceptions=True)
    asyncio.run(run())
    assert path.read_text(encoding='utf-8') == '原文件'
    assert not many('SELECT * FROM job_file_outputs WHERE job_id=?', (job,))


def test_delayed_database_read_does_not_block_independent_request(tmp_path, monkeypatch):
    project = create_project('响应测试')['id'];ident, _ = source(tmp_path, project)
    entered, release = threading.Event(), threading.Event();real = server.source_records
    def slow(*args, **kwargs):entered.set();assert release.wait(4);return real(*args, **kwargs)
    monkeypatch.setattr(server, 'source_records', slow)
    async def run():
        task = asyncio.create_task(server.source_records_async([ident], project, metadata_only=True))
        try:
            await wait_until(entered.is_set, task)
            # Equivalent to a concurrently dispatched progress/switch request.
            async with scheduling.model_slot('independent'): pass
            assert not task.done()
        finally: release.set()
        return await asyncio.wait_for(task, 4)
    assert asyncio.run(run())[0]['id'] == ident


def test_generation_can_pause_during_full_source_assembly_then_resume_without_loss(tmp_path, monkeypatch):
    from docx import Document
    project = create_project('准备中暂停')['id'];ident, path = source(tmp_path, project)
    entered, release = threading.Event(), threading.Event();calls = [];real = ai._assemble_source_digest
    def assemble(*args):entered.set();assert release.wait(4);return real(*args)
    monkeypatch.setattr(ai, '_assemble_source_digest', assemble)
    class Client:
        model = 'same-model';effort = 'high'
        async def complete(self, system, user):
            calls.append(user)
            assert '完整原文件：必要条件与末尾结论。' in user and '旧预览' not in user
            return '# 前提与结论\n\n完整原文件中的必要条件应先核对。\n\n## 系统性总结\n保留末尾结论。'
    monkeypatch.setattr(server, 'client_for', lambda *a, **kw: Client())
    value = server.GenerateIn(project_id=project, source_ids=[ident], provider='deepseek', format='docx', review_mode='express')
    job = create_job(project, 'generate', value.model_dump())
    async def run():
        task = asyncio.create_task(server._generate_job(job, value))
        control = None
        try:
            await wait_until(entered.is_set, task)
            control = generation_control.active_generations[job];control.pause()
            release.set()
            await wait_until(lambda: one('SELECT status FROM jobs WHERE id=?', (job,))['status'] == 'paused', task)
            assert not calls and not many('SELECT * FROM artifacts WHERE project_id=?', (project,))
            control.resume();await asyncio.wait_for(task, 6)
        finally:
            release.set()
            if control and not task.done():control.resume()
            if not task.done():task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())
    assert one('SELECT status FROM jobs WHERE id=?', (job,))['status'] == 'completed' and len(calls) == 1
    artifact = one('SELECT * FROM artifacts WHERE project_id=?', (project,))
    assert '末尾结论' in '\n'.join(paragraph.text for paragraph in Document(artifact['path']).paragraphs)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == materials.file_sha256(path)
