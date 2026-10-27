from __future__ import annotations

import asyncio
from fastapi import APIRouter, HTTPException

from . import providers
from .db import many, unj

router = APIRouter(prefix='/api/providers')
_connection_tests = set()


def inactive(identifier):
    if identifier in _connection_tests:
        raise HTTPException(409, '此服务正在检测连接，请等检测结束后修改、退出账号或移除服务')
    from .server import active_chat_conversations
    chats = many('SELECT id FROM conversations WHERE provider=?', (identifier,))
    if any(row['id'] in active_chat_conversations for row in chats):
        raise HTTPException(409, '此服务仍在回复，请结束回复后修改或移除服务')
    for row in many("SELECT payload_json FROM jobs WHERE status IN ('queued','running','pausing','paused')"):
        payload = unj(row['payload_json'], {})
        if identifier in (payload.get('provider'), payload.get('mentor_provider')):
            raise HTTPException(409, '此服务有未完成的任务，请先完成或删除这些任务，再修改或移除服务')


@router.get('')
def services():
    return {'services': providers.list_services()}


@router.post('')
def add(value: dict):
    try: return providers.save_service(value)
    except (ValueError, TypeError) as exc: raise HTTPException(400, str(exc)) from exc
    except Exception as exc: raise HTTPException(503, '服务未保存，请检查本机凭据存储是否可用') from exc


@router.put('/{identifier}')
def update(identifier: str, value: dict):
    inactive(identifier)
    try: return providers.save_service(value, identifier)
    except (ValueError, TypeError) as exc: raise HTTPException(400, str(exc)) from exc
    except Exception as exc: raise HTTPException(503, '服务未保存，请检查本机凭据存储是否可用') from exc


@router.delete('/{identifier}')
def remove(identifier: str):
    inactive(identifier)
    try:
        from .ai import save_settings, settings
        if settings().get('chat_provider') == identifier: save_settings({'chat_provider': 'deepseek'})
        providers.delete_service(identifier)
        return {'deleted': True, 'note': '服务配置和 API 密钥已移除，历史对话及成果保留'}
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.get('/{identifier}/models')
async def models(identifier: str):
    try: return await providers.model_catalog(identifier)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.post('/{identifier}/test')
async def test(identifier: str, value: dict):
    if identifier in _connection_tests: raise HTTPException(409, '此服务已在检测连接，请等待结果')
    _connection_tests.add(identifier)
    client = None
    try:
        from .provider_clients import service_client
        model = providers.model_name(value['model']) if value.get('model') else None
        client = service_client(identifier, model)
        text = await client.complete('只用中文回复一句简短的连接确认。', '请确认你已收到本次连接检测。', max_tokens=1024)
        return {'ok': True, 'model': client.model, 'message': text[:500], 'note': '连接检测会使用少量模型额度'}
    except (ValueError, RuntimeError) as exc: raise HTTPException(400, str(exc)) from exc
    finally:
        try:
            if client: await client.close()
        finally: _connection_tests.discard(identifier)


@router.post('/gemini-cli/install')
async def install_gemini_cli():
    from .gemini_cli import install_cli
    try: return await install_cli()
    except (ValueError, RuntimeError) as exc: raise HTTPException(400, str(exc)) from exc


@router.post('/{identifier}/login')
async def login(identifier: str):
    from .gemini_cli import login
    try: return await asyncio.to_thread(login, identifier)
    except (ValueError, RuntimeError, OSError) as exc: raise HTTPException(400, str(exc)) from exc


@router.post('/{identifier}/logout')
async def logout(identifier: str):
    inactive(identifier)
    from .gemini_cli import logout
    try: return await asyncio.to_thread(logout, identifier)
    except (ValueError, OSError) as exc: raise HTTPException(400, str(exc)) from exc
