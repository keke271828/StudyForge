import asyncio
import json
import sys
from pathlib import Path

import pytest

from studyforge import gemini_cli, providers, ai, conversations, server
from studyforge.db import create_project, many
from studyforge.deepseek_protocol import DeepSeekReplyError, Reply
from studyforge.gemini_stream import ContentStream, cli_error
from studyforge.provider_clients import service_client


@pytest.mark.parametrize('content',[
    '中文正文。\n\\(S=\\int L\\,dt\\) 与 "原文"。',
    'Unicode：🙂𐐀，反斜杠\\，换行\n与制表\t。',
    '', '包含 content 和 tool_calls 的普通教学文字'])
@pytest.mark.parametrize('ascii_encoded',[True,False])
@pytest.mark.parametrize('reordered',[True,False])
def test_public_content_survives_every_character_boundary_without_tool_leak(content,ascii_encoded,reordered):
    secret=[{'name':'sf_write_text','arguments':{'text':'PRIVATE_REFERENCE_ANSWER','nested':{'content':'PRIVATE_NESTED_TEXT'}}}]
    envelope={'tool_calls':secret,'content':content} if reordered else {'content':content,'tool_calls':secret}
    text=json.dumps(envelope,ensure_ascii=ascii_encoded)
    decoder=ContentStream()
    actual=''.join(decoder.feed(char) for char in text)
    assert actual==content and 'PRIVATE_REFERENCE_ANSWER' not in actual and 'PRIVATE_NESTED_TEXT' not in actual


@pytest.mark.parametrize('bad',[r'{"content":"bad\q"}',r'{"content":"bad\uXXFF"}',r'{"content":"bad\uD800x"}'])
def test_broken_escapes_never_become_valid_text(bad):
    with pytest.raises(DeepSeekReplyError):ContentStream().feed(bad)


@pytest.mark.parametrize('diagnostic,expected',[
    ('invalid_grant: REFRESH_TOKEN_PRIVATE','重新登录'),('RESOURCE_EXHAUSTED quota 429 PRIVATE_KEY','额度'),
    ('Model not found 404 PRIVATE_PROMPT','模型不可用'),('PERMISSION_DENIED 403 PRIVATE_EMAIL','账号没有'),
    ('fetch failed ENOTFOUND PRIVATE_PROXY','网络'),('unknown failure PRIVATE_PASSWORD','请求未完成')])
def test_diagnostics_are_actionable_and_do_not_echo_account_data(diagnostic,expected):
    error=cli_error(diagnostic,1)
    assert expected in str(error) and 'PRIVATE' not in str(error)


@pytest.fixture
def account(monkeypatch,tmp_path):
    monkeypatch.setattr(providers,'get_secret',lambda _:None)
    row=providers.save_service({'name':'账号流式测试','protocol':'gemini_cli','default_model':'auto','models':['auto']})
    root,_=gemini_cli.prepare_profile(row['id']);(root/'.gemini'/'oauth_creds.json').write_text('{}')
    return row


def cli_program(monkeypatch,tmp_path,source):
    path=tmp_path/'fixture_cli.py';path.write_text(source,encoding='utf-8')
    monkeypatch.setattr(gemini_cli,'cli_command',lambda:[sys.executable,'-u',str(path)])


def test_real_child_process_publishes_chinese_and_math_before_completion_then_validates_calls(account,monkeypatch,tmp_path):
    marker=tmp_path/'finished.txt'
    cli_program(monkeypatch,tmp_path,"""
import json,sys,time
sys.stdin.buffer.read()
text=json.dumps({'content':'先解释概念。\\n数学公式：\\\\(F=ma\\\\)。🙂','tool_calls':[{'name':'sf_read_learning_profile','arguments':{}}]},ensure_ascii=True)
for char in text:
    print(json.dumps({'type':'message','role':'assistant','delta':True,'content':char}),flush=True)
    time.sleep(.002)
time.sleep(.1)
from pathlib import Path
Path("""+repr(str(marker))+""").write_text('done')
print(json.dumps({'type':'result','status':'success'}),flush=True)
""")
    async def run():
        reply=Reply(service_name='Gemini');early=False
        client=service_client(account['id'])
        async for packet in client.stream_packets({'messages':[{'role':'user','content':'学习问题'}]}):
            reply.accept(packet)
            if reply.content and not marker.exists():early=True
            if not marker.exists():assert not reply.calls and reply.finish is None
        reply.validate('auto')
        assert early and reply.content=='先解释概念。\n数学公式：\\(F=ma\\)。🙂'
        assert len(reply.calls)==1 and marker.exists()
    asyncio.run(run())


def test_cli_success_with_warning_preserves_content_but_fenced_envelope_stays_private(account,monkeypatch,tmp_path):
    cli_program(monkeypatch,tmp_path,"""
import json,sys
sys.stdin.buffer.read()
print(json.dumps({'type':'error','severity':'warning','message':'Non-fatal warning'}))
print(json.dumps({'type':'message','role':'assistant','content':'```json\\n'+json.dumps({'content':'完整正文','tool_calls':[]})+'\\n```'}))
print(json.dumps({'type':'result','status':'success'}))
""")
    async def run():
        client=service_client(account['id']);reply=Reply()
        async for packet in client.stream_packets({'messages':[]}):reply.accept(packet)
        reply.validate('auto');assert reply.content=='完整正文'
    asyncio.run(run())


def test_real_cli_failed_result_never_exposes_tool_calls_or_private_error(account,monkeypatch,tmp_path):
    cli_program(monkeypatch,tmp_path,"""
import json,sys
sys.stdin.buffer.read()
print(json.dumps({'type':'message','role':'assistant','content':json.dumps({'content':'暂时回复','tool_calls':[{'name':'sf_write_text','arguments':{'text':'SECRET_ANSWER'}}]})}))
print(json.dumps({'type':'result','status':'error','error':{'type':'RESOURCE_EXHAUSTED','message':'quota PRIVATE_TOKEN'}}))
sys.exit(1)
""")
    async def run():
        reply=Reply();client=service_client(account['id'])
        with pytest.raises(RuntimeError,match='额度') as result:
            async for packet in client.stream_packets({'messages':[]}):reply.accept(packet)
        assert not reply.calls and reply.finish is None and 'PRIVATE_TOKEN' not in str(result.value)
    asyncio.run(run())


def test_stderr_is_drained_without_deadlock_or_disclosure(account,monkeypatch,tmp_path):
    cli_program(monkeypatch,tmp_path,"""
import sys
sys.stdin.buffer.read()
sys.stderr.write('PRIVATE_CREDENTIAL '*100000+' ENOTFOUND fetch failed')
sys.exit(1)
""")
    async def run():
        with pytest.raises(RuntimeError,match='网络') as result:
            await asyncio.wait_for(service_client(account['id']).run_cli({'messages':[]}),5)
        assert 'PRIVATE_CREDENTIAL' not in str(result.value)
    asyncio.run(run())


def test_cancelling_live_reply_stops_only_its_child(account,monkeypatch,tmp_path):
    marker=tmp_path/'alive.txt'
    cli_program(monkeypatch,tmp_path,"""
import sys,time,json
from pathlib import Path
sys.stdin.buffer.read()
print(json.dumps({'type':'message','role':'assistant','content':'{\"content\":\"正文'}),flush=True)
while True:
    Path("""+repr(str(marker))+""").write_text(str(time.monotonic()))
    time.sleep(.03)
""")
    async def run():
        client=service_client(account['id']);stream=client.stream_packets({'messages':[]})
        packet=await asyncio.wait_for(anext(stream),4)
        assert packet['choices'][0]['delta']['content']=='正文'
        await stream.aclose()
        previous=marker.read_text();await asyncio.sleep(.12)
        assert marker.read_text()==previous
    asyncio.run(run())


def test_cancelling_chat_preserves_visible_fragment_and_does_not_create_mastery_evidence(account,monkeypatch,tmp_path):
    cli_program(monkeypatch,tmp_path,"""
import sys,time,json
sys.stdin.buffer.read()
print(json.dumps({'type':'message','role':'assistant','content':'{\"content\":\"只完成了第一步概念讲解。'}),flush=True)
time.sleep(30)
""")
    ai.save_settings({'chat_provider':account['id'],'background_learning_enabled':False})
    project=create_project('中断保留')['id'];cid=conversations.create(project,account['id'],'auto')['id']
    async def run():
        response=await server.chat_stream(server.ChatIn(project_id=project,conversation_id=cid,provider=account['id'],text='说明概念'))
        seen=asyncio.Event()
        async def consume():
            async for line in response.body_iterator:
                packet=json.loads(line)
                if packet['type']=='delta':seen.set()
        task=asyncio.create_task(consume());await asyncio.wait_for(seen.wait(),5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert cid not in server.active_chat_conversations
    asyncio.run(run())
    replies=many("SELECT content FROM messages WHERE conversation_id=? AND role='assistant'",(cid,))
    assert len(replies)==1 and '第一步概念讲解' in replies[0]['content'] and '尚未完成' in replies[0]['content']
    assert not many('SELECT * FROM agent_dialogue_state WHERE conversation_id=?',(cid,))
    assert not many('SELECT * FROM learning_events WHERE conversation_id=?',(cid,))


@pytest.mark.parametrize('question',['论证是怎样想到的？','这个构造是如何想到的？','这里怎样理解？'])
def test_teaching_motivation_questions_are_profile_candidates_without_unrelated_html(question):
    from studyforge.learning_signals import learning_excerpt
    assert learning_excerpt(question+'<img src=x onerror=alert(1)>','当前讲解的知识理解反馈。')==question
    assert not learning_excerpt('按钮怎样打开？请重新生成文档。','工作台操作说明')
