"""Observed page boundaries, conservative suggestions and crash-safe handoff."""
import asyncio
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

from studyforge import library,library_ranges as ranges,library_worker,server
from studyforge.db import execute,j,many,one,uid,unj


def textbook(tmp_path):
    path=tmp_path/'headings.pdf'
    with fitz.open() as doc:
        for index in range(7):
            page=doc.new_page()
            page.insert_text((50,50),'Running header: Chapter 1')
            if index==0:page.insert_text((50,120),'Cover and publication information')
            if index==1:page.insert_text((50,120),'Contents: Chapter 1 .... 1; Chapter 2 .... 3')
            if index==2:
                page.insert_text((50,110),'Chapter 1 Foundations')
                page.insert_text((50,220),'1 Definitions')
                page.insert_text((50,250),'DEF_ONLY: closure and nonzero divisors.')
                page.insert_text((50,500),'2 Examples')
                page.insert_text((50,550),'EXAMPLE_ONLY: an unrelated example.')
            if index==3:
                page.insert_text((50,200),'3 Proofs')
                page.insert_text((50,260),'PROOF_ONLY: hypotheses are necessary.')
            if index==4:
                page.insert_text((50,110),'Chapter 2 Vectors')
                page.insert_text((50,220),'1 Coordinates')
                page.insert_text((50,270),'VECTOR_ONLY: coordinate dependence.')
            if index>4:page.insert_text((50,160),'Later body paragraphs and appendix.')
            if index>=2:page.insert_text((280,805),str(index-1))
        doc.save(path)
    b=library.import_book(path,'标题定位测试.pdf')['book']
    a,c=uid(),uid()
    outline=[(a,'Chapter 1 Foundations','chapter',None,1),
             (uid(),'1 Definitions','section',a,1),(uid(),'2 Examples','section',a,1),
             (uid(),'3 Proofs','section',a,2),(c,'Chapter 2 Vectors','chapter',None,3),
             (uid(),'1 Coordinates','section',c,3)]
    library.save_outline(b['id'],[{'id':ident,'title':title,'kind':kind,'parent_id':parent,
        'printed_page':printed,'start_page':None,'provenance':{'method':'toc_ocr'}}
        for ident,title,kind,parent,printed in outline])
    execute('UPDATE library_books SET toc_pages=? WHERE id=?',('2',b['id']))
    return library.book(b['id']),many('SELECT * FROM library_nodes WHERE book_id=? ORDER BY position',(b['id'],))


async def locate(b,ids,**options):
    job=ranges.range_job(b['id'],ids,foreground=True,**options)
    worker=library_worker.LibraryWorker(lambda p:pytest.fail('Exact headings need no cloud model'))
    worker.launch(job['id']);await worker.tasks[job['id']]
    return library.public_job(one('SELECT * FROM library_jobs WHERE id=?',(job['id'],)))


def test_automatic_offsets_and_same_page_section_crops(tmp_path):
    b,n=textbook(tmp_path)
    result=asyncio.run(locate(b,[r['id'] for r in n]))
    assert result['status']=='completed',result
    assert not result['result']['pending_node_ids'] and result['result']['ai_choices']==0
    mapping=result['result']['mapping']
    assert mapping['offset']==2 and len(mapping['observations'])==2
    a,definitions,examples,proofs,c,coordinates=[library.node(r['id']) for r in n]
    assert (a['start_page'],a['end_page'])==(3,4)
    assert (definitions['start_page'],definitions['end_page'])==(3,3)
    assert definitions['end_y']==examples['start_y'] and definitions['start_y']<definitions['end_y']
    extracted=library.extract_page(b,definitions,3)['original_text']
    assert 'DEF_ONLY' in extracted and 'EXAMPLE_ONLY' not in extracted and '2 Examples' not in extracted
    assert c['end_page']==b['page_count'] and coordinates['confirmed']
    assert not many('SELECT * FROM library_readings')  # locating is not understanding
    assert result['result']['boundary_pages']==3  # no full-book OCR


def test_confirmed_manual_ranges_are_never_overwritten(tmp_path):
    b,n=textbook(tmp_path)
    manual=library.update_node(n[1]['id'],{'start_page':3,'end_page':3,'start_y':.3,'end_y':.4,'confirmed':True})
    result=asyncio.run(locate(b,[n[1]['id'],n[2]['id']]))
    assert result['status']=='completed'
    assert library.version(b,library.node(manual['id']))==library.version(b,manual)
    assert 'auto_range' not in unj(library.node(manual['id'])['provenance_json'])
    with pytest.raises(ValueError,match='均已可用'):ranges.range_job(b['id'],[manual['id']])


def test_automatic_boundary_follows_original_book_after_directory_reparenting(tmp_path):
    from studyforge import library_outline
    b,n=textbook(tmp_path)
    before=library.details(b['id'])['outline_revision']
    library_outline.move(b['id'],n[1]['id'],n[4]['id'],None,before)
    moved=library.node(n[1]['id'])
    assert moved['parent_id']==n[4]['id']
    result=asyncio.run(locate(b,[n[1]['id']]))
    assert result['status']=='completed' and not result['result']['pending_node_ids']
    current=library.node(n[1]['id'])
    assert current['start_page']==current['end_page']==3
    assert unj(current['provenance_json'])['auto_range']['next_heading']['text']=='2 Examples'
    extracted=library.extract_page(b,current,3)['original_text']
    assert 'DEF_ONLY' in extracted and 'EXAMPLE_ONLY' not in extracted


def test_fuzzy_ocr_and_invented_model_rows_cannot_authorize_reading(tmp_path,monkeypatch):
    b,n=textbook(tmp_path);original=ranges.page_rows;asked=[]
    def imperfect(book,page):
        result=original(book,page)
        result['rows']=[dict(r,text=r['text'].replace('Definitions','Definitionz')) for r in result['rows']]
        return result
    monkeypatch.setattr(ranges,'page_rows',imperfect)
    class Model:
        async def complete(self,system,user,**kw):
            asked.append((system,user));return j({'row_id':'99999:0:1','reason':'fabricated boundary'})
        async def close(self):pass
    async def scenario():
        job=ranges.range_job(b['id'],[n[1]['id']],provider='fixture',model='fixture',foreground=True,read_after=True,allow_ai=True)
        worker=library_worker.LibraryWorker(lambda p:Model())
        worker.launch(job['id']);await worker.tasks[job['id']]
        return library.public_job(one('SELECT * FROM library_jobs WHERE id=?',(job['id'],)))
    result=asyncio.run(scenario());node=library.node(n[1]['id'])
    assert result['status']=='completed' and result['result']['pending_node_ids']==[node['id']]
    assert asked and not node['confirmed'] and node['start_page']==3
    assert not many("SELECT * FROM library_jobs WHERE kind='read'")
    with pytest.raises(ValueError):library.normalize_nodes(b['id'],[node['id']])


def test_outline_edit_during_detection_survives_atomic_recheck(tmp_path,monkeypatch):
    b,n=textbook(tmp_path);original=ranges.page_rows;edited=False
    def edit_during_scan(book,page):
        nonlocal edited
        if not edited:
            edited=True;library.update_node(n[1]['id'],{'title':'My corrected chapter'})
        return original(book,page)
    monkeypatch.setattr(ranges,'page_rows',edit_during_scan)
    result=asyncio.run(locate(b,[n[1]['id']]))
    assert result['status']=='failed' and '没有覆盖手动修改' in result['error']
    current=library.node(n[1]['id'])
    assert current['title']=='My corrected chapter' and not current['confirmed']
    assert not any(unj(r['provenance_json']).get('auto_range') for r in many('SELECT * FROM library_nodes'))


def test_crash_after_applying_ranges_reuses_one_followup_job(tmp_path):
    b,n=textbook(tmp_path)
    async def scenario():
        row=ranges.range_job(b['id'],[n[0]['id'],n[1]['id']],provider='fixture',model='fixture',foreground=True,
            parallel=True,read_after=True)
        control=library_worker.LibraryControl(row['id'])
        payload=row['payload']
        first=await ranges.run_ranges(control,b,payload,lambda p:pytest.fail('No model needed'))
        # Simulate restart between range application/handoff and worker completion.
        second=await ranges.run_ranges(control,b,payload,lambda p:pytest.fail('Cached result must be reused'))
        assert first['read_job_id']==second['read_job_id']
        jobs=many("SELECT * FROM library_jobs WHERE kind='read'")
        assert len(jobs)==1
        followup=unj(jobs[0]['payload_json'])
        assert followup['node_ids']==[n[0]['id']]  # parent contains child
        assert followup['foreground'] and followup['parallel'] and followup['origin_job_id']==row['id']
    asyncio.run(scenario())


def test_failure_before_handoff_retries_without_losing_confirmed_ranges(tmp_path,monkeypatch):
    b,n=textbook(tmp_path);original=library_worker.new_read_job
    async def scenario():
        row=ranges.range_job(b['id'],[n[1]['id']],provider='fixture',model='fixture',foreground=True,read_after=True)
        control=library_worker.LibraryControl(row['id'])
        monkeypatch.setattr(library_worker,'new_read_job',lambda *a,**kw:(_ for _ in ()).throw(ValueError('queue temporarily unavailable')))
        with pytest.raises(ValueError,match='queue temporarily'):
            await ranges.run_ranges(control,b,row['payload'],lambda p:None)
        assert library.node(n[1]['id'])['confirmed']
        monkeypatch.setattr(library_worker,'new_read_job',original)
        retried=await ranges.run_ranges(control,b,row['payload'],lambda p:pytest.fail('Must reuse applied result'))
        assert retried['read_job_id'] and len(many("SELECT id FROM library_jobs WHERE kind='read'"))==1
    asyncio.run(scenario())


def test_unresolvable_mapping_stays_pending_instead_of_scanning_entire_book(tmp_path,monkeypatch):
    b,n=textbook(tmp_path)
    monkeypatch.setattr(ranges,'page_rows',lambda book,page:{'page':page,'method':'local_ocr','rows':[
        {'text':'Unreadable body, no headings or page numbers','top':.5,'bottom':.53,'score':.5}]})
    result=asyncio.run(locate(b,[n[1]['id']]))
    assert result['status']=='completed' and result['result']['mapping']['offset'] is None
    assert result['result']['pending_node_ids']==[n[1]['id']] and not library.node(n[1]['id'])['confirmed']
    assert result['result']['boundary_pages']<=12


def test_range_endpoint_accepts_foreground_and_rejects_foreign_nodes(tmp_path):
    b,n=textbook(tmp_path)
    with TestClient(server.app) as client:
        response=client.post(f"/api/library/books/{b['id']}/ranges",json={'node_ids':[n[1]['id']],
            'foreground':True,'allow_ai':False})
        assert response.status_code==200,response.text
        assert response.json()['kind']=='ranges' and response.json()['payload']['foreground']
        invalid=client.post(f"/api/library/books/{b['id']}/ranges",json={'node_ids':[uid()]})
        assert invalid.status_code==400


def test_geometry_ocr_cache_is_reused_and_temporary_image_is_removed(tmp_path,monkeypatch):
    from PIL import Image
    image=tmp_path/'scan.png';Image.new('RGB',(400,600),'white').save(image)
    path=tmp_path/'scan.pdf'
    with fitz.open() as doc:
        page=doc.new_page(width=400,height=600);page.insert_image(page.rect,filename=str(image));doc.save(path)
    b=library.import_book(path,path.name)['book'];calls=[]
    def ocr(path):
        calls.append(str(path));return [{'text':'Chapter 1','y':150,'height':30,'scores':[.95,.98]}]
    monkeypatch.setattr(library,'ocr_rows',ocr)
    first=ranges.page_rows(b,1);second=ranges.page_rows(b,1)
    assert first==second and len(calls)==1 and not Path(calls[0]).exists()
    assert first['method']=='local_ocr' and first['rows'][0]['score']==.95
    assert first['rows'][0]['top']==pytest.approx(.15)
