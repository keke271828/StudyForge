"""Original evidence must remain complete and consistent with a launched task."""
import asyncio
from pathlib import Path
import tracemalloc

import pytest
from fastapi import HTTPException

from studyforge import library, library_annotations, server
from studyforge.db import create_job, execute, j, many, now, one, uid, unj
from test_global_library import chat, scoped_node, setup_book


def add_reading(book,node,model='original-reader',marker='ORIGINAL_SOURCE',pages=None):
    ident=uid()
    stamp=now() if model=='original-reader' else '2099-01-01T00:00:00+00:00'
    execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,warnings_json,created_at,updated_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        (ident,node['id'],library.reading_signature(book,node,'fixture',model,'none'),
         'fixture',model,'none','completed',marker+'_NOTE',j(['原页公式须核对']),now(),stamp))
    for number in pages or range(node['start_page'],node['end_page']+1):
        page=library.extract_page(book,node,number,ocr=False)
        execute('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',
            (ident,number,page['locator'],marker+'\n'+page['original_text'],'图像核对：参考原页',
             page['image_path'],page['image_sha256']))
    return ident


def prepared(tmp_path,pages=1):
    book,_=setup_book(tmp_path,count=max(2,pages))
    node=scoped_node(book,start=1,end=pages)
    reading=add_reading(book,node)
    project,conversation=chat()
    library.set_preferences(conversation,project['id'],'manual',[{'node_id':node['id'],'purpose':'primary'}])
    snapshot=library.reference_snapshot(conversation,project['id'],'ORIGINAL_SOURCE')
    return book,node,reading,project,conversation,snapshot


def test_generation_uses_the_pinned_reading_even_when_a_newer_model_finishes(tmp_path):
    book,node,reading,_,_,snapshot=prepared(tmp_path)
    newest=add_reading(book,node,'newer-reader','NEWER_SOURCE')
    assert library.ready_reading(node,metadata_only=True)['id']==newest
    record=library.generation_records(snapshot)[0]
    assert 'ORIGINAL_SOURCE' in record['segments'][0]['text']
    assert 'NEWER_SOURCE' not in record['segments'][0]['text']
    assert record['read_manifest']['library_reading']['id']==reading
    assert record['read_manifest']['library_reading']['model']=='original-reader'


@pytest.mark.parametrize('change',['delete','overwrite'])
def test_unavailable_pinned_version_never_falls_back_to_a_different_extraction(tmp_path,change):
    book,node,reading,_,_,snapshot=prepared(tmp_path)
    add_reading(book,node,'newer-reader','NEWER_SOURCE')
    if change=='delete':execute('DELETE FROM library_readings WHERE id=?',(reading,))
    else:execute("UPDATE library_readings SET updated_at='2098-01-01',notes='rewritten' WHERE id=?",(reading,))
    with pytest.raises(ValueError,match='没有改用其他版本'):
        library.generation_records(snapshot)


@pytest.mark.parametrize('change',['missing','outside'])
def test_full_node_generation_requires_every_authorized_original_page(tmp_path,change):
    book,node,reading,_,_,snapshot=prepared(tmp_path,pages=3)
    if change=='missing':execute('DELETE FROM library_chunks WHERE reading_id=? AND page=2',(reading,))
    elif change=='outside':execute('UPDATE library_chunks SET page=4 WHERE reading_id=? AND page=3',(reading,))
    with pytest.raises(ValueError,match='原页'):
        library.generation_records(snapshot)


def test_page_without_text_remains_an_explicit_gap_not_a_claim_of_understanding(tmp_path):
    _,_,reading,_,_,snapshot=prepared(tmp_path,pages=3)
    execute("UPDATE library_chunks SET original_text='',visual_text='' WHERE reading_id=? AND page=2",(reading,))
    record=library.generation_records(snapshot)[0]
    assert len(record['segments'])==3
    assert '内容待核对' in record['segments'][1]['text']
    assert any('没有可读文字' in text for text in record['read_manifest']['limitations'])


def test_one_generation_verifies_each_shared_book_once_but_rechecks_next_time(tmp_path,monkeypatch):
    book,_=setup_book(tmp_path)
    refs=[]
    for number in range(4):
        node=scoped_node(book,title=f'独立引用 {number}')
        reading=add_reading(book,node)
        refs.append({'node_id':node['id'],'purpose':'primary','source_version':library.version(book,node),
            'note_annotation':{'reading_id':reading,'reading_updated_at':one('SELECT updated_at FROM library_readings WHERE id=?',(reading,))['updated_at']}})
    native=library.file_sha256;calls=[]
    def count(path):calls.append(str(path));return native(path)
    monkeypatch.setattr(library,'file_sha256',count)
    assert len(library.generation_records({'references':refs}))==4
    assert calls.count(book['original_path'])==1
    Path(book['original_path']).write_bytes(b'file changed after generation')
    with pytest.raises(ValueError,match='原文件已改变'):
        library.generation_records({'references':refs})
    assert calls.count(book['original_path'])==2


def test_reference_preparation_keeps_only_metadata_and_one_navigation_note(tmp_path,monkeypatch):
    book,node,reading,_,_,snapshot=prepared(tmp_path)
    native=library.reference_reading;metadata=[]
    def choose(n,b,ref,*,metadata_only=False):
        metadata.append(metadata_only)
        return native(n,b,ref,metadata_only=metadata_only)
    monkeypatch.setattr(library,'reference_reading',choose)
    result=library.reference_content(snapshot,'ORIGINAL_SOURCE')
    assert metadata==[True]
    assert 'ORIGINAL_SOURCE_NOTE' in result['text']
    library_annotations.save(node['id'],reading,True,'校订：请核对原页',0)
    snapshot['references'][0]['note_annotation']={'reading_id':reading,**library_annotations.get(reading)}
    result=library.reference_content(snapshot,'ORIGINAL_SOURCE')
    assert 'ORIGINAL_SOURCE_NOTE' not in result['text'] and '校订' in result['text']


def test_reference_note_is_not_used_if_it_changes_after_metadata_validation(tmp_path,monkeypatch):
    _,_,reading,_,_,snapshot=prepared(tmp_path)
    native=library.reference_reading
    def changed(*args,**kwargs):
        result=native(*args,**kwargs)
        execute("UPDATE library_readings SET updated_at='2098-01-01',notes='REPLACED_NOTE' WHERE id=?",(reading,))
        return result
    monkeypatch.setattr(library,'reference_reading',changed)
    with pytest.raises(ValueError,match='取用笔记时改变'):
        library.reference_content(snapshot,'ORIGINAL_SOURCE')


def test_generation_launch_reports_changed_book_as_input_error_not_server_failure(tmp_path,monkeypatch):
    book,_,_,project,conversation,_=prepared(tmp_path)
    async def chosen(value):pass
    monkeypatch.setattr(server,'choose_generation_model',chosen)
    Path(book['original_path']).write_bytes(b'changed original')
    value=server.GenerateIn(project_id=project['id'],conversation_id=conversation,source_ids=[],
        provider='deepseek',model='fixture',format='docx',review_mode='express',instructions='ORIGINAL_SOURCE')
    with pytest.raises(HTTPException) as failure:asyncio.run(server.generate(value))
    assert failure.value.status_code==400 and '书库原文件已改变' in failure.value.detail
    assert not many('SELECT id FROM jobs WHERE project_id=?',(project['id'],))


def test_dense_keywords_do_not_allocate_a_match_for_the_entire_chapter():
    text='alpha_beta '*30000
    tracemalloc.start()
    try:
        excerpt,span=library.text_window(text,{'alpha_beta'},450)
        peak=tracemalloc.get_traced_memory()[1]
    finally:tracemalloc.stop()
    assert len(excerpt)<=450 and span['start_char']==0 and span['truncated']
    assert peak<900_000,peak


def test_real_document_export_preserves_the_original_reading_and_complete_pages(tmp_path,monkeypatch):
    book,node,reading,project,conversation,snapshot=prepared(tmp_path,pages=3)
    context=library.reference_content(snapshot,'ORIGINAL_SOURCE')['text']
    add_reading(book,node,'newer-reader','NEWER_SOURCE')
    inputs=[]
    class Writer:
        model='fixture';effort='none'
        async def complete(self,system,user,**kwargs):
            inputs.append(user)
            return '# 选定章节\n\n本次依据原页解释定义、条件与方法。\n\n## 系统性总结\n原文范围与条件保持一致。'
    monkeypatch.setattr(server,'client_for',lambda *a,**kw:Writer())
    value=server.GenerateIn(project_id=project['id'],conversation_id=conversation,source_ids=[],
        provider='deepseek',model='fixture',format='docx',review_mode='express',
        library_snapshot=snapshot,library_context=context)
    job=create_job(project['id'],'generate',value.model_dump())
    asyncio.run(server._generate_job(job,value))
    completed=one('SELECT * FROM jobs WHERE id=?',(job,))
    assert completed['status']=='completed',completed['error']
    assert any('ORIGINAL_SOURCE' in user for user in inputs)
    assert not any('NEWER_SOURCE' in user for user in inputs)
    outputs=many("SELECT * FROM artifacts WHERE project_id=? AND kind='explanation'",(project['id'],))
    assert len(outputs)==1 and Path(outputs[0]['path']).read_bytes()[:2]==b'PK'
    manifest=unj(outputs[0]['metadata_json'])['source_reading'][0]
    assert manifest['segments']==3 and manifest['library_reading']['id']==reading
    assert manifest['library_reading']['model']=='original-reader'
