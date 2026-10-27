"""User-owned model services. Credentials never enter the public registry."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from threading import RLock
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from .config import data_dir, get_secret, set_secret, delete_secret

_lock = RLock()
PROTOCOLS = {'openai', 'gemini', 'gemini_cli'}
BUILTINS = {'codex', 'deepseek'}


def _read():
    path = data_dir() / 'model-services.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []


def _write(rows):
    descriptor, name = tempfile.mkstemp(prefix='.services-', dir=data_dir())
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(rows, handle, ensure_ascii=False, indent=2)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(name, data_dir() / 'model-services.json')
    finally:
        Path(name).unlink(missing_ok=True)


def model_name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 120 or any(ord(c) < 32 for c in value):
        raise ValueError('模型名称须为不超过 120 字符的非空单行文本')
    return value.strip()


def secret_name(identifier):
    if not re.fullmatch(r'svc_[a-f0-9]{32}', identifier): raise ValueError('第三方服务 ID 无效')
    return 'STUDYFORGE_' + identifier.upper() + '_API_KEY'


def get_service(identifier, enabled=True):
    with _lock:
        row = next((row for row in _read() if row['id'] == identifier), None)
    if not row: raise ValueError('AI 服务不存在，请重新选择或添加服务')
    if enabled and not row['enabled']: raise ValueError('此 AI 服务已停用，请在服务管理中启用')
    return dict(row)


def require_provider(identifier):
    if identifier not in BUILTINS: get_service(identifier)
    return identifier


def provider_name(identifier):
    if identifier in BUILTINS: return {'codex': 'Codex', 'deepseek': 'DeepSeek'}[identifier]
    try: return get_service(identifier, enabled=False)['name']
    except ValueError: return '已移除的服务'


def default_model(identifier, config=None):
    if identifier not in BUILTINS: return get_service(identifier, enabled=False)['default_model']
    if config is None:
        from .ai import settings
        config = settings()
    if identifier == 'deepseek': return config.get('deepseek_model') or 'deepseek-flash'
    model = config.get('codex_model')
    if not model:
        import tomllib
        try: model = tomllib.loads((Path(os.environ.get('CODEX_HOME', Path.home()/'.codex'))/'config.toml').read_text(encoding='utf-8')).get('model')
        except (OSError, ValueError): pass
    return model


def public(row):
    result = dict(row)
    if row['protocol'] == 'gemini_cli':
        from .gemini_cli import status
        result.update(status(row['id']))
    else:
        result['configured'] = bool(get_secret(secret_name(row['id']))) or not row['requires_key']
    return result


def list_services():
    with _lock: rows = _read()
    return [public(row) for row in rows]


def save_service(value, identifier=None):
    if not isinstance(value, dict): raise ValueError('服务配置必须为对象')
    known = {'name', 'protocol', 'base_url', 'default_model', 'models', 'enabled', 'supports_tools',
             'supports_vision', 'supports_json', 'requires_key', 'api_key', 'clear_key'}
    if set(value) - known: raise ValueError('存在未知的服务配置字段')
    with _lock:
        rows = _read()
        old = get_service(identifier, enabled=False) if identifier else {}
        protocol = value.get('protocol', old.get('protocol', 'openai'))
        if protocol not in PROTOCOLS: raise ValueError('请选择 OpenAI 兼容、Gemini API 或 Gemini 账号协议')
        if old and protocol != old['protocol']: raise ValueError('已有服务的协议不能修改，请新增另一项服务')
        name = value.get('name', old.get('name', ''))
        if not isinstance(name, str): raise ValueError('服务名称必须为文本')
        name = name.strip()
        if not name or len(name) > 60 or any(ord(c) < 32 for c in name): raise ValueError('服务名称须为 1 至 60 字符的单行文本')
        base = value.get('base_url', old.get('base_url', 'https://generativelanguage.googleapis.com/v1beta' if protocol == 'gemini' else ''))
        if not isinstance(base, str): raise ValueError('API 基础地址必须为文本')
        base = base.strip().rstrip('/')
        if protocol == 'gemini_cli': base = ''
        else:
            parsed = urlparse(base)
            if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or
                (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')))):
                raise ValueError('API 地址须为 HTTPS；本机 localhost／127.0.0.1 可使用 HTTP。不包含密钥、查询参数或片段')
            if base.endswith(('/chat/completions', ':generateContent', '/models')):
                raise ValueError('请填写 API 基础地址，例如 https://服务域名/v1，不要填写完整请求路径')
        model = model_name(value.get('default_model', old.get('default_model', '')))
        models = value.get('models', old.get('models', []))
        if not isinstance(models, list) or len(models) > 200: raise ValueError('手动模型列表最多 200 项')
        models = list(dict.fromkeys([model] + [model_name(item) for item in models]))
        row = {'id': identifier or 'svc_' + uuid4().hex, 'name': name, 'protocol': protocol,
               'base_url': base, 'default_model': model, 'models': models}
        for flag, default in [('enabled', True), ('supports_tools', True), ('supports_vision', protocol != 'openai'),
                              ('supports_json', True), ('requires_key', protocol != 'gemini_cli')]:
            item = value.get(flag, old.get(flag, default))
            if type(item) is not bool: raise ValueError('服务能力选项须为开关值')
            row[flag] = item
        if protocol == 'gemini': row['requires_key'] = True
        if protocol == 'gemini_cli': row.update(requires_key=False, supports_vision=False, supports_json=True)
        key = value.get('api_key', '')
        if not isinstance(key, str) or len(key) > 4096 or any(ord(c) < 32 for c in key): raise ValueError('API 密钥格式无效')
        if value.get('clear_key') and key.strip(): raise ValueError('不能同时清除与保存密钥')
        if type(value.get('clear_key', False)) is not bool: raise ValueError('清除密钥必须是开关值')
        if key.strip(): set_secret(secret_name(row['id']), key.strip())
        elif value.get('clear_key'): delete_secret(secret_name(row['id']))
        if identifier: rows = [row if item['id'] == identifier else item for item in rows]
        else: rows.append(row)
        _write(rows)
    return public(row)


def delete_service(identifier):
    with _lock:
        row = get_service(identifier, enabled=False)
        if row['protocol'] == 'gemini_cli':
            from .gemini_cli import remove_profile
            remove_profile(identifier)
        delete_secret(secret_name(identifier))
        _write([row for row in _read() if row['id'] != identifier])


def validate_preferences(value):
    if not isinstance(value, dict) or len(value) > 100: raise ValueError('模型偏好设置无效')
    result = {}
    for key, item in value.items():
        if not re.fullmatch(r'svc_[a-f0-9]{32}', key): raise ValueError('模型偏好服务 ID 无效')
        get_service(key, enabled=False)
        if not isinstance(item, str): raise ValueError('模型偏好必须为文本')
        result[key] = model_name(item) if item else ''
    return result


def request_error(response, name, model=''):
    from .deepseek_protocol import http_error
    # Never echo service response bodies: proxies sometimes include credentials.
    return http_error(response, model).replace('DeepSeek', name)


async def model_catalog(identifier):
    row = get_service(identifier)
    manual = [{'id': name, 'name': name, 'listed': False} for name in row['models']]
    result = {'models': manual, 'source': 'manual', 'listed_count': 0,
              'provider': identifier, 'warning': ''}
    if row['protocol'] == 'gemini_cli':
        result['warning'] = '账号入口没有公开的模型目录接口；可手动填写账号可用的 Gemini 模型调用名'
        return result
    key = get_secret(secret_name(identifier))
    if row['requires_key'] and not key:
        result['warning'] = '尚未保存 API 密钥；当前显示手动模型列表'
        return result
    headers = {'x-goog-api-key': key} if row['protocol'] == 'gemini' else {'Authorization': 'Bearer '+key} if key else {}
    listed = []
    try:
        from .api_network import http_options
        async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=10), follow_redirects=False, **http_options()) as client:
            page = None
            for _ in range(10):
                response = await client.get(row['base_url']+'/models', headers=headers,
                                            params={'pageSize': 100, **({'pageToken': page} if page else {})} if row['protocol'] == 'gemini' else None)
                if not response.is_success: raise RuntimeError(request_error(response, row['name']))
                data = response.json()
                items = data.get('models' if row['protocol'] == 'gemini' else 'data', [])
                if not isinstance(items, list): raise ValueError('服务目录格式无效')
                for item in items:
                    if not isinstance(item, dict): continue
                    if row['protocol'] == 'gemini' and 'generateContent' not in item.get('supportedGenerationMethods', []): continue
                    name = item.get('name' if row['protocol'] == 'gemini' else 'id')
                    if not name: continue
                    name = model_name(name.removeprefix('models/'))
                    listed.append({'id': name, 'name': str(item.get('displayName') or name)[:160], 'listed': True})
                page = data.get('nextPageToken') if row['protocol'] == 'gemini' else None
                if not page: break
        result.update(source='api', listed_count=len(listed), models=list({item['id']: item for item in manual+listed}.values()))
    except (httpx.HTTPError, RuntimeError, ValueError):
        result['warning'] = '未能读取服务模型目录，请核对地址、密钥、网络和权限；手动填写的模型仍可选择'
    return result
