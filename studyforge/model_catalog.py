"""A small, resilient catalog for the local Codex model picker."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from .codex_bridge import CodexBridge, codex_executable
from .runtime import background_process_options

_cache: tuple[float, dict] | None = None
_cache_scope = None
_CACHE_SECONDS = 300
EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}


def recommended_generation(models: list[dict]) -> dict:
    by_id = {item['id']: item for item in models}
    for name in ('gpt-6-astra', 'gpt-6.1-sol', 'gpt-6-sol', 'gpt-5.6-sol', 'gpt-5.4'):
        if name in by_id:
            item = by_id[name]
            effort = next((value for value in ('high', 'xhigh', 'medium') if value in item['efforts']),
                          item.get('default_effort'))
            return {'model': name, 'effort': effort, 'name': item['name']}
    raise ValueError('目录中没有可确认的高质量讲解模型，请在更多设置中明确指定模型')


def _normalize(items: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or item.get("hidden") or item.get("visibility") not in (None, "list"):
            continue
        model_id = item.get("model") or item.get("slug") or item.get("id")
        if not isinstance(model_id, str) or not model_id or model_id in seen:
            continue
        seen.add(model_id)
        raw_efforts = item.get("supportedReasoningEfforts") or item.get("supported_reasoning_levels") or []
        if not isinstance(raw_efforts, list): raw_efforts = []
        efforts = [entry.get("reasoningEffort") or entry.get("effort") if isinstance(entry, dict) else entry
                   for entry in raw_efforts]
        result.append({
            "id": model_id,
            "name": item.get("displayName") or item.get("display_name") or model_id,
            "efforts": list(dict.fromkeys(effort for effort in efforts if isinstance(effort, str) and effort in EFFORTS)),
            "default_effort": item.get("defaultReasoningEffort") or item.get("default_reasoning_level"),
            "is_default": bool(item.get("isDefault")),
        })
    return result


async def _bundled_models() -> list[dict]:
    executable = codex_executable()
    result = await asyncio.to_thread(
        subprocess.run, [executable, "debug", "models", "--bundled"],
        capture_output=True, timeout=15, **background_process_options())
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip()
                           or "Codex 自带模型目录读取失败")
    payload = json.loads(result.stdout)
    return payload.get("models", []) if isinstance(payload, dict) else payload


async def get_models(force: bool = False) -> dict:
    global _cache, _cache_scope
    home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
    config = home / 'config.toml'
    try:
        config_revision = (config.stat().st_mtime_ns, config.stat().st_size)
    except OSError:
        config_revision = None
    try:
        auth_revision = (home / 'auth.json').stat().st_mtime_ns
    except OSError:
        auth_revision = None
    scope = (str(home), shutil.which('codex'), config_revision, auth_revision,
             os.environ.get('STUDYFORGE_DATA_DIR'))
    previous = _cache[1] if _cache and _cache_scope == scope else None
    if not force and previous and time.monotonic() - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    probe = CodexBridge()
    failure = None
    try:
        raw = await asyncio.wait_for(probe.list_models(), timeout=20)
        models = _normalize(raw)
        if not models:
            raise RuntimeError("App Server 返回空模型目录")
        answer = {"models": models, "source": "app_server", "warning": None}
    except Exception as exc:
        failure = str(exc) or type(exc).__name__
        if previous and previous.get('source') in ('app_server', 'cached'):
            return previous | {'source': 'cached', 'warning':
                '实时目录暂不可用，保留上次读取的 Codex 目录；刷新后再确认型号和推理档位。'}
        try:
            models = _normalize(await _bundled_models())
            if not models:
                raise RuntimeError("Codex 自带模型目录为空")
            answer = {"models": models, "source": "bundled",
                      "warning": "App Server 模型目录暂不可用；已显示本机 Codex 自带目录。选中模型后仍需实际对话验证可用。"}
        except Exception as fallback_exc:
            raise RuntimeError(f"模型目录暂不可用：{failure}；备用目录：{fallback_exc}") from fallback_exc
    finally:
        await probe.close()
    try:
        answer['recommended_generation'] = recommended_generation(answer['models'])
    except ValueError:
        answer['recommended_generation'] = None
    _cache, _cache_scope = (time.monotonic(), answer), scope
    return answer


async def validate_effort(model: str | None, effort: str | None) -> None:
    if not effort:
        return
    if effort not in EFFORTS:
        raise ValueError("不支持的推理强度")
    catalog = await get_models()
    selected = next((item for item in catalog["models"] if item["id"] == model), None) if model else None
    if selected is None and not model:
        selected = next((item for item in catalog["models"] if item["is_default"]), None)
    if selected is None:
        raise ValueError("无法确认当前模型支持的推理强度；请选择模型列表中的模型，或设为自动")
    if effort not in selected["efforts"]:
        raise ValueError(f"{selected['name']} 不支持 {effort} 推理强度；可用：{', '.join(selected['efforts'])}")
