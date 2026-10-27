"""Documented DeepSeek choices plus an explicit, non-inference /models refresh."""
from __future__ import annotations

import hashlib
import time

import httpx

from .deepseek_protocol import http_error

DOC_URL = 'https://api-docs.deepseek.com/quick_start/pricing/'
DOC_DATE = '2026-10-03'
_cache: tuple[str, float, dict] | None = None


def documented_models() -> list[dict]:
    return [
        {'id': 'deepseek-flash', 'name': 'DeepSeek V4.1 Flash', 'listed': False,
         'note': '当前官方调用名 deepseek-flash；支持图像输入。'},
        {'id': 'deepseek-v4-pro', 'name': 'DeepSeek V4 Pro', 'listed': False,
         'note': '官方调用名 deepseek-v4-pro；画面分析仍使用单独配置的视觉模型。'},
        {'id': 'deepseek-v4-flash', 'name': 'V4 Flash 兼容名 → V4.1 Flash', 'listed': False,
         'note': '旧 V4 Flash 已退役；此兼容名目前转向 V4.1 Flash，不能固定旧版本。'}
    ]


def _answer(models=None, *, source='documented', warning=None):
    return {'models': models if models is not None else documented_models(), 'source': source,
            'warning': warning, 'documentation': DOC_URL, 'documentation_checked': DOC_DATE,
            'inference_verified': False}


async def get_models(force=False, *, api_key: str | None = None) -> dict:
    global _cache
    scope = hashlib.sha256(api_key.encode()).hexdigest() if api_key else None
    previous = _cache[2] if scope and _cache and _cache[0] == scope else None
    if not force:
        if previous and time.monotonic() - _cache[1] < 300:
            return previous
        return _answer(warning='已显示官方文档中的型号；点击刷新读取服务目录。' if api_key else
                       '已显示官方文档中的型号；保存 API 密钥后可刷新服务目录。')
    if not api_key:
        return _answer(warning='尚未配置 DeepSeek API 密钥；当前显示官方文档中的型号。')
    try:
        # Refresh metadata only. Never send learning material or chat messages.
        from .api_network import http_options
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=8), **http_options()) as client:
            response = await client.get('https://api.deepseek.com/models',
                                        headers={'Authorization': f'Bearer {api_key}'})
        if response.is_error:
            raise RuntimeError(http_error(response))
        payload = response.json()
        items = payload.get('data') if isinstance(payload, dict) else None
        if not isinstance(items, list) or not items:
            raise ValueError('empty catalog')
        models = documented_models()
        known = {row['id']: row for row in models}
        listed = set()
        for item in items:
            name = item.get('id') if isinstance(item, dict) else None
            if not isinstance(name, str) or not name.strip() or len(name) > 120 or any(ord(c) < 32 for c in name):
                continue
            if name in listed: continue
            listed.add(name)
            if name in known:
                known[name]['listed'] = True
            else:
                models.append({'id': name, 'name': name, 'listed': True,
                    'note': ('旧视觉兼容名，当前转向 V4.1 Flash。' if name == 'deepseek-v4-flash-vision-exp' else
                             '由服务目录返回；该型号的版本和能力需以服务说明及实际调用为准。')})
        if not listed: raise ValueError('invalid catalog')
        answer = _answer(models, source='api', warning=None)
        answer['listed_count'] = len(listed)
        _cache = (scope, time.monotonic(), answer)
        return answer
    except httpx.TimeoutException:
        warning = '读取 DeepSeek 模型目录超时，请检查网络后刷新。'
    except (httpx.ConnectError, httpx.ProxyError):
        warning = '无法连接 DeepSeek 模型目录，请检查网络或代理。'
    except httpx.RequestError:
        warning = '读取 DeepSeek 模型目录时网络中断，请稍后刷新。'
    except RuntimeError as exc:
        warning = str(exc)
    except (ValueError, TypeError):
        warning = 'DeepSeek 返回的模型目录格式无效，请稍后刷新。'
    if previous:
        return previous | {'source': 'cached', 'warning': warning + ' 已保留上次服务目录。'}
    return _answer(warning=warning + ' 当前保留官方文档中的型号，可继续手动选择。')
