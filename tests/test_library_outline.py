import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import threading

import pytest
from fastapi.testclient import TestClient

from studyforge import library, library_outline as outline, library_worker, server
from studyforge.db import connect, execute, many, one, unj
from studyforge.mobile_access import allowed
from test_global_library import Client, chat, ready, scoped_node, setup_book, tracker


def move(b, n, parent=None, before=None, revision=None):
    return outline.move(b['id'], n['id'], parent['id'] if parent else None,
                        before['id'] if before else None, revision or library.details(b['id'])['outline_revision'])


def ids(b):
    return [n['id'] for n in library.details(b['id'])['nodes']]


def tree(tmp_path):
    b, _ = setup_book(tmp_path, count=6)
    a = scoped_node(b, '第一章', 1, 3)
    x = scoped_node(b, '第一节', parent_id=a['id'])
    z = scoped_node(b, '第一节下的证明', parent_id=x['id'])
    y = scoped_node(b, '第二节', 2, 2, parent_id=a['id'])
    c = scoped_node(b, '第二章', 4, 6)
    d = scoped_node(b, '第三章', 6, 6)
    return b, a, x, z, y, c, d


def test_new_nested_node_is_inserted_in_parent_subtree(tmp_path):
    b, a, x, z, y, c, d = tree(tmp_path)
    inserted = library.add_node(b['id'], '后补的第一章小节', a['id'])
    nested = library.add_node(b['id'], '后补的证明步骤', x['id'])
    assert ids(b) == [a['id'], x['id'], z['id'], nested['id'], y['id'], inserted['id'], c['id'], d['id']]
    assert library.node(inserted['id'])['parent_id'] == a['id']
    assert inserted['state'] == 'range_pending'


def test_whole_subtree_reorders_and_can_undo_without_touching_scopes(tmp_path):
    b, a, x, z, y, c, d = tree(tmp_path)
    original = many('SELECT * FROM library_nodes ORDER BY id')
    first = move(b, a, before=d)
    assert ids(b) == [c['id'], a['id'], x['id'], z['id'], y['id'], d['id']]
    for old in original:
        new = library.node(old['id'])
        for field in ('id', 'book_id', 'title', 'printed_page', 'start_page', 'end_page',
                      'start_y', 'end_y', 'confirmed', 'provenance_json'):
            assert new[field] == old[field]
    undo = first['undo']
    outline.move(b['id'], undo['node_id'], undo['parent_id'], undo['before_id'], first['revision'])
    assert ids(b) == [a['id'], x['id'], z['id'], y['id'], c['id'], d['id']]


def test_reparent_promote_and_noop(tmp_path):
    b, a, x, z, y, c, d = tree(tmp_path)
    move(b, x, parent=c)
    assert ids(b) == [a['id'], y['id'], c['id'], x['id'], z['id'], d['id']]
    assert library.node(x['id'])['parent_id'] == c['id']
    assert library.node(z['id'])['parent_id'] == x['id']
    move(b, x, before=a)
    assert library.node(x['id'])['kind'] == 'chapter'
    assert library.node(z['id'])['kind'] == 'section'
    old = library.details(b['id'])
    assert move(b, x, before=a)['changed'] == 0
    assert library.details(b['id']) == old


@pytest.mark.parametrize('bad', ['self', 'descendant', 'foreign_parent', 'foreign_node', 'wrong_sibling', 'self_before'])
def test_invalid_moves_leave_directory_unchanged(tmp_path, bad):
    b, a, x, z, y, c, d = tree(tmp_path)
    other, _ = setup_book(tmp_path, count=7)
    foreign = scoped_node(other, '另一本书的章')
    old = library.details(b['id'])
    cases = {'self': (a, a, None), 'descendant': (a, z, None),
             'foreign_parent': (a, foreign, None), 'foreign_node': (foreign, None, None),
             'wrong_sibling': (y, c, x), 'self_before': (a, None, a)}
    n, parent, before = cases[bad]
    with pytest.raises(ValueError): move(b, n, parent, before)
    assert library.details(b['id']) == old


def test_concurrent_edits_use_revision_instead_of_overwriting(tmp_path):
    b, a, x, z, y, c, d = tree(tmp_path)
    initial = library.details(b['id'])['outline_revision']; barrier = threading.Barrier(2)
    def change(n, parent):
        barrier.wait()
        try: return move(b, n, parent, revision=initial)
        except outline.OutlineConflict: return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(change, x, c), pool.submit(change, y, d)]
        results = [f.result() for f in pending]
    assert results.count('conflict') == 1
    assert sum(library.node(n['id'])['parent_id'] == p['id'] for n, p in [(x, c), (y, d)]) == 1
    assert len(set(ids(b))) == 6


def test_database_failure_rolls_back_all_positions(tmp_path, monkeypatch):
    b, a, x, z, y, c, d = tree(tmp_path)
    old = library.details(b['id']); real_connect = connect
    class Broken:
        def __init__(self, db): self.db = db
        def execute(self, *args): return self.db.execute(*args)
        def executemany(self, sql, values):
            self.db.execute(sql, list(values)[0])
            raise RuntimeError('interrupted write')
    @contextmanager
    def broken():
        with real_connect() as db: yield Broken(db)
    monkeypatch.setattr(outline, 'connect', broken)
    with pytest.raises(RuntimeError, match='interrupted'): move(b, a, before=d)
    assert library.details(b['id']) == old


def test_reading_results_and_chat_references_survive_reparent(tmp_path):
    b, n, _ = ready(tmp_path)
    parent = scoped_node(b, '组织用的新章', 2, 2)
    p, conversation = chat()
    library.set_preferences(conversation, p['id'], 'manual', [{'node_id': n['id'], 'purpose': 'reference'}])
    snapshot = library.reference_snapshot(conversation, p['id'], '数域')
    old_reading = library.ready_reading(n)
    old_records = library.generation_records(snapshot)
    move(b, n, parent=parent)
    current = library.node(n['id'])
    assert library.ready_reading(current) == old_reading
    assert library.version(b, current) == library.version(b, n)
    assert library.generation_records(snapshot) == old_records
    assert library.preferences(conversation, p['id'])['references'][0]['node_id'] == n['id']
    assert library.details(b['id'])['nodes'][-1]['state'] == 'read'


@pytest.mark.parametrize('child_start,child_end,child_y,expect_two', [(2, 2, .5, True), (1, 1, .8, True), (1, 1, .3, False)])
def test_selected_child_is_skipped_only_when_parent_covers_its_scope(tmp_path, child_start, child_end, child_y, expect_two):
    b, _ = setup_book(tmp_path)
    parent = scoped_node(b, '父节点', 1, 1)
    child = scoped_node(b, '子节点', child_start, child_end, end_y=child_y, parent_id=parent['id'])
    result = library.normalize_nodes(b['id'], [parent['id'], child['id']])
    assert [n['id'] for n in result] == ([parent['id'], child['id']] if expect_two else [parent['id']])


@pytest.mark.parametrize('status', ['queued', 'paused'])
def test_scheduled_job_retains_original_ids_order_and_ranges(tmp_path, status):
    b, _ = setup_book(tmp_path)
    a = scoped_node(b, '原先第一节点', 1, 2)
    c = scoped_node(b, '原先第二节点', 2, 2)
    job = library_worker.new_read_job(b['id'], [a['id'], c['id']], 'fixture', 'fixture', 'none')
    execute('UPDATE library_jobs SET status=? WHERE id=?', (status, job['id']))
    move(b, c, parent=a)
    # New selections deduplicate by coverage; the submitted job retains both.
    assert len(library.normalize_nodes(b['id'], [a['id'], c['id']])) == 1
    assert unj(one('SELECT payload_json FROM library_jobs WHERE id=?', (job['id'],))['payload_json']) == job['payload']
    t = tracker()
    async def run():
        worker = library_worker.LibraryWorker(lambda payload: Client(t))
        if status == 'paused': await worker.action(job['id'], 'resume')
        worker.launch(job['id']); await asyncio.wait_for(worker.tasks[job['id']], 15)
    asyncio.run(run())
    result = library.public_job(one('SELECT * FROM library_jobs WHERE id=?', (job['id'],)))
    assert result['status'] == 'completed', result
    assert [n['node_id'] for n in result['result']['nodes_completed']] == [a['id'], c['id']]
    assert result['payload']['scopes'] == job['payload']['scopes']
    chunks = many('SELECT page,original_text FROM library_chunks')
    assert {part['page'] for part in chunks} == {1, 2}
    # The first page of the two-page parent is authorized in full; only the
    # last page is cropped. Reparenting must preserve that distinction.
    assert all('BOTTOM:' not in part['original_text'] for part in chunks if part['page'] == 2)


def test_running_job_retains_order_when_unstarted_nodes_move(tmp_path):
    b, _ = setup_book(tmp_path)
    a = scoped_node(b, '开始读取的节点', 1, 2)
    c = scoped_node(b, '原先第二节点', 2, 2)
    d = scoped_node(b, '原先第三节点', 3, 3)
    job = library_worker.new_read_job(b['id'], [a['id'], c['id'], d['id']], 'fixture', 'fixture', 'none')
    async def run():
        t = tracker(); t['started'] = asyncio.Event(); t['release'] = asyncio.Event()
        worker = library_worker.LibraryWorker(lambda payload: Client(t))
        worker.launch(job['id'])
        try:
            await asyncio.wait_for(t['started'].wait(), 15)
            assert one('SELECT status FROM library_jobs WHERE id=?', (job['id'],))['status'] == 'running'
            move(b, d, before=a)
            move(b, c, parent=a)
            t['release'].set()
            await asyncio.wait_for(worker.tasks[job['id']], 15)
        finally:
            t['release'].set(); await worker.close()
    asyncio.run(run())
    result = library.public_job(one('SELECT * FROM library_jobs WHERE id=?', (job['id'],)))
    assert result['status'] == 'completed', result
    assert [n['node_id'] for n in result['result']['nodes_completed']] == [a['id'], c['id'], d['id']]
    assert result['payload'] == job['payload']


def test_move_api_revision_validation_and_mobile_allowlist(tmp_path):
    b, a, x, z, y, c, d = tree(tmp_path)
    path = f"/api/library/books/{b['id']}/outline/move"
    payload = {'node_id': x['id'], 'parent_id': c['id'], 'before_id': None,
               'revision': library.details(b['id'])['outline_revision']}
    with TestClient(server.app) as client:
        response = client.post(path, json=payload)
        assert response.status_code == 200, response.text
        assert response.json()['changed'] > 0
        assert client.post(path, json=payload).status_code == 409
        assert client.post(path, json=payload | {'revision': response.json()['revision'], 'parent_id': z['id']}).status_code == 400
        assert client.post(path, json=payload | {'start_page': 5}).status_code == 422
        assert client.post(path, json=payload | {'revision': 'bad'}).status_code == 422
    assert allowed('POST', path)
    assert not allowed('DELETE', path)
    assert not allowed('POST', '/api/library/books/not-an-id/outline/move')
