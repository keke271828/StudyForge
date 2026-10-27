"""Agent page reads retain supplied spans and their launch reading version."""
import asyncio
import hashlib

import pytest

from studyforge import library, library_history
from studyforge.agent_tools import AgentRuntime, ReadLibrary
from studyforge.db import execute, j, many
from test_global_library import chat
from test_library_retrieval import book, reading
from test_library_query_memory import add_version, original_text


def prepared(tmp_path):
    b=book(tmp_path)
    pages=[(1,'PRIVATE_ORIGINAL_ONE: alpha '*50,'AI_IMAGE_ONE: observed symbols.'),
           (2,'PRIVATE_ORIGINAL_TWO: beta '*50,'AI_IMAGE_TWO: needs verification.')]
    n,rid=reading(b,'当时的章节标题',{p:raw for p,raw,_ in pages},notes='PRIVATE_NOTE_BODY '*200)
    for page,_,visual in pages:
        execute('UPDATE library_chunks SET visual_text=? WHERE reading_id=? AND page=?',(visual,rid,page))
    p,c=chat();library.set_preferences(c,p['id'],'manual',[{'node_id':n['id'],'purpose':'reference'}])
    runtime=AgentRuntime(p['id'],conversation_id=c,provider='deepseek',model='fixture')
    return b,n,rid,p,c,runtime,pages


def read(runtime,n,**kwargs):
    return asyncio.run(runtime.sf_read_library_node(ReadLibrary(node_id=n['id'],**kwargs)))


def test_agent_read_receipt_matches_public_text_and_only_actual_body_page(tmp_path):
    b,n,rid,p,c,runtime,pages=prepared(tmp_path)
    text=original_text(b,n,[pages[1]])
    offset=text.index('PRIVATE_ORIGINAL_TWO')+5
    value=read(runtime,n,page=2,offset=offset,limit=100)
    assert value['text']==text[offset:offset+100]
    receipt=value['library_history']['receipt']
    assert receipt['input_kind']=='agent_library_read'
    assert receipt['context_sha256']==hashlib.sha256(value['text'].encode()).hexdigest()
    source=receipt['sources'][0]
    assert source['library_reading']['id']==rid and source['included']
    assert [r['page'] for r in source['pages']]==[2]
    span=source['pages'][0]['original_excerpt']
    assert (span['start_char'],span['end_char'],span['total_chars'])==(5,105,len(pages[1][1]))
    assert source['pages'][0]['visual_excerpt']['end_char']==0
    assert receipt['read_window']['offset']==offset and receipt['read_window']['limit']==100
    saved=library_history.history(c,p['id'])['entries'][0]
    assert saved['receipt']==receipt and saved['nodes'][0]['pages']==[2]
    assert all(token not in j(saved) for token in ('PRIVATE_ORIGINAL_ONE','PRIVATE_ORIGINAL_TWO','PRIVATE_NOTE_BODY'))


def test_frozen_older_reading_is_not_relabelled_as_a_new_reading(tmp_path):
    b,n,old,p,c,runtime,pages=prepared(tmp_path)
    runtime.library_snapshot=library.reference_snapshot(c,p['id'],'原文')
    newer=add_version(b,n,model='NEWER_MODEL',notes='NEWER_NOTE')
    execute('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',(newer,1,'PDF 第 1 页','NEWER_PAGE','',None,None))
    assert library.ready_reading(n,metadata_only=True)['id']==newer
    value=read(runtime,n,page=1)
    receipt=value['library_history']['receipt']
    assert 'PRIVATE_ORIGINAL_ONE' in value['text']
    assert receipt['sources'][0]['library_reading']['id']==old
    assert receipt['sources'][0]['library_reading']['model']=='fixture'
    assert 'NEWER_MODEL' not in j(receipt)


def test_directory_change_after_read_does_not_rewrite_historical_source_scope(tmp_path,monkeypatch):
    b,n,rid,p,c,runtime,pages=prepared(tmp_path)
    native=library.read_text_window
    def change_after_read(*args,**kwargs):
        result=native(*args,**kwargs)
        library.update_node(n['id'],{'title':'后来改名的章节','end_y':.5,'confirmed':True})
        return result
    monkeypatch.setattr(library,'read_text_window',change_after_read)
    value=read(runtime,n,page=1)
    saved=library_history.history(c,p['id'])['entries'][0]
    assert value['library_history']['nodes'][0]['title']==n['title']
    assert saved['nodes'][0]['scope_changed']
    assert saved['receipt']['sources'][0]['scope']['end_y']==1


@pytest.mark.parametrize('position',['header_only','past_end'])
def test_no_source_body_is_not_published_as_an_original_page_read(tmp_path,position):
    b,n,rid,p,c,runtime,pages=prepared(tmp_path)
    if position=='header_only':
        # A long but valid node title can fill the whole first 100 characters.
        n=library.update_node(n['id'],{'title':'很长的目录标题'*30})
        offset=0
    else:offset=len(original_text(b,n,[pages[0]]))+100
    value=read(runtime,n,page=1,offset=offset,limit=100)
    saved=value['library_history']
    assert saved is None or all(hit['kind']!='original' for hit in saved['nodes'])
    if saved:
        assert not saved['receipt']['sources'][0]['included']
        assert saved['receipt']['sources'][0]['pages']==[]


def test_visual_only_slice_retains_ai_provenance_without_claiming_raw_ocr(tmp_path):
    b,n,rid,p,c,runtime,pages=prepared(tmp_path)
    text=original_text(b,n,[pages[0]])
    offset=text.index('AI_IMAGE_ONE')
    value=read(runtime,n,page=1,offset=offset,limit=100)
    page=value['library_history']['receipt']['sources'][0]['pages'][0]
    assert page['original_excerpt']['end_char']==0
    assert page['visual_excerpt']['start_char']==0 and page['visual_excerpt']['end_char']==len(pages[0][2])


def test_cross_page_window_records_only_intersecting_original_ranges(tmp_path):
    b,n,rid,p,c,runtime,pages=prepared(tmp_path)
    whole=original_text(b,n,pages)
    first=whole.index('PRIVATE_ORIGINAL_ONE')
    offset=first+len(pages[0][1])-30
    value=read(runtime,n,offset=offset,limit=300)
    assert value['text']==whole[offset:offset+300]
    evidence=value['library_history']['receipt']['sources'][0]['pages']
    assert [r['page'] for r in evidence]==[1,2]
    assert evidence[0]['original_excerpt']['start_char']==len(pages[0][1])-30
    assert evidence[1]['original_excerpt']['start_char']==0


@pytest.mark.parametrize('hidden',['private_context','document','non_publishing','unbound'])
def test_hidden_document_or_grading_branch_still_writes_no_public_navigation(tmp_path,hidden):
    b,n,rid,p,c,runtime,pages=prepared(tmp_path)
    if hidden=='private_context':runtime.private_context=True
    elif hidden=='document':runtime.job_id='document-job'
    elif hidden=='non_publishing':runtime.publishing=False
    else:
        runtime.library_snapshot=library.reference_snapshot(c,p['id'],'原文')
        runtime.conversation_id=None
    if hidden=='unbound':
        with pytest.raises(PermissionError,match='学习对话'):read(runtime,n,page=1)
        assert asyncio.run(runtime.remember_library_lookup('no owner',evidence=[{'node_id':n['id'],'page':1}])) is None
    else:assert read(runtime,n,page=1)['library_history'] is None
    assert not many('SELECT * FROM conversation_library_history')


@pytest.mark.parametrize('offset_kind',['header','raw_start','raw_end','visual_start','past_end'])
def test_unicode_window_spans_exactly_reconstruct_returned_layers(tmp_path,offset_kind):
    b,n,rid,p,c,runtime,pages=prepared(tmp_path)
    raw='原文\x00甲😀e\u0301乙'*30
    visual='图像AI\x00😀e\u0301'*18
    execute('UPDATE library_chunks SET original_text=?,visual_text=? WHERE reading_id=? AND page=1',(raw,visual,rid))
    whole=original_text(b,n,[(1,raw,visual)])
    raw_start=whole.index(raw);visual_start=whole.index(visual)
    offset={'header':0,'raw_start':raw_start+5,'raw_end':raw_start+len(raw)-8,
            'visual_start':visual_start+5,'past_end':len(whole)+20}[offset_kind]
    value=library.read_text_window(rid,b['title'],n['title'],page=1,offset=offset,limit=12)
    assert value['text']==whole[offset:offset+12] and value['total_characters']==len(whole)
    supplied=value['provided_pages']
    if offset_kind in ('header','past_end'):assert not supplied
    else:
        assert len(supplied)==1 and supplied[0]['page']==1
        for key,body,start in [('original_excerpt',raw,raw_start),('visual_excerpt',visual,visual_start)]:
            span=supplied[0][key]
            expected=whole[max(offset,start):min(offset+12,start+len(body))] if offset<start+len(body) and offset+12>start else ''
            assert body[span['start_char']:span['end_char']]==expected
            assert span['total_chars']==len(body)


def test_deleted_node_after_read_keeps_captured_provenance_without_live_lookup(tmp_path,monkeypatch):
    b,n,rid,p,c,runtime,pages=prepared(tmp_path)
    native=library.read_text_window
    def delete_after_read(*args,**kwargs):
        value=native(*args,**kwargs)
        execute('DELETE FROM library_nodes WHERE id=?',(n['id'],))
        return value
    monkeypatch.setattr(library,'read_text_window',delete_after_read)
    value=read(runtime,n,page=1)
    saved=library_history.history(c,p['id'])['entries'][0]
    assert saved['nodes'][0]['available'] is False
    assert saved['receipt']==value['library_history']['receipt']
    assert saved['receipt']['sources'][0]['library_reading']['id']==rid
    assert saved['receipt']['sources'][0]['scope']['end_y']==1


def test_receipt_window_is_whitelisted_and_regular_reference_schema_is_unchanged(tmp_path):
    from studyforge.library_evidence import receipt
    ordinary=receipt({'text':'sample','sources':[],'mode':'manual'})
    assert 'input_kind' not in ordinary and 'read_window' not in ordinary and 'image_rechecked' not in ordinary
    direct=receipt({'text':'sample','sources':[],'input_kind':'agent_library_read',
                    'read_window':{'page':2,'offset':0,'limit':100,'next_offset':None,
                                   'total_characters':6,'private_body':'SECRET_BODY'},'image_rechecked':True})
    assert direct['image_rechecked'] is True
    assert set(direct['read_window'])=={'page','offset','limit','next_offset','total_characters'}
    assert 'SECRET_BODY' not in j(direct)
