import asyncio
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

from studyforge import library, library_toc, library_worker, server
from studyforge.db import execute, many, one, unj


def make_book(tmp_path, count=40, contents=None):
    path = tmp_path / 'contents.pdf'
    with fitz.open() as document:
        for number in range(1, count + 1):
            page = document.new_page()
            if contents and number in contents:
                page.insert_text((50, 55), '目录' if number == min(contents) else '目录（续）', fontname='china-s')
                for i, (title, printed) in enumerate(contents[number]):
                    page.insert_text((55, 105 + 30 * i), title, fontname='china-s')
                    page.insert_text((440, 105 + 30 * i), str(printed))
            else:
                page.insert_text((50, 80), 'This is front matter or body text, not a contents page.')
                page.insert_text((50, 120), 'No full-book reading is authorized by this test.')
        document.save(path)
    return library.import_book(path, path.name)['book']


def rows(count=4, label=True, leaders=True):
    result = [{'text': '目 录', 'y': 40, 'height': 16}] if label else []
    for i in range(count):
        result.append({'text': f'第{i+1}章 数学结构 ' + ('…… ' if leaders else ' ') + str(i * 10 + 1),
                       'y': 80 + i * 25, 'height': 16})
    return result


async def run_toc(book, payload):
    worker = library_worker.LibraryWorker(lambda p: pytest.fail('目录识别不能调用云模型'))
    job = library_worker.create_job(book['id'], 'toc', dict(payload, foreground=True))
    worker.launch(job['id'])
    await worker.tasks[job['id']]
    return library.public_job(one('SELECT * FROM library_jobs WHERE id=?', (job['id'],)))


def test_contents_label_and_aligned_columns_are_preserved_without_ocr(tmp_path, monkeypatch):
    book = make_book(tmp_path, contents={3:[('第一章 数域与结构', 1), ('1 有理数及其扩张', 1), ('2 代数运算', 8)]})
    monkeypatch.setattr(library, 'ocr_rows', lambda *a: pytest.fail('原文字可用时无需 OCR'))
    found = library_toc.probe_page(book, 3)
    assert found['strong'] and found['entries'] == 3 and found['layouts'] == 3
    assert found['label'] == ['目录'] and found['method'] == 'native_pdf'
    assert not list((library.root()/book['id']/'toc-discovery').glob('*.png'))
    assert not many('SELECT * FROM library_readings')


def test_no_label_continuation_requires_repeated_contents_layout():
    assert library_toc.classify_rows(rows(label=False), 600, 300)['strong']
    assert library_toc.classify_rows(rows(2, label=False), 600, 300)['continuation']
    assert not library_toc.classify_rows(rows(label=False, leaders=False), 600, 300)['strong']


def test_roman_running_header_is_a_contents_label():
    assert library_toc.classify_rows([{'text':'II 目录'}]+rows(2, label=False),600,300)['strong']


@pytest.mark.parametrize('values', [
    [{'text':'目录'}],
    [{'text':'请先读本书的目录 1'}, {'text':'习题 2'}, {'text':'第一章 3'}],
    [{'text':'第一章 数域 1'}, {'text':'1 对公式证明 2'}, {'text':'2 求和式 3'}, {'text':'习题 4'}],
    rows(1),
    [{'text':'第一章 … 80'}, {'text':'第二章 … 50'}, {'text':'第三章 … 20'}, {'text':'第四章 … 1'}],
])
def test_body_index_and_weak_candidates_do_not_automatically_become_contents(values):
    assert not library_toc.classify_rows(values, 600, 300)['strong']


def test_automatic_directory_stops_after_block_and_keeps_scopes_unconfirmed(tmp_path, monkeypatch):
    book = make_book(tmp_path, contents={
        3:[('第一章 数域',1),('1 数域与封闭运算',1),('2 多项式',8)],
        4:[('第二章 行列式',20),('1 定义',20),('2 展开',25)]})
    probed=[]
    original=library_toc.probe_page
    monkeypatch.setattr(library_toc,'probe_page',lambda b,p:(probed.append(p),original(b,p))[1])
    result=asyncio.run(run_toc(book,{'auto_discover':True,'scan_limit':32}))
    assert result['status']=='completed',result
    found=result['result']['toc_discovery']
    assert found['status']=='found' and found['candidate_pages']==[3,4] and probed==list(range(1,7))
    assert found['model_requests']==0 and result['result']['nodes']==6
    detail=library.details(book['id'])
    assert all(not n['confirmed'] and n['reading'] is None for n in detail['nodes'])
    assert detail['book']['toc_pages']=='3,4'
    assert all(n['provenance']['toc_pdf_page'] in (3,4) for n in detail['nodes'])
    assert not many('SELECT * FROM library_readings')


def test_search_limit_with_more_contents_waits_for_review_instead_of_truncating(tmp_path):
    book=make_book(tmp_path,contents={3:[('第一章 数域',1),('1 数域',1),('2 多项式',8)],
                                      4:[('第二章 行列式',20),('1 定义',20)]})
    result=asyncio.run(run_toc(book,{'auto_discover':True,'scan_limit':3}))
    found=result['result']['toc_discovery']
    assert result['status']=='completed' and found['status']=='review' and found['candidate_pages']==[3]
    assert '后续页' in ''.join(found['warnings'])
    assert not library.details(book['id'])['nodes']


def test_contents_tail_with_only_one_entry_is_included(tmp_path,monkeypatch):
    book=make_book(tmp_path,contents={3:[('第一章 数域',1),('1 数域',1),('2 多项式',8)],
                                      4:[('附录一 代数基础',20)]})
    monkeypatch.setattr(library,'ocr_rows',lambda *a:pytest.fail('短目录续页已有原文字，不应 OCR'))
    result=asyncio.run(run_toc(book,{'auto_discover':True,'scan_limit':32}))
    assert result['status']=='completed' and result['result']['toc_discovery']['status']=='found',result
    assert result['result']['toc_discovery']['candidate_pages']==[3,4]
    assert result['result']['nodes']==4


def test_contents_absent_has_actionable_result_and_cannot_search_entire_book(tmp_path,monkeypatch):
    book=make_book(tmp_path,count=80)
    probed=[]
    monkeypatch.setattr(library_toc,'probe_page',lambda b,p:(probed.append(p),
        {'page':p,'strong':False,'continuation':False,'entries':0,'label':[],'samples':[],'method':'local_ocr'})[1])
    result=asyncio.run(run_toc(book,{'auto_discover':True,'scan_limit':1000}))
    assert probed==list(range(1,65)) and result['status']=='completed'
    assert result['result']['toc_discovery']['status']=='review'
    assert not library.details(book['id'])['nodes']


def test_twelve_page_limit_never_silently_saves_partial_outline(tmp_path,monkeypatch):
    book=make_book(tmp_path)
    def candidate(b,p):
        return {'page':p,'strong':True,'continuation':True,'entries':4,'label':['目录'],
                'samples':['第一章 · 1'],'method':'native_pdf'}
    monkeypatch.setattr(library_toc,'probe_page',candidate)
    result=asyncio.run(run_toc(book,{'auto_discover':True,'scan_limit':32}))
    assert result['result']['toc_discovery']['status']=='review'
    assert len(result['result']['toc_discovery']['inspected_pages'])==13
    assert not library.details(book['id'])['nodes']


def test_unrecognized_page_inside_contents_block_is_not_silently_omitted(tmp_path,monkeypatch):
    book=make_book(tmp_path)
    def candidate(b,p):
        hit=p in (3,5)
        return {'page':p,'strong':hit,'continuation':hit,'entries':4 if hit else 0,
                'label':[],'samples':[],'method':'local_ocr'}
    monkeypatch.setattr(library_toc,'probe_page',candidate)
    result=asyncio.run(run_toc(book,{'auto_discover':True}))
    found=result['result']['toc_discovery']
    assert found['status']=='review' and found['candidate_pages']==[3,4,5]
    assert not library.details(book['id'])['nodes']


def test_step_resume_uses_saved_probes_and_does_not_duplicate_outline(tmp_path,monkeypatch):
    book=make_book(tmp_path,contents={2:[('第一章 数域',1),('1 数域',1),('2 多项式',8)]})
    job=library_worker.create_job(book['id'],'toc',{'auto_discover':True,'scan_limit':32,'foreground':True})
    calls=[];original=library_toc.probe_page
    monkeypatch.setattr(library_toc,'probe_page',lambda b,p:(calls.append(p),original(b,p))[1])
    async def scenario():
        control=library_worker.LibraryControl(job['id'])
        await control.step('toc-probe',[library_toc.VERSION,book['sha256'],1],
                           lambda:asyncio.to_thread(library_toc.probe_page,book,1))
        first=await library_worker.run_directory(control,book,job['payload'])
        before=list(calls)
        monkeypatch.setattr(library,'directory_page',lambda *a:pytest.fail('已提交的目录不能重新识别'))
        second=await library_worker.run_directory(library_worker.LibraryControl(job['id']),book,job['payload'])
        assert first==second and calls==before
    asyncio.run(scenario())
    assert calls==[1,2,3,4] and len(library.details(book['id'])['nodes'])==3


def test_cancelled_discovery_does_not_write_nodes(tmp_path):
    book=make_book(tmp_path)
    job=library_worker.create_job(book['id'],'toc',{})
    execute("UPDATE library_jobs SET status='cancelled' WHERE id=?",(job['id'],))
    with pytest.raises(asyncio.CancelledError):
        library_toc.commit_outline(book['id'],library.parse_directory([(2,rows())]),'2',job['id'],{'nodes':4})
    assert not library.details(book['id'])['nodes'] and library_toc.applied_result(job['id']) is None


def test_one_bad_contents_page_cannot_be_hidden_by_other_good_pages(tmp_path,monkeypatch):
    book=make_book(tmp_path,contents={
        3:[('第一章 数域',1),('1 数域',1),('2 多项式',8)],
        4:[('第二章 行列式',20),('1 定义',20),('2 展开',25)]})
    original=library.directory_page
    monkeypatch.setattr(library,'directory_page',lambda b,p:original(b,p) if p==3 else [{'text':'无法识别'}])
    result=asyncio.run(run_toc(book,{'auto_discover':True}))
    found=result['result']['toc_discovery']
    assert found['status']=='review' and '第 4 页' in ''.join(found['warnings'])
    assert not library.details(book['id'])['nodes']


def test_failed_transaction_rolls_back_outline_as_well_as_checkpoint(tmp_path,monkeypatch):
    book=make_book(tmp_path)
    job=library_worker.create_job(book['id'],'toc',{})
    original=library.save_outline
    def fail_after_save(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('模拟目录写入后异常')
    monkeypatch.setattr(library,'save_outline',fail_after_save)
    with pytest.raises(RuntimeError):
        library_toc.commit_outline(book['id'],library.parse_directory([(2,rows())]),'2',job['id'],{'nodes':4})
    assert not library.details(book['id'])['nodes'] and library_toc.applied_result(job['id']) is None


def test_same_probe_cache_is_shared_without_retaining_ocr_images(tmp_path,monkeypatch):
    path=tmp_path/'scan.pdf'
    with fitz.open() as document:
        document.new_page();document.save(path)
    book=library.import_book(path,path.name)['book']
    calls=[]
    def ocr(path):
        calls.append(path)
        assert path.is_file()
        return rows()
    monkeypatch.setattr(library,'ocr_rows',ocr)
    first=library_toc.probe_page(book,1);second=library_toc.probe_page(book,1)
    assert first==second and first['method']=='local_ocr' and len(calls)==1 and not calls[0].exists()
    cached=(library.root()/book['id']/'toc-discovery'/f'{library_toc.VERSION}-1.json').read_text(encoding='utf-8')
    assert 'rows' not in unj(cached) and not many('SELECT * FROM library_readings')


def test_toc_api_explicit_automatic_option_and_duplicate_guard(tmp_path):
    book=make_book(tmp_path)
    client=TestClient(server.app)
    url='/api/library/books/'+book['id']+'/toc'
    for payload in ({}, {'auto_discover':True,'page_spec':'2'}, {'auto_discover':True,'scan_limit':65}):
        assert client.post(url,json=payload).status_code in (400,422)
    assert not many('SELECT * FROM library_jobs')
    result=client.post(url,json={'auto_discover':True,'foreground':True})
    assert result.status_code==200 and result.json()['payload']['auto_discover']
    assert client.post(url,json={'page_spec':'2'}).status_code==409


def test_manual_directory_still_accepts_exact_page_mapping(tmp_path):
    book=make_book(tmp_path,contents={3:[('第一章 数域',1),('1 数域',1),('2 多项式',8)]})
    result=asyncio.run(run_toc(book,{'page_spec':'3','first_printed':1,'first_pdf':6}))
    assert result['status']=='completed' and result['result']['nodes']==3
    assert library.details(book['id'])['nodes'][0]['start_page']==6
