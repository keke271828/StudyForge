import asyncio
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

from studyforge import library, library_worker, server
from studyforge.db import create_project, execute, many, now, one, uid, unj
from studyforge.scheduling import execution_scope, model_slot


def setup_book(tmp_path, count=3, bookmarks=False):
    path=tmp_path/'textbook.pdf'
    with fitz.open() as doc:
        for i in range(count):
            p=doc.new_page();p.insert_text((50,70),f'TOP: field definition and closure conditions. Page {i+1}.')
            p.insert_text((50,700),f'BOTTOM: unrelated section and exercise answers. Page {i+1}.')
        if bookmarks:doc.set_toc([[1,'Chapter 1',1],[2,'Fields',1],[2,'Polynomials',2]])
        doc.save(path)
    return library.import_book(path,path.name)['book'],path


def scoped_node(b,title='数域',start=1,end=1,**kwargs):
    n=library.add_node(b['id'],title,kwargs.pop('parent_id',None))
    return library.update_node(n['id'],{'start_page':start,'end_page':end,'end_y':.5,'confirmed':True,**kwargs})


def chat(project=None):
    p=project or create_project('学习项目')
    ident=uid()
    execute('INSERT INTO conversations(id,project_id,provider,created_at) VALUES (?,?,?,?)',(ident,p['id'],'deepseek',now()))
    return p,ident


class Client:
    model='fixture';effort='none'
    def __init__(self,tracker):self.t=tracker
    async def complete(self,system,user,**kwargs):
        self.t['inputs'].append(user)
        async with model_slot('fixture'):
            self.t['active']+=1;self.t['peak']=max(self.t['peak'],self.t['active'])
            try:
                if self.t.get('started'):self.t['started'].set()
                if self.t.get('release'):await self.t['release'].wait()
                await asyncio.sleep(.025)
                if self.t.get('fail') and '坏节点' in user:self.t['fail']=False;raise ValueError('故意失败')
                return '概念：数域的封闭性；非零除数；本段来源 PDF 第 1 页。'
            finally:self.t['active']-=1
    async def close(self):pass


def tracker():return {'inputs':[],'active':0,'peak':0}


async def run_nodes(b,nodes,t,parallel=False):
    worker=library_worker.LibraryWorker(lambda payload:Client(t))
    row=library_worker.new_read_job(b['id'],[n['id'] for n in nodes],'fixture','fixture','none',parallel)
    worker.launch(row['id']);await worker.tasks[row['id']]
    return library.public_job(one('SELECT * FROM library_jobs WHERE id=?',(row['id'],)))


def ready(tmp_path,title='数域',start=1,end=1):
    b,path=setup_book(tmp_path);n=scoped_node(b,title,start,end)
    result=asyncio.run(run_nodes(b,[n],tracker()))
    assert result['status']=='completed',result
    return b,library.node(n['id']),path


def test_upload_does_not_read_book_and_duplicate_is_reused(tmp_path,monkeypatch):
    monkeypatch.setattr(library,'directory_page',lambda *a:pytest.fail('未选择目录页'))
    b,path=setup_book(tmp_path)
    assert b['status']=='stored'
    assert not many('SELECT * FROM library_nodes') and not many('SELECT * FROM library_readings')
    assert library.import_book(path,'second-name.pdf')['duplicate']
    assert len(library.catalogue())==1


def test_invalid_pdf_upload_is_a_clear_input_error_and_leaves_no_book(tmp_path):
    path=tmp_path/'broken.pdf';path.write_bytes(b'not a PDF')
    with TestClient(server.app) as client:
        response=client.post('/api/library/books',files={'file':('broken.pdf',path.read_bytes(),'application/pdf')})
    assert response.status_code==400 and 'PDF' in response.json()['detail']
    assert not library.catalogue()


def test_bookmarks_become_candidate_scopes_without_reading(tmp_path):
    b,_=setup_book(tmp_path,bookmarks=True)
    detail=library.details(b['id'])
    assert len(detail['nodes'])==3
    assert all(not n['confirmed'] and n['reading'] is None for n in detail['nodes'])
    assert detail['nodes'][1]['parent_id']==detail['nodes'][0]['id']


def test_native_directory_preserves_page_number_columns_without_ocr(tmp_path,monkeypatch):
    path=tmp_path/'native-directory.pdf'
    with fitz.open() as doc:
        page=doc.new_page()
        page.insert_text((50,40),'目录：标题与页码分列，按同一行建立节点而不是把页码丢弃。',fontname='china-s')
        page.insert_text((50,80),'第一章 数域',fontname='china-s')
        page.insert_text((420,80),'1',fontname='china-s')
        page.insert_text((60,110),'1 数域',fontname='china-s')
        page.insert_text((420,110),'1',fontname='china-s')
        doc.save(path)
    b=library.import_book(path,path.name)['book']
    monkeypatch.setattr(library,'ocr_rows',lambda *a:pytest.fail('有效文字目录不应重复 OCR'))
    rows=library.directory_page(b['id'],1)
    nodes=library.parse_directory([(1,rows)])
    assert [n['kind'] for n in nodes]==['chapter','section']
    assert [n['printed_page'] for n in nodes]==[1,1]
    assert all(n['provenance']['method']=='native_pdf_directory' for n in nodes)


def test_scanned_directory_hierarchy_and_page_mapping_are_not_confirmed(tmp_path):
    b,_=setup_book(tmp_path,count=20)
    values=[(3,[{'text':'第一章 多项式 ........ 1'},{'text':'§1 数域 ........ 1'},
                {'text':'§2 一元多项式 ........ 2'}]),(4,[{'text':'第二章 行列式 ........ 6'},
                  {'text':'§1 引言 ........ 6'},{'text':'习题 ........ 8'},{'text':'附录一 整数理论 ...... 12'}])]
    nodes=library.parse_directory(values,1,6);library.save_outline(b['id'],nodes)
    detail=library.details(b['id'])
    assert [n['kind'] for n in detail['nodes']]==['chapter','section','section','chapter','section','exercises','appendix']
    assert detail['nodes'][1]['start_page']==6
    assert detail['nodes'][4]['parent_id']==detail['nodes'][3]['id']
    assert not any(n['confirmed'] for n in detail['nodes'])
    with pytest.raises(ValueError,match='确认'):library.normalize_nodes(b['id'],[nodes[1]['id']])


@pytest.mark.parametrize('change',[{'start_page':0},{'end_page':4},{'start_y':1},{'end_y':0},{'start_y':.7,'end_y':.6}])
def test_invalid_scope_is_rejected(tmp_path,change):
    b,_=setup_book(tmp_path);n=scoped_node(b)
    with pytest.raises(ValueError):library.update_node(n['id'],change|{'confirmed':True})


def test_scope_edit_invalidates_confirmation(tmp_path):
    b,_=setup_book(tmp_path);n=scoped_node(b)
    current=library.update_node(n['id'],{'end_y':.4})
    assert not current['confirmed']


def test_page_crop_and_selected_pages_exclude_neighbor_material(tmp_path):
    b,_=setup_book(tmp_path);n=scoped_node(b)
    content=library.extract_page(b,library.node(n['id']),1)
    assert 'TOP:' in content['original_text'] and 'BOTTOM:' not in content['original_text']
    with pytest.raises(ValueError,match='范围'):library.extract_page(b,library.node(n['id']),2)


def test_selected_parent_does_not_duplicate_child(tmp_path):
    b,_=setup_book(tmp_path);parent=scoped_node(b,'章节',1,2)
    child=scoped_node(b,'小节',parent_id=parent['id'])
    assert [n['id'] for n in library.normalize_nodes(b['id'],[child['id'],parent['id']])]==[parent['id']]


@pytest.mark.parametrize('parallel,expected',[(False,1),(True,2)])
def test_parallel_toggle_changes_actual_request_overlap(tmp_path,parallel,expected):
    b,_=setup_book(tmp_path);a=scoped_node(b,'数域',1,1);c=scoped_node(b,'多项式',2,2);t=tracker()
    row=asyncio.run(run_nodes(b,[a,c],t,parallel))
    assert row['status']=='completed',row
    assert row['result']['workers']==expected and t['peak']==expected
    assert len(many("SELECT * FROM library_readings WHERE status='completed'"))==2
    assert all('BOTTOM:' not in text for text in t['inputs'])


@pytest.mark.parametrize('parallel_enabled,cap,reason',[(False,2,'全软件并行已关闭'),(True,1,'模型并发上限为 1')])
def test_parallel_reading_respects_global_toggle_and_reports_reason(tmp_path,parallel_enabled,cap,reason):
    from studyforge.ai import save_settings
    save_settings({'task_parallel_enabled':parallel_enabled,'model_concurrency':cap})
    b,_=setup_book(tmp_path);a=scoped_node(b,'数域',1,1);c=scoped_node(b,'多项式',2,2);t=tracker()
    row=asyncio.run(run_nodes(b,[a,c],t,parallel=True))
    assert row['status']=='completed',row
    assert row['result']['workers']==1 and t['peak']==1
    assert row['result']['parallel_reason']==reason


def test_long_node_reports_progress_before_whole_node_finishes(tmp_path):
    b,_=setup_book(tmp_path,count=6);n=scoped_node(b,end=6);t=tracker()
    async def scenario():
        waiting=asyncio.Event();release=asyncio.Event()
        class DelayedSecondBatch(Client):
            count=0
            async def complete(self,system,user,**kwargs):
                self.count+=1
                if self.count==2:
                    waiting.set();await release.wait()
                return await super().complete(system,user,**kwargs)
        worker=library_worker.LibraryWorker(lambda payload:DelayedSecondBatch(t))
        row=library_worker.new_read_job(b['id'],[n['id']],'fixture','fixture','none')
        worker.launch(row['id'])
        await asyncio.wait_for(waiting.wait(),5)
        current=library.public_job(one('SELECT * FROM library_jobs WHERE id=?',(row['id'],)))
        assert current['status']=='running' and 0<current['progress']<100
        assert current['result']['pages_processed']==4 and current['result']['total_pages']==6
        release.set();await worker.tasks[row['id']]
        assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='completed'
    asyncio.run(scenario())


def test_frontend_priority_does_not_start_background_model(tmp_path):
    b,_=setup_book(tmp_path);n=scoped_node(b);t=tracker()
    async def scenario():
        from studyforge.learning_memory import foreground_activity
        worker=library_worker.LibraryWorker(lambda payload:Client(t))
        row=library_worker.new_read_job(b['id'],[n['id']],'fixture','fixture','none')
        with foreground_activity():
            worker.launch(row['id']);task=worker.tasks[row['id']]
            await asyncio.sleep(.08)
            assert not t['inputs']
        await asyncio.wait_for(task,3)
        assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='completed'
    asyncio.run(scenario())


def test_pause_waits_and_resume_reuses_completed_model_step(tmp_path):
    b,_=setup_book(tmp_path);n=scoped_node(b);t=tracker()
    async def scenario():
        t.update(started=asyncio.Event(),release=asyncio.Event())
        worker=library_worker.LibraryWorker(lambda payload:Client(t))
        row=library_worker.new_read_job(b['id'],[n['id']],'fixture','fixture','none')
        worker.launch(row['id']);task=worker.tasks[row['id']]
        await t['started'].wait();await worker.action(row['id'],'pause')
        assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='pausing'
        t['release'].set();await asyncio.sleep(.10)
        assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='paused'
        assert not task.done()
        await worker.action(row['id'],'resume');await asyncio.wait_for(task,3)
        assert len(t['inputs'])==1
        assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='completed'
    asyncio.run(scenario())


def test_restart_reuses_saved_steps_and_keeps_user_paused_jobs(tmp_path):
    b,_=setup_book(tmp_path);n=scoped_node(b);t=tracker()
    async def scenario():
        t.update(started=asyncio.Event(),release=asyncio.Event())
        worker=library_worker.LibraryWorker(lambda payload:Client(t))
        row=library_worker.new_read_job(b['id'],[n['id']],'fixture','fixture','none')
        worker.launch(row['id']);task=worker.tasks[row['id']]
        await t['started'].wait();await worker.action(row['id'],'pause');t['release'].set();await asyncio.sleep(.1)
        await worker.close()
        restarted=library_worker.LibraryWorker(lambda payload:Client(t));await restarted.start()
        await asyncio.sleep(.05)
        assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='paused'
        await restarted.action(row['id'],'resume')
        for _ in range(15):
            await asyncio.sleep(.1)
            if one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='completed':break
        await restarted.close()
        assert len(t['inputs'])==1
        assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='completed'
    asyncio.run(scenario())


def test_partial_failure_retains_other_nodes_and_retry_avoids_duplicate_calls(tmp_path):
    b,_=setup_book(tmp_path);a=scoped_node(b,'数域');c=scoped_node(b,'坏节点',2,2);t=tracker();t['fail']=True
    async def scenario():
        worker=library_worker.LibraryWorker(lambda payload:Client(t))
        row=library_worker.new_read_job(b['id'],[a['id'],c['id']],'fixture','fixture','none',True)
        worker.launch(row['id']);await worker.tasks[row['id']]
        assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='failed'
        assert library.ready_reading(library.node(a['id']))
        await worker.action(row['id'],'resume');worker.launch(row['id']);await worker.tasks[row['id']]
        assert one('SELECT status FROM library_jobs WHERE id=?',(row['id'],))['status']=='completed'
        assert len(t['inputs'])==3
    asyncio.run(scenario())


def test_cross_project_reference_uses_original_excerpts_and_never_chat_history(tmp_path):
    b,n,_=ready(tmp_path);p,a=chat();q,c=chat()
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),a,'user','秘密聊天不可共享',now()))
    for project,ident in [(p,a),(q,c)]:
        snap=library.reference_snapshot(ident,project['id'],'数域为何需要封闭性')
        result=library.reference_content(snap,'数域')
        assert result['evidence'] and 'TOP:' in result['text']
        assert '秘密聊天不可共享' not in result['text'] and 'BOTTOM:' not in result['text']
    assert not many('SELECT * FROM mastery') and not many('SELECT * FROM learning_events')


def test_unread_node_produces_metadata_suggestion_and_does_not_extract(tmp_path,monkeypatch):
    b,_=setup_book(tmp_path);n=scoped_node(b);p,c=chat()
    monkeypatch.setattr(library,'extract_page',lambda *a:pytest.fail('未授权正文读取'))
    snap=library.reference_snapshot(c,p['id'],'数域是什么')
    result=library.reference_content(snap,'数域')
    assert not result['evidence'] and result['candidates'][0]['node_id']==n['id']
    assert 'TOP:' not in result['text']


def test_preferences_are_isolated_and_off_mode_is_effective(tmp_path):
    b,n,_=ready(tmp_path);p,a=chat();_,c=chat(p)
    library.set_preferences(a,p['id'],'manual',[{'node_id':n['id'],'purpose':'primary'}])
    assert library.preferences(c,p['id'])['references']==[]
    library.set_preferences(a,p['id'],'off',[{'node_id':n['id'],'purpose':'primary'}])
    snap=library.reference_snapshot(a,p['id'],'数域')
    assert not snap['references'] and not snap['candidates']
    with pytest.raises(ValueError):library.preferences(a,create_project('其他项目')['id'])


def test_generation_primary_node_has_full_selected_scope_not_three_page_snippet(tmp_path):
    b,_=setup_book(tmp_path,count=6);n=scoped_node(b,start=1,end=6);t=tracker()
    asyncio.run(run_nodes(b,[n],t));p,c=chat()
    library.set_preferences(c,p['id'],'manual',[{'node_id':n['id'],'purpose':'primary'}])
    snap=library.reference_snapshot(c,p['id'],'数域')
    records=library.generation_records(snap)
    assert len(records[0]['segments'])==6
    assert len(t['inputs'])==3 # two 4-page batches, one node index
    assert records[0]['read_manifest']['method']=='explicit_selected_library_node'


def test_library_only_document_passes_export_revalidation_and_preserves_provenance(tmp_path,monkeypatch):
    b,n,_=ready(tmp_path);p,c=chat()
    library.set_preferences(c,p['id'],'manual',[{'node_id':n['id'],'purpose':'primary'}])
    snapshot=library.reference_snapshot(c,p['id'],'数域')
    inputs=[]
    class Writer:
        model='fixture';effort='none'
        async def complete(self,system,user,**kwargs):
            inputs.append(user)
            return '# 数域\n\n四则运算的封闭性需要检查，除数不能为零。\n\n## 系统性总结\n定义和条件必须一起使用。'
    monkeypatch.setattr(server,'client_for',lambda *args,**kwargs:Writer())
    value=server.GenerateIn(project_id=p['id'],source_ids=[],provider='deepseek',model='fixture',
                            format='docx',review_mode='express',library_snapshot=snapshot)
    from studyforge.db import create_job as new_project_job
    job_id=new_project_job(p['id'],'generate',value.model_dump())
    asyncio.run(server._generate_job(job_id,value))
    job=one('SELECT * FROM jobs WHERE id=?',(job_id,))
    assert job['status']=='completed',job['error']
    assert any('TOP:' in text for text in inputs) and all('BOTTOM:' not in text for text in inputs)
    artifact=one("SELECT * FROM artifacts WHERE project_id=? AND kind='explanation'",(p['id'],))
    meta=unj(artifact['metadata_json'])
    assert meta['library_references']['references'][0]['node_id']==n['id']
    assert meta['source_reading'][0]['method']=='explicit_selected_library_node'
    assert Path(artifact['path']).read_bytes()[:2]==b'PK'


def test_changed_scope_or_original_is_not_silently_mixed_with_snapshot(tmp_path):
    b,n,_=ready(tmp_path);p,c=chat()
    library.set_preferences(c,p['id'],'manual',[{'node_id':n['id'],'purpose':'primary'}])
    snap=library.reference_snapshot(c,p['id'],'数域')
    library.update_node(n['id'],{'end_y':.4,'confirmed':True})
    with pytest.raises(ValueError,match='改变'):library.generation_records(snap)
    Path(b['original_path']).write_bytes(b'changed')
    # Newly scoped notes are unavailable rather than replaying an old reading.
    assert library.ready_reading(library.node(n['id'])) is None


def test_project_delete_preserves_book_and_book_delete_preserves_imported_original(tmp_path):
    b,n,path=ready(tmp_path);p,c=chat()
    library.set_preferences(c,p['id'],'manual',[{'node_id':n['id'],'purpose':'reference'}])
    asyncio.run(server.remove_project(p['id']))
    server.permanent_project_delete(p['id'],{'confirmation_name':p['name']})
    assert Path(b['original_path']).is_file() and library.ready_reading(n)
    library.delete_book(b['id']);assert path.is_file()
    assert not many('SELECT * FROM library_readings') and not many('SELECT * FROM library_chunks')


def test_agent_read_tools_honor_off_manual_and_unread_scopes(tmp_path):
    from studyforge.agent_tools import AgentRuntime,ReadLibrary,SearchLibrary
    b,n,_=ready(tmp_path);unread=scoped_node(b,'其他未读章节',2,2);p,c=chat()
    library.set_preferences(c,p['id'],'manual',[{'node_id':n['id'],'purpose':'reference'}])
    runtime=AgentRuntime(p['id'],[],provider='deepseek',model='fixture',conversation_id=c)
    async def scenario():
        answer=await runtime.sf_read_library_node(ReadLibrary(node_id=n['id']))
        assert 'TOP:' in answer['text'] and 'BOTTOM:' not in answer['text']
        with pytest.raises(PermissionError):await runtime.sf_read_library_node(ReadLibrary(node_id=unread['id']))
        with pytest.raises(PermissionError):await runtime.sf_read_library_node(ReadLibrary(node_id=n['id'],page=3))
        library.set_preferences(c,p['id'],'off',[])
        assert (await runtime.sf_search_library(SearchLibrary(query='数域')))['nodes']==[]
        with pytest.raises(PermissionError):await runtime.sf_read_library_node(ReadLibrary(node_id=n['id']))
    asyncio.run(scenario())
    with pytest.raises(PermissionError,match='书库范围'):runtime.checked_path(b['original_path'])


def test_api_upload_and_toc_do_not_autoparse_and_invalid_pdf_rejected(tmp_path):
    b,path=setup_book(tmp_path);client=TestClient(server.app)
    response=client.post('/api/library/books',files={'file':('again.pdf',path.read_bytes(),'application/pdf')})
    assert response.status_code==200 and response.json()['duplicate']
    response=client.post('/api/library/books',files={'file':('bad.docx',b'no','application/octet-stream')})
    assert response.status_code==400
    assert client.post('/api/library/books/'+b['id']+'/toc',json={'page_spec':'1-60'}).status_code==400
    assert client.get('/api/library/books/'+b['id']+'/page?page=2').headers['content-type']=='image/png'


def test_mobile_scope_allows_library_without_exposing_private_files():
    from studyforge.mobile_access import SAFE_ROUTES,request_limit
    import re
    ident='a'*32
    def allowed(method,path):return any(m==method and re.fullmatch(pattern,path) for m,pattern in SAFE_ROUTES)
    assert allowed('POST','/api/library/books')
    assert allowed('POST',f'/api/library/books/{ident}/read')
    assert allowed('PUT',f'/api/library/conversations/{ident}')
    assert not allowed('GET','/api/library/files/original.pdf')
    assert not allowed('DELETE',f'/api/library/books/{ident}')
    assert request_limit('/api/library/books')[0]>512*1024*1024


def test_library_completion_notification_is_live_without_a_project(tmp_path):
    b,n,_=ready(tmp_path)
    from studyforge.desktop_notifications import feed
    rows=feed()['events']
    assert any(r['category']=='complete' and r['target'].get('book_id')==b['id'] for r in rows)
