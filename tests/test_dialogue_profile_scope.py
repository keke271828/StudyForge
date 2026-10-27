import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from studyforge import conversations, learning_memory as memory, learning_profile, server
from studyforge.ai import DeepSeekClient, save_settings
from studyforge.agent_tools import AgentRuntime
from studyforge.codex_bridge import CodexBridge
from studyforge.config import data_dir
from studyforge.db import create_project, execute, j, many, now, one, uid
from studyforge.teaching_policy import chat_policy_signature


def chats():
    a=create_project('数学项目');b=create_project('哲学项目')
    return a,b,conversations.create(a['id'],'deepseek'),conversations.create(a['id'],'deepseek'),conversations.create(b['id'],'deepseek')


def call(runtime,name,args):return asyncio.run(runtime.execute(name,args))


def mock_transport(monkeypatch,responder):
    original=httpx.AsyncClient
    monkeypatch.setattr('studyforge.ai.get_secret',lambda key:'test-only')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:original(transport=httpx.MockTransport(responder)))


def reply(text):
    return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':text},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')


def test_global_profile_available_without_other_chat_quotes_or_payloads():
    a,b,c1,c2,c3=chats()
    event=memory.record_event('learn','chat',{'student_text':'为什么要构造柯西不等式的辅助函数？\nRAW_CHAT_SENTINEL',
        'mentor_context':'PRIVATE_MENTOR_SENTINEL'},a['id'],c1['id'],analyzed=True)
    memory._save_insight(event,'柯西不等式','gap','reasoning','需要解释辅助函数的构造动机。','RAW_CHAT_SENTINEL','暂定',anchors=['柯西不等式'])
    memory.assessment_record('quiz','柯西不等式','做题',79,'RAW_ASSESSMENT_SENTINEL','遗漏等号条件。',a['id'])
    memory.assessment_record('feynman','柯西不等式','费曼讲解',86,'OTHER_CHAT_EXPLANATION','论证清晰。',a['id'])
    memory.assessment_record('self','柯西不等式','自评',92,'RAW_SELF_REPORT','主观熟悉。',a['id'])
    tool=call(AgentRuntime(b['id'],conversation_id=c3['id']),'sf_read_learning_profile',{})
    assert tool['scope']=='global_learning_profile' and tool['chat_history_shared'] is False
    score=next(t for t in tool['topics'] if t['topic']=='柯西不等式')
    assert (score['quiz_score'],score['feynman_score'],score['self_rating'])==(79,86,92)
    assert '构造动机' in j(tool)
    for marker in ['RAW_CHAT_SENTINEL','PRIVATE_MENTOR_SENTINEL','RAW_ASSESSMENT_SENTINEL','OTHER_CHAT_EXPLANATION',c1['id'],a['id']]:
        assert marker not in j(tool)
    overview=memory.profile_context('我的用户画像是什么？')
    assert '柯西不等式' in overview and '79' in overview and '92' in overview
    assert 'RAW_' not in overview


def test_profile_tool_pagination_and_user_removal_are_current():
    a,b,c1,c2,c3=chats()
    for i in range(4):memory.assessment_record('quiz:'+str(i),'知识点'+str(i),'做题',80,'自己的作答','评分依据',a['id'])
    runtime=AgentRuntime(b['id'],conversation_id=c3['id'])
    first=call(runtime,'sf_read_learning_profile',{'limit':2})
    last=call(runtime,'sf_read_learning_profile',{'limit':2,'offset':first['next_offset']})
    assert len(first['topics'])==len(last['topics'])==2 and last['next_offset'] is None
    item=one('SELECT id FROM learning_insights WHERE topic=?',('知识点0',))
    learning_profile.change_insight(item['id'],0,deleted=True)
    assert call(runtime,'sf_read_learning_profile',{'query':'知识点0'})['topics']==[]
    save_settings({'agent_tools_enabled':False})
    assert call(runtime,'sf_read_learning_profile',{})['total_topics']==3


def test_chat_workspaces_isolated_and_persistent_with_broad_folder_grant(tmp_path):
    a,b,c1,c2,c3=chats()
    runtimes=[AgentRuntime(p,conversation_id=c['id']) for p,c in [(a['id'],c1),(a['id'],c2),(b['id'],c3)]]
    paths=[]
    for i,runtime in enumerate(runtimes):
        result=call(runtime,'sf_write_text',{'path':'notes.txt','text':'CHAT_SECRET_'+str(i)})
        paths.append(result['path'])
    assert len(set(paths))==3
    later=AgentRuntime(a['id'],conversation_id=c1['id'])
    assert later.workspace==runtimes[0].workspace
    save_settings({'agent_read_roots':[str(tmp_path)],'agent_write_roots':[str(tmp_path)]})
    assert 'CHAT_SECRET_0' in call(later,'sf_read_file',{'path':paths[0]})['text']
    for path in paths[1:]+[str(data_dir()/'studyforge.sqlite3'),str(data_dir()/'settings.json')]:
        assert call(later,'sf_read_file',{'path':path})['type']=='PermissionError'
        assert call(later,'sf_write_text',{'path':path,'text':'overwrite','overwrite':True})['type']=='PermissionError'
    assert call(later,'sf_list_files',{'path':str(data_dir())})['type']=='PermissionError'
    assert AgentRuntime(a['id']).workspace!=AgentRuntime(a['id']).workspace


def test_shared_library_requires_current_selection_even_with_broad_data_grant(tmp_path):
    a,b,c1,c2,c3=chats();path=data_dir()/'files'/'shared.txt';path.parent.mkdir(exist_ok=True)
    path.write_text('明确选中的共同资料',encoding='utf-8');sid=uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (sid,a['id'],path.name,'.txt',str(path),'ready',now()))
    save_settings({'agent_read_roots':[str(tmp_path)]})
    for chat in [c1,c2]:
        assert '共同资料' in call(AgentRuntime(a['id'],[sid],conversation_id=chat['id']),'sf_read_source',{})['text']
    assert call(AgentRuntime(a['id'],[],conversation_id=c2['id']),'sf_read_file',{'path':str(path)})['type']=='PermissionError'
    assert call(AgentRuntime(b['id'],[sid],conversation_id=c3['id']),'sf_read_file',{'path':str(path)})['type']=='PermissionError'


def test_deepseek_actual_request_has_profile_but_never_foreign_history(monkeypatch):
    a,b,c1,c2,c3=chats();captured=[]
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),c1['id'],'user','OTHER_SAME_PROJECT_RAW_CHAT',now()))
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),c3['id'],'user','OTHER_PROJECT_RAW_CHAT',now()))
    memory.assessment_record('quiz','柯西不等式','做题',80,'PRIVATE_QUOTE','论证需要等号条件。',a['id'])
    execute('INSERT INTO agent_dialogue_state VALUES (?,?,?,?,?)',
            (c2['id'],0,j([{'role':'assistant','content':'UNSCOPED_LEGACY_TOOL_SECRET'}]),now(),1))
    mock_transport(monkeypatch,lambda request:captured.append(json.loads(request.content)) or reply('已读取画像摘要'))
    api=TestClient(server.app)
    output=api.post('/api/chat/stream',json={'project_id':a['id'],'conversation_id':c2['id'],'provider':'deepseek','source_ids':[],
        'text':'我的用户画像是什么？'})
    assert '"error"' not in output.text
    packet=j(captured[-1]);assert '柯西不等式' in packet and '80' in packet and 'sf_read_learning_profile' in packet
    assert all(s not in packet for s in ['OTHER_SAME_PROJECT_RAW_CHAT','OTHER_PROJECT_RAW_CHAT','UNSCOPED_LEGACY_TOOL_SECRET','PRIVATE_QUOTE'])
    scope_runtime = AgentRuntime(a['id'],conversation_id=c2['id'],
        teaching_signature=chat_policy_signature('deep','clear','zh'))
    assert one('SELECT scope_key FROM agent_dialogue_scopes')['scope_key']==scope_runtime.state_key()
    captured.clear()
    output=api.post('/api/chat/stream',json={'project_id':b['id'],'conversation_id':c3['id'],'provider':'deepseek','source_ids':[],
        'text':'我的用户画像是什么？'})
    assert '"error"' not in output.text and '柯西不等式' in j(captured[-1])
    assert 'OTHER_SAME_PROJECT_RAW_CHAT' not in j(captured[-1])


def test_mismatched_project_or_chat_rejected_before_provider(monkeypatch):
    a,b,c1,c2,c3=chats()
    with pytest.raises(PermissionError):AgentRuntime(a['id'],conversation_id=c3['id'])
    monkeypatch.setattr('studyforge.ai.get_secret',lambda key:'test-only')
    client=DeepSeekClient(agent_runtime=AgentRuntime(a['id'],conversation_id=c1['id']),conversation=c2)
    with pytest.raises(PermissionError):asyncio.run(client.complete('导师','读取历史'))


def test_codex_cannot_reuse_other_conversation_live_thread(monkeypatch):
    a,b,c1,c2,c3=chats();bridge=CodexBridge();requests=[]
    async def start():pass
    async def request(method,params):
        requests.append((method,params))
        if method=='thread/start':return {'thread':{'id':'thread-'+str(len(requests)),'ephemeral':True}}
        if method=='turn/start':await bridge.events.put({'method':'turn/completed','params':{'threadId':params['threadId'],'turn':{'status':'completed'}}})
        return {}
    monkeypatch.setattr(bridge,'start',start);monkeypatch.setattr(bridge,'request',request)
    async def scenario():
        first=[e async for e in bridge.stream_turn('第一对话',agent_runtime=AgentRuntime(a['id'],conversation_id=c1['id']))]
        remote=next(v for k,v in first if k=='thread')
        await asyncio.sleep(0)
        other=[e async for e in bridge.stream_turn('第二对话',remote,agent_runtime=AgentRuntime(a['id'],conversation_id=c2['id']),fallback_history='CURRENT_CHAT_ONLY')]
        assert next(v for k,v in other if k=='thread')!=remote
    asyncio.run(scenario())
    starts=[p for m,p in requests if m=='thread/start']
    assert len(starts)==2 and starts[0]['cwd']!=starts[1]['cwd']
    assert 'CURRENT_CHAT_ONLY' in [p for m,p in requests if m=='turn/start'][-1]['input'][0]['text']


@pytest.mark.parametrize('text',['继续','谢谢','新建一个项目','生成PDF，颜色改成绿色。','为什么按钮没有反应？',
    '软件报错JSONDecodeError，我不理解这个工作台。','我的用户画像是什么？','明天北京天气如何？'])
def test_nonlearning_chats_do_not_create_profile_events(text):
    a,b,c1,c2,c3=chats();mid=uid()
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(mid,c1['id'],'user',text,now()))
    memory.discussion_completed(c1['id'],mid)
    assert many('SELECT * FROM learning_events')==[]


@pytest.mark.parametrize('text',['什么是规训权力？','我认为这个论证忽略了等号成立条件。','这一步还是不懂为什么。',
    '看懂计算但不知道什么时候用这个方法。','请讲慢一些，证明部分我没有看懂。'])
def test_learning_questions_and_own_understanding_remain_candidates(text):
    a,b,c1,c2,c3=chats();mid=uid()
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(mid,c1['id'],'user',text,now()))
    memory.discussion_completed(c1['id'],mid)
    assert one('SELECT payload_json FROM learning_events') is not None
    assert many('SELECT * FROM mastery')==[]


def test_legacy_unrelated_profile_soft_excluded_and_user_can_restore():
    a,b,c1,c2,c3=chats()
    eid=memory.record_event('old','chat',{'student_text':'为什么删除按钮没有反应？'},a['id'],c1['id'],analyzed=True)
    memory._save_insight(eid,'点击按钮','gap','','用户不会操作按钮。','删除按钮','暂定',anchors=['删除按钮'])
    assert learning_profile.mentor_profile()['topics']==[]
    assert memory.memory_snapshot()['total_insights']==0
    removed=memory.memory_snapshot(status='removed')['insights'][0]
    restored=learning_profile.change_insight(removed['id'],removed['version'],deleted=False)
    assert restored['deleted'] is False and learning_profile.mentor_profile()['total_topics']==1


def test_excluded_legacy_pending_event_never_spends_background_call_after_restart():
    a,b,c1,c2,c3=chats()
    eid=memory.record_event('unrelated','chat',{'student_text':'为什么删除按钮没反应？'},a['id'],c1['id'],provider='deepseek')
    memory.filter_existing_events()
    execute("UPDATE learning_events SET status='running' WHERE id=?",(eid,))
    def forbidden(event):pytest.fail('被过滤的旧操作请求不应再次调用模型')
    async def scenario():
        worker=memory.MemoryWorker(forbidden)
        await worker.start();await worker.close()
        assert await worker.run_once(ignore_idle=True) is False
    asyncio.run(scenario())
    assert memory.memory_snapshot()['pending']==0 and many('SELECT * FROM learning_runs')==[]


def test_generated_images_owned_by_chat_and_ambiguous_legacy_owner_not_restored():
    from studyforge.config import artifacts_dir
    a,b,c1,c2,c3=chats();asset=uid();path=artifacts_dir()/(asset+'.png');path.write_bytes(b'image-fixture')
    execute('INSERT INTO agent_assets VALUES (?,?,?,?,?,?)',(asset,a['id'],str(path),'image/png','自己的图',now()))
    execute('INSERT INTO agent_tool_events VALUES (?,?,?,?,?,?,?,?,?)',
            (uid(),a['id'],c1['id'],None,'sf_generate_image','completed',j({'asset_id':asset}),now(),now()))
    first=AgentRuntime(a['id'],conversation_id=c1['id']);second=AgentRuntime(a['id'],conversation_id=c2['id'])
    assert first.generated_images()[0]['path']==str(path) and second.generated_images()==[]
    assert call(second,'sf_read_file',{'path':str(path)})['type']=='PermissionError'
    assert call(second,'sf_write_text',{'path':str(path),'text':'x','overwrite':True})['type']=='PermissionError'
    ambiguous=uid()
    execute('INSERT INTO agent_assets VALUES (?,?,?,?,?,?)',(ambiguous,a['id'],str(path),'image/png','旧共享图',now()))
    for chat in (c1,c2):
        execute('INSERT INTO agent_tool_events VALUES (?,?,?,?,?,?,?,?,?)',
                (uid(),a['id'],chat['id'],None,'sf_generate_image','completed',j({'asset_id':ambiguous}),now(),now()))
    assert one('SELECT * FROM agent_asset_scopes WHERE asset_id=?',(ambiguous,)) is None
    first.generated_images();second.generated_images()
    assert one('SELECT * FROM agent_asset_scopes WHERE asset_id=?',(ambiguous,)) is None


def test_codex_native_memory_and_hooks_disabled_before_process_initialization(monkeypatch):
    from studyforge.codex_bridge import NATIVE_CONTEXT_OVERRIDES,learning_tool_config
    bridge=CodexBridge();commands=[]
    class Process:
        returncode=None
        def terminate(self):self.returncode=0
        async def wait(self):return 0
    async def spawn(*args,**kwargs):commands.append(args);return Process()
    async def read():await asyncio.Event().wait()
    async def request(method,params):return {}
    async def send(message):pass
    monkeypatch.setattr('studyforge.codex_bridge.codex_executable',lambda:'codex-test')
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
    monkeypatch.setattr(bridge,'_read',read);monkeypatch.setattr(bridge,'request',request);monkeypatch.setattr(bridge,'_send',send)
    async def scenario():await bridge.start();await bridge.close()
    asyncio.run(scenario())
    for key,value in NATIVE_CONTEXT_OVERRIDES.items():
        assert key+'=false' in commands[0] and learning_tool_config()[key] is False
