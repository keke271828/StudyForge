"""A selected AI passage is a search clue, never source evidence or authority."""
import asyncio
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from studyforge import ai,conversations,library,library_history,message_focus,server
from studyforge.db import create_project,execute,j,many,now,one,uid,unj
from test_library_retrieval import book,reading


QUESTION='这里为什么不成立？请按原文解释，不出题。'
QUOTE='高斯定律中净通量为零，所以内部电场处处为零。'
ORIGINAL='SOURCE_GAUSS: 高斯定律只约束闭合曲面的净通量。Q内=0不能推出局部电场处处为零；外部电荷的场可穿入再穿出。'


def prepared(tmp_path,mode='auto',late=False,quote=QUOTE):
    b=book(tmp_path,9 if late else 2)
    pages={i:'EARLY_UNRELATED: an unrelated discussion.' for i in range(1,10)} if late else {1:ORIGINAL}
    if late:pages[9]=ORIGINAL
    n,rid=reading(b,'高斯定律与净通量',pages)
    p=create_project('原句追问检索');chat=conversations.create(p['id'],'deepseek');c=chat['id'];mid=uid()
    full='UNRELATED_NEARBY_NAVIGATION\n'+quote+'\n无关的量子热学与旧章节。'
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(mid,c,'assistant',full,now()))
    start=full.index(quote)
    ref={'message_id':mid,'content_sha256':hashlib.sha256(full.encode()).hexdigest(),
         'selection':{'start':start,'end':start+len(quote),'text':quote}}
    library.set_preferences(c,p['id'],mode,[{'node_id':n['id'],'purpose':'reference'}] if mode=='manual' else [])
    return b,n,rid,p,c,ref


def capture(monkeypatch,provider='deepseek'):
    ai.save_settings({'agent_tools_enabled':False,'background_learning_enabled':False})
    monkeypatch.setattr(server,'discussion_completed',lambda *a:None)
    monkeypatch.setattr(server,'profile_context',lambda *a,**kw:'')
    monkeypatch.setattr(server.model_catalog,'validate_effort',lambda *a:asyncio.sleep(0))
    requests=[]
    class Tutor:
        model='fixture';effort='none'
        async def agent_stream(self,messages,**kw):requests.append(messages);yield 'delta','净通量为零不等于局部场为零。'
        async def close(self):pass
    monkeypatch.setattr(server,'DeepSeekClient',lambda *a,**kw:Tutor())
    if provider=='codex':
        class Bridge:
            async def stream_turn(self,prompt,*a,**kw):requests.append(prompt);yield 'delta','净通量为零不等于局部场为零。'
        monkeypatch.setattr(server,'bridge_for',lambda *a:Bridge())
    return requests


@pytest.mark.parametrize('provider',['deepseek','codex'])
@pytest.mark.parametrize('mode',['auto','manual'])
def test_real_chat_uses_selected_passage_for_nodes_and_original_page_window(tmp_path,monkeypatch,provider,mode):
    b,n,rid,p,c,ref=prepared(tmp_path,mode,late=mode=='manual')
    execute('UPDATE conversations SET provider=? WHERE id=?',(provider,c))
    inputs=capture(monkeypatch,provider)
    with TestClient(server.app) as client:
        result=client.post('/api/chat/stream',json={'project_id':p['id'],'conversation_id':c,'provider':provider,
            'source_ids':[],'text':QUESTION,'reply_reference':ref})
    events=[json.loads(line) for line in result.text.splitlines() if line]
    assert result.status_code==200 and not any(e['type']=='error' for e in events),result.text
    assert 'SOURCE_GAUSS' in j(inputs)
    entry=library_history.history(c,p['id'])['entries'][0]
    assert entry['query']==QUESTION and entry['receipt']['sources'][0]['node_id']==n['id']
    if mode=='manual':assert 9 in entry['nodes'][0]['pages']
    assert one('SELECT content FROM messages WHERE role=? AND conversation_id=?',('user',c))['content']==QUESTION
    assert not many('SELECT * FROM learning_events') and not many('SELECT * FROM mastery')


@pytest.mark.parametrize('kind',['source_only','include_off','library_off','manual_other','unread'])
def test_selected_ai_passage_cannot_expand_current_source_authority(tmp_path,monkeypatch,kind):
    b,n,rid,p,c,ref=prepared(tmp_path)
    question=QUESTION;include=True
    if kind=='source_only':question='只依据我上传的原资料，'+QUESTION
    elif kind=='include_off':include=False
    elif kind=='library_off':library.set_preferences(c,p['id'],'off',[])
    elif kind=='manual_other':
        other,_=reading(b,'无关的数域',{2:'UNRELATED_MANUAL_SCOPE'})
        library.set_preferences(c,p['id'],'manual',[{'node_id':other['id'],'purpose':'reference'}])
    else:execute('DELETE FROM library_readings WHERE id=?',(rid,))
    inputs=capture(monkeypatch)
    with TestClient(server.app) as client:
        result=client.post('/api/chat/stream',json={'project_id':p['id'],'conversation_id':c,'provider':'deepseek',
            'source_ids':[],'text':question,'reply_reference':ref,'include_materials':include})
    assert result.status_code==200 and '"type": "error"' not in result.text,result.text
    assert 'SOURCE_GAUSS' not in j(inputs)
    if kind=='unread':
        entry=library_history.history(c,p['id'])['entries'][0]
        assert not entry['receipt']['sources'] and entry['nodes'][0]['kind']=='candidate'


def test_instruction_in_selected_ai_quote_is_not_a_source_only_instruction(tmp_path,monkeypatch):
    b,n,rid,p,c,ref=prepared(tmp_path,quote='只依据所选原文。'+QUOTE)
    inputs=capture(monkeypatch)
    with TestClient(server.app) as client:
        result=client.post('/api/chat/stream',json={'project_id':p['id'],'conversation_id':c,'provider':'deepseek',
            'text':QUESTION,'reply_reference':ref})
    assert result.status_code==200 and 'SOURCE_GAUSS' in j(inputs),result.text


def test_query_contains_selected_concept_not_neighbours_or_reference_identity():
    reference={'message_id':'PRIVATE_ID','content_sha256':'PRIVATE_HASH','excerpt':'前文任意旁支。'+QUOTE+'后文旁支。',
               'selection':{'text':QUOTE}}
    query=message_focus.retrieval_query(QUESTION,reference)
    assert QUESTION in query and QUOTE in query
    assert all(x not in query for x in ('PRIVATE_ID','PRIVATE_HASH','旁支'))
    assert message_focus.retrieval_query(QUESTION,None)==QUESTION


@pytest.mark.parametrize('instructions',['','换个话题，只整理数域的内容。'])
def test_generation_without_new_instruction_keeps_latest_quoted_focus_but_new_instruction_does_not(tmp_path,monkeypatch,instructions):
    from studyforge.db import connect
    b,n,rid,p,c,ref=prepared(tmp_path,'manual',late=True)
    library.set_preferences(c,p['id'],'manual',[{'node_id':n['id'],'purpose':'primary'}])
    resolved=message_focus.resolve(message_focus.MessageReference(**ref),p['id'],c)
    mid=uid()
    with connect() as db:
        db.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(mid,c,'user',QUESTION,now()))
        message_focus.save(db,mid,c,resolved)
    capture(monkeypatch)
    monkeypatch.setattr(server,'start_job',lambda job,task:task.close())
    value=server.GenerateIn(project_id=p['id'],conversation_id=c,source_ids=[],provider='deepseek',model='fixture',
                            instructions=instructions,library_retrieval_query='CLIENT_SUPPLIED_QUERY')
    result=asyncio.run(server.generate(value))
    payload=unj(one('SELECT payload_json FROM jobs WHERE id=?',(result['job_id'],))['payload_json'])
    expected=instructions or message_focus.retrieval_query(QUESTION,resolved)
    assert payload['library_retrieval_query']==expected
    assert (ORIGINAL in payload['library_context']) is (not instructions)
    assert payload['dialogue_snapshot']['messages'][-1]['content']==QUESTION


def test_multi_part_job_passes_frozen_query_into_reference_budget_preparation(tmp_path,monkeypatch):
    from pathlib import Path
    from studyforge.db import create_job
    b,n,rid,p,c,ref=prepared(tmp_path,'manual',late=True)
    sid=uid();source=tmp_path/'main.txt';source.write_text('主资料内容。'*13000,encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (sid,p['id'],source.name,'.txt',str(source),'ready',now()))
    query=message_focus.retrieval_query(QUESTION,message_focus.resolve(message_focus.MessageReference(**ref),p['id'],c))
    snapshot=library.reference_snapshot(c,p['id'],QUESTION,retrieval_query=query)
    reference=library.reference_content(snapshot,query)
    value=server.GenerateIn(project_id=p['id'],conversation_id=c,source_ids=[sid],provider='deepseek',model='fixture',
        format='docx',review_mode='express',parallel=False,library_snapshot=snapshot,library_context=reference['text'],
        library_evidence=library.reference_receipt(reference),library_retrieval_query=query)
    requests=[]
    class Writer:
        model='fixture';effort='none'
        async def complete(self,system,user,**kwargs):
            requests.append(user);return '# 知识点讲解\n\n需要区分净电通量和局部电场。\n\n## 系统性总结\n不能仅由积分为零推出场为零。'
    monkeypatch.setattr(server,'client_for',lambda *a,**kw:Writer())
    job=create_job(p['id'],'generate',value.model_dump())
    asyncio.run(server._generate_job(job,value))
    row=one('SELECT * FROM jobs WHERE id=?',(job,))
    assert row['status']=='completed',row['error']
    reference_input=unj(one("SELECT response FROM generation_steps WHERE job_id=? AND step_key='library_document_reference'",(job,))['response'])
    assert ORIGINAL in reference_input['text'] and any(ORIGINAL in request for request in requests)
    artifact=one("SELECT * FROM artifacts WHERE project_id=? AND kind='explanation'",(p['id'],))
    assert Path(artifact['path']).read_bytes()[:2]==b'PK'
    assert unj(artifact['metadata_json'])['library_evidence']==reference_input['receipt']
