import asyncio
import json
from types import SimpleNamespace

import pytest

from studyforge import model_catalog
from studyforge.ai import CodexClient
from studyforge.codex_bridge import CodexBridge


def test_catalog_uses_bundled_models_when_app_server_is_unavailable(monkeypatch):
    async def unavailable(self):
        raise RuntimeError("App Server 忙碌")

    async def bundled():
        return [{"slug": "gpt-6-luna", "display_name": "GPT-6-Luna", "visibility": "list",
                 "supported_reasoning_levels": [{"effort": "low"}, {"effort": "medium"}]}]

    monkeypatch.setattr(CodexBridge, "list_models", unavailable)
    monkeypatch.setattr(model_catalog, "_bundled_models", bundled)
    result = asyncio.run(model_catalog.get_models(force=True))
    assert result["source"] == "bundled"
    assert result["models"][0]["id"] == "gpt-6-luna"
    assert result["models"][0]["efforts"] == ["low", "medium"]
    with pytest.raises(ValueError, match="不支持 high"):
        asyncio.run(model_catalog.validate_effort("gpt-6-luna", "high"))


def test_bundled_catalog_reads_utf8_on_chinese_windows(monkeypatch):
    payload = json.dumps({"models": [{"slug": "gpt-6-luna", "display_name": "物理讲解"}]},
                         ensure_ascii=False).encode("utf-8")
    monkeypatch.setattr(model_catalog.shutil, "which", lambda name: "codex.cmd")
    monkeypatch.setattr(model_catalog.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=0, stdout=payload, stderr=b""))
    assert asyncio.run(model_catalog._bundled_models())[0]["display_name"] == "物理讲解"


def test_model_and_effort_reach_live_private_codex_turn(monkeypatch):
    calls = []
    bridge = CodexBridge()
    bridge.live_threads.add('prior-thread')

    async def start():
        return None

    async def request(method, params):
        calls.append((method, params))
        if method == "thread/resume":
            return {"thread": {"id": "prior-thread"}}
        if method == "turn/start":
            await bridge.events.put({"method": "turn/completed", "params": {
                "threadId": "prior-thread", "turn": {"status": "completed"}}})
        return {}

    monkeypatch.setattr(bridge, "start", start)
    monkeypatch.setattr(bridge, "request", request)

    async def run():
        return [item async for item in bridge.stream_turn("测试", "prior-thread", "gpt-6-luna", "high")]

    assert asyncio.run(run()) == [("thread", "prior-thread")]
    turn = next(params for method, params in calls if method == "turn/start")
    assert turn["model"] == "gpt-6-luna"
    assert turn["effort"] == "high"
    assert not any(method == 'thread/resume' for method,params in calls)


def test_generation_client_keeps_effort_for_independent_review():
    client = CodexClient(model="gpt-6-luna", effort="medium")
    reviewer = client.fork()
    assert (reviewer.model, reviewer.effort) == ("gpt-6-luna", "medium")
