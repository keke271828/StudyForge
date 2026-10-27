"""Source-boundary repair, partial handoff and explicit batch confirmation."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from studyforge import library,library_ranges as ranges,library_worker,server
from studyforge import library_range_review as review
from studyforge.db import execute,j,many,one,uid,unj
from studyforge.library_outline import OutlineConflict
from test_library_ranges import textbook,locate


def test_renaming_display_title_keeps_original_heading_for_location(tmp_path):
    b,n=textbook(tmp_path)
    library.update_node(n[1]['id'],{'title':'My definitions notebook'})
    result=asyncio.run(locate(b,[n[1]['id']]))
    assert result['status']=='completed' and not result['result']['pending_node_ids']
    current=library.node(n[1]['id'])
    assert current['title']=='My definitions notebook' and current['confirmed']
    assert unj(current['provenance_json'])['auto_range']['start']['text']=='1 Definitions'


def test_independent_local_title_band_repairs_low_confidence_scan(tmp_path,monkeypatch):
    b,n=textbook(tmp_path);original=ranges.page_rows;calls=[]
    def weak(book,page):
        data=original(book,page)
        data['method']='local_ocr'
        data['rows']=[dict(r,text='1 Definitionz',score=.7) if r['text']=='1 Definitions' else r for r in data['rows']]
        return data
    def band(book,page,top,bottom):
        calls.append((page,top,bottom))
        return [{'text':'1 Definitions','top':top,'bottom':bottom,'score':.97}]
    monkeypatch.setattr(ranges,'page_rows',weak);monkeypatch.setattr(ranges,'reread_band',band)
    result=asyncio.run(locate(b,[n[1]['id']]))
    assert not result['result']['pending_node_ids'] and library.node(n[1]['id'])['confirmed']
    assert len(calls)==1 and result['result']['heading_rechecks']==1
    assert result['result']['ranges'][0]['start']['basis']=='原页标题局部高清复核'


def test_directory_scan_recheck_corrects_ocr_title_without_inventing_pages(tmp_path,monkeypatch):
    b,n=textbook(tmp_path);item=n[1]
    provenance=unj(item['provenance_json'])|{'toc_pdf_page':2,'directory_y':220.,'directory_height':30.,
                                            'directory_title':'1 Definitionz'}
    execute('UPDATE library_nodes SET title=?,provenance_json=? WHERE id=?',('1 Definitionz',j(provenance),item['id']))
    monkeypatch.setattr(ranges,'reread_band',lambda *args:[{'text':'1 Definitions 1','top':.15,'bottom':.17,'score':.96}])
    result=asyncio.run(locate(b,[item['id']]))
    current=library.node(item['id'])
    assert current['confirmed'] and current['title']=='1 Definitions'
    assert (current['start_page'],current['end_page'])==(3,3)
    assert result['result']['ranges'][0]['start']['basis']=='目录原图复核与正文标题一致'


def test_missing_next_heading_has_no_end_of_book_proposal(tmp_path,monkeypatch):
    b,n=textbook(tmp_path);original=ranges.page_rows
    def missing(book,page):
        data=original(book,page);data['rows']=[r for r in data['rows'] if r['text']!='2 Examples'];return data
    monkeypatch.setattr(ranges,'page_rows',missing)
    result=asyncio.run(locate(b,[n[1]['id']]))
    current=library.node(n[1]['id'])
    assert not current['confirmed'] and current['start_page'] is None
    assert result['result']['ranges'][0]['crop'] is None and review.proposal(current) is None
    with pytest.raises(ValueError,match='没有完整'):review.confirm(b['id'],{current['id']:ranges.node_signature(current)})


def test_ready_node_is_enqueued_while_other_selected_scope_stays_pending(tmp_path,monkeypatch):
    b,n=textbook(tmp_path);original=ranges.page_rows
    def weak(book,page):
        data=original(book,page);data['rows']=[dict(r,text=r['text'].replace('Definitions','Definitionz')) for r in data['rows']];return data
    monkeypatch.setattr(ranges,'page_rows',weak)
    async def scenario():
        job=ranges.range_job(b['id'],[n[1]['id'],n[3]['id']],provider='fixture',foreground=True,read_after=True,allow_ai=False)
        result=await ranges.run_ranges(library_worker.LibraryControl(job['id']),b,job['payload'],lambda p:pytest.fail('No model'))
        reading=one('SELECT * FROM library_jobs WHERE id=?',(result['read_job_id'],))
        payload=unj(reading['payload_json'])
        assert payload['node_ids']==[n[3]['id']] and payload['foreground']
        assert result['ready_node_ids']==[n[3]['id']] and result['pending_node_ids']==[n[1]['id']]
    asyncio.run(scenario())


def test_primary_boundaries_reserve_budget_before_neighbour_search(tmp_path,monkeypatch):
    b,n=textbook(tmp_path)
    ident=uid()
    execute('INSERT INTO library_nodes(id,book_id,parent_id,position,title,kind,printed_page,start_page,end_page,provenance_json,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?)',(ident,b['id'],n[4]['id'],6,'Later body paragraphs and appendix.','section',4,None,None,'{}',n[0]['updated_at']))
    monkeypatch.setattr(ranges,'MAX_PAGES',3)
    result=asyncio.run(locate(b,[row['id'] for row in n]+[ident]))
    assert result['status']=='completed' and library.node(ident)['confirmed']
    assert result['result']['page_limit']>3 and result['result']['boundary_pages']==4


def test_matching_repeated_title_in_wrong_chapter_cannot_authorize_scope(tmp_path):
    b,n=textbook(tmp_path);ident=uid()
    # A wrong directory number points to a real, perfectly readable heading in
    # the prior chapter. Text similarity alone is insufficient.
    execute('INSERT INTO library_nodes(id,book_id,parent_id,position,title,kind,printed_page,start_page,end_page,provenance_json,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?)',(ident,b['id'],n[4]['id'],6,'1 Definitions','section',1,None,None,
            j({'directory_order':6,'directory_parent_id':n[4]['id'],'directory_kind':'section'}),n[0]['updated_at']))
    result=asyncio.run(locate(b,[ident]))
    row=library.node(ident)
    assert not row['confirmed'] and result['result']['ranges'][0]['crop'] is None
    assert '不在原目录所属章节内' in result['result']['ranges'][0]['reason']


def proposed_pair(tmp_path,monkeypatch):
    b,n=textbook(tmp_path);original=ranges.page_rows
    def fuzzy(book,page):
        data=original(book,page);data['rows']=[dict(r,text=r['text'].replace('Examples','Examplez')) for r in data['rows']];return data
    monkeypatch.setattr(ranges,'page_rows',fuzzy)
    result=asyncio.run(locate(b,[n[1]['id'],n[2]['id']]))
    assert result['status']=='completed'
    return b,[library.node(row['id']) for row in n[1:3]]


def test_batch_confirmation_is_explicit_atomic_and_allows_no_foreign_scope(tmp_path,monkeypatch):
    b,n=proposed_pair(tmp_path,monkeypatch)
    revisions={row['id']:ranges.node_signature(row) for row in n}
    assert all(review.proposal(row) for row in n)
    with TestClient(server.app) as client:
        invalid=client.post(f"/api/library/books/{b['id']}/ranges/confirm",json={'revisions':revisions|{uid():'fake'}})
        assert invalid.status_code==400 and all(not library.node(row['id'])['confirmed'] for row in n)
        response=client.post(f"/api/library/books/{b['id']}/ranges/confirm",json={'revisions':revisions})
        assert response.status_code==200,response.text
        assert response.json()['confirmed_node_ids']==list(revisions)
    assert all(library.node(row['id'])['confirmed'] for row in n)
    assert not many("SELECT id FROM library_jobs WHERE kind='read'")


def test_stale_batch_or_active_reading_does_not_partly_confirm(tmp_path,monkeypatch):
    b,n=proposed_pair(tmp_path,monkeypatch)
    revisions={row['id']:ranges.node_signature(row) for row in n}
    library.update_node(n[1]['id'],{'title':'Edited elsewhere'})
    with pytest.raises(OutlineConflict):review.confirm(b['id'],revisions)
    assert not library.node(n[0]['id'])['confirmed']
    job=library_worker.create_job(b['id'],'ranges',{'node_ids':[n[0]['id']]})
    with pytest.raises(ValueError,match='仍在阅读或定位'):review.confirm(b['id'],{n[0]['id']:revisions[n[0]['id']]})
    execute("UPDATE library_jobs SET status='cancelled' WHERE id=?",(job['id'],))
    assert not library.node(n[0]['id'])['confirmed']
