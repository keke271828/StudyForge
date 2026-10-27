"""OpenAI compatible and native Gemini transports using the shared agent loop."""
from __future__ import annotations

import base64
import copy
import io
import json
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import httpx

from .ai import DeepSeekClient
from .config import get_secret
from .deepseek_protocol import DeepSeekReplyError, response_packets
from .providers import get_service, secret_name, request_error
from .scheduling import model_slot
from .api_network import http_options


class ServiceClient(DeepSeekClient):
    protocol_version = 2

    def __init__(self, provider, model=None, agent_runtime=None, conversation=None):
        self.service = get_service(provider)
        self.provider, self.service_name = provider, self.service['name']
        self.model = model or self.service['default_model']
        self.key = get_secret(secret_name(provider))
        if self.service['requires_key'] and not self.key:
            raise RuntimeError(f'请先在 AI 服务管理中保存 {self.service_name} API 密钥')
        self.agent_runtime = agent_runtime
        self.effort = getattr(agent_runtime, 'effort', None)
        self.conversation = None if getattr(agent_runtime, 'private_context', False) else copy.deepcopy(conversation)
        self.detached = bool(getattr(agent_runtime, 'job_id', None) or getattr(agent_runtime, 'branch_key', None))
        self.session_messages = []

    def fork(self):
        return service_client(self.provider, self.model, self.agent_runtime.fork() if self.agent_runtime else None,
                              copy.deepcopy(self.conversation))

    def supports_tools(self): return self.service['supports_tools']

    @property
    def vision_model(self): return self.model

    @property
    def supports_image_batches(self): return self.service['supports_vision']

    def prepare_body(self, body):
        body = copy.deepcopy(body)
        body.pop('thinking', None)
        if not self.service['supports_json']: body.pop('response_format', None)
        for message in body['messages']:
            message.pop('reasoning_content', None)
            message.pop('_gemini_content', None)
        return body

    def assistant_message(self, reply):
        row = super().assistant_message(reply)
        row.pop('reasoning_content', None)
        return row

    @property
    def headers(self): return {'Authorization': f'Bearer {self.key}'} if self.key else {}

    async def _post(self, body, timeout=240, retry=True):
        from .vision_batches import admitted_request_body
        async with admitted_request_body(body, self.provider, self.agent_runtime) as prepared, httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15), **http_options()) as client:
            from .library_policy import model_request
            try:
                with model_request(prepared, self.provider) as meter:
                    response = await client.post(self.service['base_url']+'/chat/completions', json=self.prepare_body(prepared), headers=self.headers)
                    if not response.is_success: raise RuntimeError(request_error(response, self.service_name, self.model))
                    try:
                        packet = response.json(); meter.accept(packet); return packet
                    except ValueError as exc: raise DeepSeekReplyError(self.service_name+' 返回了无效 JSON 响应', True) from exc
            finally:
                prepared = None

    async def stream_packets(self, body):
        async with httpx.AsyncClient(timeout=httpx.Timeout(240, connect=15), **http_options()) as client:
            async with client.stream('POST', self.service['base_url']+'/chat/completions', json=body, headers=self.headers) as response:
                if not response.is_success: raise RuntimeError(request_error(response, self.service_name, self.model))
                async for packet in response_packets(response): yield packet

    async def agent_stream(self, messages, json_mode=False):
        try:
            async for event in self._agent_stream(messages, json_mode): yield event
        except httpx.HTTPError as exc:
            raise RuntimeError(f'{self.service_name} 请求失败，请检查 API 地址、网络或代理；无需启动 Codex') from exc

    async def complete(self, system, user, json_mode=False, max_tokens=None):
        if json_mode: system += '\n只返回一个完整合法的 JSON 对象，不加 Markdown 围栏。'
        try: return await super().complete(system, user, json_mode, max_tokens)
        except httpx.HTTPError as exc:
            raise RuntimeError(f'{self.service_name} 连接失败或请求超时，请检查 API 地址、网络或代理') from exc

    async def analyze_image(self, path: Path, locator: str, ocr_text=''):
        if not self.service['supports_vision']:
            raise RuntimeError(f'{self.service_name} 未启用图片能力；请选择支持视觉的模型，并在服务管理中启用图片读取')
        return await super().analyze_image(path, locator, ocr_text)


def gemini_body(body):
    """Preserve native response Parts, including opaque thought signatures."""
    system, contents, functions = [], [], {}
    for message in body['messages']:
        role = message['role']
        if role == 'system':
            system.append(str(message['content'])); continue
        if role == 'assistant':
            if message.get('_gemini_content'):
                native = copy.deepcopy(message['_gemini_content'])
            else:
                parts = [{'text': message['content']}] if message.get('content') else []
                for call in message.get('tool_calls', []):
                    parts.append({'functionCall': {'id': call['id'], 'name': call['function']['name'],
                                                  'args': json.loads(call['function']['arguments'])}})
                native = {'role': 'model', 'parts': parts}
            native_calls = [part['functionCall'] for part in native.get('parts', []) if 'functionCall' in part]
            for call, native_call in zip(message.get('tool_calls', []), native_calls):
                functions[call['id']] = native_call
        elif role == 'tool':
            call = functions.get(message['tool_call_id'])
            if not call: raise ValueError('Gemini 工具结果缺少对应调用，未发送混乱的上下文')
            response = {'name': call['name'], 'response': json.loads(message['content'])}
            if call.get('id'): response['id'] = call['id']
            native = {'role': 'user', 'parts': [{'functionResponse': response}]}
            if contents and contents[-1]['role'] == 'user' and all('functionResponse' in p for p in contents[-1]['parts']):
                contents[-1]['parts'].extend(native['parts']); continue
        else:
            value = message.get('content', '')
            if isinstance(value, str): parts = [{'text': value}]
            else:
                parts = []
                for part in value:
                    if part['type'] == 'text': parts.append({'text': part['text']})
                    elif part['type'] == 'image_url':
                        url = part['image_url']['url']
                        if not url.startswith('data:'): raise ValueError('Gemini 图片须为已读取的本地原图')
                        prefix, data = url.split(',', 1)
                        parts.append({'inlineData': {'mimeType': prefix[5:].split(';')[0], 'data': data}})
            native = {'role': 'user', 'parts': parts}
        if native.get('parts'): contents.append(native)
    result = {'contents': contents, 'generationConfig': {}}
    if system: result['systemInstruction'] = {'parts': [{'text': '\n'.join(system)}]}
    if body.get('max_tokens'): result['generationConfig']['maxOutputTokens'] = body['max_tokens']
    if body.get('tools'):
        # Full JSON Schema is supported here (Pydantic's optional anyOf included).
        declarations = [{'name': item['function']['name'], 'description': item['function'].get('description', ''),
                         'parametersJsonSchema': item['function']['parameters']} for item in body['tools']]
        result['tools'] = [{'functionDeclarations': declarations}]
    elif body.get('response_format'): result['generationConfig']['responseMimeType'] = 'application/json'
    return result


class GeminiClient(ServiceClient):
    protocol_version = 3

    @property
    def headers(self): return {'x-goog-api-key': self.key}

    def prepare_body(self, body):
        result = copy.deepcopy(body)
        if not self.service['supports_json']: result.pop('response_format', None)
        return result

    def url(self, streaming=False):
        model = self.model.removeprefix('models/')
        return self.service['base_url']+'/models/'+quote(model, safe='')+(':streamGenerateContent?alt=sse' if streaming else ':generateContent')

    def packet(self, packet, streaming):
        if packet.get('error'): raise DeepSeekReplyError('Gemini 报告服务错误，请核对账户权限与请求', True)
        candidates = packet.get('candidates') or []
        if not candidates:
            if packet.get('promptFeedback', {}).get('blockReason'):
                raise DeepSeekReplyError('Gemini 拒绝了本次内容，请调整请求')
            return {'choices': []}
        candidate = candidates[0]
        parts = candidate.get('content', {}).get('parts', [])
        calls, text = [], ''
        for part in parts:
            self.native_parts.append(copy.deepcopy(part))
            if part.get('text') and not part.get('thought'): text += part['text']
            if 'functionCall' in part:
                call = part['functionCall']
                calls.append({'index': self.call_index, 'id': call.get('id') or uuid4().hex,
                              'type': 'function', 'function': {'name': call['name'], 'arguments': json.dumps(call.get('args', {}), ensure_ascii=False)}})
                self.call_index += 1
        finish = candidate.get('finishReason')
        mapped = ('tool_calls' if self.call_index else 'stop') if finish == 'STOP' else 'length' if finish == 'MAX_TOKENS' else 'content_filter' if finish else None
        return {'choices': [{'delta' if streaming else 'message': {'content': text, 'tool_calls': calls}, 'finish_reason': mapped}]}

    def assistant_message(self, reply):
        result = super().assistant_message(reply)
        result['_gemini_content'] = {'role': 'model', 'parts': copy.deepcopy(self.native_parts)}
        return result

    async def _post(self, body, timeout=240, retry=True):
        self.native_parts, self.call_index = [], 0
        from .vision_batches import admitted_request_body
        async with admitted_request_body(body, self.provider, self.agent_runtime) as prepared, httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15), **http_options()) as client:
            from .library_policy import model_request
            try:
                with model_request(prepared, self.provider) as meter:
                    response = await client.post(self.url(), json=gemini_body(prepared), headers=self.headers)
                    if not response.is_success: raise RuntimeError(request_error(response, self.service_name, self.model))
                    try:
                        packet = response.json(); meter.accept(packet); return self.packet(packet, False)
                    except ValueError as exc: raise DeepSeekReplyError('Gemini 返回无效响应', True) from exc
            finally:
                prepared = None

    async def stream_packets(self, body):
        self.native_parts, self.call_index = [], 0
        async with httpx.AsyncClient(timeout=httpx.Timeout(240, connect=15), **http_options()) as client:
            async with client.stream('POST', self.url(True), json=gemini_body(body), headers=self.headers) as response:
                if not response.is_success: raise RuntimeError(request_error(response, self.service_name, self.model))
                async for packet in response_packets(response): yield self.packet(packet, True)


def service_client(provider, model=None, agent_runtime=None, conversation=None):
    protocol = get_service(provider)['protocol']
    if protocol == 'gemini_cli':
        from .gemini_cli import GeminiCliClient
        cls = GeminiCliClient
    else: cls = GeminiClient if protocol == 'gemini' else ServiceClient
    return cls(provider, model, agent_runtime, conversation)
