"""Desktop-owned, streaming access to this project's public GitHub releases only."""
from __future__ import annotations

import os
import re
import asyncio
import ssl
from urllib.parse import urlsplit

import anyio
import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

BASE = 'https://api.github.com/repos/keke271828/StudyForge/releases'


def transfer_target(kind: str, asset_id: int | None, byte_range: str | None):
    if kind == 'latest' and asset_id is None:
        if byte_range:
            raise ValueError('版本检查不接受分段下载')
        return BASE + '/latest', {'Accept': 'application/vnd.github+json'}
    if kind != 'asset' or not isinstance(asset_id, int) or isinstance(asset_id, bool) or not 0 < asset_id <= 2**53 - 1:
        raise ValueError('安装包附件编号无效')
    headers = {'Accept': 'application/octet-stream'}
    if byte_range:
        match = re.fullmatch(r'bytes=0-(\d{1,7})', byte_range)
        if not match or int(match[1]) > 1024**2 - 1:
            raise ValueError('下载试读范围无效')
        headers['Range'] = byte_range
    return f'{BASE}/assets/{asset_id}', headers


def proxy_options() -> dict:
    value = next((os.environ.get(name) for name in
                  ('HTTPS_PROXY', 'https_proxy', 'ALL_PROXY', 'all_proxy', 'HTTP_PROXY', 'http_proxy')
                  if os.environ.get(name)), '')
    if value:
        parsed = urlsplit(value)
        if parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username and not parsed.password:
            return {'trust_env': False, 'proxy': value}
    return {'trust_env': False}


async def transfer(kind: str, asset_id: int | None = None, byte_range: str | None = None,
                   *, client_factory=None):
    target, headers = transfer_target(kind, asset_id, byte_range)
    for attempt in range(5):
        client = (client_factory or httpx.AsyncClient)(
            **proxy_options(), follow_redirects=True,
            timeout=httpx.Timeout(45, connect=10), limits=httpx.Limits(max_connections=2))
        try:
            response = await client.send(client.build_request('GET', target, headers=headers), stream=True)
            if response.url.scheme != 'https':
                raise HTTPException(502, 'GitHub 返回了不受支持的下载地址')
            break
        except BaseException as exc:
            with anyio.CancelScope(shield=True):
                await client.aclose()
            if not isinstance(exc, (httpx.TransportError, ssl.SSLError)):
                raise
            if attempt == 4:
                raise HTTPException(502, '更新连接暂时未成功，请检查网络或稍后重试') from exc
            await asyncio.sleep(min(.25 * 2**attempt, 2))

    async def stream():
        try:
            async for chunk in response.aiter_bytes(chunk_size=64*1024):
                yield chunk
        finally:
            # A cancelled desktop download must close the remote stream as well.
            with anyio.CancelScope(shield=True):
                await response.aclose()
                await client.aclose()

    outgoing = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
    for name in ('content-type', 'content-range', 'retry-after', 'x-ratelimit-reset'):
        if name in response.headers:
            outgoing[name] = response.headers[name]
    if 'content-length' in response.headers and not response.headers.get('content-encoding'):
        outgoing['content-length'] = response.headers['content-length']
    return StreamingResponse(stream(), status_code=response.status_code, headers=outgoing)
