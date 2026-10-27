"""Actual observed DSML text cannot complete a lesson or execute a tool."""
import asyncio
import json

import httpx
import pytest

from studyforge.ai import DeepSeekClient
from studyforge.deepseek_protocol import Reply
from studyforge.db import many, one
from tests.test_deepseek_standalone import collect, install_transport, sse


PRINTED_CALL = '我先读取原文件核对。\n\n<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="sf_read_file">\n<｜｜DSML｜｜ parameter name="path" string="true">original.pdf</｜｜DSML｜｜ parameter>\n</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>'


@pytest.mark.parametrize('streaming', [True, False])
@pytest.mark.parametrize('recover', [True, False])
def test_printed_call_retries_pending_reply_only_and_never_completes_or_executes_it(monkeypatch, streaming, recover):
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        content = '实际完成的核对正文。' if recover and len(requests) == 2 else PRINTED_CALL
        return sse({'content':content}) if streaming else httpx.Response(200, json={
            'choices':[{'message':{'content':content}, 'finish_reason':'stop'}]})
    install_transport(monkeypatch, respond)
    client = DeepSeekClient('fixture-model')
    if recover:
        result = collect(client)[-1][1] if streaming else asyncio.run(client.complete('导师','核对原文'))
        assert result == '实际完成的核对正文。'
    else:
        with pytest.raises(RuntimeError, match='把工具调用写成了正文.*尚未执行.*自动重试一次'):
            if streaming: collect(client)
            else: asyncio.run(client.complete('导师','核对原文'))
    assert len(requests) == 2 and requests[0] == requests[1]
    assert not many('SELECT * FROM agent_tool_events')
    assert not many('SELECT * FROM artifacts') and not many('SELECT * FROM agent_dialogue_state')


@pytest.mark.parametrize('content', [
    '下面是协议示例：\n```xml\n'+PRINTED_CALL+'\n```\n这段代码未执行。',
    '协议教学\n~~~xml\n'+PRINTED_CALL+'\n~~~',
    '引用日志：\n'+ '\n'.join('> '+line for line in PRINTED_CALL.splitlines()),
    '标签 `<｜｜DSML｜｜ invoke name="example">` 是正文示例。',
    '下面正常解释两个邻域不相交，与工具无关。',
])
def test_teaching_code_and_quoted_logs_remain_valid_text(content):
    Reply(content=content, finish='stop').validate('fixture-model')


def test_even_valid_structured_call_cannot_authorize_an_unrelated_printed_call():
    reply = Reply(content=PRINTED_CALL, finish='tool_calls', calls={0:{'id':'valid','function':{'name':'sf_read_source','arguments':'{}'}}})
    with pytest.raises(RuntimeError, match='尚未执行'): reply.validate('fixture-model')


def test_native_feedback_failure_keeps_question_without_saving_a_fake_completed_reply(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from studyforge import server
    from tests.test_lesson_read_request import setup
    root, _, _, _, _ = setup(tmp_path,monkeypatch,'第2页的讲解','ready','deepseek')
    monkeypatch.setattr(server, 'DeepSeekClient', DeepSeekClient)
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return sse({'content':PRINTED_CALL})
    install_transport(monkeypatch, respond)
    api = TestClient(server.app)
    section = api.get('/api/lesson-feedback/'+root['id']+'/sections').json()['items'][0]
    assert api.post('/api/lesson-feedback/'+root['id']+'/submit',json={'difficulties':['content_accuracy'],
        'other_text':'请对照原文核对。','focus_section_id':section['id']}).status_code == 200
    response = api.post('/api/lesson-feedback/'+root['id']+'/followup')
    assert '把工具调用写成了正文' in response.text and '"done"' not in response.text
    saved = one('SELECT * FROM lesson_questionnaires WHERE id=?',(root['id'],))
    assert saved['reply_status'] == 'failed' and not saved['reply_message_id']
    assert saved['other_text'] == '请对照原文核对。' and len(requests) == 2
    assert len(many("SELECT * FROM messages WHERE role='assistant'")) == 1  # Only the old lesson.
    for table in ('agent_tool_events','learning_events','exercise_sets','agent_dialogue_state'):
        assert not many('SELECT * FROM ' + table)
