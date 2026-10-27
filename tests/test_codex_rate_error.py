"""A failed provider turn must be recognizable without dumping its dictionary."""
import asyncio

import pytest

from studyforge import server
from studyforge.codex_bridge import CodexBridge,CodexTurnError
from studyforge.task_retry import classify
from tests.test_chat_approval_wait import setup_chat,start_reply

DETAILS={'message':'exceeded retry limit, last status: 429 Too Many Requests',
    'codexErrorInfo':{'responseTooManyFailedAttempts':{'httpStatusCode':429}},
    'additionalDetails':None,'misalignment':None}


@pytest.mark.parametrize('value',[DETAILS,{'message':'server failed','codexErrorInfo':{'httpConnectionFailed':{'httpStatusCode':429}}}])
def test_known_429_is_friendly_and_retains_original_details(value):
    error=CodexTurnError(value,'failed')
    assert error.details is value and 'HTTP 429' in str(error) and '本次回复已停止' in str(error)
    assert 'codexErrorInfo' not in str(error) and '稍后重试' in str(error)
    assert classify(error)[0] is True


def test_unrelated_error_retains_its_message_without_assuming_a_rate_limit():
    error=CodexTurnError({'message':'The requested model is unavailable'},'failed')
    assert str(error)=='The requested model is unavailable' and '429' not in str(error)


def test_native_chat_stream_reports_failed_turn_without_success_or_learning_evidence(monkeypatch):
    project,chat=setup_chat('codex');bridge=CodexBridge()
    monkeypatch.setattr(server,'bridge_for',lambda _:bridge)
    async def start():pass
    async def request(method,params):
        if method=='thread/start':return {'thread':{'id':'rate-limit-fixture','ephemeral':True}}
        if method=='turn/start':await bridge.events.put({'method':'turn/completed',
            'params':{'threadId':'rate-limit-fixture','turn':{'status':'failed','error':DETAILS}}})
        return {}
    monkeypatch.setattr(bridge,'start',start);monkeypatch.setattr(bridge,'request',request)
    async def check():
        task,events=await start_reply(project,chat,'codex');await asyncio.wait_for(task,5)
        assert events[-1]['type']=='error' and 'HTTP 429' in events[-1]['value']
        assert not any(event['type']=='done' for event in events)
        from studyforge.db import many
        assert many("SELECT * FROM learning_events WHERE kind='做题'")==[]
        assert chat not in server.active_chat_conversations
        await bridge.close()
    asyncio.run(check())
