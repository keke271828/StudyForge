import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from studyforge import library, library_history as lookups, server
from studyforge.db import connect, execute, many, one, unj
from test_global_library import chat, ready


def lookup(node, page=1):
    return {'evidence':[{'node_id':node['id'],'page':page}], 'candidates':[],
            'text':'SOURCE_BODY_MUST_NOT_BE_STORED'*10000, 'truncated':True}


def test_lookup_restores_only_in_its_original_conversation_and_project(tmp_path):
    b,n,_=ready(tmp_path);p,a=chat();_,same_project=chat(p);q,other=chat()
    saved=lookups.record(a,p['id'],'封闭性的条件',lookup(n))
    restored=lookups.history(a,p['id'])['entries']
    assert len(restored)==1 and restored[0]['id']==saved['id']
    hit=restored[0]['nodes'][0]
    assert hit['node_id']==n['id'] and hit['pages']==[1] and hit['available'] and not hit['scope_changed']
    assert lookups.history(same_project,p['id'])['entries']==[]
    assert lookups.history(other,q['id'])['entries']==[]
    with pytest.raises(ValueError):lookups.history(a,q['id'])
    # Restoration is navigation only: old queries are never expanded into the
    # next prompt, explicitly chosen references, or a learner assessment.
    assert library.preferences(a,p['id'])['references']==[]
    assert not many('SELECT * FROM learning_events') and not many('SELECT * FROM mastery')


def test_history_is_bounded_and_does_not_duplicate_source_bodies(tmp_path):
    _,n,_=ready(tmp_path);p,c=chat()
    for i in range(lookups.LIMIT+7):lookups.record(c,p['id'],f'问题 {i}',lookup(n))
    restored=lookups.history(c,p['id'])['entries']
    assert len(restored)==30 and restored[0]['query']=='问题 36' and restored[-1]['query']=='问题 7'
    rows=many('SELECT * FROM conversation_library_history')
    assert max(len(row['payload_json']) for row in rows)<1200
    assert all('SOURCE_BODY_MUST_NOT_BE_STORED' not in row['payload_json'] for row in rows)
    assert lookups.record(c,p['id'],'没有命中',{'evidence':[],'candidates':[]}) is None


def test_changed_and_deleted_scopes_keep_historical_locations_without_reuse(tmp_path):
    b,n,path=ready(tmp_path);p,c=chat();lookups.record(c,p['id'],'数域',lookup(n))
    library.update_node(n['id'],{'end_y':.4,'confirmed':True})
    hit=lookups.history(c,p['id'])['entries'][0]['nodes'][0]
    assert hit['scope_changed'] and hit['pages']==[1]
    library.delete_book(b['id'])
    hit=lookups.history(c,p['id'])['entries'][0]['nodes'][0]
    assert not hit['available'] and hit['title']==n['title'] and path.exists()


def test_clear_and_conversation_delete_preserve_book_and_other_chat(tmp_path):
    b,n,_=ready(tmp_path);p,a=chat();_,c=chat(p)
    library.set_preferences(a,p['id'],'manual',[{'node_id':n['id'],'purpose':'reference'}])
    for ident in [a,c]:lookups.record(ident,p['id'],'数域',lookup(n))
    with TestClient(server.app) as client:
        invalid=client.delete(f'/api/library/conversations/{a}/history?project_id=wrong')
        assert invalid.status_code==400 and len(lookups.history(a,p['id'])['entries'])==1
        assert client.delete(f'/api/library/conversations/{a}/history?project_id='+p['id']).status_code==200
    assert lookups.history(a,p['id'])['entries']==[] and len(lookups.history(c,p['id'])['entries'])==1
    assert library.preferences(a,p['id'])['references'][0]['node_id']==n['id']
    assert library.ready_reading(n) and library.book(b['id'])
    execute('DELETE FROM conversations WHERE id=?',(c,))
    assert not many('SELECT * FROM conversation_library_history')


def test_reference_api_saves_results_and_enforces_project_owner(tmp_path):
    _,n,_=ready(tmp_path);p,c=chat()
    library.set_preferences(c,p['id'],'manual',[{'node_id':n['id'],'purpose':'reference'}])
    with TestClient(server.app) as client:
        path=f'/api/library/conversations/{c}/references?project_id='+p['id']+'&query=closure'
        response=client.get(path)
        assert response.status_code==200,response.text
        value=response.json()
        assert value['evidence'] and value['history']['nodes'][0]['kind']=='original'
        restored=client.get(f'/api/library/conversations/{c}/history?project_id='+p['id']).json()
        assert restored['entries'][0]['id']==value['history']['id']
        assert client.get(f'/api/library/conversations/{c}/history?project_id=wrong').status_code==400


def test_public_agent_search_and_original_recheck_are_saved_but_private_jobs_are_not(tmp_path):
    from studyforge.agent_tools import AgentRuntime,ReadLibrary,SearchLibrary
    b,n,_=ready(tmp_path);p,c=chat()
    snapshot=library.set_preferences(c,p['id'],'manual',[{'node_id':n['id'],'purpose':'reference'}])
    async def scenario():
        runtime=AgentRuntime(p['id'],[],provider='deepseek',conversation_id=c)
        found=await runtime.sf_search_library(SearchLibrary(query='数域'))
        assert found['nodes'] and found['library_history']['nodes'][0]['kind']=='candidate'
        read=await runtime.sf_read_library_node(ReadLibrary(node_id=n['id'],page=1))
        assert read['library_history']['nodes'][0]['kind']=='original' and 'TOP:' in read['text']
        assert len(lookups.history(c,p['id'])['entries'])==2
        job=AgentRuntime(p['id'],[],provider='deepseek',conversation_id=c,job_id='private-grade')
        assert (await job.sf_search_library(SearchLibrary(query='数域')))['library_history'] is None
        private=AgentRuntime(p['id'],[],provider='deepseek',conversation_id=c,private_context=True)
        private.library_snapshot=snapshot
        assert await private.remember_library_lookup('秘密答案',evidence=[{'node_id':n['id']}]) is None
        unpublished=AgentRuntime(p['id'],[],provider='deepseek',conversation_id=c,publishing=False)
        assert (await unpublished.sf_read_library_node(ReadLibrary(node_id=n['id'])))['library_history'] is None
    asyncio.run(scenario())
    assert len(lookups.history(c,p['id'])['entries'])==2


def test_chat_stream_persists_retrieval_before_returning_answer(tmp_path,monkeypatch):
    _,n,_=ready(tmp_path);p,c=chat()
    library.set_preferences(c,p['id'],'manual',[{'node_id':n['id'],'purpose':'reference'}])
    expected=library.reference_content(library.reference_snapshot(c,p['id'],'数域为什么需要非零除数'),'数域为什么需要非零除数')
    model_inputs=[]
    class Tutor:
        model='fixture';effort='none'
        async def agent_stream(self,messages,**kw):
            model_inputs.append(messages);yield 'delta','除法必须排除零除数。'
        async def close(self):pass
    from studyforge import ai
    ai.save_settings({'agent_tools_enabled':False,'background_learning_enabled':False})
    monkeypatch.setattr(server,'DeepSeekClient',lambda *a,**kw:Tutor())
    monkeypatch.setattr(server,'profile_context',lambda *a,**kw:'')
    with TestClient(server.app) as client:
        result=client.post('/api/chat/stream',json={'project_id':p['id'],'conversation_id':c,
            'source_ids':[],'text':'数域为什么需要非零除数','provider':'deepseek'})
        assert result.status_code==200,result.text
    events=[json.loads(line) for line in result.text.splitlines() if line]
    assert not [event for event in events if event['type']=='error'],events
    library_event=next(event for event in events if event['type']=='library')['value']
    assert library_event['history']['id']==lookups.history(c,p['id'])['entries'][0]['id']
    receipt=library_event['receipt']
    assert receipt==lookups.history(c,p['id'])['entries'][0]['receipt']
    assert receipt==library.reference_receipt(expected)
    assert expected['text'] in model_inputs[0][0]['content']
    assert receipt['sources'][0]['node_id']==n['id'] and receipt['sources'][0]['pages'][0]['page']==1
    assert any(event['type']=='delta' for event in events)


def test_history_schema_is_added_to_existing_database_on_reopen(tmp_path):
    # Migration uses the regular startup schema and preserves existing chats.
    p,c=chat()
    with connect() as db:db.execute('DROP TABLE conversation_library_history')
    from studyforge import db as storage
    storage._initialized_databases.pop((tmp_path/'data'/'studyforge.sqlite3').resolve(),None)
    with connect() as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='conversation_library_history'").fetchone()
        assert db.execute('SELECT id FROM conversations WHERE id=?',(c,)).fetchone()


def test_paired_phone_can_restore_clear_and_schedule_ranges_without_other_project_records(tmp_path):
    from test_mobile_access import mobile_client,pair
    b,n,_=ready(tmp_path);p,c=chat();q,other=chat()
    lookups.record(c,p['id'],'封闭性',lookup(n))
    lookups.record(other,q['id'],'其他项目',lookup(n))
    manager,client=mobile_client()
    with client:
        pair(manager,client)
        path=f'/api/library/conversations/{c}/history?project_id='+p['id']
        response=client.get(path)
        assert response.status_code==200,response.text
        assert [r['query'] for r in response.json()['entries']]==['封闭性']
        assert client.get(f'/api/library/conversations/{c}/history?project_id='+q['id']).status_code==400
        # A confirmed node correctly refuses replacement; test an eligible node.
        execute('UPDATE library_nodes SET confirmed=0 WHERE id=?',(n['id'],))
        response=client.post(f'/api/library/books/{b["id"]}/ranges',json={
            'node_ids':[n['id']],'allow_ai':False,'foreground':True})
        assert response.status_code==200,response.text
        job=one('SELECT payload_json FROM library_jobs WHERE id=?',(response.json()['id'],))
        assert unj(job['payload_json'])['foreground']
        assert client.delete(path).status_code==200
        assert lookups.history(c,p['id'])['entries']==[]
        assert len(lookups.history(other,q['id'])['entries'])==1
        assert library.details(b['id'])['nodes']
