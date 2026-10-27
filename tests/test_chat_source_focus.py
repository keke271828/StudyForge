"""Real tutor entry point with isolated originals and controlled providers."""
import asyncio
import hashlib

import pytest

from studyforge import ai, conversations, server
from studyforge.db import create_project, execute, j, now, uid
from studyforge.learning import source_fingerprint
from studyforge.materials import read_original_sources


def material(tmp_path):
    project = create_project('长资料追问范围')
    path = tmp_path / '代数教材.txt'
    path.write_text(('前半部分讨论矩阵记号和初等变换。\n\n' * 6000) +
        '\n\n## 尾部：商环与可逆元\n\n'
        '本节只讨论交换含幺环。商环 R/I 中的陪集 [u] 可逆，当且仅当存在 v 使 uv−1 属于 I。\n\n'
        '取 R=Z、I=6Z。陪集 [5] 可逆，因为 5×5−1=24 属于 6Z；[2] 不可逆。\n\n'
        '不能把“非零”当作“可逆”；这不要求原环本身是域。TAIL_CONDITION_INCLUDED\n', encoding='utf-8')
    sid = uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) '
            'VALUES (?,?,?,?,?,?,?,?)',
            (sid, project['id'], path.name, '.txt', str(path), '[]', 'ready', now()))
    record = dict(id=sid, project_id=project['id'], name=path.name, kind='.txt', original_path=str(path))
    records = read_original_sources([record])
    rid = uid()
    execute('INSERT INTO reading_sessions VALUES (?,?,?,?,?,?,?,?,?,?)',
        (rid, project['id'], j([sid]), source_fingerprint(records), 'deepseek', 'fixture', None,
         j([{'part':1,'text':'这份教材分为矩阵与商环两部分；笔记不是原文。'}]),
         j([records[0]['read_manifest']]), now()))
    return project, sid, rid


@pytest.mark.parametrize('provider', ['deepseek', 'codex'])
@pytest.mark.parametrize('send_reading', [True, False])
@pytest.mark.parametrize('reference', [False, True])
def test_long_source_followup_reaches_tail_conditions_in_actual_provider_input(tmp_path, monkeypatch, provider, send_reading, reference):
    project, sid, rid = material(tmp_path)
    chat = conversations.create(project['id'], provider, 'fixture')
    conversations.update(chat['id'], project['id'], {'source_ids':[sid], 'reading_id':rid})
    ai.save_settings({'background_learning_enabled':False, 'agent_tools_enabled':False,
                      'library_reference_mode':'off'})
    captured = []
    question = '请只据教材解释商环中陪集可逆的充要条件，为什么非零不一定可逆？不要出题。'
    reply_reference = None
    if reference:
        from studyforge.message_focus import MessageReference
        old = '商环中非零的陪集总能求逆。'
        mid = uid()
        execute('INSERT INTO messages VALUES (?,?,?,?,?)',(mid,chat['id'],'assistant',old,now()))
        reply_reference = MessageReference(message_id=mid,content_sha256=hashlib.sha256(old.encode()).hexdigest())
        question = '这句话为什么不对？只解释这里，不出题。'
    class Client:
        model = 'fixture'
        async def close(self): pass
        async def agent_stream(self, messages):
            captured.append(messages[0]['content'])
            yield 'final', '这里只给出受控回复，不作为模型教学质量证据。'
    monkeypatch.setattr(server, 'DeepSeekClient', lambda **kw: Client())
    monkeypatch.setattr(server, 'client_for', lambda *a, **kw: Client())
    monkeypatch.setattr(server, 'discussion_completed', lambda *a: None)
    async def stream(prompt, *a, **kw):
        captured.append(prompt)
        yield 'final', '这里只给出受控回复，不作为模型教学质量证据。'
    monkeypatch.setattr(server, 'bridge_for', lambda *a: type('Bridge', (), {'stream_turn':staticmethod(stream)})())
    async def run():
        response = await server._chat_response(server.ChatIn(project_id=project['id'], conversation_id=chat['id'],
            provider=provider, model='fixture', source_ids=[sid], reading_id=rid if send_reading else None,
            text=question, reply_reference=reply_reference))
        chunks = [part async for part in response.body_iterator]
        assert not any(b'"error"' in part for part in chunks), chunks
    asyncio.run(run())
    assert len(captured) == 1
    assert 'TAIL_CONDITION_INCLUDED' in captured[0]
    assert '本节只讨论交换含幺环' in captured[0]
    assert '5×5−1=24' in captured[0]
    assert '来源 代数教材.txt｜' in captured[0]
    assert '不是全文' in captured[0]


@pytest.mark.parametrize('problem',['missing','changed_file','other_project','different_selection'])
def test_long_source_still_requires_a_current_reading_for_exact_selected_originals(tmp_path,monkeypatch,problem):
    from fastapi import HTTPException
    from studyforge.db import one
    project,sid,rid=material(tmp_path)
    chat=conversations.create(project['id'],'deepseek','fixture')
    conversations.update(chat['id'],project['id'],{'source_ids':[sid],'reading_id':rid})
    if problem=='missing':
        execute('DELETE FROM reading_sessions WHERE id=?',(rid,))
    elif problem=='changed_file':
        from pathlib import Path
        path=Path(one('SELECT original_path FROM sources WHERE id=?',(sid,))['original_path'])
        path.write_text(path.read_text(encoding='utf-8')+'文件已修改。',encoding='utf-8')
    elif problem=='other_project':
        execute('UPDATE reading_sessions SET project_id=? WHERE id=?',(create_project('其他项目')['id'],rid))
    else:
        execute('UPDATE reading_sessions SET fingerprint=? WHERE id=?',('wrong-selection',rid))
    class Client:
        model='fixture'
        async def close(self):pass
        async def agent_stream(self,*a):raise AssertionError('must not call model');yield
    ai.save_settings({'agent_tools_enabled':False,'background_learning_enabled':False})
    monkeypatch.setattr(server,'DeepSeekClient',lambda **kw:Client())
    with pytest.raises(HTTPException,match='先完成通读'):
        asyncio.run(server._chat_response(server.ChatIn(project_id=project['id'],conversation_id=chat['id'],
            provider='deepseek',model='fixture',source_ids=[sid],text='请讲解商环可逆元。')))
    assert chat['id'] not in server.active_chat_conversations


def test_small_source_is_still_provided_completely_without_lexical_filtering(tmp_path,monkeypatch):
    project,sid,rid=material(tmp_path)
    from pathlib import Path
    from studyforge.db import one
    path=Path(one('SELECT original_path FROM sources WHERE id=?',(sid,))['original_path'])
    path.write_text('开头：完整定义。\n\n中间：完整推导。\n\n结尾：完整条件。',encoding='utf-8')
    chat=conversations.create(project['id'],'deepseek','fixture')
    ai.save_settings({'agent_tools_enabled':False,'background_learning_enabled':False,'library_reference_mode':'off'})
    captured=[]
    class Client:
        model='fixture'
        async def close(self):pass
        async def agent_stream(self,messages):captured.append(messages);yield 'final','受控回复。'
    monkeypatch.setattr(server,'DeepSeekClient',lambda **kw:Client())
    monkeypatch.setattr(server,'discussion_completed',lambda *a:None)
    async def run():
        response=await server._chat_response(server.ChatIn(project_id=project['id'],conversation_id=chat['id'],
            provider='deepseek',model='fixture',source_ids=[sid],text='我想先整体了解。'))
        assert not any(b'"error"' in row for row in [part async for part in response.body_iterator])
    asyncio.run(run())
    text=captured[0][0]['content']
    assert path.read_text(encoding='utf-8') in text and '长资料的相关原文片段' not in text
