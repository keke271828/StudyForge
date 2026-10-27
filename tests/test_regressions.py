import asyncio
import json
import socket
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from studyforge import server, urls
from studyforge.ai import CodexClient, DeepSeekClient, client_for, save_settings, settings
from studyforge.db import create_job, create_project, execute, now, one, uid
from studyforge.parsers import parse_file


def test_public_url_html_import_and_local_redirect_rejection(tmp_path, monkeypatch):
    monkeypatch.setattr(urls.socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, 0, 0, "", ("93.184.215.14", 443))])
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="<h1>牛顿定律</h1>",
                                                       headers={"content-type": "text/html"}))
    monkeypatch.setattr(urls.httpx, "Client", lambda *args, **kwargs: real_client(transport=transport))
    path = urls.download_public_resource("https://example.org/lesson", "test")
    assert path.suffix == ".html"
    assert "牛顿定律" in parse_file(path)[0]["text"]
    with pytest.raises(ValueError, match="内网"):
        urls.validate_public_url("http://127.0.0.1/secret")


def test_url_job_imports_html_and_delete_removes_stored_copy(tmp_path, monkeypatch):
    original = tmp_path / "lesson.html"
    original.write_text("<h1>动量守恒</h1>", encoding="utf-8")
    monkeypatch.setattr(server, "download_public_resource", lambda url, stem, **kwargs: original)
    project = create_project("网址导入")
    source_id, job_id = uid(), create_job(project["id"], "import_url", {})
    execute("INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,error,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (source_id, project["id"], "https://example.org/lesson", "url", "https://example.org/lesson",
             "[]", "pending", None, now()))
    asyncio.run(server._url_job(job_id, source_id, "https://example.org/lesson"))
    row = one("SELECT * FROM sources WHERE id=?", (source_id,))
    assert row["status"] == "ready"
    stored = Path(row["original_path"])
    assert stored.is_file()
    response = TestClient(server.app).delete(f"/api/sources/{source_id}")
    assert response.status_code == 200
    assert not stored.exists()
    assert one("SELECT * FROM sources WHERE id=?", (source_id,)) is None


def test_voice_endpoint_returns_actual_transcript_and_no_speech_error(monkeypatch):
    client = TestClient(server.app)
    monkeypatch.setattr(server, "transcribe", lambda path, language: [{"text": "这是牛顿第二定律"}])
    response = client.post("/api/voice/transcribe", files={"file": ("voice.webm", b"a" * 2000)})
    assert response.status_code == 200
    assert response.json() == {"text": "这是牛顿第二定律", "language": "zh"}
    monkeypatch.setattr(server, "transcribe", lambda path, language: [])
    response = client.post("/api/voice/transcribe", files={"file": ("voice.webm", b"a" * 2000)})
    assert response.status_code == 422
    assert "没有识别到语音" in response.json()["detail"]


def test_codex_model_setting_and_catalog(monkeypatch):
    save_settings({"codex_model": "gpt-6.1-sol"})
    assert settings()["codex_model"] == "gpt-6.1-sol"
    assert isinstance(client_for("codex"), CodexClient)

    async def models(force=False):
        return {"models": [{"id": "gpt-6.1-sol", "name": "Sol", "efforts": ["low", "high"]}],
                "source": "app_server", "warning": None}

    monkeypatch.setattr(server.model_catalog, "get_models", models)
    response = TestClient(server.app).get("/api/codex/models")
    assert response.json()["models"][0]["id"] == "gpt-6.1-sol"
    assert response.json()["models"][0]["efforts"] == ["low", "high"]


def test_selected_codex_model_reaches_app_server_and_local_default_is_visible(tmp_path, monkeypatch):
    config = tmp_path / "codex"
    config.mkdir()
    (config / "config.toml").write_text('model = "gpt-6-sol"\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(config))
    assert TestClient(server.app).get("/api/settings").json()["codex_local_default"] == "gpt-6-sol"
    save_settings({"codex_model": "gpt-6.1-sol"})
    calls = []

    async def stream_turn(prompt, model):
        calls.append(model)
        yield "delta", "模型已响应"

    monkeypatch.setattr(server.bridge, "stream_turn", stream_turn)
    result = asyncio.run(CodexClient().complete("讲解", "牛顿定律"))
    assert result == "模型已响应"
    assert calls == ["gpt-6.1-sol"]


def test_network_error_explains_failure(monkeypatch):
    original = httpx.AsyncClient

    def fail(request):
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(fail)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: original(transport=transport))
    client = object.__new__(DeepSeekClient)
    client.key = "placeholder"
    client.model = "test"
    with pytest.raises(RuntimeError, match="api.deepseek.com"):
        asyncio.run(client.complete("test", "test"))
