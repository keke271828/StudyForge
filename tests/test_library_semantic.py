"""Permissions, persisted batches, genuine mode choice and original anchors."""
import asyncio
import hashlib
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from studyforge import library,library_semantic as semantic,server
from studyforge.db import connect,create_project,execute,j,many,now,uid
from test_library_retrieval import book,reading,snapshot


class Encoder:
    def passages(self,row):
        text=row['original_text']
        return [('original',i,min(len(text),i+90),text[i:i+90]) for i in range(0,len(text),90)]

    def encode(self,texts,query=False):
        return np.asarray([[1,0] if 'needle' in text or 'one-to-one' in text else [0,1] for text in texts],dtype='<f4')


@pytest.fixture
def local_model(monkeypatch):
    monkeypatch.setattr(semantic,'model_ready',lambda:True)
    monkeypatch.setattr(semantic,'encoder',lambda:Encoder())
    semantic.set_enabled(True)


def test_model_is_opt_in_and_released_on_idle_or_disable(monkeypatch):
    assert semantic.enabled() is False
    monkeypatch.setattr(semantic, '_engine', object())
    monkeypatch.setattr(semantic, '_last_used', semantic.time.monotonic()-31)
    semantic.release_idle()
    assert semantic._engine is None
    semantic.set_enabled(True)
    semantic._engine = object()
    semantic.set_enabled(False)
    assert semantic._engine is None and not semantic.enabled()


def test_index_resume_has_no_ocr_or_generation_calls(tmp_path,local_model,monkeypatch):
    b=book(tmp_path);n,r=reading(b,'目录',{1:('background '*120)+'needle meaning'})
    monkeypatch.setattr(library,'extract_page',lambda *a:pytest.fail('索引不得读取新原页'))
    assert semantic.index_step()
    first=many('SELECT * FROM library_embeddings')
    assert len(first)==4 and semantic.status()['indexed_pages']==0
    semantic.set_enabled(False)
    assert not semantic.index_step() and len(many('SELECT * FROM library_embeddings'))==4
    semantic.set_enabled(True)
    while semantic.index_step():pass
    assert semantic.status()['indexed_pages']==1
    assert len({(x['page'],x['ordinal']) for x in many('SELECT * FROM library_embeddings')})==len(many('SELECT * FROM library_embeddings'))
    assert library.ready_reading(n)['id']==r


def test_keyword_and_semantic_choices_produce_different_real_paths(tmp_path,local_model):
    b=book(tmp_path);n,r=reading(b,'映射',{1:'needle injectivity'})
    while semantic.index_step():pass
    assert not library.search('one-to-one',mode='keyword')
    found=library.search('one-to-one',mode='hybrid',with_meta=True)
    assert found['semantic_used'] and found['nodes'][0]['node_id']==n['id']
    assert found['nodes'][0]['match_kind']=='semantic'
    semantic.set_enabled(False)
    assert not library.search('one-to-one',mode='hybrid',with_meta=True)['semantic_used']


def test_unread_and_changed_range_cannot_use_embeddings(tmp_path,local_model):
    b=book(tmp_path);n,r=reading(b,'所选',{1:'needle meaning'})
    unread=library.add_node(b['id'],'未读')
    while semantic.index_step():pass
    library.update_node(n['id'],{'start_page':2,'end_page':2,'confirmed':True})
    assert not library.search('one-to-one',mode='hybrid')
    assert not semantic.eligible() and semantic.status()['total_pages']==0


def test_manual_restriction_applies_before_semantic_ranking(tmp_path,local_model):
    b=book(tmp_path);allowed,_=reading(b,'允许',{1:'unrelated body'})
    other,_=reading(b,'其他',{2:'needle meaning'})
    while semantic.index_step():pass
    assert library.search('one-to-one',mode='hybrid')[0]['node_id']==other['id']
    assert not library.search('one-to-one',node_ids=[allowed['id']],mode='hybrid')


def test_content_changes_and_deletion_invalidate_vectors(tmp_path,local_model):
    b=book(tmp_path);n,r=reading(b,'章节',{1:'needle meaning'})
    while semantic.index_step():pass
    execute('UPDATE library_chunks SET original_text=? WHERE reading_id=?',('changed body',r))
    assert not many('SELECT * FROM library_embeddings') and semantic.status()['indexed_pages']==0
    while semantic.index_step():pass
    assert semantic.status()['indexed_pages']==1
    execute('DELETE FROM library_chunks WHERE reading_id=?',(r,))
    assert not many('SELECT * FROM library_embeddings')


def test_semantic_anchor_quotes_late_original_and_ignores_forged_offset(tmp_path,local_model):
    b=book(tmp_path);raw=('introductory background\n'*450)+'needle decisive condition'
    n,r=reading(b,'长证明',{1:raw})
    while semantic.index_step():pass
    hits=library.search('one-to-one',mode='hybrid')[0]['semantic_hits']
    snap=snapshot(b,[n]);snap['references'][0]['semantic_hits']=hits
    result=library.reference_content(snap,'one-to-one',max_chars=1800)
    assert 'needle decisive condition' in result['text']
    assert result['evidence'][0]['original_excerpt']['start_char']>6000
    snap['references'][0]['semantic_hits']=[dict(hits[0],text_hash='forged')]
    invalid=library.reference_content(snap,'one-to-one',max_chars=1800)
    assert invalid['evidence'][0]['original_excerpt']['start_char']==0


def test_missing_model_does_not_download_or_break_keyword(tmp_path,monkeypatch):
    b=book(tmp_path);n,r=reading(b,'数学',{1:'closure of operations'})
    monkeypatch.setattr(semantic,'download_model',lambda *a:pytest.fail('查询不得自动下载'))
    result=library.search('closure',mode='hybrid',with_meta=True)
    assert result['nodes'][0]['node_id']==n['id'] and not result['semantic_used']


def test_english_fragments_do_not_make_unrelated_auto_references(tmp_path):
    b=book(tmp_path);n,r=reading(b,'记忆',{1:'Repeatedly rereading is different from retrieval practice.'})
    assert not library.search('What did I eat for breakfast yesterday?',mode='keyword')
    assert library.relevance(library.terms('repeatedly'),'Repeatedly rereading')>0


def test_index_worker_defers_to_foreground(tmp_path,local_model,monkeypatch):
    from studyforge import scheduling
    monkeypatch.setattr(scheduling,'library_foreground_busy',lambda:True)
    monkeypatch.setattr(semantic,'index_step',lambda:pytest.fail('前台忙时不得启动索引'))
    async def run():
        worker=semantic.SemanticWorker();await worker.start()
        await asyncio.sleep(.05);await worker.close()
    asyncio.run(run())


def test_search_and_settings_routes_and_phone_permissions(tmp_path,local_model):
    from studyforge.mobile_access import allowed
    b=book(tmp_path);n,r=reading(b,'单射',{1:'needle meaning'})
    while semantic.index_step():pass
    with TestClient(server.app) as client:
        assert client.get('/api/library/search',params={'query':'one-to-one','mode':'keyword'}).json()['nodes']==[]
        assert client.get('/api/library/search',params={'query':'one-to-one','mode':'hybrid'}).json()['semantic_used']
        assert client.put('/api/library/semantic',json={'enabled':False}).json()['enabled'] is False
        assert client.get('/api/library/search',params={'query':'one-to-one','mode':'hybrid'}).json()['nodes']==[]
        assert client.get('/api/library/search',params={'query':'one-to-one','mode':'unknown'}).status_code==422
    assert allowed('GET','/api/library/semantic') and allowed('PUT','/api/library/semantic')
    assert not allowed('POST','/api/library/semantic/download')


@pytest.mark.parametrize('case',['resume','bad_hash','cancel'])
def test_model_download_checks_and_resume_without_network(tmp_path,monkeypatch,case):
    import httpx
    import threading
    body=b'abcdef';sha=hashlib.sha256(body).hexdigest()
    monkeypatch.setattr(semantic,'FILES',{'model.onnx':('weights.onnx',len(body),sha)})
    root=semantic.model_root();root.mkdir(parents=True,exist_ok=True)
    partial=root/'model.onnx.partial';partial.write_bytes(body[:2])
    class Response:
        status_code=206
        headers={'Content-Range':'bytes 2-5/6'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
        def iter_bytes(self,size):yield b'zzzz' if case=='bad_hash' else body[2:]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def stream(self,method,url,headers):
            assert headers=={'Range':'bytes=2-'}
            assert semantic.REVISION in url
            return Response()
    monkeypatch.setattr(httpx,'Client',Client)
    event=threading.Event()
    if case=='cancel':event.set()
    if case=='bad_hash':
        with pytest.raises(ValueError):semantic.download_model(event)
        assert semantic.download_state()['state']=='failed' and not (root/'model.onnx').exists()
    else:
        semantic.download_model(event)
        if case=='resume':
            assert (root/'model.onnx').read_bytes()==body and semantic.download_state()['state']=='ready'
        else:assert partial.read_bytes()==body[:2] and semantic.download_state()['state']=='cancelled'


def test_download_fallback_resumes_partial_transport_failure(monkeypatch):
    import httpx
    import urllib.request
    body=b'abcdef'
    monkeypatch.setattr(semantic,'FILES',{'model.onnx':('weights.onnx',len(body),hashlib.sha256(body).hexdigest())})
    root=semantic.model_root();root.mkdir(parents=True,exist_ok=True)
    (root/'model.onnx.partial').write_bytes(body[:2])
    class Response:
        status_code=206
        headers={'Content-Range':'bytes 2-5/6'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
        def iter_bytes(self,size):
            yield body[2:3]
            raise httpx.ReadError('interrupted transport')
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def stream(self,method,url,headers):return Response()
    class Fallback:
        status=206
        headers={'Content-Range':'bytes 3-5/6'}
        delivered=False
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,size):
            if self.delivered:return b''
            self.delivered=True
            return body[3:]
    def urlopen(request,timeout):
        assert request.get_header('Range')=='bytes=3-'
        assert request.full_url.startswith('https://huggingface.co/') and semantic.REVISION in request.full_url
        assert timeout==30
        return Fallback()
    monkeypatch.setattr(httpx,'Client',Client)
    monkeypatch.setattr(urllib.request,'urlopen',urlopen)
    semantic.download_model()
    assert (root/'model.onnx').read_bytes()==body
    assert semantic.download_state()['state']=='ready'
