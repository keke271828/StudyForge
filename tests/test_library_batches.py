"""Bulk selection must change execution, preserve boundaries and survive restart."""
import asyncio
from collections import Counter

import fitz
import pytest
from pydantic import ValidationError

from studyforge import library, library_batches as batches, library_ranges as ranges, library_worker as worker
from studyforge.db import execute, j, many, one, uid, unj
from studyforge.library_range_review import confirm
from studyforge.library_routes import ReadIn, RangesIn, ConfirmRangesIn
from studyforge.scheduling import model_slot


def bulk_book(tmp_path, count=316, confirmed=False):
    path=tmp_path/'bulk.pdf'
    with fitz.open() as doc:
        for number in range(1,count+1):
            page=doc.new_page()
            page.insert_text((50,110),f'Section {number:04d} Knowledge')
            page.insert_text((50,180),'Original definition, assumptions and a short derivation. Not learner evidence.')
            page.insert_text((280,805),str(number))
        doc.save(path)
    book=library.import_book(path,'316节点教材.pdf')['book']
    library.save_outline(book['id'],[{'id':uid(),'title':f'Section {number:04d} Knowledge',
        'kind':'section','parent_id':None,'printed_page':number,'start_page':number,
        'provenance':{'method':'test_native_pdf'}} for number in range(1,count+1)])
    if confirmed:
        execute('UPDATE library_nodes SET end_page=start_page,end_y=1,confirmed=1 WHERE book_id=?',(book['id'],))
    return library.book(book['id']),many('SELECT * FROM library_nodes WHERE book_id=? ORDER BY position,id',(book['id'],))


def fake_extract(book,node,page):
    # Keep real read_one, step storage, scheduler and reading writes, without
    # allocating 316 page images in every scheduling test.
    return {'page':page,'scanned':False,'image_path':'unused-fixture.png','image_sha256':f'page-{page}',
            'locator':f'PDF 第 {page} 页','original_text':'Original definition and necessary conditions.'}


class Model:
    model='fixture';effort='none'
    def __init__(self, track):self.track=track
    async def complete(self,system,user,**kwargs):
        number=int(user.split('节点：Section ')[1][:4]);t=self.track
        async with model_slot('fixture'):
            t['calls'].append(number);t['active']+=1;t['peak']=max(t['peak'],t['active'])
            try:
                if number==t.get('gate_number'):
                    t['started'].set();await t['release'].wait()
                await asyncio.sleep(.001)
                if number==t.get('fail_number'):
                    t['fail_number']=None;raise ValueError('fixture interrupted node')
                return f'本节点定义、条件、构造动机与原文疑点；来源 PDF 第 {number} 页。'
            finally:t['active']-=1
    async def close(self):self.track['closed']+=1


def tracker():return {'calls':[],'active':0,'peak':0,'closed':0}


def job_row(ident):return library.public_job(one('SELECT * FROM library_jobs WHERE id=?',(ident,)))


async def launch(runner,ident):
    runner.launch(ident);await runner.tasks[ident]
    return job_row(ident)


async def until(predicate,timeout=120):
    async def wait():
        while not predicate():await asyncio.sleep(.02)
    await asyncio.wait_for(wait(),timeout)


@pytest.mark.parametrize('count,expected',[(200,{}),(201,{'batch_size':100,'batches_total':3}),
                                           (316,{'batch_size':100,'batches_total':4})])
def test_threshold_has_bounded_real_batches(count,expected):
    assert batches.batch_plan(range(count))==expected


@pytest.mark.parametrize('parallel,peak',[(False,1),(True,2)])
def test_316_nodes_execute_four_ordered_batches_with_global_model_caps(tmp_path,monkeypatch,parallel,peak):
    b,n=bulk_book(tmp_path,confirmed=True);t=tracker()
    monkeypatch.setattr(library,'extract_page',fake_extract)
    async def scenario():
        job=worker.new_read_job(b['id'],list(reversed([x['id'] for x in n])),'fixture','fixture','none',parallel,foreground=True)
        assert job['payload']['node_ids']==[x['id'] for x in n]
        result=await launch(worker.LibraryWorker(lambda p:Model(t)),job['id'])
        assert result['status']=='completed',result
        assert result['result']['batches_completed']==result['result']['batches_total']==4
        assert result['result']['nodes_completed_count']==result['result']['total_pages']==316
        assert len(result['result']['nodes_completed'])==16  # Only the last batch is sent to the UI.
        saved=[batches.saved_step(job['id'],f'read-batch-result-v1:{i}') for i in range(4)]
        assert [len(row['nodes_completed']) for row in saved]==[100,100,100,16]
        assert [r['node_id'] for row in saved for r in row['nodes_completed']]==[x['id'] for x in n]
        assert t['calls']==list(range(1,317)) and t['peak']==peak and t['closed']==316
        assert len(many("SELECT id FROM library_readings WHERE status='completed'"))==316
        assert len(many("SELECT id FROM library_jobs WHERE kind='read'"))==1
    asyncio.run(scenario())


def test_ancestor_coverage_is_normalized_before_batch_boundaries(tmp_path):
    b,n=bulk_book(tmp_path,confirmed=True)
    parent=n[0];execute('UPDATE library_nodes SET end_page=? WHERE id=?',(316,parent['id']))
    for child in [n[1],n[100],n[200],n[315]]:
        execute('UPDATE library_nodes SET parent_id=? WHERE id=?',(parent['id'],child['id']))
    job=worker.new_read_job(b['id'],[x['id'] for x in n],'fixture',foreground=True)
    expected=[x['id'] for x in n if x not in [n[1],n[100],n[200],n[315]]]
    assert job['payload']['node_ids']==expected and len(expected)==312
    assert job['payload']['batches_total']==4
    with pytest.raises(ValueError,match='已有阅读任务'):
        worker.new_read_job(b['id'],[n[250]['id']],'fixture')


def test_retry_does_not_read_a_scope_whose_confirmation_was_revoked(tmp_path):
    b,n=bulk_book(tmp_path,201,confirmed=True)
    job=worker.new_read_job(b['id'],[x['id'] for x in n],'fixture',foreground=True)
    execute("UPDATE library_jobs SET status='failed' WHERE id=?",(job['id'],))
    library.update_node(n[150]['id'],{'confirmed':False})
    async def scenario():
        runner=worker.LibraryWorker(lambda p:pytest.fail('Revoked scopes must stop before model calls'))
        await runner.action(job['id'],'resume')
        result=await launch(runner,job['id'])
        assert result['status']=='failed' and '阅读范围已改变' in result['error']
        assert not many('SELECT id FROM library_readings')
    asyncio.run(scenario())


def test_failure_stops_next_batch_and_resume_reuses_completed_nodes(tmp_path,monkeypatch):
    b,n=bulk_book(tmp_path,confirmed=True);t=tracker();t['fail_number']=103
    monkeypatch.setattr(library,'extract_page',fake_extract)
    async def scenario():
        job=worker.new_read_job(b['id'],[x['id'] for x in n],'fixture',foreground=True)
        runner=worker.LibraryWorker(lambda p:Model(t))
        first=await launch(runner,job['id'])
        assert first['status']=='failed' and first['result']['batches_completed']==1
        assert max(t['calls'])==200 and batches.saved_step(job['id'],'read-batch-result-v1:0')
        assert batches.saved_step(job['id'],'read-batch-result-v1:1') is None
        await runner.action(job['id'],'resume')
        result=await launch(runner,job['id'])
        assert result['status']=='completed',result
        assert Counter(t['calls'])==Counter(range(1,317))+Counter([103])
        assert result['result']['batches_completed']==4
    asyncio.run(scenario())


def test_pause_in_second_batch_survives_restart_without_repeating_requests(tmp_path,monkeypatch):
    b,n=bulk_book(tmp_path,confirmed=True);t=tracker()
    monkeypatch.setattr(library,'extract_page',fake_extract)
    async def scenario():
        t.update(gate_number=101,started=asyncio.Event(),release=asyncio.Event())
        job=worker.new_read_job(b['id'],[x['id'] for x in n],'fixture',foreground=True)
        runner=worker.LibraryWorker(lambda p:Model(t));runner.launch(job['id'])
        await asyncio.wait_for(t['started'].wait(),90)
        await runner.action(job['id'],'pause');t['release'].set()
        await until(lambda:job_row(job['id'])['status']=='paused')
        assert len(t['calls'])==101 and job_row(job['id'])['result']['batches_completed']==1
        await runner.close()
        restarted=worker.LibraryWorker(lambda p:Model(t));await restarted.start()
        try:
            await asyncio.sleep(.1);assert job_row(job['id'])['status']=='paused' and len(t['calls'])==101
            await restarted.action(job['id'],'resume')
            await until(lambda:job_row(job['id'])['status']=='completed')
            assert t['calls']==list(range(1,317))
        finally:await restarted.close()
    asyncio.run(scenario())


def test_cancelling_second_batch_stops_future_nodes_and_keeps_first_batch(tmp_path,monkeypatch):
    b,n=bulk_book(tmp_path,confirmed=True);t=tracker()
    monkeypatch.setattr(library,'extract_page',fake_extract)
    async def scenario():
        t.update(gate_number=101,started=asyncio.Event(),release=asyncio.Event())
        job=worker.new_read_job(b['id'],[x['id'] for x in n],'fixture',foreground=True)
        runner=worker.LibraryWorker(lambda p:Model(t));runner.launch(job['id'])
        await asyncio.wait_for(t['started'].wait(),90)
        await runner.action(job['id'],'cancel');await asyncio.sleep(.05)
        assert job_row(job['id'])['status']=='cancelled' and t['calls']==list(range(1,102)) and t['active']==0
        assert batches.saved_step(job['id'],'read-batch-result-v1:0')
        assert len(many("SELECT id FROM library_readings WHERE status='completed'"))==100
        assert len(many('SELECT id FROM library_jobs'))==1
    asyncio.run(scenario())


def test_real_native_316_ranges_commit_in_four_batches_and_handoff_once(tmp_path,monkeypatch):
    b,n=bulk_book(tmp_path);original=ranges.run_ranges;attempts=[]
    async def watched(control,book,payload,factory):
        attempts.append(list(payload['node_ids']))
        result=await original(control,book,payload,factory)
        # Simulate a crash after batch 2 committed its scopes, before its parent
        # advanced the batch counter. Restart must reuse the atomic checkpoint.
        if len(attempts)==2:raise ValueError('fixture crash after range commit')
        return result
    monkeypatch.setattr(ranges,'run_ranges',watched)
    async def scenario():
        job=ranges.range_job(b['id'],[x['id'] for x in n],provider='fixture',foreground=True,read_after=True,parallel=True)
        runner=worker.LibraryWorker(lambda p:pytest.fail('Exact native headings require no cloud model'))
        first=await launch(runner,job['id'])
        assert first['status']=='failed' and len(many("SELECT id FROM library_nodes WHERE confirmed=1"))==200
        assert not many("SELECT id FROM library_jobs WHERE kind='read'")
        await runner.action(job['id'],'resume');result=await launch(runner,job['id'])
        assert result['status']=='completed',result
        assert [len(ids) for ids in attempts]==[100,100,100,16]
        assert len(many("SELECT id FROM library_nodes WHERE confirmed=1"))==316
        assert result['result']['pending_node_ids']==[] and result['result']['ai_choices']==0
        assert len(result['result']['ranges'])==16 and result['result']['batches_completed']==4
        follow=one("SELECT * FROM library_jobs WHERE kind='read'");plan=unj(follow['payload_json'])
        assert plan['foreground'] and plan['parallel'] and plan['batches_total']==4
        assert plan['node_ids']==[x['id'] for x in n] and plan['origin_job_id']==job['id']
        repeated=await batches.run_range_batches(worker.LibraryControl(job['id']),b,job['payload'],lambda p:None)
        assert repeated['read_job_id']==follow['id'] and len(many("SELECT id FROM library_jobs WHERE kind='read'"))==1
    asyncio.run(scenario())


def test_range_resume_rejects_manual_edit_between_batches(tmp_path,monkeypatch):
    b,n=bulk_book(tmp_path,201);original=ranges.run_ranges;attempts=[]
    async def crash(control,book,payload,factory):
        attempts.append(list(payload['node_ids']))
        if len(attempts)==2:raise ValueError('fixture stop before second batch')
        return await original(control,book,payload,factory)
    monkeypatch.setattr(ranges,'run_ranges',crash)
    async def scenario():
        job=ranges.range_job(b['id'],[x['id'] for x in n],foreground=True)
        runner=worker.LibraryWorker(lambda p:None)
        assert (await launch(runner,job['id']))['status']=='failed'
        library.update_node(n[150]['id'],{'title':'My corrected title'})
        await runner.action(job['id'],'resume');result=await launch(runner,job['id'])
        assert result['status']=='failed' and '没有覆盖手动修改' in result['error']
        assert library.node(n[150]['id'])['title']=='My corrected title'
        assert len(many('SELECT id FROM library_nodes WHERE confirmed=1'))==100
    asyncio.run(scenario())


def test_entire_range_job_keeps_six_heading_ai_choices_across_batches_and_retries(tmp_path):
    b,n=bulk_book(tmp_path,201);job=ranges.range_job(b['id'],[x['id'] for x in n])
    accepted=[]
    for batch in range(4):
        for number in range(batch*5,(batch+1)*5):
            if batches.reserve_ai_choice(job['id'],['ambiguous-heading',number],6):accepted.append(number)
    assert accepted==list(range(6))
    assert batches.reserve_ai_choice(job['id'],['ambiguous-heading',3],6)
    assert len(batches.saved_step(job['id'],batches.AI_BUDGET_STEP))==6


def test_handoff_normalizes_all_ready_nodes_once_and_excludes_pending_nodes(tmp_path):
    b,n=bulk_book(tmp_path,confirmed=True)
    parent=n[0]
    execute('UPDATE library_nodes SET end_page=316 WHERE id=?',(parent['id'],))
    for child in n[1:]:execute('UPDATE library_nodes SET parent_id=? WHERE id=?',(parent['id'],child['id']))
    # Model a saved multi-batch locator result. The uncertain child is never
    # marked as a separately read node; the selected verified chapter can
    # still be read under its own complete, explicitly chosen scope.
    execute('UPDATE library_nodes SET confirmed=0 WHERE id=?',(n[201]['id'],))
    row=worker.create_job(b['id'],'ranges',{'node_ids':[x['id'] for x in n],'provider':'fixture',
                         'foreground':True,'parallel':False,'read_after':True})
    current=many('SELECT * FROM library_nodes WHERE book_id=?',(b['id'],))
    saved={'output':{'pending_node_ids':[n[201]['id']]},
           'versions':{x['id']:library.version(b,x) for x in current}}
    result=ranges.finish_ranges(worker.LibraryControl(row['id']),b,row['payload'],saved)
    assert result['reading_node_ids']==[parent['id']] and n[201]['id'] not in result['ready_node_ids']
    repeated=ranges.finish_ranges(worker.LibraryControl(row['id']),b,row['payload'],saved)
    assert result['read_job_id']==repeated['read_job_id'] and len(many("SELECT id FROM library_jobs WHERE kind='read'"))==1


def test_bulk_review_is_atomic_and_does_not_run_ai(tmp_path):
    from studyforge.library_outline import OutlineConflict
    b,n=bulk_book(tmp_path)
    for item in n:
        crop={'start_page':item['start_page'],'end_page':item['start_page'],'start_y':0,'end_y':1}
        evidence={'title':item['title'],'crop':crop,'start':{'page':item['start_page']},'terminal':True}
        execute('UPDATE library_nodes SET end_page=start_page,end_y=1,provenance_json=? WHERE id=?',
                (j({'auto_range':evidence}),item['id']))
    current=many('SELECT * FROM library_nodes WHERE book_id=? ORDER BY position,id',(b['id'],))
    revisions={x['id']:ranges.node_signature(x) for x in current}
    invalid=revisions|{current[-1]['id']:'stale revision'}
    with pytest.raises(OutlineConflict):confirm(b['id'],invalid)
    assert not many('SELECT id FROM library_nodes WHERE confirmed=1')
    assert len(confirm(b['id'],revisions)['confirmed_node_ids'])==316
    assert not many('SELECT id FROM library_jobs') and not many('SELECT id FROM library_readings')


def test_all_bulk_interfaces_share_bounded_selection_limit():
    ids=[f'id-{i}' for i in range(316)]
    assert len(ReadIn(node_ids=ids,provider='deepseek').node_ids)==316
    assert len(RangesIn(node_ids=ids).node_ids)==316
    assert len(ConfirmRangesIn(revisions={ident:'v' for ident in ids}).revisions)==316
    for schema,kwargs in [(ReadIn,{'provider':'deepseek'}),(RangesIn,{})]:
        with pytest.raises(ValidationError):schema(node_ids=['id']*2001,**kwargs)
    with pytest.raises(ValidationError):ConfirmRangesIn(revisions={str(i):'v' for i in range(2001)})
