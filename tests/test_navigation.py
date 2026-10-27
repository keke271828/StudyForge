import asyncio

import pytest
from fastapi.testclient import TestClient

from studyforge import conversations, navigation, server
from studyforge.db import create_project, create_job, execute, j, many, now, one, uid
from studyforge.job_control import active_jobs, start_job


def fixtures():
    a, b = create_project('代数项目'), create_project('文学项目')
    chats = [conversations.create(a['id'], 'deepseek') for _ in range(3)]
    return a, b, chats


def test_activation_does_not_reorder_and_manual_order_survives_new_client():
    project, _, chats = fixtures()
    client = TestClient(server.app)
    before = client.get(f"/api/projects/{project['id']}/conversations").json()['conversations']
    for chat in chats:
        client.post(f"/api/conversations/{chat['id']}/activate?project_id={project['id']}")
    assert [row['id'] for row in conversations.list_project(project['id'])['conversations']] == [row['id'] for row in before]
    ids = [row['id'] for row in chats]
    response = client.put('/api/navigation/order', json={'kind':'conversation','project_id':project['id'],'ids':ids})
    assert response.status_code == 200, response.text
    assert [row['id'] for row in TestClient(server.app).get(f"/api/projects/{project['id']}/conversations").json()['conversations']] == ids


def test_pin_and_new_chat_have_explicit_stable_position():
    project, _, chats = fixtures()
    navigation.reorder('conversation',[row['id'] for row in chats],project['id'])
    navigation.update_item('conversation',chats[-1]['id'],pinned=True)
    new = conversations.create(project['id'],'deepseek')
    rows = conversations.list_project(project['id'])['conversations']
    assert rows[0]['id'] == chats[-1]['id'] and rows[1]['id'] == new['id']
    for chat in chats: conversations.activate(chat['id'])
    assert [row['id'] for row in conversations.list_project(project['id'])['conversations']] == [row['id'] for row in rows]


@pytest.mark.parametrize('ids', [[{},'x'], ['x','x'], ['missing'], [], None])
def test_order_rejects_invalid_or_partial_membership(ids):
    a, b, _ = fixtures()
    response = TestClient(server.app).put('/api/navigation/order',json={'kind':'project','ids':ids})
    assert response.status_code == 400
    assert {row['id'] for row in navigation.projects()} == {a['id'],b['id']}


def test_reorder_cannot_move_chat_to_other_project():
    a, b, chats = fixtures()
    foreign = conversations.create(b['id'],'deepseek')
    with pytest.raises(ValueError): navigation.reorder('conversation',[row['id'] for row in chats]+[foreign['id']],a['id'])


def test_inline_rename_preserves_workspace_and_does_not_count_as_new_message():
    a, b, chats = fixtures()
    chat = chats[0]
    conversations.update(chat['id'],a['id'],{'draft':'当前学习疑问'})
    client = TestClient(server.app)
    stamp = conversations.detail(chat['id'],a['id'])['updated_at']
    assert client.put(f"/api/navigation/conversation/{chat['id']}",json={'name':'  构造动机  '}).status_code == 200
    assert client.put(f"/api/navigation/project/{b['id']}",json={'name':'比较文学'}).status_code == 200
    row = conversations.detail(chat['id'],a['id'])
    assert row['title'] == '构造动机' and row['draft']=='当前学习疑问' and row['updated_at']==stamp
    assert client.get('/api/workspace').json()['project_id']==a['id']
    assert client.put(f"/api/navigation/project/{b['id']}",json={'name':'  '}).status_code == 400
    assert client.put(f"/api/navigation/project/{b['id']}",json={'name':'a\nb'}).status_code == 400
    assert client.put(f"/api/navigation/project/{b['id']}",json={'pinned':'true'}).status_code == 400


def test_preferences_survive_restart_and_ignore_unknown_keys():
    a, _, _ = fixtures()
    client = TestClient(server.app)
    assert client.put('/api/navigation/preferences',json={'sort':'name','expanded':[a['id']],'other':'ignore'}).status_code == 200
    assert TestClient(server.app).get('/api/navigation').json()['preferences']=={'sort':'name','expanded':[a['id']]}
    assert client.put('/api/navigation/preferences',json={'sort':'invalid'}).status_code == 400
    assert client.put('/api/navigation/preferences',json={'expanded':[{}]}).status_code == 400


def test_explicit_collapse_overrides_initial_active_project_default():
    a, _, _ = fixtures()
    assert navigation.preferences()['expanded']==[a['id']]
    navigation.save_preferences({'expanded':[]})
    assert navigation.preferences()['expanded']==[]


def test_tree_counts_drafts_and_impact_without_disclosing_draft_text():
    a, _, chats = fixtures()
    conversations.update(chats[0]['id'],a['id'],{'draft':'私有草稿'})
    create_job(a['id'],'generate',{'conversation_id':chats[0]['id']})
    create_job(a['id'],'generate',{'conversation_id':chats[1]['id']})
    folder = next(row for row in navigation.tree()['projects'] if row['id']==a['id'])
    assert folder['pending_count']==2
    current = next(row for row in folder['conversations'] if row['id']==chats[0]['id'])
    assert current['pending_count']==1 and current['has_draft'] is True and 'draft' not in current
    assert navigation.impact('project',a['id'])['pending_count']==2
    assert navigation.impact('conversation',chats[0]['id'])['pending_count']==1


def test_recycle_hides_all_resource_urls_and_mcp_preserves_files_on_restore(tmp_path):
    from studyforge import mcp_server
    from studyforge.agent_tools import AgentRuntime
    a, b, chats = fixtures()
    path=tmp_path/'原资料.txt';path.write_text('完整正文',encoding='utf-8')
    sid, category = uid(),uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (sid,a['id'],path.name,'.txt',str(path),'[]','ready',now()))
    execute('INSERT INTO source_categories VALUES (?,?,?,?)',(category,a['id'],'分类',now()))
    artifact=server.add_artifact(a['id'],[],'external','txt','原文',path)
    job=create_job(a['id'],'generate',{'conversation_id':chats[0]['id']})
    foreign=create_job(b['id'],'generate',{})
    runtime=AgentRuntime(a['id'],[sid],provider='deepseek')
    client=TestClient(server.app)
    impact=client.get(f"/api/navigation/project/{a['id']}/impact").json()
    assert impact['source_count']==impact['artifact_count']==1
    removed=client.delete('/api/projects/'+a['id'])
    assert removed.status_code==200 and removed.json()['cancelled_tasks']==1
    assert one('SELECT status FROM jobs WHERE id=?',(job,))['status']=='cancelled'
    assert one('SELECT status FROM jobs WHERE id=?',(foreign,))['status']=='queued'
    assert {row['id'] for row in client.get('/api/projects').json()}=={b['id']}
    assert {row['id'] for row in client.get('/api/artifact-folders').json()}=={b['id']}
    assert {row['id'] for row in mcp_server.list_projects()}=={b['id']}
    for url in [f"/api/projects/{a['id']}/sources",f"/api/conversations/{chats[0]['id']}?project_id={a['id']}",
                f"/api/sources/{sid}",f"/api/categories/{category}",f"/api/artifacts/{artifact['id']}/download",f"/api/jobs/{job}"]:
        assert client.get(url).status_code==404,url
    with pytest.raises(ValueError): mcp_server.read_source(sid)
    with pytest.raises(ValueError): create_job(a['id'],'generate',{})
    assert asyncio.run(runtime.execute('sf_read_source',{'source_id':sid}))['type']=='ValueError'
    assert path.read_text(encoding='utf-8')=='完整正文'
    assert client.post(f"/api/projects/{a['id']}/restore").status_code==200
    assert len(conversations.list_project(a['id'])['conversations'])==3
    assert client.get(f"/api/projects/{a['id']}/sources").status_code==200
    assert one('SELECT title FROM artifacts WHERE id=?',(artifact['id'],))['title']=='原文'
    assert one('SELECT status FROM jobs WHERE id=?',(job,))['status']=='cancelled'


def test_project_deletion_rejects_live_chat_reply():
    a, _, chats = fixtures()
    server.active_chat_conversations.add(chats[0]['id'])
    try:
        response=TestClient(server.app).delete('/api/projects/'+a['id'])
        assert response.status_code==409 and navigation.removed(a['id']) is False
    finally: server.active_chat_conversations.discard(chats[0]['id'])


def test_project_removal_cancels_real_running_coroutine():
    a, _, chats = fixtures()
    job=create_job(a['id'],'generate',{'conversation_id':chats[0]['id']})
    stopped=[]
    async def scenario():
        async def running():
            try: await asyncio.Event().wait()
            finally: stopped.append(True)
        start_job(job,running());await asyncio.sleep(0)
        await server.remove_project(a['id'])
    asyncio.run(scenario())
    assert stopped==[True] and job not in active_jobs
    assert one('SELECT status FROM jobs WHERE id=?',(job,))['status']=='cancelled'


def test_delete_last_chat_keeps_empty_project_without_synthetic_chat():
    a=create_project('留空项目');chat=conversations.create(a['id'],'deepseek')
    response=TestClient(server.app).delete(f"/api/conversations/{chat['id']}?project_id={a['id']}")
    assert response.status_code==200
    assert conversations.list_project(a['id'])=={'conversations':[],'active_conversation_id':None}
    assert navigation.require_project(a['id'])['name']=='留空项目'


def test_recycled_project_is_not_analyzed_by_background_memory():
    from studyforge import learning_memory as memory
    a, _, chats = fixtures()
    memory.record_event('chat:fixture','chat',{'student_text':'柯西不等式这里的辅助函数我不明白为什么这样构造'},
                        project_id=a['id'],conversation_id=chats[0]['id'],provider='deepseek')
    execute('INSERT INTO removed_projects VALUES (?,?)',(a['id'],now()))
    class Client:
        calls=0
        async def complete(self,*args,**kwargs):
            self.calls+=1;return j({'insights':[]})
        async def close(self): pass
    client=Client();worker=memory.MemoryWorker(lambda _:client)
    assert asyncio.run(worker.run_once(ignore_idle=True)) is False and client.calls==0
    navigation.restore(a['id'])
    assert asyncio.run(worker.run_once(ignore_idle=True)) is True and client.calls==1


def test_background_reply_cannot_commit_after_project_was_removed():
    from studyforge import learning_memory as memory
    a, _, chats = fixtures()
    memory.record_event('chat:fixture','chat',{'student_text':'柯西不等式这里的辅助函数我不明白为什么这样构造'},
                        project_id=a['id'],conversation_id=chats[0]['id'],provider='deepseek')
    class Client:
        async def complete(self,*args,**kwargs):
            execute('INSERT INTO removed_projects VALUES (?,?)',(a['id'],now()))
            return j({'insights':[]})
        async def close(self): pass
    with pytest.raises(asyncio.CancelledError): asyncio.run(memory.MemoryWorker(lambda _:Client()).run_once(ignore_idle=True))
    assert many('SELECT * FROM learning_insights')==[]
    assert one('SELECT status FROM learning_runs')['status']=='interrupted'
