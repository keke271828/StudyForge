from __future__ import annotations

import json
import re
import base64
import io
import asyncio
import hashlib
import shutil
import copy
import os
import tempfile
from threading import RLock
from collections import OrderedDict
from pathlib import Path
from typing import AsyncIterator, Callable

import httpx

from .config import data_dir, get_secret
from .teaching import TEACHER_PERSONA, LECTURE_RULES, TEACHING_TASK_REMINDER
from .teaching_styles import style_policy, style_task_reminder, language_policy
from .learning_modes import mode_policy, mode_structure, mode_task_reminder
from .deepseek_protocol import DeepSeekReplyError, Reply, response_packets, http_error
from .appearance import BACKGROUND_DEFAULTS, validate_background_settings
from .surfaces import SURFACE_DEFAULTS, FONT_DEFAULTS, READABILITY_DEFAULTS, validate_surface_settings
from .desktop_notifications import DEFAULTS as NOTICE_DEFAULTS, validate_settings as validate_notices
from .scheduling import DEFAULTS as SCHEDULING_DEFAULTS, validate_settings as validate_scheduling, model_slot
from .task_retry import DEFAULTS as RETRY_DEFAULTS, validate_settings as validate_retry

DEEPSEEK_BASE = "https://api.deepseek.com"


DEFAULT_SETTINGS = {"deepseek_model": "deepseek-flash", "deepseek_vision_model": "deepseek-flash",
                    "codex_model": "", "codex_generation_model": "", "deepseek_generation_model": "",
                    "whisper_model": "small", "voice_language": "zh",
                    "chat_provider": "codex", "review_mode": "express", "explanation_style": "clear",
                    "output_language": "zh", "default_output_format": "docx",
                    "auto_select_imports": True, "learning_mode": "deep"}
DEFAULT_SETTINGS.update(chat_model_codex=None, chat_model_deepseek=None, chat_effort_codex=None, chat_effort_deepseek=None)
from .asr_backend import DEFAULTS as ASR_DEFAULTS,validate_settings as validate_asr_settings
DEFAULT_SETTINGS.update(ASR_DEFAULTS)
DEFAULT_SETTINGS['provider_model_preferences'] = {}
DEFAULT_SETTINGS['api_connection_mode'] = 'system'
DEFAULT_SETTINGS.update(ui_theme='paper', ui_text_size='standard', ui_density='comfortable',
                        ui_motion='system', ui_focus=False, ui_send_key='enter')
DEFAULT_SETTINGS.update(BACKGROUND_DEFAULTS)
DEFAULT_SETTINGS.update(SURFACE_DEFAULTS, **FONT_DEFAULTS)
DEFAULT_SETTINGS.update(READABILITY_DEFAULTS)
DEFAULT_SETTINGS.update(SCHEDULING_DEFAULTS)
DEFAULT_SETTINGS.update(RETRY_DEFAULTS)
DEFAULT_SETTINGS['generation_quality'] = 'custom'
DEFAULT_SETTINGS.update(background_learning_enabled=True, background_learning_interval_minutes=15,
                        background_learning_daily_limit=6)
DEFAULT_SETTINGS.update(agent_tools_enabled=True, agent_network_enabled=True, agent_web_video_enabled=False,
                        agent_file_write_enabled=True, agent_image_generation_enabled=True,
                        agent_read_roots=[], agent_write_roots=[], agent_max_tool_calls=12,
                        image_api_base='https://api.openai.com/v1', image_model='gpt-image-2.5-flare')
DEFAULT_SETTINGS['video_import_mode'] = 'full'
DEFAULT_SETTINGS['agent_permission_mode'] = 'approval'
DEFAULT_SETTINGS.update(ui_reading_share=.65,ui_generation_options_visible=True,ui_tutor_tools_visible=True)
DEFAULT_SETTINGS.update(NOTICE_DEFAULTS)

_SETTINGS_LOCK = RLock()


def settings() -> dict:
    with _SETTINGS_LOCK:
        path = data_dir() / "settings.json"
        if path.exists():
            return DEFAULT_SETTINGS | json.loads(path.read_text(encoding="utf-8"))
        return DEFAULT_SETTINGS.copy()


def default_provider() -> str:
    """Missing provider fields follow the user's choice, without requiring Codex."""
    provider = settings().get('chat_provider', 'codex')
    if provider == 'codex' and not shutil.which('codex'):
        return 'deepseek'
    from .providers import require_provider
    require_provider(provider)
    return provider


def save_settings(value: dict) -> dict:
    value = dict(value)
    allowed = {"deepseek_model", "deepseek_vision_model", "codex_model", "codex_generation_model",
               "deepseek_generation_model", "voice_language",
               "whisper_model", "chat_provider", "voice_enabled", "review_mode",
               "explanation_style", "output_language", "default_output_format", "auto_select_imports", 'generation_quality', 'learning_mode',
               'agent_tools_enabled', 'agent_network_enabled', 'agent_web_video_enabled', 'agent_file_write_enabled',
               'agent_image_generation_enabled', 'agent_read_roots', 'agent_write_roots', 'agent_max_tool_calls', 'image_api_base', 'image_model',
               'background_learning_enabled', 'background_learning_interval_minutes', 'background_learning_daily_limit'}
    allowed.update({'chat_model_codex', 'chat_model_deepseek', 'chat_effort_codex', 'chat_effort_deepseek'})
    allowed.add('provider_model_preferences')
    allowed.add('api_connection_mode')
    if 'api_connection_mode' in value and value['api_connection_mode'] not in ('system','direct'):
        raise ValueError('API连接方式须为沿用环境配置或直接连接')
    from .providers import require_provider, validate_preferences
    if 'provider_model_preferences' in value:
        value['provider_model_preferences'] = validate_preferences(value['provider_model_preferences'])
    if 'chat_provider' in value: require_provider(value['chat_provider'])
    allowed.update({'ui_theme', 'ui_text_size', 'ui_density', 'ui_motion', 'ui_focus', 'ui_send_key'})
    allowed.update({'ui_reading_share','ui_generation_options_visible','ui_tutor_tools_visible'})
    allowed.add('video_import_mode')
    allowed.add('agent_permission_mode')
    if 'agent_permission_mode' in value and value['agent_permission_mode'] not in ('read_only','approval','full_access'):
        raise ValueError('Agent权限必须为只读、需要审批或完全访问')
    if 'video_import_mode' in value and value['video_import_mode'] not in ('full','subtitles_first'):
        raise ValueError('视频读取方式须为完整音画或字幕优先')
    allowed.update(BACKGROUND_DEFAULTS)
    allowed.update(SURFACE_DEFAULTS);allowed.update(FONT_DEFAULTS);allowed.update(READABILITY_DEFAULTS)
    allowed.update(SCHEDULING_DEFAULTS)
    allowed.update(RETRY_DEFAULTS)
    allowed.update(ASR_DEFAULTS)
    allowed.update(NOTICE_DEFAULTS)
    validate_notices(value)
    validate_scheduling(value)
    validate_retry(value)
    validate_asr_settings(value)
    validate_background_settings(value)
    validate_surface_settings(value)
    if 'ui_focus' in value and type(value['ui_focus']) is not bool:
        raise ValueError('专注模式必须是开关值')
    if 'ui_generation_options_visible' in value and type(value['ui_generation_options_visible']) is not bool:raise ValueError('生成选项显隐必须是开关值')
    if 'ui_tutor_tools_visible' in value and type(value['ui_tutor_tools_visible']) is not bool:raise ValueError('导师工具显隐必须是开关值')
    if 'ui_reading_share' in value and (type(value['ui_reading_share']) not in (float,int) or not .2<=value['ui_reading_share']<=.95):raise ValueError('阅读区比例应在 0.2 至 0.95 之间')
    for key, options in {'ui_theme': {'paper', 'forest', 'night'},
                         'ui_text_size': {'standard', 'large'},
                         'ui_density': {'comfortable', 'compact'},
                         'ui_motion': {'system', 'reduced'},
                         'ui_send_key': {'enter', 'ctrl-enter'}}.items():
        if key in value and (not isinstance(value[key], str) or value[key] not in options):
            raise ValueError(f'{key} 外观设置无效')
    for key in ('deepseek_model', 'deepseek_vision_model', 'codex_model', 'codex_generation_model',
                'deepseek_generation_model', 'chat_model_codex', 'chat_model_deepseek'):
        if key in value:
            model = value[key]
            if not isinstance(model, str) or len(model) > 120 or any(ord(char) < 32 for char in model):
                raise ValueError('模型名称须为不超过 120 字符的单行文本')
            value[key] = model.strip()
    if 'chat_effort_codex' in value:
        from .model_catalog import EFFORTS
        if not isinstance(value['chat_effort_codex'], str) or value['chat_effort_codex'] not in EFFORTS | {''}:
            raise ValueError('不支持的 Codex 推理强度')
    if 'chat_effort_deepseek' in value:
        from .deepseek_protocol import thinking_parameters
        if not isinstance(value['chat_effort_deepseek'], str): raise ValueError('不支持的 DeepSeek 推理强度')
        if value['chat_effort_deepseek']: thinking_parameters(value['chat_effort_deepseek'])
    if 'background_learning_enabled' in value and type(value['background_learning_enabled']) is not bool:
        raise ValueError('后台学习必须是开关值')
    for key, low, high in [('background_learning_interval_minutes', 5, 120), ('background_learning_daily_limit', 1, 24)]:
        if key in value and (type(value[key]) is not int or not low <= value[key] <= high):
            raise ValueError(f'{key} 必须是 {low} 到 {high} 之间的整数')
    for key in ('agent_tools_enabled', 'agent_network_enabled', 'agent_web_video_enabled', 'agent_file_write_enabled', 'agent_image_generation_enabled'):
        if key in value and not isinstance(value[key], bool): raise ValueError(f'{key} 必须是开关值')
    for key in ('agent_read_roots', 'agent_write_roots'):
        if key in value:
            roots = value[key]
            if not isinstance(roots, list) or len(roots) > 20 or any(not isinstance(root, str) or not Path(root).is_absolute() or not Path(root).is_dir() for root in roots):
                raise ValueError('授权目录须为已存在的本机绝对路径，最多 20 个')
            value[key] = [str(Path(root).resolve()) for root in roots]
    if 'agent_max_tool_calls' in value and (type(value['agent_max_tool_calls']) is not int or not 1 <= value['agent_max_tool_calls'] <= 30):
        raise ValueError('每次工具调用额度须在 1 到 30 之间')
    if 'image_api_base' in value:
        from urllib.parse import urlparse
        if not isinstance(value['image_api_base'], str): raise ValueError('绘图 API 地址必须是 HTTPS 地址')
        parsed = urlparse(value['image_api_base'])
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password: raise ValueError('绘图 API 地址必须是 HTTPS 地址')
    choices = {'generation_quality': {'quality', 'custom'}, "review_mode": {"express", "fast", "balanced", "strict"},
               "explanation_style": {"clear", "balanced", "academic"}, "learning_mode": {"overview", "deep", "research"},
               "output_language": {"zh", "bilingual", "en"},
               "voice_language": {"auto", "zh", "en"},
               "whisper_model": {"tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"},
               "default_output_format": {"docx", "pdf", "pptx", "mm", "apkg", "py", "ipynb", "js", "ts", "cpp", "m", "wl", "zip"}}
    for key, options in choices.items():
        if key in value and (not isinstance(value[key], str) or value[key] not in options):
            raise ValueError(f"{key} 设置无效")
    for key in ('auto_select_imports', 'voice_enabled'):
        if key in value and type(value[key]) is not bool:
            raise ValueError(f'{key} 必须是开关值')
    # Separate UI queues can update preferences, model and learning mode at once.
    # Lock the entire read/merge/write and replace atomically so readers (including
    # MCP processes) never see a truncated JSON document.
    with _SETTINGS_LOCK:
        merged = settings() | {key: item for key, item in value.items() if key in allowed}
        if 'provider_model_preferences' in value:
            merged['provider_model_preferences'] = settings().get('provider_model_preferences', {}) | value['provider_model_preferences']
        if merged.get('ui_background') == 'image' and not merged.get('ui_background_asset'):
            raise ValueError('请先上传背景图片')
        if merged.get('ui_font_family') == 'custom' and not merged.get('ui_font_asset'):
            raise ValueError('请先上传自定义字体')
        directory = data_dir()
        descriptor, name = tempfile.mkstemp(prefix='.settings-', suffix='.tmp', dir=directory)
        pending = Path(name)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                json.dump(merged, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(pending, directory / 'settings.json')
        finally:
            pending.unlink(missing_ok=True)
        return merged


def parse_json_response(value: str) -> dict:
    value = value.strip()
    if not value: raise ValueError('模型返回了空的结构化内容')
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", value, re.S | re.I)
    if fenced:
        value = fenced.group(1)
    else:
        start, end = value.find("{"), value.rfind("}")
        if start >= 0 and end > start:
            value = value[start:end + 1]
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        if exc.msg != 'Invalid \\escape' or value[exc.pos:exc.pos+2] not in (r'\(',r'\)',r'\[',r'\]'):
            raise
        from .json_math import escape_delimiters
        # Preserve the literal delimiter; never guess missing punctuation,
        # unknown escapes, formula commands or the schema. Strict decoding and
        # the caller's existing validation must still succeed afterwards.
        result = json.loads(escape_delimiters(value))
    if not isinstance(result, dict):
        raise ValueError("模型未返回 JSON 对象")
    return result


async def complete_json(client, system, user, validate=None, on_repair=None):
    """One bounded format repair, in the same private context as the caller."""
    request_system, request_user = system, user
    raw = await client.complete(request_system, request_user, json_mode=True)
    for attempt in range(2):
        try:
            result = parse_json_response(raw)
            if validate: validate(result)
            return result
        except (ValueError, TypeError, KeyError) as exc:
            discard = getattr(client, 'discard_response', None)
            if discard: discard(request_system, request_user, json_mode=True)
            from .task_retry import current_attempt
            if current_attempt.get() and current_attempt.get().unsafe_replay:
                raise RuntimeError('返回内容无效，且当前步骤可能已经修改用户文件；请核对结果后继续，未自动重放该操作') from exc
            if attempt: raise RuntimeError('模型返回的 JSON 内容经一次格式修复仍不符合任务要求，请重试；已完成的成果保留') from exc
            if on_repair:on_repair()
            # Preserve the original request and schema, never put private answers
            # in the public conversation or blindly remove punctuation from JSON.
            request_system = system+'\n上一次返回格式无效。只返回一个完整合法的JSON对象，保留要求的键名、字段类型和内容；不加说明文字。'
            request_user = user+'\n上次格式错误：'+str(exc)+'\n上次回答（仅作格式修复参考）：\n'+str(raw)[:20000]
            raw = await client.complete(request_system, request_user, json_mode=True)
    raise RuntimeError('结构化任务未完成')


class DeepSeekClient:
    provider = 'deepseek'
    service_name = 'DeepSeek'
    protocol_version = 1
    def __init__(self, model: str | None = None, agent_runtime=None, conversation=None, effort: str | None = None,
                 vision_model: str | None = None):
        self.model = model or settings().get("deepseek_model") or 'deepseek-flash'
        self._vision_model = vision_model or settings().get('deepseek_vision_model','deepseek-flash')
        self.key = get_secret("DEEPSEEK_API_KEY")
        if not self.key:
            raise RuntimeError("请先在设置中保存 DeepSeek API 密钥")
        self.agent_runtime = agent_runtime
        self.effort = effort if effort is not None else getattr(agent_runtime, 'effort', None)
        self.conversation = None if getattr(agent_runtime, 'private_context', False) else copy.deepcopy(conversation)

        self.detached = bool(getattr(agent_runtime, 'job_id', None) or getattr(agent_runtime, 'branch_key', None))
        self.session_messages = []

    def supports_tools(self): return True

    def prepare_body(self, body):
        # Preserve an explicit disabled request (e.g. a short background note).
        # None retains the provider default; never lower a selected strength.
        body = copy.deepcopy(body)
        effort = getattr(self, 'effort', None)
        if effort and 'thinking' not in body:
            from .deepseek_protocol import thinking_parameters
            body.update(thinking_parameters(effort))
        return body

    def assistant_message(self, reply):
        result = {'role': 'assistant', 'content': reply.content, 'reasoning_content': reply.reasoning}
        if reply.calls: result['tool_calls'] = list(reply.calls.values())
        return result

    def http_client(self):
        """Reuse this task's connections without sharing credentials or dialogue."""
        client = getattr(self, '_http', None)
        if client is None or client.is_closed:
            from .api_network import http_options
            client = httpx.AsyncClient(timeout=httpx.Timeout(240, connect=15),
                limits=httpx.Limits(max_connections=8, max_keepalive_connections=4,
                                    keepalive_expiry=60), **http_options())
            self._http = client
        return client

    async def stream_packets(self, body):
        async with self.http_client().stream('POST', f'{DEEPSEEK_BASE}/chat/completions', json=body,
                                 headers={'Authorization': f'Bearer {self.key}'},
                                 timeout=httpx.Timeout(240, connect=15)) as response:
            response.raise_for_status()
            async for packet in response_packets(response): yield packet

    def fork(self):
        runtime = self.agent_runtime.fork() if self.agent_runtime else None
        return DeepSeekClient(self.model, runtime, copy.deepcopy(self.conversation), effort=self.effort,
                              vision_model=self._vision_model)

    async def close(self):
        client = getattr(self, '_http', None)
        self._http = None
        if client is not None and not client.is_closed:
            await client.aclose()

    def request_status(self, message: str) -> None:
        """Expose recovery in the same job card, without changing its progress."""
        runtime = getattr(self, 'agent_runtime', None)
        if not runtime or not runtime.job_id: return
        from .db import connect, j, now, unj
        with connect() as database:
            row = database.execute('SELECT status,result_json FROM jobs WHERE id=?', (runtime.job_id,)).fetchone()
            if not row or row['status'] not in ('queued', 'running', 'pausing'): return
            result = unj(row['result_json'], {})
            if not message and 'request_status' not in result: return
            if message: result['request_status'] = message
            else: result.pop('request_status', None)
            database.execute('UPDATE jobs SET result_json=?,updated_at=? WHERE id=?', (j(result), now(), runtime.job_id))

    async def _post(self, body: dict, timeout: int = 240, retry: bool = True) -> dict:
        client = self.http_client()
        for attempt in range(2 if retry else 1):
            try:
                from .vision_batches import admitted_request_body
                async with admitted_request_body(body, 'deepseek', getattr(self, 'agent_runtime', None)) as prepared:
                    from .library_policy import model_request
                    try:
                        with model_request(prepared, 'deepseek') as meter:
                            response = await client.post(f"{DEEPSEEK_BASE}/chat/completions", json=prepared,
                                                         headers={"Authorization": f"Bearer {self.key}"},
                                                         timeout=httpx.Timeout(timeout, connect=15))
                            response.raise_for_status()
                            packet = response.json(); meter.accept(packet)
                            return packet
                    finally:
                        # The queued descriptor never retains a materialized
                        # body, including across network/content retries.
                        prepared = None
            except (httpx.ConnectError, httpx.ProxyError, httpx.ConnectTimeout) as exc:
                if attempt == 0 and retry:
                    await asyncio.sleep(1)
                    continue
                raise RuntimeError("无法连接 api.deepseek.com。请检查网络或代理；DeepSeek 直接连接 API，无需启动 Codex。") from exc
            except httpx.TimeoutException as exc:
                raise RuntimeError("DeepSeek 请求超时，请稍后重试或减少单次资料长度。") from exc
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(http_error(exc.response, body.get('model'))) from exc
        raise RuntimeError("DeepSeek 请求未完成")

    async def _request_content(self, body: dict, timeout: int = 240, attempts: int = 2) -> str:
        for attempt in range(attempts):
            reply = Reply(service_name=self.service_name)
            try:
                reply.accept(await self._post(body, timeout) if attempts > 1 else await self._post(body, timeout, retry=False))
                reply.validate(body['model'])
                if reply.calls: raise DeepSeekReplyError('模型请求了未启用的工具')
                self.request_status('')
                return reply.content
            except DeepSeekReplyError as exc:
                if not exc.retryable: raise
                if attempts == 1: raise RuntimeError('后台整理响应未完成，已停止此次请求') from exc
                if attempt:
                    raise RuntimeError(str(exc) + '；自动重试一次仍未成功，请稍后重试。没有生成空文档。') from exc
                self.request_status(self.service_name+' 响应未完成，正在自动重试一次…')
                await asyncio.sleep(.3)
        raise RuntimeError('DeepSeek 请求未完成')

    async def complete(self, system: str, user: str, json_mode: bool = False, max_tokens: int | None = None) -> str:
        if getattr(self, 'agent_runtime', None) or getattr(self, 'conversation', None):
            from .dialogue_scope import validate_client
            validate_client(self.agent_runtime,self.conversation)
            messages = [{'role': 'system', 'content': system}]
            if self.conversation:
                from .db import many
                from .message_focus import history as focused_history, model_history
                history = [] if self.detached else focused_history(self.conversation.get('id'))
                messages += model_history(history or self.conversation.get('messages', []))
            messages.append({'role': 'user', 'content': user})
            final = ''
            async for kind, item in self.agent_stream(messages, json_mode=json_mode):
                if kind == 'final': final = item
            return final
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            body['max_tokens'] = max_tokens
            body['thinking'] = {'type': 'disabled'}
        body = self.prepare_body(body)
        return await self._request_content(body, timeout=90, attempts=1) if max_tokens is not None else await self._request_content(body)

    async def agent_stream(self, messages: list[dict], json_mode=False):
        try:
            async for event in self._agent_stream(messages, json_mode): yield event
        except (httpx.ConnectError, httpx.ProxyError, httpx.ConnectTimeout) as exc:
            raise RuntimeError('无法连接 api.deepseek.com。请检查网络或代理；DeepSeek 无需启动 Codex。') from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError('DeepSeek 请求超时，请稍后重试。') from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(http_error(exc.response, self.model)) from exc

    async def _agent_stream(self, messages: list[dict], json_mode=False):
        from .agent_tools import AGENT_RULES, LEARNING_RECORD_TOOLS, tool_specs
        from .db import connect, one, many, j, now, unj
        from .dialogue_scope import CONTEXT_BOUNDARY, validate_client, validate_conversation
        runtime = getattr(self, 'agent_runtime', None)
        validate_client(runtime,getattr(self,'conversation',None))
        if runtime: runtime.calls = 0
        messages = [dict(row) for row in messages]
        conversation_id = runtime.conversation_id if runtime else (getattr(self, 'conversation', None) or {}).get('id')
        if getattr(runtime, 'private_context', False) or getattr(self, 'detached', False): conversation_id = None
        published_count = 0
        if conversation_id:
            validate_conversation(conversation_id,getattr(runtime,'project_id',None))
            published_count = len(many('SELECT id FROM messages WHERE conversation_id=?', (conversation_id,)))
            saved = one('SELECT * FROM agent_dialogue_state WHERE conversation_id=?', (conversation_id,))
            # Tools and provider reasoning remain internal; the student sees only
            # final replies. Reattach newer public messages after the saved state.
            scope=one('SELECT * FROM agent_dialogue_scopes WHERE conversation_id=?',(conversation_id,))
            scope_matches=bool(runtime and scope and scope['project_id']==runtime.project_id and scope['scope_key']==runtime.state_key())
            if saved and scope_matches and saved['protocol_version'] == self.protocol_version and saved['published_count'] <= len(messages) - 2:
                messages = [messages[0]] + unj(saved['messages_json'], []) + messages[1 + saved['published_count']:]
        messages[0]['content'] += CONTEXT_BOUNDARY
        if runtime:
            messages[0]['content'] += '\n' + AGENT_RULES + '\n工具环境：' + runtime.context()
        for message in messages:
            if message['role'] == 'assistant':
                message.setdefault('reasoning_content', '')
                if message.get('tool_calls'): message['content'] = message.get('content') or ''
        limit = settings().get('agent_max_tool_calls', 12) + 2
        for round_number in range(limit):
            body = {'model': self.model, 'messages': messages, 'stream': True}
            if runtime and self.supports_tools() and round_number < limit - 1:
                # Omitting tool_choice uses the provider's default and avoids
                # compatibility failures in thinking-mode tool calls.
                body.update(tools=tool_specs(names=None if settings().get('agent_tools_enabled',True) else LEARNING_RECORD_TOOLS))
            if json_mode: body['response_format'] = {'type': 'json_object'}
            body = self.prepare_body(body)
            for attempt in range(2):
                reply = Reply(service_name=self.service_name)
                try:
                    async with model_slot(self.provider, runtime):
                        async for packet in self.stream_packets(body):
                            delta = reply.accept(packet)
                            if delta: yield 'delta', delta
                    reply.validate(self.model)
                    break
                except DeepSeekReplyError as exc:
                    if not exc.retryable: raise
                    if attempt:
                        raise RuntimeError(str(exc) + '；自动重试一次仍未成功，请稍后重试。没有生成空文档。') from exc
                except httpx.HTTPStatusError as exc:
                    raise RuntimeError(http_error(exc.response, self.model).replace('DeepSeek', self.service_name)) from exc
                except (httpx.TransportError, httpx.TimeoutException) as exc:
                    if attempt:
                        reason = '请求超时' if isinstance(exc, httpx.TimeoutException) else '网络连接失败或响应中断'
                        raise RuntimeError(f'{self.service_name}（{self.model}）{reason}；自动重试一次仍未成功，请检查网络或代理后重试。没有生成空文档。') from exc
                # Retry only the pending response, preserving completed tool
                # results. Never execute calls from an interrupted response.
                recovery = self.service_name + ' 响应未完成，正在自动重试一次…'
                self.request_status(recovery)
                yield 'replace', ''
                yield 'status', recovery
                await asyncio.sleep(.3)
            self.request_status('')
            calls, content, reasoning = reply.calls, reply.content, reply.reasoning
            if not calls:
                if conversation_id:
                    messages.append(self.assistant_message(reply))
                    count = published_count + (0 if runtime and runtime.job_id else 1)
                    with connect() as database:
                        database.execute('INSERT OR REPLACE INTO agent_dialogue_state '
                            '(conversation_id,published_count,messages_json,updated_at,protocol_version) VALUES (?,?,?,?,?)',
                            (conversation_id, count, j(messages[1:]), now(), self.protocol_version))
                        if runtime:
                            database.execute('INSERT OR REPLACE INTO agent_dialogue_scopes VALUES (?,?,?)',
                                             (conversation_id,runtime.project_id,runtime.state_key()))
                yield 'final', content; return
            assistant = self.assistant_message(reply)
            messages.append(assistant)
            for call in calls.values():
                if not runtime: raise RuntimeError('模型请求了未启用的工具')
                yield 'tool', {'tool': call['function']['name'], 'status': 'running'}
                result = await runtime.execute(call['function']['name'], call['function']['arguments'])
                yield 'tool', {'tool': call['function']['name'], 'status': 'failed' if 'error' in result else 'completed',
                               'result': {key: value for key, value in result.items() if key not in ('text', 'description', 'results')}}
                messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(result, ensure_ascii=False)})
        raise RuntimeError('AI 工具调用达到轮数限制，请缩小任务范围')

    async def analyze_image(self, path: Path, locator: str, ocr_text: str = "") -> str:
        from .vision_batches import image_request_body
        from .vision_inflight import observe
        async def request(frames):
            body = await image_request_body(self, frames, structured=False)
            return {frames[0]['id']: await self._request_content(body, timeout=180)}
        result = await observe(self, [{'id': '0', 'path': path, 'locator': locator, 'ocr': ocr_text}], request)
        return result.get('0', '')

    @property
    def vision_model(self):
        return getattr(self, '_vision_model', None) or settings().get('deepseek_vision_model', 'deepseek-flash')

    @property
    def supports_image_batches(self): return True

    async def analyze_images(self, frames: list[dict]) -> dict[str, str]:
        from .vision_batches import BATCH_SIZE, image_request_body, observations
        from .vision_inflight import observe
        if not self.supports_image_batches: raise RuntimeError('当前模型服务未启用图片读取')
        if not 1 <= len(frames) <= BATCH_SIZE: raise ValueError('逐批核对图片数量超出限制')
        async def request(selected):
            body = await image_request_body(self, selected, structured=True)
            raw = await self._request_content(body, timeout=240)
            return observations(parse_json_response(raw), [frame['id'] for frame in selected])
        return await observe(self, frames, request)

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        # Legacy text-only callers cannot reset an interrupted partial reply.
        # Publish only the verified final text; the UI uses agent_stream events.
        async for kind, value in self.agent_stream(messages):
            if kind == 'final': yield value


class CodexClient:
    """Use the configured Codex App Server model for document and grading calls."""

    def __init__(self, private_bridge=None, model: str | None = None, effort: str | None = None, agent_runtime=None, conversation=None):
        self.detached = bool(getattr(agent_runtime, 'job_id', None) or getattr(agent_runtime, 'branch_key', None))
        if private_bridge is None and (getattr(agent_runtime, 'private_context', False) or self.detached):
            from .codex_bridge import CodexBridge
            private_bridge = CodexBridge()
        self.private_bridge = private_bridge
        self.model = model or settings().get("codex_model") or None
        self.effort = effort
        self.agent_runtime = agent_runtime
        self.conversation = None if getattr(agent_runtime, 'private_context', False) else copy.deepcopy(conversation)
        if self.detached and self.conversation: self.conversation['remote_thread_id'] = None

    def fork(self):
        from .codex_bridge import CodexBridge
        runtime = self.agent_runtime.fork() if self.agent_runtime else None
        child = CodexClient(CodexBridge(), self.model, self.effort, runtime, copy.deepcopy(self.conversation))
        child.detached = True
        if child.conversation: child.conversation['remote_thread_id'] = None
        return child

    async def close(self) -> None:
        if self.private_bridge:
            await self.private_bridge.close()

    async def complete(self, system: str, user: str, json_mode: bool = False,
                       image_paths: list[str] | None = None) -> str:
        from .codex_bridge import bridge, bridge_for
        from .dialogue_scope import validate_client
        validate_client(self.agent_runtime,self.conversation)
        prompt = f"任务要求：\n{system}\n\n输入内容：\n{user}"
        if json_mode:
            prompt += "\n\n只输出一个有效 JSON 对象，不要 Markdown 代码围栏。"
        chunks: list[str] = []
        turn_options = {"model": self.model}
        if self.effort:
            turn_options["effort"] = self.effort
        if image_paths:
            turn_options['image_paths'] = image_paths
        if self.agent_runtime: turn_options['agent_runtime'] = self.agent_runtime
        if self.conversation:
            from .db import one, many
            current = None if self.detached else one('SELECT remote_thread_id FROM conversations WHERE id=?', (self.conversation.get('id'),))
            if current: self.conversation['remote_thread_id'] = current['remote_thread_id']
            turn_options['remote_thread_id'] = self.conversation.get('remote_thread_id')
            from .message_focus import history as focused_history, model_history
            history = [] if self.detached else focused_history(self.conversation.get('id'))
            turn_options['fallback_history'] = json.dumps(model_history(history or self.conversation.get('messages', [])), ensure_ascii=False)
        final = None
        connection = self.private_bridge or (bridge_for(self.conversation['id']) if self.conversation else bridge)
        async for kind, value in connection.stream_turn(prompt, **turn_options):
            if kind == 'thread' and self.conversation:
                self.conversation['remote_thread_id'] = value
                from .db import execute
                if not self.detached: execute('UPDATE conversations SET remote_thread_id=? WHERE id=?', (value, self.conversation['id']))
            elif kind == "delta":
                chunks.append(value)
            elif kind == 'final':
                final = value
        result = (final if final is not None else "".join(chunks)).strip()
        if not result:
            raise RuntimeError("Codex 没有返回内容；请在设置里检查模型和 Codex 登录状态")
        return result

    async def analyze_image(self, path: Path, locator: str, ocr_text: str = "") -> str:
        return await self.complete('客观读取原图中的公式、坐标轴、板书和图表。无法辨认处明确说明。',
                                   f'来源位置：{locator}\n本地 OCR：{ocr_text}', image_paths=[str(path.resolve())])


def client_for(provider: str | None = None, model: str | None = None, generation: bool = False,
               effort: str | None = None, agent_runtime=None, conversation=None, vision_model: str | None = None):
    provider = provider or default_provider()
    if agent_runtime is None:
        from .agent_tools import AgentRuntime
        agent_runtime = AgentRuntime(project_id=(conversation or {}).get('project_id'),
                                     conversation_id=(conversation or {}).get('id'),provider=provider, model=model, effort=effort)
    if provider == "codex":
        return CodexClient(model=model,
                           effort=effort, agent_runtime=agent_runtime, conversation=conversation)
    if provider == "deepseek":
        return DeepSeekClient(model=model,
                              agent_runtime=agent_runtime, conversation=conversation, effort=effort, vision_model=vision_model)
    from .provider_clients import service_client
    return service_client(provider, model, agent_runtime, conversation)


def source_chunks(sources: list[dict], max_chars: int = 12000) -> list[str]:
    chunks: list[str] = []
    current = ""
    for source in sources:
        for item in source["segments"]:
            header = f"\n[来源 {source['name']}｜{item['locator']}]\n"
            continuation = header + '[原文续接]\n'
            if max_chars <= len(continuation):
                raise ValueError('原文分段长度不足以保留来源定位，请增大分段长度')
            value = ''.join((header, str(item.get("text", "")), "\n"))
            offset, prefix = 0, ''
            while offset < len(value):
                available = max_chars - len(current)
                if available < 1000:
                    if current: chunks.append(current)
                    current = ""
                    available = max_chars
                count = min(available - len(prefix), len(value) - offset)
                current += prefix + value[offset:offset + count]
                offset += count
                if offset < len(value):
                    chunks.append(current)
                    current = ''
                    prefix = continuation
    if current:
        chunks.append(current)
    return chunks


_VISION_CACHE = OrderedDict()
_VISION_CACHE_OWNERS = {}
_VISION_CACHE_CHAR_LIMIT = 1_000_000
_VISION_CACHE_EPOCH = 0
# Cache operations also run from FastAPI's synchronous deletion endpoints.
from threading import RLock
_VISION_CACHE_LOCK = RLock()


def clear_source_digest_cache(source_id=None, project_id=None) -> None:
    global _VISION_CACHE_EPOCH
    from .vision_cache import clear, clear_source, clear_project
    with _VISION_CACHE_LOCK:
        _VISION_CACHE_EPOCH += 1
        if source_id is None and project_id is None:
            _VISION_CACHE.clear();_VISION_CACHE_OWNERS.clear()
        else:
            for key in tuple(_VISION_CACHE):
                owner = _VISION_CACHE_OWNERS.get(key)
                if (owner is None or (source_id is not None and owner[0] == source_id) or
                    (source_id is None and owner[1] == project_id) or
                    (owner[0] is None and (owner[1] is None or owner[1] == project_id))):
                    _VISION_CACHE.pop(key,None);_VISION_CACHE_OWNERS.pop(key,None)
    if source_id is not None:clear_source(source_id,project_id)
    elif project_id is not None:clear_project(project_id)
    else:clear()


def vision_identity(client):
    from .vision_batches import POLICY_VERSION
    base=client
    while type(base).__name__ == 'PausableClient':base=base.client
    model=getattr(base,'vision_model',None)
    service=getattr(base,'service',{}) or {}
    endpoint=service.get('base_url') if isinstance(service,dict) else None
    if endpoint is None and isinstance(base,DeepSeekClient):endpoint=DEEPSEEK_BASE
    # Actual image model/endpoint and adapter version are part of identity.
    # Old keys did not prove these values, so are not silently reused.
    return ['source-vision-v2',type(base).__module__,type(base).__qualname__,
            model or settings().get('deepseek_vision_model'),
            getattr(base,'model',None) if model is None else None,
            getattr(base,'effort',None),getattr(base,'provider',None),endpoint,
            service.get('protocol') if isinstance(service,dict) else None,
            getattr(base,'protocol_version',None),POLICY_VERSION]


def _memory_vision(key):
    with _VISION_CACHE_LOCK:
        value=_VISION_CACHE.get(key)
        if value is not None:_VISION_CACHE.move_to_end(key)
        return value


def _remember_vision(key,description,source,epoch):
    with _VISION_CACHE_LOCK:
        if epoch != _VISION_CACHE_EPOCH:return
        for missing in _VISION_CACHE_OWNERS.keys()-_VISION_CACHE.keys():_VISION_CACHE_OWNERS.pop(missing,None)
        _VISION_CACHE[key]=description;_VISION_CACHE.move_to_end(key)
        _VISION_CACHE_OWNERS[key]=(source.get('id'),source.get('project_id'))
        weight=sum(len(value) for value in _VISION_CACHE.values())
        while _VISION_CACHE and (len(_VISION_CACHE)>64 or weight>_VISION_CACHE_CHAR_LIMIT):
            old,value=_VISION_CACHE.popitem(last=False);weight-=len(value);_VISION_CACHE_OWNERS.pop(old,None)


def _prepare_digest_sources(sources):
    """Pure local preparation, with no AI calls or progress callbacks."""
    working = [dict(source, segments=copy.deepcopy(source['segments'])) for source in sources]
    images = []
    for source in working:
        for item in source['segments']:
            metadata = item.get('meta', {})
            if 'image_path' not in metadata: continue
            path = Path(str(metadata['image_path']))
            if path.is_file(): images.append((source, item, path))
    return working, images


def _assemble_source_digest(sources, working, include_source_ids):
    from .source_origins import for_records,ARTIFACT_ROLES
    chunks = source_chunks(working)
    if not chunks:
        raise ValueError("所选资料没有可解析内容，请先查看资料库中的解析结果")
    paths = '\n'.join(f"- {source['name']}：{source.get('original_path', '原文输入')}" for source in sources)
    scoped = any(source.get('read_manifest', {}).get('method', '').startswith('explicit_selected') for source in sources)
    generated = any(source.get('read_manifest', {}).get('content_origin', {}).get('role') in ARTIFACT_ROLES for source in working)
    duplicate_names=set()
    if generated:
        from collections import Counter
        duplicate_names={name for name,count in Counter(source['name'] for source in working).items() if count>1}
    heading = ('本次选定原文范围（未概括、未截断）\n只读取下方选定页或选段，不代表已经通读整本原文件。'
               if scoped else '原资料全文（未概括、未截断）')
    if generated:
        heading = ('本次所选文件的选段（未概括、未截断）\n只读取下方选定页或选段，不代表已经通读整本文件。'
                   if scoped else '所选文件全文（未概括、未截断）')
    # Join references to existing text once, rather than first constructing a
    # second full original and then copying it again to add the document header.
    pieces = [for_records(working),'## 保存的原文件\n', paths, '\n\n## ', heading, '\n']
    for source in working:
        for item in source['segments']:
            pieces.append(f"\n[来源 {source['name']}｜{item['locator']}]")
            if include_source_ids or source['name'] in duplicate_names: pieces.append(f" [资料ID:{source['id']}]")
            pieces.extend(('\n', str(item.get('text', '')), '\n'))
    return ''.join(pieces), chunks


async def source_digest(client: DeepSeekClient, sources: list[dict],
                        on_chunk: Callable[[int, int], None] | None = None,
                        include_source_ids: bool = False,
                        on_image: Callable[[int, int, int], None] | None = None,
                        on_cache: Callable[[dict], None] | None = None) -> tuple[str, list[str]]:
    from .materials import file_sha256
    from .vision_batches import BATCH_SIZE
    from .scheduling import run_local
    base = client
    while type(base).__name__ == 'PausableClient': base = base.client
    identity=vision_identity(base)
    reuse=dict(total_images=0,memory_hits=0,disk_hits=0,inflight_hits=0,new_images=0,failed_images=0,
               cache_read_failures=0,cache_save_failures=0,vision_model=identity[3])
    # AI descriptions must never become the preserved original or a quotation
    # index. Only copy segments; limitations still reach the reading manifest.
    working, images = await run_local('source_prepare', _prepare_digest_sources, sources,
                                     label='原文与图像索引准备', track_outputs=False)
    images_done = images_failed = 0
    batch_method = getattr(client, 'analyze_images', None)
    batch_supported = (callable(batch_method) and callable(getattr(base, 'analyze_images', None))
                       and getattr(base, 'supports_image_batches', True))

    def finish(record, description=None, error=None):
        nonlocal images_done, images_failed
        source, item, _, original, _, _ = record
        if error is None:
            item['text'] = original + '\n[画面分析] ' + description
        else:
            images_failed += 1
            item['text'] = original + f'\n[画面分析待核实：{type(error).__name__}]'
            if source.get('read_manifest'):
                source['read_manifest']['limitations'].append(f"{item['locator']}：图像未成功理解，须核对原图")
        images_done += 1
        if on_image: on_image(images_done, len(images), images_failed)

    async def validate(record, description):
        source, _, path, _, checksum, key = record
        if not isinstance(description, str) or not description.strip(): raise ValueError('画面分析为空')
        if await asyncio.to_thread(file_sha256, path) != checksum: raise ValueError('图像在分析期间变更')

    async def save(found,epoch):
        from .vision_cache import remember_many
        if epoch != _VISION_CACHE_EPOCH:return
        rows=[dict(key=record[5],description=text,project_id=record[0].get('project_id'),source_id=record[0].get('id'))
              for record,text in found if len(text)<=32000]
        try:
            saved=await asyncio.to_thread(remember_many,rows)
        except Exception:
            reuse['cache_save_failures']+=len(rows)
            # A cache failure must not erase a successfully read image. Original
            # provenance and all actual model observations remain in this task.
            for record,_ in found:
                manifest=record[0].get('read_manifest')
                if manifest is not None:
                    note='画面复用缓存未保存；本次核对记录保留，下次可能重新核对'
                    if note not in manifest.setdefault('limitations',[]):manifest['limitations'].append(note)
            return
        for record,text in found:
            if record[5] in saved:_remember_vision(record[5],text,record[0],epoch)

    async def describe_batch(entries):
        from .vision_cache import lookup_many
        epoch=_VISION_CACHE_EPOCH
        prepared=[];pending=[]
        for source, item, path in entries:
            original = str(item.get('text', ''))
            record = (source, item, path, original, None, None)
            try:
                checksum = await asyncio.to_thread(file_sha256, path)
                signature = [identity, source.get('id'), source['name'], str(path.resolve()), checksum, item['locator'], original]
                key = hashlib.sha256(json.dumps([str(data_dir()), signature], ensure_ascii=False, default=str).encode()).hexdigest()
                record = (source, item, path, original, checksum, key)
                prepared.append((record,_memory_vision(key)))
            except Exception as exc:
                finish(record, error=exc)

        keys=[record[5] for record,text in prepared if text is None]
        try:disk=await asyncio.to_thread(lookup_many,keys) if keys else {}
        except Exception:
            reuse['cache_read_failures']+=len(keys);disk={}
        for record,text in prepared:
            description=text if text is not None else disk.get(record[5])
            if description is None:
                pending.append(record)
                continue
            try:
                await validate(record,description)
                reuse['memory_hits' if text is not None else 'disk_hits']+=1
                _remember_vision(record[5],description,record[0],epoch)
                finish(record,description)
            except Exception as exc:finish(record,error=exc)

        reuse['new_images']+=len(pending)
        from .vision_inflight import track_reuse, reference
        with track_reuse() as shared:
            accepted = await analyze_pending(pending)
        for record,_ in accepted:
            frame=dict(path=record[2],locator=f"{record[0]['name']}｜{record[1]['locator']}",ocr=record[3])
            if reference(frame) in shared:
                reuse['inflight_hits']+=1
                reuse['new_images']-=1
        await save(accepted,epoch)
        for record,description in accepted:finish(record,description)

    async def analyze_pending(pending):
        found = {}
        if batch_supported and len(pending) > 1:
            frames = [{'id': str(index), 'path': record[2],
                       'locator': f"{record[0]['name']}｜{record[1]['locator']}", 'ocr': record[3]}
                      for index, record in enumerate(pending)]
            try:
                found = await batch_method(frames)
                expected = {frame['id'] for frame in frames}
                if (not isinstance(found, dict) or not set(found).issubset(expected) or
                        any(not isinstance(value, str) or not value.strip() for value in found.values())):
                    raise ValueError('逐图核对的返回内容或ID不合法')
            except Exception:
                # A service without usable multi-image JSON remains usable.
                # Retry only unresolved images, never skip them or misattribute.
                found = {}
        accepted=[]
        for index, record in enumerate(pending):
            try:
                description = found.get(str(index))
                if description is None:
                    description = await client.analyze_image(record[2], f"{record[0]['name']}｜{record[1]['locator']}", record[3])
                await validate(record,description)
                accepted.append((record,description))
            except Exception as exc:
                finish(record, error=exc)
        return accepted

    reuse['total_images']=len(images)
    if images and on_image: on_image(0, len(images), 0)
    # Keep at most three working requests and no encoded images in the queue.
    # A large scanned book should not allocate one live coroutine per page.
    batch_size = BATCH_SIZE if batch_supported else 1
    queue = asyncio.Queue()
    current = []
    for entry in images:
        if current and (len(current) >= batch_size or current[0][0] is not entry[0]):
            queue.put_nowait(current)
            current = []
        current.append(entry)
    if current: queue.put_nowait(current)

    async def worker():
        while True:
            try: entries = queue.get_nowait()
            except asyncio.QueueEmpty: return
            await describe_batch(entries)

    workers=[asyncio.create_task(worker()) for _ in range(min(3, queue.qsize()))]
    try:
        await asyncio.gather(*workers)
    except BaseException:
        # A cancelled/failed source read must not leave sibling image workers
        # running after its task is removed or waiting for another task forever.
        for task in workers:task.cancel()
        await asyncio.gather(*workers,return_exceptions=True)
        raise
    reuse['failed_images']=images_failed
    if images and on_cache:on_cache(dict(reuse))
    # Every source character is retained. The chunk list is a transport division,
    # never a model-written summary or a truncated UI preview.
    result = await run_local('source_prepare', _assemble_source_digest, sources, working, include_source_ids,
                             label='完整原文分段与组装', track_outputs=False)
    if on_chunk:
        on_chunk(len(result[1]), len(result[1]))
    return result


LEVEL_GUIDANCE = {
    1: "概括性最强：保留主旨、知识主干、关键概念与必要条件；术语释义和强关联延伸简明。涉及证明时凝练方法选择的理由与关键推理，不能省去关键解释与最终总结。",
    2: "概括性较强：主干完整，解释关键细节和少量例子；证明保留主要转折及其动机。",
    3: "平衡：系统讲解主干、重要细节、典型推导和例子；解释为什么选择方法、关键步骤怎样想到及适用边界。",
    4: "细节较多：展开推导、方法动机、思路重建、边界条件、例子、常见误解和图表。",
    5: "细节最多：尽可能覆盖原资料的重要内容，逐步解释推导、假设、例子和细微差别；展开方法选择、关键构造的启发、背后思想与迁移条件，必要时比较替代方法。",
}


async def generate_explanation(client: DeepSeekClient, digest: str, level: int, mastery: list[dict],
                               style: str = "clear", language: str = "zh", section: str = '',
                               exercises: bool = False, requirements: str = '', preparation: str = '',
                               learning_mode: str = 'deep') -> str:
    from .learning_memory import profile_context
    from .learning_profile import assessment_context
    # Memory lookup still uses the full task-start transcript. Only the model
    # request loses its redundant copy, not the evidence used for retrieval.
    memory_query = digest + '\n' + requirements
    conversation = getattr(client, 'conversation', None)
    if conversation and conversation.get('messages'):
        from .learning import requirements_without_duplicate_history
        requirements = requirements_without_duplicate_history(requirements, conversation['messages'])
    from .learning import profile_focus
    focus = profile_focus((conversation or {}).get('messages', []), requirements)
    learner_memory = profile_context(memory_query, focus=focus)
    profile = assessment_context(mastery, memory_query, focus=focus)
    style_prompt = style_policy(style)
    language_prompt = language_policy(language)
    from .source_origins import RULES as SOURCE_ORIGIN_RULES
    return await client.complete(
        TEACHER_PERSONA + LECTURE_RULES + style_prompt + language_prompt + mode_policy(learning_mode) +
        "完整阅读所选资料，继续当前学习对话中的导师任务，落实学生的最新要求与实际理解证据。"
        "相关画像是暂定教学依据，不能取代习题评分。阅读笔记只辅助组织，不能取代原文。"
        "下方资料内容由软件直接读取所选文件提供，并非界面摘要；不重复工具读取已完整提供的文字。" + SOURCE_ORIGIN_RULES +
        "确有缺口、需核对原图、补充可靠来源或执行用户文件操作时才调用相应工具。"
        "直接输出完整讲解正文，不输出处理过程、工具调用、计划或阅读进度，不使用自定义公式宏。",
        f"相关学习评估参考：{profile}\n{learner_memory}\n详略要求：{LEVEL_GUIDANCE[level]}\n"
        '详略档位只调节当前模式内的展开程度，不更改学习目标；学生明确指定结构时按其要求安排。\n'
        f"同步出题：{'已勾选，习题另行生成，讲解中不重复布置' if exercises else '未勾选，不生成习题；讲解深度仍遵循当前学习模式与学生要求'}。\n"
        f"本模式参考组织（无需把它逐项变成固定标题）：{mode_structure(learning_mode)}。{section}\n"
        + (f'\n学习对话与讲解要求：\n{requirements}\n' if requirements else '')
        + (f'\n已完成的阅读笔记（辅助理解）：\n{preparation}\n' if preparation else '')
        + f"\n所选资料内容：\n{digest}" + style_task_reminder(style) + TEACHING_TASK_REMINDER
        + mode_task_reminder(learning_mode, role='lecture'))


def explanation_batches(digest: str, max_chars: int = 60000) -> list[str]:
    from .source_origins import batches
    return batches(digest,max_chars,_plain_explanation_batches)


def _plain_explanation_batches(digest: str, max_chars: int = 60000) -> list[str]:
    """Divide original text at provenance boundaries, retaining every character."""
    parts = re.split(r'(?=\n\[来源 )', digest)
    batches, current = [], ''
    for part in parts:
        locator = re.match(r'\n\[来源 [^\n]+\]\n', part)
        while len(current) + len(part) > max_chars:
            available = max_chars - len(current)
            if current and available < max_chars // 3:
                batches.append(current); current = ''
                continue
            # Prefer a natural boundary so a formula or word is not interrupted.
            limit = available - 200
            boundary = max(part.rfind('\n', 0, limit), part.rfind('。', 0, limit), part.rfind(' ', 0, limit)) + 1
            if boundary < available // 3:
                boundary = limit
            batches.append(current + part[:boundary]); current = ''
            part = (locator[0] + '[原文续接]\n' if locator else '') + part[boundary:]
        current += part
    if current:
        batches.append(current)
    return batches
