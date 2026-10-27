import pytest
from fastapi.testclient import TestClient

from studyforge import conversations, library, library_annotations, server
from studyforge.db import execute, now, one, uid
from test_global_library import scoped_node, setup_book


def notes(tmp_path):
    b,_=setup_book(tmp_path);n=scoped_node(b);ident=uid();signature=library.reading_signature(b,n,'fixture','fixture','none')
    execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,warnings_json,created_at,updated_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?)',(ident,n['id'],signature,'fixture','fixture','none','completed',
        'WRONG_NOTE_ALPHA：含零的条件不能从其他条件推出。','[]',now(),now()))
    execute('INSERT INTO library_chunks(reading_id,page,locator,original_text) VALUES (?,?,?,?)',
        (ident,1,'PDF 第 1 页','ORIGINAL_EVIDENCE：集合含 1 且对减法封闭。'))
    return b,n,ident


def test_version_corrections_preserve_ai_text_and_original_pages(tmp_path):
    _,n,r=notes(tmp_path);client=TestClient(server.app)
    route=f"/api/library/nodes/{n['id']}/notes/{r}/annotation"
    saved=client.put(route,json={'suspect':True,'comment':'原页条件推出 1−1=0，因此含零不独立。','revision':0})
    assert saved.status_code==200,saved.text
    public=client.get(f"/api/library/nodes/{n['id']}/notes?reading_id={r}").json()
    assert public['annotation']['suspect'] and public['annotation']['revision']==1
    assert public['versions'][0]['suspect'] and 'WRONG_NOTE_ALPHA' in public['notes']
    assert one('SELECT original_text FROM library_chunks WHERE reading_id=?',(r,))['original_text'].startswith('ORIGINAL_EVIDENCE')
    conflict=client.put(route,json={'suspect':False,'comment':'过期设备草稿','revision':0})
    assert conflict.status_code==409
    assert library_annotations.get(r)['suspect']


def test_suspect_note_is_excluded_but_original_evidence_and_correction_are_shared(tmp_path):
    _,n,r=notes(tmp_path)
    query=library.terms('WRONG_NOTE_ALPHA')
    assert library.note_matches(query,{n['id']:{'id':r}})[r]>0
    library_annotations.save(n['id'],r,True,'检查原页：1−1=0。',0)
    assert r not in library.note_matches(query,{n['id']:{'id':r}})
    context=library.reference_content({'references':[{'node_id':n['id'],'purpose':'reference'}]},'closure')
    assert 'WRONG_NOTE_ALPHA' not in context['text']
    assert 'ORIGINAL_EVIDENCE' in context['text'] and '1−1=0' in context['text']
    assert '不是原文或学生能力证据' in context['text']
    assert library.ready_reading(n,metadata_only=True)['id']==r


def test_clear_restores_navigation_and_optimistic_revision_survives(tmp_path):
    _,n,r=notes(tmp_path);library_annotations.save(n['id'],r,True,'有疑点',0)
    result=library_annotations.save(n['id'],r,False,'',1)
    assert result['revision']==2 and not result['suspect'] and result['comment']==''
    assert r in library.note_matches(['WRONG_NOTE_ALPHA'],{n['id']:{'id':r}})


def test_wrong_version_scope_and_invalid_input_are_rejected(tmp_path):
    b,n,r=notes(tmp_path);other=scoped_node(b,title='其他节点',start=2,end=2)
    client=TestClient(server.app)
    route=f"/api/library/nodes/{other['id']}/notes/{r}/annotation"
    assert client.put(route,json={'revision':0}).status_code==400
    route=f"/api/library/nodes/{n['id']}/notes/{r}/annotation"
    for payload in ({'revision':-1},{'revision':0,'comment':'a'*1201},{'revision':0,'unknown':1}):
        assert client.put(route,json=payload).status_code==422
    library.update_node(n['id'],{'end_y':.3})
    assert client.put(route,json={'revision':0}).status_code==400


def test_an_annotation_in_launch_snapshot_does_not_change_mid_task(tmp_path):
    _,n,r=notes(tmp_path);mark=library_annotations.save(n['id'],r,True,'启动时校订',0)
    snapshot={'references':[{'node_id':n['id'],'purpose':'reference','note_annotation':{'reading_id':r,**mark}}]}
    library_annotations.save(n['id'],r,False,'后来修改的说明',1)
    frozen=library.reference_content(snapshot,'closure')['text']
    assert '启动时校订' in frozen and '后来修改的说明' not in frozen and 'WRONG_NOTE_ALPHA' not in frozen


def test_phone_can_save_version_corrections_only_after_pairing(tmp_path):
    from test_mobile_access import mobile_client, pair
    from studyforge.mobile_access import allowed
    _,n,r=notes(tmp_path)
    route=f"/api/library/nodes/{n['id']}/notes/{r}/annotation"
    assert allowed('PUT',route) and not allowed('DELETE',route)
    manager,client=mobile_client()
    with client:
        assert client.put(route,json={'revision':0}).status_code==401
        pair(manager,client)
        saved=client.put(route,json={'suspect':True,'comment':'手机校订','revision':0})
        assert saved.status_code==200,saved.text
        assert library_annotations.get(r)['comment']=='手机校订'
        assert client.put(route,json={'revision':0}).status_code==409


def test_correction_rebuilds_hidden_tool_history_but_keeps_current_public_chat(tmp_path,monkeypatch):
    from test_teaching_session_state import prepared_chat, post_chat
    project,chat,args,requests=prepared_chat(tmp_path,monkeypatch)
    _,n,r=notes(tmp_path)
    library.set_preferences(chat['id'],project['id'],'manual',[{'node_id':n['id'],'purpose':'reference'}])
    api=TestClient(server.app)
    post_chat(api,args,'请解释集合封闭性。')
    old_scope=one('SELECT scope_key FROM agent_dialogue_scopes WHERE conversation_id=?',(chat['id'],))['scope_key']
    post_chat(api,args,'请继续说。')
    assert any(m.get('reasoning_content')=='HIDDEN_PROTOCOL_1' for m in requests[-1]['messages'])
    library_annotations.save(n['id'],r,True,'CORRECTION_NOW：1−1=0，请核对原页。',0)
    post_chat(api,args,'继续核对这个定义。')
    current=requests[-1]['messages']
    assert not any(m.get('reasoning_content')=='HIDDEN_PROTOCOL_1' for m in current)
    assert 'CORRECTION_NOW' in current[0]['content'] and 'WRONG_NOTE_ALPHA' not in current[0]['content']
    assert current[1]['content']=='请解释集合封闭性。' and current[2]['content']=='可见讲解1，条件须核对。'
    assert one('SELECT scope_key FROM agent_dialogue_scopes WHERE conversation_id=?',(chat['id'],))['scope_key']!=old_scope
    assert len(requests)==3 and len(conversations.detail(chat['id'],project['id'])['messages'])==6


def new_version(b,n):
    ident=uid();model='another-reading-model'
    execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,warnings_json,created_at,updated_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?)',(ident,n['id'],library.reading_signature(b,n,'fixture',model,'none'),
        'fixture',model,'none','completed','LATEST_NOTE_BODY','[]',now(),'2099-01-01'))
    execute('INSERT INTO library_chunks(reading_id,page,locator,original_text) VALUES (?,?,?,?)',
        (ident,1,'PDF 第 1 页','LATEST_SOURCE_EXTRACTION'))
    return ident


def test_launched_reference_and_agent_tool_keep_the_same_reading_version(tmp_path):
    import asyncio
    from studyforge.agent_tools import AgentRuntime,ReadLibrary
    from studyforge.db import create_project
    b,n,r=notes(tmp_path);project=create_project('已启动的任务');chat=conversations.create(project['id'],'deepseek')
    library.set_preferences(chat['id'],project['id'],'manual',[{'node_id':n['id'],'purpose':'reference'}])
    library_annotations.save(n['id'],r,True,'PINNED_CORRECTION',0)
    snapshot=library.reference_snapshot(chat['id'],project['id'],'closure')
    newer=new_version(b,n)
    assert library.ready_reading(n,metadata_only=True)['id']==newer
    text=library.reference_content(snapshot,'closure')['text']
    assert 'ORIGINAL_EVIDENCE' in text and 'PINNED_CORRECTION' in text and 'LATEST_SOURCE' not in text
    runtime=AgentRuntime(project['id'],conversation_id=chat['id'],provider='deepseek')
    runtime.library_snapshot=snapshot
    result=asyncio.run(runtime.sf_read_library_node(ReadLibrary(node_id=n['id'],page=1)))
    assert 'ORIGINAL_EVIDENCE' in result['text'] and 'LATEST_SOURCE' not in result['text']
    next_snapshot=library.reference_snapshot(chat['id'],project['id'],'closure')
    assert 'LATEST_SOURCE_EXTRACTION' in library.reference_content(next_snapshot,'closure')['text']


def test_removed_pinned_version_never_silently_switches_to_a_newer_one(tmp_path):
    b,n,r=notes(tmp_path)
    snapshot={'references':[{'node_id':n['id'],'purpose':'reference',
        'note_annotation':{'reading_id':r,**library_annotations.get(r)}}]}
    new_version(b,n)
    execute('DELETE FROM library_readings WHERE id=?',(r,))
    with pytest.raises(ValueError,match='没有改用其他版本'):
        library.reference_content(snapshot,'closure')


def test_a_forced_rewrite_of_the_same_reading_id_invalidates_old_task_and_editor(tmp_path):
    from studyforge.db import create_project
    _,n,r=notes(tmp_path);project=create_project('重新整理版本');chat=conversations.create(project['id'],'deepseek')
    library.set_preferences(chat['id'],project['id'],'manual',[{'node_id':n['id'],'purpose':'reference'}])
    old=one('SELECT updated_at FROM library_readings WHERE id=?',(r,))['updated_at']
    snapshot=library.reference_snapshot(chat['id'],project['id'],'closure')
    execute('UPDATE library_readings SET notes=?,updated_at=? WHERE id=?',('重新整理的正文','2099-01-01',r))
    with pytest.raises(ValueError,match='没有改用其他版本'):
        library.reference_content(snapshot,'closure')
    client=TestClient(server.app);route=f"/api/library/nodes/{n['id']}/notes/{r}/annotation"
    stale=client.put(route,json={'revision':0,'comment':'旧笔记草稿','reading_updated_at':old})
    assert stale.status_code==409 and '重新整理' in stale.json()['detail']
    assert library_annotations.get(r)['revision']==0
    assert client.put(route,json={'revision':0,'comment':'针对新内容的校订','reading_updated_at':'2099-01-01'}).status_code==200


def test_save_response_cannot_claim_another_writers_later_revision(tmp_path,monkeypatch):
    from contextlib import contextmanager
    _,n,r=notes(tmp_path);native=library_annotations.connect;pending=True
    @contextmanager
    def interleaved_commit():
        nonlocal pending
        with native() as database:yield database
        if pending:
            pending=False
            library_annotations.save(n['id'],r,False,'另一端的新内容',1)
    monkeypatch.setattr(library_annotations,'connect',interleaved_commit)
    saved=library_annotations.save(n['id'],r,True,'本次保存的内容',0)
    assert saved['revision']==1 and saved['comment']=='本次保存的内容'
    assert library_annotations.get(r)['revision']==2 and library_annotations.get(r)['comment']=='另一端的新内容'
