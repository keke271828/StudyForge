"""Composer directory references: no implicit reading, exact scope, atomic merge."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from studyforge import conversations,library,library_semantic,server
from studyforge.db import create_project,execute,one
from test_library_retrieval import book,reading


def chat(name='学习项目'):
    p=create_project(name);return p,conversations.create(p['id'],'deepseek')['id']


def test_picker_uses_only_directory_and_signature_metadata(tmp_path,monkeypatch):
    b=book(tmp_path);parent=library.add_node(b['id'],'第一章 映射')
    n,_=reading(b,'单射',{1:'private original'},notes='private large note '*4000)
    execute('UPDATE library_nodes SET parent_id=? WHERE id=?',(parent['id'],n['id']))
    # Parent changes do not expand or alter the child's authorized page crop.
    monkeypatch.setattr(library,'extract_page',lambda *a:pytest.fail('autocomplete must not extract'))
    monkeypatch.setattr(library_semantic,'matches',lambda *a:pytest.fail('autocomplete must not embed'))
    original=library.many
    def metadata_only(sql,params=()):
        assert 'notes' not in sql and 'library_chunks' not in sql
        return original(sql,params)
    monkeypatch.setattr(library,'many',metadata_only)
    result=library.directory_suggestions('第一章 单射')
    assert result['nodes'][0]['node_id']==n['id']
    assert result['nodes'][0]['path']=='第一章 映射 / 单射' and result['nodes'][0]['state']=='read'
    assert 'private' not in str(result) and 'original_path' not in str(result)
    assert len(library.directory_suggestions('',limit=1)['nodes'])==1
    assert library.directory_suggestions('',limit=1)['has_more']


def test_same_named_nodes_are_distinguished_by_book_and_id(tmp_path):
    a=book(tmp_path,2);b=book(tmp_path,3)
    execute('UPDATE library_books SET title=? WHERE id=?',('高等代数',a['id']))
    execute('UPDATE library_books SET title=? WHERE id=?',('数学分析',b['id']))
    na,_=reading(a,'基本概念',{1:'first'});nb,_=reading(b,'基本概念',{1:'second'})
    assert {n['node_id'] for n in library.directory_suggestions('基本概念')['nodes']}=={na['id'],nb['id']}
    assert library.directory_suggestions('数学分析 基本概念')['nodes'][0]['node_id']==nb['id']
    assert [n['node_id'] for n in library.directory_suggestions('基本概念',a['id'])['nodes']]==[na['id']]
    # Characters are literal metadata text, never SQL LIKE wildcards.
    assert not library.directory_suggestions('%_')['nodes']


def test_changed_scope_or_incomplete_reading_is_not_a_ready_option(tmp_path):
    b=book(tmp_path);n,r=reading(b,'数域',{1:'field'})
    library.update_node(n['id'],{'end_y':.5,'confirmed':True})
    assert library.directory_suggestions('数域')['nodes'][0]['state']=='unread'
    p,c=chat()
    with pytest.raises(ValueError,match='尚未完成'):library.add_reference(c,p['id'],n['id'])
    assert library.preferences(c,p['id'])['references']==[]


def test_reference_merge_is_atomic_and_keeps_both_independent_selections(tmp_path):
    b=book(tmp_path);a,_=reading(b,'数域',{1:'field'});d,_=reading(b,'多项式',{2:'polynomial'})
    p,c=chat()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda n:library.add_reference(c,p['id'],n),[a['id'],d['id']]))
    assert len(results)==2
    assert {r['node_id'] for r in library.preferences(c,p['id'])['references']}=={a['id'],d['id']}


def test_reference_is_scoped_idempotent_and_explicitly_enables_manual_mode(tmp_path):
    b=book(tmp_path);n,_=reading(b,'数域',{1:'field'})
    p,c=chat();other,q=chat('另一个项目')
    library.set_preferences(c,p['id'],'off',[])
    result=library.add_reference(c,p['id'],n['id'],'primary')
    assert result['mode']=='manual' and result['references'][0]['purpose']=='primary'
    assert not library.preferences(q,other['id'])['references']
    execute('UPDATE conversations SET remote_thread_id=? WHERE id=?',('unchanged-thread',c))
    library.add_reference(c,p['id'],n['id'],'primary')
    assert one('SELECT remote_thread_id FROM conversations WHERE id=?',(c,))['remote_thread_id']=='unchanged-thread'
    with pytest.raises(ValueError,match='项目不匹配'):library.add_reference(c,other['id'],n['id'])


def test_reference_limit_deduplicates_before_rejecting(tmp_path):
    b=book(tmp_path);nodes=[reading(b,str(i),{1:'field'})[0] for i in range(13)]
    p,c=chat();library.set_preferences(c,p['id'],'manual',[{'node_id':n['id'],'purpose':'reference'} for n in nodes[:12]])
    assert len(library.add_reference(c,p['id'],nodes[0]['id'],'primary')['references'])==12
    with pytest.raises(ValueError,match='12 个'):library.add_reference(c,p['id'],nodes[12]['id'])
    assert len(library.preferences(c,p['id'])['references'])==12


def test_picker_routes_are_shared_with_phone_and_reject_unread_refs(tmp_path):
    from studyforge.mobile_access import allowed
    b=book(tmp_path);n,_=reading(b,'数域',{1:'field'});unread=library.add_node(b['id'],'未读章节');p,c=chat()
    with TestClient(server.app) as client:
        result=client.get('/api/library/nodes/suggest',params={'query':'数域'}).json()
        assert result['nodes'][0]['node_id']==n['id']
        path=f'/api/library/conversations/{c}/references'
        assert client.post(path,json={'project_id':p['id'],'node_id':n['id'],'purpose':'primary'}).json()['references'][0]['purpose']=='primary'
        assert client.post(path,json={'project_id':p['id'],'node_id':unread['id']}).status_code==400
        assert client.get('/api/library/nodes/suggest',params={'query':'x'*161}).status_code==422
        assert client.get('/api/library/nodes/suggest',params={'book_id':'missing'}).status_code==400
    assert allowed('GET','/api/library/nodes/suggest')
    assert allowed('POST',path) and not allowed('DELETE',path)
