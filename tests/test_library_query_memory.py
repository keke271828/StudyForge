"""Large saved notes must not leak into status, stale scope, or ranking state."""
from contextlib import contextmanager
import asyncio
import sqlite3

import pytest

from studyforge import library, library_semantic as semantic
from studyforge.db import connect, execute, now, uid
from test_library_retrieval import book, reading


def add_version(b, n, *, model, notes, valid=True, completed=True, updated='2099-01-01T00:00:00+00:00'):
    ident = uid()
    signature = library.reading_signature(b, n, 'fixture', model, 'none') if valid else 'obsolete-' + ident
    execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?)',
            (ident, n['id'], signature, 'fixture', model, 'none', 'completed' if completed else 'reading', notes, now(), updated))
    return ident


@contextmanager
def no_note_body_reads(monkeypatch, statements=None):
    """Use SQLite's real column authorizer rather than matching Python mocks."""
    original = library.connect
    @contextmanager
    def guarded():
        with original() as db:
            def permit(action, table, column, *rest):
                return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and table == 'library_readings' and column == 'notes' else sqlite3.SQLITE_OK
            db.set_authorizer(permit)
            if statements is not None: db.set_trace_callback(statements.append)
            yield db
    with monkeypatch.context() as patch:
        patch.setattr(library, 'connect', guarded)
        yield


def test_directory_batches_states_without_reading_note_bodies(tmp_path, monkeypatch):
    b = book(tmp_path)
    states = {}
    for i in range(14):
        n, current = reading(b, f'目录 {i}', {1: 'Original'}, notes='保存的完整笔记。' * 20000)
        add_version(b, n, model=f'stale-{i}', notes='错误范围的历史笔记' * 20000, valid=False)
        if i % 3 == 0:
            library.update_node(n['id'], {'confirmed': False})
            states[n['id']] = ('range_pending', None)
        elif i % 3 == 1:
            library.update_node(n['id'], {'start_page': 2, 'end_page': 2, 'confirmed': True})
            states[n['id']] = ('unread', None)
        else: states[n['id']] = ('read', current)
    statements = []
    with no_note_body_reads(monkeypatch, statements):
        result = library.details(b['id'])
    assert {n['id']: (n['state'], (n['reading'] or {}).get('id')) for n in result['nodes']} == states
    # Any number of nodes needs only one metadata query, rather than one
    # connection/query per node on every front-end refresh.
    selects = [s for s in statements if s.startswith('SELECT') and 'FROM library_readings' in s]
    assert len(selects) == 1


def test_latest_metadata_and_explicit_body_have_same_selection(tmp_path, monkeypatch):
    b = book(tmp_path)
    n, old = reading(b, '所选', {1: 'body'}, notes='older_note_marker')
    body = '完整有效笔记\n' * 20000 + 'current_tail_marker'
    current = add_version(b, n, model='current', notes=body)
    add_version(b, n, model='stale', notes='stale_note_marker', valid=False, updated='2099-02-01')
    add_version(b, n, model='interrupted', notes='not_completed_marker', completed=False, updated='2099-03-01')
    other, _ = reading(b, '未选', {2: 'another body'}, notes='outside_scope_marker' * 20000)
    with no_note_body_reads(monkeypatch):
        _, nodes, latest = library.eligible_readings([n['id']], metadata_only=True)
        meta = library.ready_reading(n, b, metadata_only=True)
        assert meta['id'] == current and 'notes' not in meta
        assert [item['id'] for item in nodes] == [n['id']]
        assert set(latest) == {n['id']} and latest[n['id']]['id'] == current
        assert 'notes' not in latest[n['id']]
    assert library.ready_reading(n, b)['notes'] == body
    full = library.eligible_readings([n['id']])[2][n['id']]
    assert full['id'] == current and full['notes'] == body and full['status'] == 'completed'
    assert not library.search('older_note_marker', node_ids=[n['id']], mode='keyword')
    assert not library.search('stale_note_marker', node_ids=[n['id']], mode='keyword')
    assert not library.search('outside_scope_marker', node_ids=[n['id']], mode='keyword')
    assert library.search('current_tail_marker', node_ids=[n['id']], mode='keyword')[0]['node_id'] == n['id']


def test_equal_timestamp_uses_same_rowid_tiebreak_for_all_paths(tmp_path):
    b = book(tmp_path)
    n, _ = reading(b, '小节', {1: 'original'})
    first = add_version(b, n, model='first', notes='first_marker')
    second = add_version(b, n, model='second', notes='second_marker')
    assert first != second
    assert library.ready_reading(n, b)['id'] == second
    assert library.eligible_readings(metadata_only=True)[2][n['id']]['id'] == second
    assert library.details(b['id'])['nodes'][0]['reading']['id'] == second
    assert library.search('second_marker')[0]['node_id'] == n['id']
    assert not library.search('first_marker')


def test_notes_are_fully_scored_without_changing_lexical_ranking(tmp_path):
    b = book(tmp_path)
    weak, weak_id = reading(b, '目录甲', {1: 'needle_marker'}, notes='needle_marker')
    strong, strong_id = reading(b, '目录乙', {2: 'body'}, notes='无关的前置整理\n' * 25000 + 'needle_marker needle_marker needle_marker')
    terms = library.terms('needle_marker')
    scores = library.note_matches(terms, library.eligible_readings(metadata_only=True)[2])
    assert scores[weak_id] == len('needle_marker') ** 2
    assert scores[strong_id] == 3 * len('needle_marker') ** 2
    result = library.search('needle_marker', mode='keyword')
    assert [n['node_id'] for n in result] == [strong['id'], weak['id']]
    assert result[0]['lexical_score'] == scores[strong_id]
    assert result[1]['lexical_score'] == scores[weak_id] + len('needle_marker') ** 2
    # Rewriting a note immediately affects retrieval; no stale in-memory cache.
    execute('UPDATE library_readings SET notes=? WHERE id=?', ('replacement_marker', strong_id))
    assert [n['node_id'] for n in library.search('needle_marker', mode='keyword')] == [weak['id']]


def test_semantic_status_and_index_do_not_read_any_navigation_notes(tmp_path, monkeypatch):
    import numpy as np
    b = book(tmp_path)
    n, ident = reading(b, '目录', {1: 'original needle'}, notes='不需要传给向量模型的笔记。' * 20000)
    monkeypatch.setattr(semantic, 'model_ready', lambda: True)
    class Encoder:
        def passages(self, row): return [('original', 0, len(row['original_text']), row['original_text'])]
        def encode(self, texts, query=False): return np.asarray([[1, 0] for _ in texts], dtype='<f4')
    monkeypatch.setattr(semantic, 'encoder', lambda: Encoder())
    semantic.set_enabled(True)
    with no_note_body_reads(monkeypatch):
        assert semantic.eligible()[n['id']]['id'] == ident
        assert semantic.status()['total_pages'] == 1
        assert semantic.index_step()
        assert not semantic.index_step()
        assert semantic.status()['indexed_pages'] == 1


def test_reference_preferences_are_metadata_only(tmp_path, monkeypatch):
    from test_global_library import chat
    b = book(tmp_path)
    n, _ = reading(b, '引用小节', {1: 'original'}, notes='大段阅读记录\n' * 20000)
    p, c = chat()
    library.set_preferences(c, p['id'], 'manual', [{'node_id': n['id'], 'purpose': 'reference'}])
    with no_note_body_reads(monkeypatch):
        preference = library.preferences(c, p['id'])
    assert preference['references'][0]['state'] == 'read'


@pytest.mark.parametrize('allowed', [[], ['missing-node-id']])
def test_empty_allowed_scope_stays_empty_without_body_reads(tmp_path, monkeypatch, allowed):
    b = book(tmp_path)
    reading(b, '其他节点', {1: 'needle_marker'}, notes='needle_marker' * 20000)
    with no_note_body_reads(monkeypatch):
        assert library.eligible_readings(allowed, metadata_only=True)[2] == {}
        assert library.search('needle_marker', node_ids=allowed, mode='keyword') == []


def test_deleted_book_drops_state_and_does_not_leave_query_cache(tmp_path):
    b = book(tmp_path)
    n, _ = reading(b, '删除的书', {1: 'needle_marker'}, notes='needle_marker' * 20000)
    assert library.search('needle_marker')
    library.delete_book(b['id'])
    assert not library.search('needle_marker') and not semantic.eligible()
    with pytest.raises(ValueError, match='不存在'): library.details(b['id'])


def original_text(b, n, pages):
    return '\n\n'.join('[来源：'+b['title']+'｜'+n['title']+f'｜PDF 第 {page} 页]\n原页 OCR：\n'+raw+
                       '\n图像核对记录（AI 读取，非原文引语）：\n'+visual for page, raw, visual in pages)


def test_full_and_page_windows_keep_exact_unicode_offsets_and_boundaries(tmp_path):
    b = book(tmp_path)
    pages = [(1, '第一行🙂 e\u0301\n' * 100 + 'A\x00B\x01C\n', '核对甲🙂'),
             (2, 'PAGE_TWO: 第二页有不同的推理。\n' * 120, ''),
             (3, '', '仅有图像核对记录；不能标为原文引语。\n' * 80)]
    n, ident = reading(b, 'π 与边界', {p: raw for p, raw, _ in pages})
    for page, _, visual in pages:
        execute('UPDATE library_chunks SET visual_text=? WHERE reading_id=? AND page=?', (visual, ident, page))
    for scope in (None, 1, 2, 3):
        original = original_text(b, n, pages if scope is None else [item for item in pages if item[0] == scope])
        cuts = [0, 1, 30, 450, max(0, len(original)-50), len(original), len(original)+1]
        cuts += [original.index('\x00')] if '\x00' in original else []
        for offset in cuts:
            for cap in (100, 12000):
                result = library.read_text_window(ident, b['title'], n['title'], page=scope, offset=offset, limit=cap)
                assert result['text'] == original[offset:offset+cap]
                assert result['next_offset'] == (offset+cap if len(original)>offset+cap else None)
                assert result['page_count'] == (3 if scope is None else 1)
    with pytest.raises(PermissionError): library.read_text_window(ident, b['title'], n['title'], page=9)


def test_page_specific_window_does_not_materialize_other_page_text(tmp_path, monkeypatch):
    b = book(tmp_path)
    n, ident = reading(b, '大章节', {1: 'OFF_PAGE_A:'+'无关正文。'*50000,
                                   2: 'REQUESTED_PAGE: 定义与条件。',
                                   3: 'OFF_PAGE_C:'+'无关正文。'*50000}, notes='不需要的笔记。'*20000)
    seen = []
    original = library.connect
    class Probe:
        def __init__(self, db): self.db=db
        def __getattr__(self, key): return getattr(self.db,key)
        def create_function(self, name, size, function, **kwargs):
            def wrapped(*args):
                if args and isinstance(args[0],str): seen.append(args[0][:30])
                return function(*args)
            return self.db.create_function(name,size,wrapped,**kwargs)
    @contextmanager
    def checked():
        with original() as db: yield Probe(db)
    monkeypatch.setattr(library,'connect',checked)
    result = library.read_text_window(ident,b['title'],n['title'],page=2,limit=100)
    assert 'REQUESTED_PAGE' in result['text'] and result['page_count']==1
    assert seen and not any('OFF_PAGE_' in value for value in seen)


def test_agent_uses_bounded_window_without_loading_notes_or_chapter(tmp_path, monkeypatch):
    from studyforge.agent_tools import AgentRuntime, ReadLibrary
    from test_global_library import chat
    b = book(tmp_path)
    pages = [(1,'原页第一部分。'*300,'图像核对一'),(2,'PAGE_TWO: 请求的原文。'*200,'图像核对二')]
    n, ident = reading(b,'所选节点',{p:raw for p,raw,_ in pages},notes='巨大的阅读笔记。'*20000)
    for page,_,visual in pages:
        execute('UPDATE library_chunks SET visual_text=? WHERE reading_id=? AND page=?',(visual,ident,page))
    p,c = chat()
    library.set_preferences(c,p['id'],'manual',[{'node_id':n['id'],'purpose':'reference'}])
    runtime=AgentRuntime(p['id'],conversation_id=c,provider='deepseek',model='fixture')
    monkeypatch.setattr('studyforge.agent_tools.many',lambda *a,**k:pytest.fail('不要把整章读入列表再截取'))
    async def scenario():
        with no_note_body_reads(monkeypatch):
            for scope in (None,2):
                expected=original_text(b,n,pages if scope is None else [pages[1]])
                for offset in (0,130,len(expected)-100,len(expected)+10):
                    answer=await runtime.sf_read_library_node(ReadLibrary(node_id=n['id'],page=scope,offset=offset,limit=100))
                    assert answer['text']==expected[offset:offset+100]
                    assert answer['next_offset']==(offset+100 if len(expected)>offset+100 else None)
            with pytest.raises(PermissionError):
                await runtime.sf_read_library_node(ReadLibrary(node_id=n['id'],page=3))
            with pytest.raises(ValueError,match='指定一个'):
                await runtime.sf_read_library_node(ReadLibrary(node_id=n['id'],verify_image=True))
        # Whole-source fingerprint checks are retained alongside pagination.
        from pathlib import Path
        Path(b['original_path']).write_bytes(b'changed')
        with pytest.raises(ValueError,match='已变更'):
            await runtime.sf_read_library_node(ReadLibrary(node_id=n['id'],page=2))
    asyncio.run(scenario())


def test_agent_slow_local_window_does_not_block_event_loop(tmp_path, monkeypatch):
    import threading
    b = book(tmp_path)
    n, _ = reading(b,'所选节点',{1:'original'})
    from studyforge.agent_tools import AgentRuntime, ReadLibrary
    from test_global_library import chat
    p,c = chat();library.set_preferences(c,p['id'],'manual',[{'node_id':n['id'],'purpose':'reference'}])
    runtime=AgentRuntime(p['id'],conversation_id=c,provider='deepseek',model='fixture')
    entered=threading.Event();release=threading.Event();native=library.read_text_window
    def slow(*args,**kwargs):
        entered.set()
        assert release.wait(3)
        return native(*args,**kwargs)
    monkeypatch.setattr(library,'read_text_window',slow)
    async def scenario():
        task=asyncio.create_task(runtime.sf_read_library_node(ReadLibrary(node_id=n['id'])))
        try:
            for _ in range(100):
                if entered.is_set():break
                await asyncio.sleep(.005)
            assert entered.is_set() and not task.done()
            await asyncio.sleep(.02)
            assert not task.done()
        finally:release.set();await task
    asyncio.run(scenario())


def test_agent_image_recheck_uses_only_requested_original_page_and_checks_cache(tmp_path, monkeypatch):
    from PIL import Image
    from studyforge.agent_tools import AgentRuntime,ReadLibrary
    from test_global_library import chat
    b=book(tmp_path)
    n,ident=reading(b,'图像核对节点',{1:'PAGE_ONE_ORIGINAL',2:'PAGE_TWO_ORIGINAL'})
    images={}
    for page in (1,2):
        path=tmp_path/f'page-{page}.png';Image.new('RGB',(80,120),(page*40,100,140)).save(path)
        images[page]=path
        execute('UPDATE library_chunks SET image_path=?,image_sha256=? WHERE reading_id=? AND page=?',
                (str(path),library.file_sha256(path),ident,page))
    p,c=chat();library.set_preferences(c,p['id'],'manual',[{'node_id':n['id'],'purpose':'reference'}])
    runtime=AgentRuntime(p['id'],conversation_id=c,provider='deepseek',model='fixture')
    calls=[];closed=[]
    class Client:
        async def analyze_image(self,path,locator,ocr):
            calls.append((path,locator,ocr));return '按原图核对的记录，不能当作原文引语。'
        async def close(self):closed.append(True)
    monkeypatch.setattr('studyforge.library_worker.default_client',lambda payload:Client())
    async def scenario():
        args=ReadLibrary(node_id=n['id'],page=2,verify_image=True,offset=10,limit=100)
        answer=await runtime.sf_read_library_node(args)
        assert '原图核对' in answer['verification'] and len(calls)==1 and closed==[True]
        assert calls[0][0]==images[2] and 'PDF 第 2 页' in calls[0][1] and calls[0][2]=='PAGE_TWO_ORIGINAL'
        images[2].write_bytes(b'changed image cache')
        with pytest.raises(ValueError,match='缓存已改变'):await runtime.sf_read_library_node(args)
        assert len(calls)==1
        execute('UPDATE library_chunks SET image_path=NULL WHERE reading_id=? AND page=?',(ident,2))
        with pytest.raises(ValueError,match='缓存已改变'):await runtime.sf_read_library_node(args)
        assert len(calls)==1
    asyncio.run(scenario())
