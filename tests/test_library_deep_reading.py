import asyncio
import hashlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from studyforge import library, library_reading, library_routes, library_worker, server
from studyforge.config import data_dir
from studyforge.db import connect, execute, j, many, now, one, uid, unj
from studyforge.library_ranges import finish_ranges
from test_global_library import chat, scoped_node, setup_book


class Reader:
    model = 'reader-fixture'
    effort = 'none'
    vision_model = 'vision-fixture'
    def __init__(self, calls): self.calls = calls
    async def complete(self, system, user, **kwargs):
        self.calls['text'].append((system, user))
        if self.calls.get('fail_second') and len(self.calls['text']) == 2:
            self.calls['fail_second'] = False
            raise ValueError('one-time failure')
        if '这是重点精读' in system:
            return '## 为什么引入参数\n\n' + ('逐步解释原文的条件和构造动机。' * 150) + '\n\nFINAL_PROOF_CONDITION: divisor must be nonzero.'
        if '阅读路线' in system: return '先理解目标，再看构造。这里只提供导航，不替代完整精读记录。'
        return 'INDEX_ONLY_MARKER：数域的定义与非零除数。[来源：PDF 第 1 页]'
    async def analyze_images(self, frames):
        self.calls['vision'].append([f['id'] for f in frames])
        return {f['id']: '原图观察：除数不能为零，不将观察当作学生能力。' for f in frames}
    async def analyze_image(self, path, locator, ocr_text=''):
        self.calls['vision'].append([locator])
        return '原图观察：除数不能为零。'
    async def close(self): pass


def tracker(): return {'text': [], 'vision': []}


async def read(book, node, calls, **options):
    worker = library_worker.LibraryWorker(lambda payload: Reader(calls))
    job = library_worker.new_read_job(book['id'], [node['id']], 'fixture', 'reader-fixture', 'none', **options)
    worker.launch(job['id']); await worker.tasks[job['id']]
    return library.public_job(one('SELECT * FROM library_jobs WHERE id=?', (job['id'],)))


def test_upgrade_adds_profile_columns_without_resetting_old_table(tmp_path):
    path = data_dir() / 'studyforge.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE library_readings(id TEXT PRIMARY KEY,node_id TEXT,signature TEXT UNIQUE,provider TEXT,model TEXT,effort TEXT,status TEXT,notes TEXT,warnings_json TEXT,created_at TEXT,updated_at TEXT)')
        db.execute('INSERT INTO library_readings VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   ('legacy', 'legacy-node', 'legacy-signature', 'fixture', 'old', 'none', 'completed', 'KEEP_OLD_NOTE', '[]', now(), now()))
    with connect() as db:
        saved = dict(db.execute('SELECT * FROM library_readings WHERE id=?', ('legacy',)).fetchone())
        assert saved['notes'] == 'KEEP_OLD_NOTE' and saved['depth'] == 'index' and saved['focus'] == ''


@pytest.mark.parametrize('options', [{'depth': 'bad'}, {'focus': 'why'}, {'depth': 'deep', 'focus': 'x' * 1201}])
def test_invalid_profile_is_rejected_before_job_creation(tmp_path, options):
    b, _ = setup_book(tmp_path); n = scoped_node(b)
    with pytest.raises(ValueError): library_worker.new_read_job(b['id'], [n['id']], 'fixture', **options)
    assert not many('SELECT * FROM library_jobs')


def test_profile_signatures_keep_legacy_and_distinguish_depth_and_focus(tmp_path):
    b, _ = setup_book(tmp_path); n = library.node(scoped_node(b)['id'])
    old = hashlib.sha256(j([library.version(b, n), 'fixture', 'm', 'none']).encode()).hexdigest()
    assert library.reading_signature(b, n, 'fixture', 'm', 'none') == old
    a = library.reading_signature(b, n, 'fixture', 'm', 'none', 'deep', 'why t?')
    assert a == library.reading_signature(b, n, 'fixture', 'm', 'none', 'deep', '  why t?  ')
    assert a != old and a != library.reading_signature(b, n, 'fixture', 'm', 'none', 'deep', 'why epsilon?')


def test_deep_reads_original_and_keeps_index_as_independent_version(tmp_path):
    b, _ = setup_book(tmp_path); n = scoped_node(b); calls = tracker()
    first = asyncio.run(read(b, n, calls)); assert first['status'] == 'completed'
    old_id = library.ready_reading(library.node(n['id']))['id']
    second = asyncio.run(read(b, n, calls, depth='deep', focus='为何要排除零除数？'))
    assert second['status'] == 'completed', second
    system, source = calls['text'][-1]
    assert '这是重点精读' in system and '为何要排除零除数' in source
    assert 'TOP:' in source and 'BOTTOM:' not in source and 'INDEX_ONLY_MARKER' not in source
    saved = library.ready_reading(library.node(n['id']))
    assert saved['depth'] == 'deep' and saved['id'] != old_id
    assert 'FINAL_PROOF_CONDITION' in saved['notes']
    variants = library.reading_variants(library.node(n['id']))
    assert {v['depth'] for v in variants} == {'deep', 'index'}
    assert one('SELECT notes FROM library_readings WHERE id=?', (old_id,))['notes'].startswith('PDF')
    before = len(calls['text'])
    again = asyncio.run(read(b, n, calls, depth='deep', focus=' 为何要排除零除数？ '))
    assert again['result']['nodes_completed'][0]['cached'] and len(calls['text']) == before
    assert not many('SELECT * FROM learning_events') and not many('SELECT * FROM mastery')


def test_detailed_tail_survives_node_navigation_and_scope_isolated(tmp_path):
    b, _ = setup_book(tmp_path, count=6); n = scoped_node(b, start=2, end=6); calls = tracker()
    job = asyncio.run(read(b, n, calls, depth='deep'))
    assert job['status'] == 'completed', job
    assert len(calls['text']) == 3  # two source batches, one navigation
    # A crop applies only at the first/last page; interior pages are whole.
    assert 'BOTTOM: unrelated section and exercise answers. Page 6.' not in calls['text'][1][1]
    assert 'BOTTOM: unrelated section and exercise answers. Page 3.' in calls['text'][0][1]
    assert 'Page 1.' not in calls['text'][0][1]
    assert calls['text'][-1][1].count('FINAL_PROOF_CONDITION') == 2
    note = library.ready_reading(library.node(n['id']))['notes']
    assert note.count('FINAL_PROOF_CONDITION') == 2 and '## 阅读路线' in note


def test_failed_deep_steps_resume_without_repeating_paid_batches(tmp_path):
    b, _ = setup_book(tmp_path, count=6); n = scoped_node(b, start=1, end=6); calls = tracker(); calls['fail_second'] = True
    async def scenario():
        worker = library_worker.LibraryWorker(lambda payload: Reader(calls))
        job = library_worker.new_read_job(b['id'], [n['id']], 'fixture', 'reader-fixture', 'none', depth='deep', focus='关键条件？')
        worker.launch(job['id']); await worker.tasks[job['id']]
        assert one('SELECT status FROM library_jobs WHERE id=?', (job['id'],))['status'] == 'failed'
        await worker.action(job['id'], 'resume'); worker.launch(job['id']); await worker.tasks[job['id']]
        assert one('SELECT status FROM library_jobs WHERE id=?', (job['id'],))['status'] == 'completed'
    asyncio.run(scenario())
    assert len(calls['text']) == 4  # first, failed second, retried second, navigation
    assert sum('Page 1.' in user for _, user in calls['text']) == 1


def test_index_synthesis_does_not_silently_discard_late_assumptions(tmp_path):
    b, _ = setup_book(tmp_path, count=6); n = scoped_node(b, start=1, end=6); calls = tracker()
    class WithLateConditions(Reader):
        async def complete(self, system, user, **kwargs):
            calls['text'].append((system, user))
            if '汇总这些已完成分页记录' in system: return '最终索引\n\n' + user
            return '短索引需要保留假设。' * 220 + '\nCRITICAL_LATE_CONDITION: denominator is nonzero.'
    async def scenario():
        worker = library_worker.LibraryWorker(lambda payload: WithLateConditions(calls))
        job = library_worker.new_read_job(b['id'], [n['id']], 'fixture')
        worker.launch(job['id']); await worker.tasks[job['id']]
        assert one('SELECT status FROM library_jobs WHERE id=?', (job['id'],))['status'] == 'completed'
    asyncio.run(scenario())
    assert calls['text'][-1][1].count('CRITICAL_LATE_CONDITION') == 2
    assert library.ready_reading(library.node(n['id']))['notes'].count('CRITICAL_LATE_CONDITION') == 2


def test_long_deep_notes_remain_complete_without_claiming_full_synthesis(tmp_path):
    b, _ = setup_book(tmp_path, count=6); n = scoped_node(b, start=1, end=6); calls = tracker()
    class LongReader(Reader):
        async def complete(self, system, user, **kwargs):
            calls['text'].append((system, user))
            return '完整分页论证与适用条件。' * 2400 + '\nIMPORTANT_END_OF_PROOF'
    async def scenario():
        worker = library_worker.LibraryWorker(lambda payload: LongReader(calls))
        job = library_worker.new_read_job(b['id'], [n['id']], 'fixture', depth='deep')
        worker.launch(job['id']); await worker.tasks[job['id']]
        return library.public_job(one('SELECT * FROM library_jobs WHERE id=?', (job['id'],)))
    result = asyncio.run(scenario())
    assert result['status'] == 'completed' and len(calls['text']) == 2
    saved = library.ready_reading(library.node(n['id']))
    assert saved['notes'].count('IMPORTANT_END_OF_PROOF') == 2
    assert any('没有执行全篇统一' in warning for warning in unj(saved['warnings_json'], []))


def mark_scanned(monkeypatch):
    original = library.extract_page
    def extract(*args, **kwargs): return original(*args, **kwargs) | {'scanned': True}
    monkeypatch.setattr(library, 'extract_page', extract)


def test_visual_observation_reused_by_deep_reading_and_invalidated_by_vision_model(tmp_path, monkeypatch):
    b, _ = setup_book(tmp_path, count=2); n = scoped_node(b, start=1, end=2); calls = tracker(); mark_scanned(monkeypatch)
    assert asyncio.run(read(b, n, calls))['status'] == 'completed'
    assert len(calls['vision']) == 1
    deep = asyncio.run(read(b, n, calls, depth='deep', focus='为什么需要封闭性？'))
    assert deep['status'] == 'completed' and deep['result']['nodes_completed'][0]['visual_pages_reused'] == 2
    assert len(calls['vision']) == 1
    monkeypatch.setattr(Reader, 'vision_model', 'different-vision')
    assert asyncio.run(read(b, n, calls, depth='deep', focus='新问题'))['status'] == 'completed'
    assert len(calls['vision']) == 2


def test_empty_visual_is_warned_and_not_cached(tmp_path, monkeypatch):
    b, _ = setup_book(tmp_path); n = scoped_node(b); calls = tracker(); mark_scanned(monkeypatch)
    async def empty(*args, **kwargs): return ''
    monkeypatch.setattr(Reader, 'analyze_image', empty)
    result = asyncio.run(read(b, n, calls, depth='deep'))
    assert result['status'] == 'completed'  # OCR text remains; uncertainty is explicit
    assert any('没有有效图像核对记录' in w for w in result['result']['nodes_completed'][0]['warnings'])
    assert 'OCR 公式、符号及条件不能视为已确认' in calls['text'][0][1]
    assert not many('SELECT * FROM library_page_observations')


def test_force_refresh_does_not_reuse_visual_or_notes(tmp_path, monkeypatch):
    b, _ = setup_book(tmp_path); n = scoped_node(b); calls = tracker(); mark_scanned(monkeypatch)
    asyncio.run(read(b, n, calls, depth='deep'))
    before = len(calls['text'])
    result = asyncio.run(read(b, n, calls, depth='deep', force=True))
    assert result['status'] == 'completed' and not result['result']['nodes_completed'][0]['cached']
    assert len(calls['vision']) == 2 and len(calls['text']) == before + 1


def test_explicit_note_version_cannot_cross_node_or_outdated_scope(tmp_path):
    b, _ = setup_book(tmp_path); n = scoped_node(b); calls = tracker()
    asyncio.run(read(b, n, calls)); old_id = library.ready_reading(library.node(n['id']))['id']
    asyncio.run(read(b, n, calls, depth='deep', focus='why?'))
    other = scoped_node(b, start=2, end=2)
    with TestClient(server.app) as client:
        response = client.get('/api/library/nodes/' + n['id'] + '/notes', params={'reading_id': old_id})
        assert response.status_code == 200 and response.json()['reading']['depth'] == 'index'
        assert len(response.json()['versions']) == 2
        assert client.get('/api/library/nodes/' + n['id'] + '/notes', params={'depth': 'index'}).json()['reading']['id'] == old_id
        assert client.get('/api/library/nodes/' + n['id'] + '/notes', params={'depth': 'deep', 'focus': ' why? '}).json()['reading']['focus'] == 'why?'
        assert client.get('/api/library/nodes/' + other['id'] + '/notes', params={'reading_id': old_id}).status_code == 400
        library.update_node(n['id'], {'end_y': .4, 'confirmed': True})
        assert client.get('/api/library/nodes/' + n['id'] + '/notes', params={'reading_id': old_id}).status_code == 400


def test_deep_only_node_remains_searchable_and_referenceable_across_projects(tmp_path):
    b, _ = setup_book(tmp_path); n = scoped_node(b); calls = tracker()
    assert asyncio.run(read(b, n, calls, depth='deep'))['status'] == 'completed'
    assert library.details(b['id'])['nodes'][0]['reading']['depth'] == 'deep'
    assert library_routes.notes(n['id'], depth='index', focus='')['reading']['depth'] == 'deep'
    assert library.directory_suggestions('数域')['nodes'][0]['state'] == 'read'
    p, a = chat(); q, c = chat()
    for project, conversation in [(p, a), (q, c)]:
        assert library.add_reference(conversation, project['id'], n['id'], 'primary')['references'][0]['node_id'] == n['id']
        snapshot = library.reference_snapshot(conversation, project['id'], '数域')
        records = library.generation_records(snapshot)
        assert 'TOP:' in records[0]['segments'][0]['text']


def test_range_handoff_preserves_deep_profile_and_origin(tmp_path):
    b, _ = setup_book(tmp_path); n = scoped_node(b)
    origin = library_worker.create_job(b['id'], 'ranges', {})
    saved = {'output': {'pending_node_ids': []}, 'versions': {n['id']: library.version(b, library.node(n['id']))}}
    payload = {'node_ids': [n['id']], 'provider': 'fixture', 'read_after': True, 'depth': 'deep', 'focus': '构造动机？', 'foreground': True, 'parallel': True}
    control = library_worker.LibraryControl(origin['id'])
    result = finish_ranges(control, b, payload, saved)
    job = library.public_job(one('SELECT * FROM library_jobs WHERE id=?', (result['read_job_id'],)))
    assert job['payload']['depth'] == 'deep' and job['payload']['focus'] == '构造动机？'
    assert job['payload']['foreground'] and job['payload']['parallel'] and job['payload']['origin_job_id'] == origin['id']
    assert finish_ranges(control, b, payload, saved)['read_job_id'] == job['id']


def test_api_depth_choices_and_focus_limits_are_explicit():
    assert library_routes.ReadIn(node_ids=['a'], provider='fixture').depth == 'index'
    assert library_routes.RangesIn(node_ids=['a'], depth='deep', focus='动机').focus == '动机'
    with pytest.raises(ValueError): library_routes.ReadIn(node_ids=['a'], provider='fixture', depth='fake')
    with pytest.raises(ValueError): library_routes.ReadIn(node_ids=['a'], provider='fixture', depth='deep', focus='x' * 1201)
