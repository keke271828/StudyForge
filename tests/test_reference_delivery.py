"""A real document job receives marked references and still reads the source."""
import asyncio
import hashlib
import json

from docx import Document
import httpx

from studyforge import ai, conversations, learning_memory, message_focus, server, job_control
from studyforge.db import connect,create_job,create_project,execute,j,many,now,one,uid


def test_full_docx_job_keeps_reference_once_source_complete_and_task_snapshot(tmp_path,monkeypatch):
    ai.save_settings({'agent_tools_enabled':False,'background_learning_enabled':False,'library_reference_mode':'off'})
    monkeypatch.setattr(ai,'get_secret',lambda *a:'fixture-only')
    p=create_project('引用到文档');chat=conversations.create(p['id'],'deepseek','fixture-model','high')
    topics=['矩阵秩','复数运算','线性映射','积分','微分','概率','动量','动能','势能']
    event=learning_memory.record_event('doc-profile-focus','chat',{'student_text':'我不理解量词约束的概念。PRIVATE_LEARNING_EVIDENCE'},p['id'],analyzed=True)
    learning_memory._save_insight(event,'量词约束','gap','reasoning','TARGET_DOC_PROFILE：学生自报需要解释全称命题取特例，尚未测验。','PRIVATE_LEARNING_EVIDENCE','自报困难（未测验）')
    for topic in topics:
        event=learning_memory.record_event('doc-noise-'+topic,'chat',{'student_text':'我不理解这个概念。'},p['id'],analyzed=True)
        learning_memory._save_insight(event,topic,'gap','concepts','OTHER_DOC_PROFILE：需要核对'+topic,'学生自己的问题','暂定')
    source=uid();path=tmp_path/'original.txt';path.write_text('原文首部哨兵：先核对条件。\n目录还包括：'+'、'.join(topics)+'。\n原文中部细节。\n原文尾部哨兵：仍有范围边界。',encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
        (source,p['id'],path.name,'.txt',str(path),'ready',now()))
    target=uid();old='旧AI背景。选中原句：量词约束不能忽略。其他解释。'
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(target,chat['id'],'assistant',old,now()))
    quote='选中原句：量词约束不能忽略。';start=old.index(quote)
    ref=message_focus.resolve(message_focus.MessageReference(message_id=target,content_sha256=hashlib.sha256(old.encode()).hexdigest(),
        selection={'start':start,'end':start+len(quote),'text':quote}),p['id'],chat['id'])
    student=uid()
    with connect() as d:
        d.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(student,chat['id'],'user','请只针对选中的这句说明理由。',now()));message_focus.save(d,student,chat['id'],ref)
    value=server.GenerateIn(project_id=p['id'],conversation_id=chat['id'],source_ids=[source],provider='deepseek',model='fixture-model',
        reasoning_effort='high',review_mode='express',format='docx',instructions='保留来源与必要条件，不出题。')
    snapshot=server.mentor_snapshot(value);payload=value.model_dump()|{'dialogue_snapshot':snapshot};job=create_job(p['id'],'generate',payload)
    frozen=one('SELECT payload_json FROM jobs WHERE id=?',(job,))['payload_json']
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),chat['id'],'user','后来新问题不能改写任务。',now()))
    posted=[];native=httpx.AsyncClient
    def respond(request):
        body=json.loads(request.content);posted.append(body)
        marked=next(row['content'] for row in body['messages'] if '学生选中的旧AI原句开始' in row['content'])
        assert marked.count(quote)==1 and '旧AI背景。' in marked and '其他解释。' in marked
        assert '原文首部哨兵' in j(body) and '原文尾部哨兵' in j(body) and '原文中部细节' in j(body)
        assert '后来新问题不能改写任务' not in j(body)
        current=body['messages'][-1]['content']
        assert 'TARGET_DOC_PROFILE' in current and current.index('TARGET_DOC_PROFILE')<current.index('OTHER_DOC_PROFILE')
        assert 'PRIVATE_LEARNING_EVIDENCE' not in j(body)
        answer='# 量词约束\n\n原文要求先核对条件。\n\n## 系统性总结\n必要条件与适用范围都要保留。'
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:native(transport=httpx.MockTransport(respond)))
    async def run_job():
        await job_control.start_job(job,server._generate_job(job,value))
    asyncio.run(run_job())
    saved=one('SELECT status,error FROM jobs WHERE id=?',(job,));assert saved['status']=='completed',saved['error']
    assert len(posted)==1
    artifact=one("SELECT * FROM artifacts WHERE project_id=? AND kind='explanation'",(p['id'],))
    assert '必要条件与适用范围都要保留。' in '\n'.join(x.text for x in Document(artifact['path']).paragraphs)
    assert one('SELECT content FROM messages WHERE id=?',(student,))['content']=='请只针对选中的这句说明理由。'
    assert one('SELECT payload_json FROM jobs WHERE id=?',(job,))['payload_json']==frozen
    assert not many('SELECT * FROM mastery') and not many('SELECT id FROM exercise_sets')
