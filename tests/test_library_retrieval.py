"""Retrieval must cover late pages, preserve source scope and bound context."""
import asyncio

import fitz
import pytest
from fastapi.testclient import TestClient

from studyforge import library, server
from studyforge.db import connect, create_project, execute, j, now, uid


def book(tmp_path,pages=3):
    path=tmp_path/'book.pdf'
    with fitz.open() as doc:
        for page in range(pages):
            p=doc.new_page();p.insert_text((40,60),f'Source page {page+1}')
        doc.save(path)
    return library.import_book(path,path.name)['book']


def reading(b,title,pages,notes='',visual='',warnings=None):
    n=library.add_node(b['id'],title)
    n=library.update_node(n['id'],{'start_page':min(pages),'end_page':max(pages),'confirmed':True})
    ident=uid();signature=library.reading_signature(b,n,'fixture','fixture','none')
    execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,warnings_json,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (ident,n['id'],signature,'fixture','fixture','none','completed',notes,j(warnings or []),now(),now()))
    with connect() as db:
        db.executemany('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',
                      [(ident,page,f'PDF 第 {page} 页',text,visual,None,None) for page,text in pages.items()])
    return n,ident


def snapshot(b,nodes):
    return {'references':[{'node_id':n['id'],'purpose':'reference','source_version':library.version(b,n)} for n in nodes],
            'candidates':[],'mode':'manual'}


def test_raw_hit_after_first_120_matches_is_ranked_not_lost(tmp_path):
    b=book(tmp_path,131)
    early,_=reading(b,'前面的章节',{p:'boundary_exception is mentioned.' for p in range(1,131)})
    late,_=reading(b,'后面的章节',{131:'boundary_exception boundary_exception boundary_exception: decisive condition.'})
    found=library.search('boundary_exception')
    assert found[0]['node_id']==late['id']
    assert found[0]['matched_pages'][0]['page']==131
    assert early['id'] in {n['node_id'] for n in found}


def test_visual_term_is_searchable_and_identified_as_ai_record(tmp_path):
    b=book(tmp_path)
    n,_=reading(b,'第四小节',{1:'[OCR 未完成]'},visual='本页图像中可见：单射（injectivity）的定义。')
    found=library.search('injectivity')
    assert found[0]['node_id']==n['id'] and found[0]['match_kind']=='visual'
    result=library.reference_content(snapshot(b,[n]),'injectivity')
    assert 'injectivity' in result['text'] and '非原文引语' in result['text']


def test_previous_valid_reading_is_used_when_newer_completed_row_has_wrong_scope(tmp_path):
    b=book(tmp_path)
    n,ident=reading(b,'定义所在节',{1:'valid_marker is in the original.'})
    invalid=uid()
    execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
            (invalid,n['id'],'wrong-range','fixture','fixture','none','completed',now(),now()))
    execute('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',(invalid,2,'PDF 第 2 页','invalid_marker', '',None,None))
    assert library.search('valid_marker')[0]['state']=='read'
    assert not library.search('invalid_marker')


def test_changed_range_does_not_search_or_quote_old_body(tmp_path):
    b=book(tmp_path)
    n,_=reading(b,'目录甲',{1:'stale_marker appears here.'})
    library.update_node(n['id'],{'start_page':2,'end_page':2,'confirmed':True})
    assert not library.search('stale_marker')


def test_restricted_search_ranks_inside_allowed_nodes(tmp_path):
    b=book(tmp_path)
    allowed,_=reading(b,'允许的节点',{1:'closure is defined.'})
    for i in range(8):reading(b,'closure closure 其他节点 '+str(i),{2:'closure closure closure'})
    assert allowed['id'] not in {n['node_id'] for n in library.search('closure')}
    found=library.search('closure',6,[allowed['id']])
    assert [n['node_id'] for n in found]==[allowed['id']]


def test_manual_agent_search_cannot_be_crowded_out_by_unselected_nodes(tmp_path):
    from studyforge.agent_tools import AgentRuntime,SearchLibrary
    b=book(tmp_path);allowed,_=reading(b,'允许的小节',{1:'closure applies.'})
    for i in range(8):reading(b,'closure closure 其他 '+str(i),{2:'closure closure closure'})
    p=create_project('本项目');c=uid()
    execute('INSERT INTO conversations(id,project_id,provider,created_at) VALUES (?,?,?,?)',(c,p['id'],'deepseek',now()))
    library.set_preferences(c,p['id'],'manual',[{'node_id':allowed['id'],'purpose':'reference'}])
    runtime=AgentRuntime(p['id'],conversation_id=c,provider='deepseek')
    found=asyncio.run(runtime.sf_search_library(SearchLibrary(query='closure')))
    assert [n['node_id'] for n in found['nodes']]==[allowed['id']]


def test_long_page_excerpt_preserves_query_at_tail_and_honest_offsets(tmp_path):
    b=book(tmp_path)
    raw=('Unrelated introductory material.\n'*950)+'epsilon_selection: choose half the distance because the open neighbourhoods do not intersect.\n'
    n,_=reading(b,'证明',{1:raw})
    result=library.reference_content(snapshot(b,[n]),'epsilon_selection',max_chars=2200)
    assert 'epsilon_selection' in result['text']
    assert '前部省略' in result['text'] and result['truncated']
    assert len(result['text'])<=2200
    span=result['evidence'][0]['original_excerpt']
    assert span['start_char']>10000
    assert 'epsilon_selection' in raw[span['start_char']:span['end_char']]


def test_relevant_page_retains_adjacent_definition_context(tmp_path):
    b=book(tmp_path,5)
    n,ident=reading(b,'长证明',{1:'INTRO',2:'OTHER',3:'PREVIOUS_DEFINITION: necessary hypothesis.',
                             4:'needle_proof: uses the definition.',5:'NEXT_STEP'})
    chunks=library.reference_chunks(ident,library.terms('needle_proof'))
    pages={c['page'] for c in chunks}
    assert 4 in pages and 3 in pages
    assert len(chunks)<=3


def test_context_shares_include_all_selected_nodes_and_all_labels(tmp_path):
    b=book(tmp_path)
    nodes=[reading(b,'小节 '+str(i),{1:'needle_marker '+('原文细节\n'*1800)},
                   notes='needle_marker '+('导航笔记\n'*500),visual='needle_marker '+('图像核对\n'*200))[0] for i in range(12)]
    result=library.reference_content(snapshot(b,nodes),'needle_marker',max_chars=18000)
    assert len(result['text'])<=18000
    assert {e['node_id'] for e in result['evidence']}=={n['id'] for n in nodes}
    assert not result['omitted_references'] and result['truncated']


def test_reading_warnings_are_sent_to_teacher_before_using_excerpts(tmp_path):
    b=book(tmp_path)
    n,_=reading(b,'条件',{1:'The formula needs verification.'},warnings=['PDF 第 1 页：公式中的上下标仍待核对'])
    result=library.reference_content(snapshot(b,[n]),'formula')
    assert '阅读疑点（尚未解决）' in result['text'] and '上下标仍待核对' in result['text']


@pytest.mark.parametrize('cap',[0,80,320,800,1600])
def test_small_context_budget_is_never_exceeded_or_faked(tmp_path,cap):
    b=book(tmp_path);n,_=reading(b,'定义',{1:'needle_marker '+('DETAIL '*1000)})
    result=library.reference_content(snapshot(b,[n]),'needle_marker',max_chars=cap)
    assert len(result['text'])<=cap
    if not result['evidence']:assert result['omitted_references']==[n['id']]


def test_search_route_validates_limit_and_does_not_read_unread_body(tmp_path,monkeypatch):
    b=book(tmp_path);n=library.add_node(b['id'],'Unread injectivity')
    monkeypatch.setattr(library,'extract_page',lambda *a:pytest.fail('搜索不应解析未读正文'))
    with TestClient(server.app) as client:
        response=client.get('/api/library/search',params={'query':'injectivity','limit':12})
        assert response.status_code==200
        assert response.json()['nodes'][0]['node_id']==n['id']
        assert response.json()['nodes'][0]['matched_pages']==[]
        assert client.get('/api/library/search',params={'query':'injectivity','limit':41}).status_code==422
