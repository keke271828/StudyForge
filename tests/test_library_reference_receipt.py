"""Receipts describe exactly what was supplied, without copying source bodies."""
import asyncio
import hashlib
from pathlib import Path

import pytest

from studyforge import library,library_history,server
from studyforge.db import create_job,execute,j,many,now,one,unj
from test_global_library import chat,scoped_node,setup_book
from test_library_generation_evidence import add_reading,prepared
from test_library_retrieval import book,reading,snapshot


def test_receipt_keeps_exact_spans_version_and_hash_without_original_or_note_bodies(tmp_path):
    b=book(tmp_path)
    raw='UNIQUE_ORIGINAL_BODY '*400+'needle: the denominator must be nonzero.'
    n,ident=reading(b,'必要条件',{1:raw},notes='UNIQUE_NOTE_BODY '*500,visual='图像核对 needle '+('可见条件。'*120))
    result=library.reference_content(snapshot(b,[n]),'needle',max_chars=1800)
    receipt=library.reference_receipt(result)
    assert receipt['context_characters']==len(result['text'])<=1800
    assert receipt['context_sha256']==hashlib.sha256(result['text'].encode()).hexdigest()
    source=receipt['sources'][0]
    assert source['library_reading']['id']==ident and source['library_reading']['model']=='fixture'
    assert source['scope']['start_page']==source['scope']['end_page']==1
    assert source['pages'][0]['original_excerpt']==result['evidence'][0]['original_excerpt']
    assert source['pages'][0]['visual_excerpt']==result['evidence'][0]['visual_excerpt']
    assert source['purpose']=='reference' and source['included'] and receipt['truncated']
    assert 'UNIQUE_ORIGINAL_BODY' not in j(receipt) and 'UNIQUE_NOTE_BODY' not in j(receipt)


def test_omitted_nodes_are_not_reported_as_provided_pages(tmp_path):
    b=book(tmp_path)
    nodes=[reading(b,'条目 '+str(i),{1:'SOURCE_BODY '*1000})[0] for i in range(3)]
    result=library.reference_content(snapshot(b,nodes),'SOURCE_BODY',max_chars=500)
    receipt=library.reference_receipt(result)
    assert len(result['text'])<=500
    assert receipt['omitted_references']==[n['id'] for n in nodes]
    assert len(receipt['sources'])==3
    assert all(not source['included'] and source['pages']==[] for source in receipt['sources'])
    assert not receipt['unread_candidates']


def test_unread_candidate_is_directory_metadata_only(tmp_path):
    b=book(tmp_path);n=library.add_node(b['id'],'尚未阅读的概念')
    result=library.reference_content({'references':[],'candidates':[{'node_id':n['id'],'book_id':b['id'],
        'title':n['title'],'start_page':1,'end_page':2,'state':'unread','notes':'NOT_READ'}]},'概念')
    receipt=library.reference_receipt(result)
    assert not receipt['sources'] and receipt['unread_candidates'][0]['node_id']==n['id']
    assert 'notes' not in receipt['unread_candidates'][0] and 'NOT_READ' not in j(receipt)


def test_reference_excerpt_never_reads_an_outside_page_even_if_it_is_more_relevant(tmp_path):
    b=book(tmp_path);n,ident=reading(b,'只授权第一页',{1:'AUTHORIZED: a condition.'})
    execute('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',
        (ident,2,'PDF 第 2 页','OUTSIDE_SCOPE needle needle needle','',None,None))
    result=library.reference_content(snapshot(b,[n]),'needle')
    assert 'AUTHORIZED' in result['text'] and 'OUTSIDE_SCOPE' not in result['text']
    assert {page['page'] for page in result['evidence']}=={1}


def test_tutor_recheck_also_enforces_node_scope_with_an_outside_cached_page(tmp_path):
    from studyforge.agent_tools import AgentRuntime,ReadLibrary
    b=book(tmp_path);n,ident=reading(b,'只授权第一页',{1:'AUTHORIZED: a condition.'})
    execute('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',
        (ident,2,'PDF 第 2 页','OUTSIDE_SCOPE needle needle needle','',None,None))
    p,c=chat();library.set_preferences(c,p['id'],'manual',[{'node_id':n['id'],'purpose':'reference'}])
    async def scenario():
        runtime=AgentRuntime(p['id'],[],provider='deepseek',conversation_id=c)
        result=await runtime.sf_read_library_node(ReadLibrary(node_id=n['id']))
        assert 'AUTHORIZED' in result['text'] and 'OUTSIDE_SCOPE' not in result['text']
        with pytest.raises(PermissionError,match='范围'):
            await runtime.sf_read_library_node(ReadLibrary(node_id=n['id'],page=2))
    asyncio.run(scenario())


def test_shared_page_image_is_verified_once_per_preparation_and_rechecked_next_time(tmp_path,monkeypatch):
    b,_=setup_book(tmp_path)
    first=scoped_node(b,title='第一个范围');first_id=add_reading(b,first)
    second=scoped_node(b,title='同页另一个范围');second_id=add_reading(b,second)
    cache=one('SELECT image_path,image_sha256 FROM library_chunks WHERE reading_id=?',(first_id,))
    execute('UPDATE library_chunks SET image_path=?,image_sha256=? WHERE reading_id=?',
        (cache['image_path'],cache['image_sha256'],second_id))
    refs=snapshot(b,[first,second]);native=library.file_sha256;calls=[]
    def counted(path):calls.append(str(path));return native(path)
    monkeypatch.setattr(library,'file_sha256',counted)
    result=library.reference_content(refs,'ORIGINAL_SOURCE')
    assert len(result['evidence'])==2 and calls.count(cache['image_path'])==1
    Path(cache['image_path']).write_bytes(b'changed cache')
    with pytest.raises(ValueError,match='原页缓存已改变'):library.reference_content(refs,'ORIGINAL_SOURCE')
    assert calls.count(cache['image_path'])==2


def test_history_keeps_the_supplied_scope_and_receipt_after_live_scope_changes(tmp_path):
    b=book(tmp_path);n,_=reading(b,'原节点标题',{1:'needle original source'})
    p,c=chat();result=library.reference_content(snapshot(b,[n]),'needle')
    original=library.version(b,n)
    library.update_node(n['id'],{'title':'后来改名','start_page':2,'end_page':2,'confirmed':True})
    saved=library_history.record(c,p['id'],'知识疑问',result)
    assert saved['nodes'][0]['title']=='原节点标题'
    assert saved['nodes'][0]['source_version']==original
    restored=library_history.history(c,p['id'])['entries'][0]
    assert restored['nodes'][0]['scope_changed']
    assert restored['receipt']['context_sha256']==library.reference_receipt(result)['context_sha256']
    assert 'needle original source' not in one('SELECT payload_json FROM conversation_library_history WHERE id=?',(saved['id'],))['payload_json']


def test_receipt_validation_checks_exact_context(tmp_path):
    from studyforge import library_evidence
    b=book(tmp_path);n,_=reading(b,'概念',{1:'needle original source'})
    result=library.reference_content(snapshot(b,[n]),'needle')
    receipt=library.reference_receipt(result)
    library_evidence.validate(receipt,result['text'])
    with pytest.raises(ValueError,match='书库参考记录与输入不一致'):
        library_evidence.validate(receipt,result['text']+'changed')


def test_mismatched_saved_receipt_stops_the_real_job_before_a_model_call(tmp_path,monkeypatch):
    _,_,_,p,c,saved=prepared(tmp_path)
    result=library.reference_content(saved,'ORIGINAL_SOURCE')
    class Writer:
        model='fixture';effort='none'
        async def complete(self,*a,**kw):pytest.fail('A mismatched reference must not reach the model')
    monkeypatch.setattr(server,'client_for',lambda *a,**kw:Writer())
    value=server.GenerateIn(project_id=p['id'],conversation_id=c,source_ids=[],provider='deepseek',model='fixture',
        format='docx',review_mode='express',library_snapshot=saved,library_context=result['text']+'changed',
        library_evidence=library.reference_receipt(result))
    job=create_job(p['id'],'generate',value.model_dump());asyncio.run(server._generate_job(job,value))
    row=one('SELECT status,error FROM jobs WHERE id=?',(job,))
    assert row['status']=='failed' and '书库参考记录与输入不一致' in row['error']
    assert not many('SELECT * FROM artifacts WHERE project_id=?',(p['id'],))


def test_launch_rebuilds_client_supplied_context_and_receipt_on_server(tmp_path,monkeypatch):
    _,_,ident,p,c,_=prepared(tmp_path)
    async def chosen(value):pass
    monkeypatch.setattr(server,'choose_generation_model',chosen)
    monkeypatch.setattr(server,'start_job',lambda job,coroutine:coroutine.close())
    value=server.GenerateIn(project_id=p['id'],conversation_id=c,source_ids=[],provider='deepseek',model='fixture',
        format='docx',review_mode='express',instructions='ORIGINAL_SOURCE',library_context='INJECTED_CONTEXT',
        library_evidence={'sources':[{'title':'INJECTED_RECEIPT'}]})
    launched=asyncio.run(server.generate(value))
    saved=unj(one('SELECT payload_json FROM jobs WHERE id=?',(launched['job_id'],))['payload_json'])
    receipt=saved['library_evidence']
    assert 'INJECTED_CONTEXT' not in saved['library_context'] and 'INJECTED_RECEIPT' not in j(receipt)
    assert receipt['sources'][0]['library_reading']['id']==ident
    assert receipt['context_sha256']==hashlib.sha256(saved['library_context'].encode()).hexdigest()


def test_deleted_live_node_does_not_erase_a_prepared_input_record(tmp_path):
    b=book(tmp_path);n,ident=reading(b,'保存的标题',{1:'needle original source'})
    p,c=chat();result=library.reference_content(snapshot(b,[n]),'needle')
    library.delete_book(b['id'])
    saved=library_history.record(c,p['id'],'知识疑问',result)
    restored=library_history.history(c,p['id'])['entries'][0]
    assert restored['id']==saved['id'] and not restored['nodes'][0]['available']
    assert restored['nodes'][0]['title']=='保存的标题'
    assert restored['receipt']['sources'][0]['library_reading']['id']==ident


def test_omitted_only_lookup_is_saved_without_claiming_the_pages_were_read(tmp_path):
    b=book(tmp_path);n,_=reading(b,'未提供的章节',{1:'SOURCE_BODY '*1000})
    p,c=chat();result=library.reference_content(snapshot(b,[n]),'SOURCE_BODY',max_chars=100)
    saved=library_history.record(c,p['id'],'知识疑问',result)
    assert saved['nodes'][0]['kind']=='omitted' and saved['nodes'][0]['pages']==[]
    restored=library_history.history(c,p['id'])['entries'][0]
    assert not restored['receipt']['sources'][0]['included']
    assert not many('SELECT * FROM learning_events') and not many('SELECT * FROM mastery')


def test_real_export_keeps_background_receipt_and_pinned_version_after_a_new_reading(tmp_path,monkeypatch):
    b,_=setup_book(tmp_path)
    primary=scoped_node(b,title='重点对象');add_reading(b,primary)
    background=scoped_node(b,title='参考背景');old=add_reading(b,background,marker='BACKGROUND_OLD')
    p,c=chat();library.set_preferences(c,p['id'],'manual',[{'node_id':primary['id'],'purpose':'primary'},
        {'node_id':background['id'],'purpose':'reference'}])
    saved=library.reference_snapshot(c,p['id'],'BACKGROUND_OLD')
    result=library.reference_content(saved,'BACKGROUND_OLD')
    receipt=library.reference_receipt(result)
    add_reading(b,background,'newer-reader','BACKGROUND_NEW')
    inputs=[]
    class Writer:
        model='fixture';effort='none'
        async def complete(self,system,user,**kw):
            inputs.append(user)
            return '# 条件的讲解\n\n区分定义、条件和参考来源。\n\n## 系统性总结\n原文条件需要一起核对。'
    monkeypatch.setattr(server,'client_for',lambda *a,**kw:Writer())
    value=server.GenerateIn(project_id=p['id'],conversation_id=c,source_ids=[],provider='deepseek',model='fixture',
        format='docx',review_mode='express',library_snapshot=saved,library_context=result['text'],library_evidence=receipt)
    job=create_job(p['id'],'generate',value.model_dump());asyncio.run(server._generate_job(job,value))
    state=one('SELECT * FROM jobs WHERE id=?',(job,));assert state['status']=='completed',state['error']
    artifact=many("SELECT * FROM artifacts WHERE project_id=? AND kind='explanation'",(p['id'],))[0]
    actual=unj(artifact['metadata_json'])['library_evidence']
    ref=next(source for source in actual['sources'] if source['purpose']=='reference')
    assert ref['library_reading']['id']==old
    assert actual['context_sha256']==receipt['context_sha256']
    assert any('BACKGROUND_OLD' in text for text in inputs) and not any('BACKGROUND_NEW' in text for text in inputs)
    assert Path(artifact['path']).read_bytes()[:2]==b'PK'


def test_long_document_receipt_matches_the_reference_received_by_every_chapter(tmp_path,monkeypatch):
    b,_=setup_book(tmp_path);primary=scoped_node(b,title='重点对象');add_reading(b,primary)
    background,ident=reading(b,'参考背景',{1:'BACKGROUND_CONDITION '*1000},notes='BACKGROUND_NOTE '*2000)
    p,c=chat();library.set_preferences(c,p['id'],'manual',[{'node_id':primary['id'],'purpose':'primary'},
        {'node_id':background['id'],'purpose':'reference'}])
    saved=library.reference_snapshot(c,p['id'],'BACKGROUND_CONDITION')
    result=library.reference_content(saved,'BACKGROUND_CONDITION');inputs=[]
    class Writer:
        model='fixture';effort='none'
        async def complete(self,system,user,**kw):
            inputs.append(user)
            return '# 条件的讲解\n\n需要核对原文条件。\n\n## 系统性总结\n保留原文范围。'
    monkeypatch.setattr(server,'client_for',lambda *a,**kw:Writer())
    monkeypatch.setattr(server,'explanation_batches',lambda digest:['完整首部原文','完整后部原文'])
    value=server.GenerateIn(project_id=p['id'],conversation_id=c,source_ids=[],provider='deepseek',model='fixture',
        format='docx',review_mode='express',instructions='BACKGROUND_CONDITION',library_snapshot=saved,
        library_context=result['text'],library_evidence=library.reference_receipt(result))
    job=create_job(p['id'],'generate',value.model_dump());asyncio.run(server._generate_job(job,value))
    state=one('SELECT * FROM jobs WHERE id=?',(job,));assert state['status']=='completed',state['error']
    artifact=many("SELECT * FROM artifacts WHERE project_id=? AND kind='explanation'",(p['id'],))[0]
    actual=unj(artifact['metadata_json'])['library_evidence']
    assert actual['context_characters']<=6000 and actual['shared_chapter_count']==2
    stored=unj(one("SELECT response FROM generation_steps WHERE job_id=? AND step_key='library_document_reference'",(job,))['response'])
    assert len(stored['text'])==actual['context_characters'] and stored['receipt']==actual
    assert sum(stored['text'] in prompt for prompt in inputs)==2
    assert any(source['included'] and source['library_reading']['id']==ident for source in actual['sources'])
    assert actual['context_sha256']==hashlib.sha256(stored['text'].encode()).hexdigest()
    from studyforge.library_evidence import for_document
    monkeypatch.setattr(library,'reference_content',lambda *a,**kw:pytest.fail('A resumed task must reuse its bounded local input'))
    resumed=for_document(job,saved,value.instructions,value.library_context,value.library_evidence,2)
    assert resumed==stored


def test_long_reading_notes_cannot_hide_the_library_reference_from_a_chapter(tmp_path,monkeypatch):
    _,_,_,p,c,saved=prepared(tmp_path)
    result=library.reference_content(saved,'ORIGINAL_SOURCE');inputs=[]
    class Writer:
        model='fixture';effort='none'
        async def complete(self,system,user,**kw):
            inputs.append(user)
            return '# 讲解\n\n保持原文范围。\n\n## 系统性总结\n检查原文条件。'
    monkeypatch.setattr(server,'client_for',lambda *a,**kw:Writer())
    monkeypatch.setattr(server,'explanation_batches',lambda digest:['首部完整原文','后部完整原文'])
    monkeypatch.setattr(server.lesson_quality,'chapter_context',lambda *a:'READING_NOTES '*3000)
    value=server.GenerateIn(project_id=p['id'],conversation_id=c,source_ids=[],provider='deepseek',model='fixture',
        format='docx',review_mode='express',instructions='ORIGINAL_SOURCE',library_snapshot=saved,
        library_context=result['text'],library_evidence=library.reference_receipt(result))
    job=create_job(p['id'],'generate',value.model_dump());asyncio.run(server._generate_job(job,value))
    state=one('SELECT * FROM jobs WHERE id=?',(job,));assert state['status']=='completed',state['error']
    stored=unj(one("SELECT response FROM generation_steps WHERE job_id=? AND step_key='library_document_reference'",(job,))['response'])
    assert sum(stored['text'] in prompt for prompt in inputs)==2
