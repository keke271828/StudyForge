import asyncio
import hashlib
import json
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from studyforge import ai, conversations, message_focus as focus, server
from studyforge.db import connect, create_project, execute, j, many, now, one, uid


def setup(text='先解释半径。\n\n再解释阈值。'):
    project=create_project('原句追问')
    chat=conversations.create(project['id'],'deepseek','deepseek-flash','high')
    mid=uid();execute('INSERT INTO messages VALUES (?,?,?,?,?)',(mid,chat['id'],'assistant',text,now()))
    return project,chat,mid


def reference(mid,text,selection=None):
    return focus.MessageReference(message_id=mid,content_sha256=hashlib.sha256(text.encode()).hexdigest(),selection=selection)


def test_unicode_window_coordinates_and_exact_repeated_selection():
    text='😀𝑁\r\n'+('重复原句。'*1100)+'最后才是卡点。'
    p,c,m=setup(text)
    page=focus.passage(m,p['id'],c['id'],4000)
    assert page['text']==text[4000:8000] and page['previous_offset']==0
    begin=text.rindex('重复原句。')
    ref=focus.resolve(reference(m,text,dict(start=begin,end=begin+5,text=text[begin:begin+5])),p['id'],c['id'])
    assert ref['selection']['start']==begin and ref['excerpt'].endswith('最后才是卡点。')
    assert ref['excerpt_start']>0 and len(ref['excerpt'])<=4400
    assert focus.passage(m,p['id'],c['id'],len(text)-1)['next_offset'] is None


@pytest.mark.parametrize('change', ['different_chat','different_project','deleted_chat','removed_project','user_message','unfinished','stale','forged_quote','outside','empty'])
def test_invalid_reference_rejected_before_user_message_or_model_request(change,monkeypatch):
    text='完整历史AI回答。';p,c,m=setup(text);pid,cid=p['id'],c['id'];ref=reference(m,text)
    if change=='different_chat':cid=conversations.create(pid,'deepseek')['id']
    elif change=='different_project':pid=create_project('无关项目')['id']
    elif change=='deleted_chat':execute('INSERT INTO deleted_conversations VALUES (?,?)',(c['id'],now()))
    elif change=='removed_project':
        execute('INSERT INTO removed_projects VALUES (?,?)',(pid,now()))
    elif change=='user_message':execute("UPDATE messages SET role='user' WHERE id=?",(m,))
    elif change=='unfinished':execute('UPDATE messages SET content=? WHERE id=?',(text+'\n[本次回复已停止，以上内容尚未完成。]',m))
    elif change=='stale':execute('UPDATE messages SET content=? WHERE id=?',(text+'变了',m))
    elif change=='forged_quote':ref=reference(m,text,dict(start=0,end=2,text='造假'))
    elif change=='outside':ref=reference(m,text,dict(start=1,end=90,text='越界'))
    elif change=='empty':ref=reference(m,text,dict(start=0,end=1,text=' '))
    with pytest.raises(ValueError):focus.resolve(ref,pid,cid)
    assert not many('SELECT * FROM message_focus_references')


@pytest.mark.parametrize('selection', [dict(start=True,end=2,text='x'),dict(start=0,end=False,text='x'),dict(start=0,end=1,text='a'*3001)])
def test_selection_types_and_size(selection):
    with pytest.raises(ValidationError):focus.PassageSelection(**selection)


def test_long_answer_requires_explicit_selection_and_resource_window():
    text='甲'*120000;p,c,m=setup(text)
    with pytest.raises(ValueError,match='较长'):focus.resolve(reference(m,text),p['id'],c['id'])
    page=focus.passage(m,p['id'],c['id'],110000)
    assert len(page['text'])==4000 and page['total']==120000
    chosen=focus.resolve(reference(m,text,dict(start=110000,end=111000,text='甲'*1000)),p['id'],c['id'])
    assert len(chosen['excerpt'])==2400
    with pytest.raises(ValueError):focus.passage(m,p['id'],c['id'],-1)


def test_saved_reference_visible_on_pages_but_student_text_stays_verbatim_and_cleanup_cascades():
    text='这是AI旧回答，可能有误。';p,c,m=setup(text);mid=uid();ref=focus.resolve(reference(m,text),p['id'],c['id'])
    with connect() as d:
        d.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(mid,c['id'],'user','这里哪里不成立？',now()))
        focus.save(d,mid,c['id'],ref)
    for rows in [conversations.detail(c['id'],p['id'])['messages'],server.conversation_messages(c['id'],p['id'],limit=60)['messages'],focus.history(c['id']),server.conversation_history(c['id'],p['id'],[])]:
        user=next(r for r in rows if r['id']==mid)
        assert user['content']=='这里哪里不成立？' and user['reply_reference']['excerpt']==text
    assert many('SELECT * FROM mastery')==[] and many('SELECT * FROM learning_insights')==[]
    execute('DELETE FROM messages WHERE id=?',(mid,))
    assert not many('SELECT * FROM message_focus_references')


def test_history_snapshot_survives_target_change_and_never_treats_it_as_student_answer():
    text='旧AI回答中的原句。';p,c,m=setup(text);u=uid()
    ref=focus.resolve(reference(m,text),p['id'],c['id'])
    with connect() as d:
        d.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(u,c['id'],'user','这句话为什么？',now()));focus.save(d,u,c['id'],ref)
    execute('UPDATE messages SET content=? WHERE id=?',('新的回答。',m))
    rows=focus.history(c['id']);formatted=focus.model_history(rows)[-1]['content']
    assert text in formatted and '不是学生作答或原文件证据' in formatted and formatted.endswith('这句话为什么？')
    assert one('SELECT content FROM messages WHERE id=?',(u,))['content']=='这句话为什么？'
    execute('DELETE FROM messages WHERE id=?',(m,))
    assert one('SELECT target_message_id FROM message_focus_references WHERE message_id=?',(u,))['target_message_id'] is None
    assert focus.history(c['id'])[-1]['reply_reference']['excerpt']==text


@pytest.mark.parametrize('provider',['deepseek','codex'])
@pytest.mark.parametrize('question', ['这一步为什么？', '```python\nb[0] = [9]\n```\n只解释这个操作，给出两个列表的完整静态结果，不重讲整章。'])
def test_current_followup_actual_provider_receives_reference_and_reopen_rebuild_keeps_it(monkeypatch,provider,question):
    text='😀第一段讲半径。\n第二段讲阈值。';p,c,m=setup(text)
    if provider=='codex':execute('UPDATE conversations SET provider=? WHERE id=?',(provider,c['id']))
    ai.save_settings({'background_learning_enabled':False,'agent_tools_enabled':False,'library_reference_mode':'off'})
    monkeypatch.setenv('DEEPSEEK_API_KEY','fixture-key')
    monkeypatch.setattr(server,'discussion_completed',lambda *a:None)
    monkeypatch.setattr(server.model_catalog,'validate_effort',lambda *a:asyncio.sleep(0))
    captured=[]
    if provider=='deepseek':
        original=httpx.AsyncClient
        def response(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':'针对半径解释。'},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
        monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**k:original(transport=httpx.MockTransport(response)))
    else:
        async def stream(prompt,*args,**kwargs):
            captured.append({'prompt':prompt,'history':json.loads(kwargs['fallback_history'])});yield 'final','针对半径解释。'
        monkeypatch.setattr(server,'bridge_for',lambda *a:type('Bridge',(),{'stream_turn':staticmethod(stream)})())
    begin=text.index('第一段');chosen=dict(start=begin,end=begin+6,text=text[begin:begin+6])
    async def run():
        request=server.ChatIn(project_id=p['id'],conversation_id=c['id'],provider=provider,model='fixture-model',text=question,source_ids=[],reply_reference=reference(m,text,chosen))
        response=await server._chat_response(request)
        output=[chunk async for chunk in response.body_iterator]
        assert not any(b'"error"' in x for x in output),output
        # Explicitly rebuild from public messages as after changing service/settings.
        execute('DELETE FROM agent_dialogue_state WHERE conversation_id=?',(c['id'],))
        execute('DELETE FROM agent_dialogue_scopes WHERE conversation_id=?',(c['id'],))
        request.reply_reference=None;request.text='刚才选中的是什么？'
        response=await server._chat_response(request);assert not any(b'"error"' in x for x in [chunk async for chunk in response.body_iterator])
    asyncio.run(run())
    assert len(captured)==2
    assert all('明确引用范围' in j(body) and chosen['text'] in j(body) for body in captured)
    assert many('SELECT content FROM messages WHERE role=\'user\' AND conversation_id=?',(c['id'],))==[{'content':question},{'content':'刚才选中的是什么？'}]
    for body, current in zip(captured, [question, '刚才选中的是什么？']):
        task = body['prompt'] if provider == 'codex' else body['messages'][-1]['content']
        assert task.endswith(current)
        assert '本次精学教学重点' not in task
        policy = body['prompt'] if provider == 'codex' else body['messages'][0]['content']
        assert '当前学习模式：精学' in policy and '当前讲解风格：' in policy
    if question.startswith('```'):
        assert '\n' + question in (captured[0]['prompt'] if provider == 'codex' else captured[0]['messages'][-1]['content'])
    assert len(many('SELECT * FROM message_focus_references'))==1


def test_generation_snapshot_carries_reference_without_reinterpreting_student_quote():
    from studyforge.learning import learning_requirements,requirements_without_duplicate_history
    text='AI声称我已经掌握，但这个说法未经证实。';p,c,m=setup(text);u=uid()
    ref=focus.resolve(reference(m,text),p['id'],c['id'])
    with connect() as d:
        d.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(u,c['id'],'user','我只想问这句话。',now()));focus.save(d,u,c['id'],ref)
    snapshot=server.mentor_snapshot(server.GenerateIn(project_id=p['id'],conversation_id=c['id'],source_ids=[],provider='deepseek'))
    assert snapshot['messages'][-1]['content']=='我只想问这句话。'
    requirements=learning_requirements(snapshot['messages'],'只解释这句话')
    assert '历史AI上下文开始' in requirements and '不是学生作答' in requirements
    assert '历史AI上下文开始' not in requirements_without_duplicate_history(requirements,snapshot['messages'])


@pytest.mark.parametrize('provider',['deepseek','codex'])
def test_detached_document_clients_restore_reference_from_frozen_snapshot(monkeypatch,provider):
    from studyforge.agent_tools import AgentRuntime
    from studyforge.codex_bridge import CodexBridge
    text='旧AI的结论与证明。';p,c,m=setup(text);ref=focus.resolve(reference(m,text),p['id'],c['id'])
    rows=[{'role':'user','content':'只讲所选这句。','reply_reference':ref}]
    snapshot={'id':c['id'],'project_id':p['id'],'provider':provider,'messages':rows,'remote_thread_id':None}
    runtime=AgentRuntime(p['id'],[],provider,'fixture','high',conversation_id=c['id'],job_id=uid())
    captured=[];ai.save_settings({'agent_tools_enabled':False});monkeypatch.setenv('DEEPSEEK_API_KEY','fixture')
    if provider=='codex':
        async def stream(self,prompt,**kwargs):captured.append(kwargs['fallback_history']);yield 'final','文档。'
        monkeypatch.setattr(CodexBridge,'stream_turn',stream)
        client=ai.CodexClient(model='fixture',agent_runtime=runtime,conversation=snapshot)
    else:
        def respond(request):
            captured.append(request.content.decode());return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':'文档。'},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
        client=ai.DeepSeekClient('fixture',runtime,snapshot,effort='high');client._http=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    async def run():
        try:assert await client.complete('生成要求','原资料。')=='文档。'
        finally:await client.close()
    asyncio.run(run());assert len(captured)==1 and '历史AI上下文开始' in captured[0] and text in captured[0]


def test_mobile_new_routes_are_limited_and_assets_available():
    from studyforge.mobile_access import allowed
    assert allowed('GET','/api/messages/'+'a'*32+'/passage')
    assert not allowed('POST','/api/messages/'+'a'*32+'/passage')
    assert not allowed('GET','/api/messages/../../file/passage')


def test_model_reference_marks_exact_passage_once_and_keeps_full_snapshot():
    import copy
    quote='唯一选中的长原句。'+r'$E=mv^2/2+kx^2/2$。'*110
    text='左侧完整上下文。'+quote+'右侧完整上下文。';p,c,m=setup(text)
    start=text.index(quote);ref=focus.resolve(reference(m,text,dict(start=start,end=start+len(quote),text=quote)),p['id'],c['id'])
    before=copy.deepcopy(ref);output=focus.content('我只问这一处。',ref)
    assert output.count(quote)==1
    assert '左侧完整上下文。' in output and '右侧完整上下文。' in output
    assert '【学生选中的旧AI原句开始，不是学生作答】\n'+quote+'\n【选中原句结束】' in output
    assert output.endswith('【学生自己的本条问题】\n我只问这一处。')
    assert ref==before and ref['selection']['text']==quote


def test_legitimately_repeated_source_sentences_are_not_deleted():
    text='重复原句。第一次说明。重复原句。第二次说明。';p,c,m=setup(text)
    start=text.rindex('重复原句。');ref=focus.resolve(reference(m,text,dict(start=start,end=start+5,text='重复原句。')),p['id'],c['id'])
    output=focus.content('问第二处。',ref)
    assert output.count('重复原句。')==2 and '第一次说明。' in output and '第二次说明。' in output


@pytest.mark.parametrize('field,value',[('excerpt','被改写的上下文'),('excerpt_start',99)])
def test_inconsistent_saved_selection_is_not_guessed_or_silently_relocated(field,value):
    text='原句ABC。';p,c,m=setup(text);ref=focus.resolve(reference(m,text,dict(start=0,end=3,text=text[:3])),p['id'],c['id'])
    ref[field]=value
    with pytest.raises(ValueError,match='不一致'):focus.content('哪里不懂。',ref)


def test_reference_input_version_rebuilds_only_affected_chat_state(monkeypatch):
    from studyforge.agent_tools import AgentRuntime
    text='当前需要引用的回答。';p,c,m=setup(text)
    other=conversations.create(p['id'],'deepseek')
    active=AgentRuntime(p['id'],conversation_id=c['id']);unrelated=AgentRuntime(p['id'],conversation_id=other['id'])
    before,other_before=active.state_key(),unrelated.state_key()
    monkeypatch.setattr(focus,'INPUT_VERSION','different-input-format')
    assert active.state_key()==before and unrelated.state_key()==other_before
    u=uid();ref=focus.resolve(reference(m,text),p['id'],c['id'])
    with connect() as d:
        d.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(u,c['id'],'user','引用这里。',now()));focus.save(d,u,c['id'],ref)
    saved=active.state_key();assert saved!=before
    monkeypatch.setattr(focus,'INPUT_VERSION','next-input-format')
    assert active.state_key()!=saved and unrelated.state_key()==other_before
    assert one('SELECT content FROM messages WHERE id=?',(m,))['content']==text


def test_new_formatter_rebuilds_legacy_private_protocol_once_and_preserves_public_history(monkeypatch):
    text='较早的AI解释里，原句只用于定位。';p,c,m=setup(text);ref=reference(m,text,dict(start=0,end=9,text=text[:9]))
    ai.save_settings({'agent_tools_enabled':False,'background_learning_enabled':False,'library_reference_mode':'off'})
    monkeypatch.setenv('DEEPSEEK_API_KEY','fixture-only')
    monkeypatch.setattr(server,'discussion_completed',lambda *a:None)
    original_http=httpx.AsyncClient;posted=[]
    def respond(request):
        posted.append(json.loads(request.content));number=len(posted)
        packet={'choices':[{'delta':{'content':'已解释'+str(number),'reasoning_content':'PRIVATE_FOCUS_'+str(number)},'finish_reason':'stop'}]}
        return httpx.Response(200,text='data: '+j(packet)+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:original_http(transport=httpx.MockTransport(respond)))
    new_content=focus.content
    def legacy_content(question,reference=None):
        return ('LEGACY_REFERENCE '+reference['selection']['text']+'\n'+reference['excerpt']+'\n'+question) if reference else question
    monkeypatch.setattr(focus,'content',legacy_content);monkeypatch.setattr(focus,'INPUT_VERSION','legacy-format')
    async def send(question,reference=None):
        response=await server._chat_response(server.ChatIn(project_id=p['id'],conversation_id=c['id'],provider='deepseek',text=question,reply_reference=reference))
        lines=[chunk async for chunk in response.body_iterator];assert not any(b'"error"' in line for line in lines),lines
    async def run():
        await send('第一次针对原句追问。',ref)
        monkeypatch.setattr(focus,'content',new_content);monkeypatch.setattr(focus,'INPUT_VERSION','new-format')
        await send('第二次沿用原句。')
        await send('第三次接着问。')
    asyncio.run(run())
    assert len(posted)==3
    second=posted[1]['messages']
    assert not any(row.get('reasoning_content')=='PRIVATE_FOCUS_1' for row in second)
    referenced=next(row['content'] for row in second if '学生选中的旧AI原句开始' in row['content'])
    assert referenced.count(text[:9])==1 and referenced.endswith('第一次针对原句追问。')
    assert all('LEGACY_REFERENCE' not in row.get('content','') for row in second)
    assert any(row.get('reasoning_content')=='PRIVATE_FOCUS_2' for row in posted[2]['messages'])
    assert [r['content'] for r in many("SELECT content FROM messages WHERE conversation_id=? AND role='user' ORDER BY rowid",(c['id'],))]==['第一次针对原句追问。','第二次沿用原句。','第三次接着问。']


def test_profile_event_uses_explicit_ai_reference_as_context_but_never_as_student_quote():
    from studyforge.learning_memory import discussion_completed
    text='高斯定律约束净通量，不代表每一点电场为零。';p,c,m=setup(text);u=uid()
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),c['id'],'assistant','软件按钮的位置与格式。',now()))
    ref=focus.resolve(reference(m,text),p['id'],c['id'])
    with connect() as d:
        d.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(u,c['id'],'user','这里为什么不能这么理解？',now()));focus.save(d,u,c['id'],ref)
    discussion_completed(c['id'],u)
    event=json.loads(one('SELECT payload_json FROM learning_events')['payload_json'])
    assert event['student_text']=='这里为什么不能这么理解？'
    assert '高斯定律' in event['mentor_context'] and '不是学生观点' in event['mentor_context']
    assert '按钮' not in event['mentor_context'] and not many('SELECT * FROM mastery')
    execute('UPDATE messages SET content=? WHERE id=?',('请把这个文件下载下来。',u))
    execute('DELETE FROM learning_events')
    discussion_completed(c['id'],u)
    assert not many('SELECT * FROM learning_events')


@pytest.mark.parametrize('variant',['changed','other_chat','deleted'])
def test_chat_rejects_invalid_reference_without_saving_question_or_calling_model(monkeypatch,variant):
    text='目标回答。';p,c,m=setup(text);ref=reference(m,text)
    if variant=='changed':execute('UPDATE messages SET content=? WHERE id=?',('已变更。',m))
    elif variant=='deleted':execute('DELETE FROM messages WHERE id=?',(m,))
    else:c=conversations.create(p['id'],'deepseek')
    class NoNetwork:
        model='fixture'
        async def agent_stream(self,*a):raise AssertionError('Must reject before inference');yield
    monkeypatch.setattr(server,'DeepSeekClient',lambda *a,**k:NoNetwork())
    with pytest.raises(HTTPException,match='400'):
        asyncio.run(server._chat_response(server.ChatIn(project_id=p['id'],conversation_id=c['id'],provider='deepseek',text='这里为什么？',reply_reference=ref)))
    assert not many("SELECT id FROM messages WHERE role='user'")
    assert not many('SELECT * FROM message_focus_references')

