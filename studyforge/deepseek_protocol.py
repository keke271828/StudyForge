"""Validate final DeepSeek replies before publishing text or executing tools."""
from __future__ import annotations

import asyncio
import json
import re
import httpx
from dataclasses import dataclass, field


def thinking_parameters(effort: str) -> dict:
    """Official DeepSeek strengths and documented compatibility aliases."""
    if effort in ('none', 'off'): return {'thinking': {'type': 'disabled'}}
    levels = {'minimal': 'low', 'low': 'low', 'medium': 'high', 'high': 'high',
              'xhigh': 'high', 'max': 'max', 'ultra': 'max'}
    if effort not in levels: raise ValueError('DeepSeek 不支持该推理强度')
    return {'thinking': {'type': 'enabled'}, 'reasoning_effort': levels[effort]}


def http_error(response, model: str | None = None) -> str:
    reasons = {400: '请求格式不正确，请核对模型及参数',
               401: '密钥无效或已失效，请在设置中更新 DeepSeek API 密钥',
               402: '账户余额不足，请检查 DeepSeek 账户余额',
               403: '请求被服务拒绝，请检查账户权限或网络代理',
               404: '模型或接口不存在，请在设置中核对 DeepSeek 模型名称',
               422: '请求参数不支持，请核对模型及参数',
               429: '请求过于频繁，请稍等后重试',
               500: '服务内部故障，请稍后重试',
               502: '服务网关暂时异常，请稍后重试',
               503: '服务繁忙，请稍后重试',
               504: '服务网关超时，请稍后重试'}
    identifier = response.headers.get('x-request-id', '')[:100]
    return (f'DeepSeek（{model}）' if model else 'DeepSeek') + f' API 返回 HTTP {response.status_code}：' + \
        reasons.get(response.status_code, '请检查网络与账户状态') + (f'；请求编号：{identifier}' if identifier else '')


class DeepSeekReplyError(RuntimeError):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def has_unexecuted_tool_markup(content: str) -> bool:
    """A model's printed DSML is text, never an authenticated tool call.

    Code examples and block quotations may legitimately teach this syntax.
    Detect exposed protocol blocks only; do not interpret or execute them.
    """
    prose = re.sub(r'(?ms)^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?^ {0,3}\1[^\n]*(?:\n|$)', '', content)
    prose = re.sub(r'`[^`\n]*`', '', prose)
    return bool(re.search(r'(?m)^\s*<｜｜DSML｜｜\s*(?:calls|function_calls|invoke)\b', prose))


@dataclass
class Reply:
    content: str = ''
    reasoning: str = ''
    finish: str | None = None
    request_id: str = ''
    calls: dict = field(default_factory=dict)
    service_name: str = 'DeepSeek'

    def accept(self, packet: dict) -> str:
        if not isinstance(packet, dict):
            raise DeepSeekReplyError('DeepSeek 返回了无效的响应格式', True)
        if packet.get('error'):
            raise DeepSeekReplyError('DeepSeek 在响应过程中报告服务错误，请重试', True)
        if packet.get('id'):
            self.request_id = str(packet['id'])[:100]
        choices = packet.get('choices') or []
        if not choices: return ''  # Heartbeats / a separate usage packet.
        choice = choices[0]
        delta = choice.get('delta') or choice.get('message') or {}
        self.finish = choice.get('finish_reason') or self.finish
        text = delta.get('content') or ''
        if not isinstance(text, str):
            raise DeepSeekReplyError('DeepSeek 正文不是文本，无法生成讲解', True)
        self.content += text
        self.reasoning += delta.get('reasoning_content') or ''
        for offset, item in enumerate(delta.get('tool_calls') or []):
            index = item.get('index', offset)
            call = self.calls.setdefault(index, {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
            if item.get('id'): call['id'] = item['id']
            function = item.get('function') or {}
            call['function']['name'] += function.get('name') or ''
            call['function']['arguments'] += function.get('arguments') or ''
        return text

    def validate(self, model: str) -> None:
        identity = f'{self.service_name}（{model}）'
        suffix = f'；请求编号：{self.request_id}' if self.request_id else ''
        if self.finish == 'length':
            raise DeepSeekReplyError(identity + '输出达到长度上限，已停止导出截断内容；请分章节生成' + suffix)
        if self.finish == 'content_filter':
            raise DeepSeekReplyError(identity + '服务拒绝了本次内容，请调整请求或联系服务商' + suffix)
        if self.finish in ('aborted', 'insufficient_system_resource'):
            raise DeepSeekReplyError(identity + '服务中断了输出（' + self.finish + '）' + suffix, True)
        if self.finish not in ('stop', 'tool_calls'):
            raise DeepSeekReplyError(identity + '响应中断，未收到完整结束标记，已停止导出不完整内容' + suffix, True)
        if has_unexecuted_tool_markup(self.content):
            raise DeepSeekReplyError(identity + '把工具调用写成了正文，尚未执行，回答未完成；请重试' + suffix, True)
        if self.calls:
            try:
                for call in self.calls.values():
                    if not call['id'] or not call['function']['name']:
                        raise ValueError('missing tool identifier')
                    if not isinstance(json.loads(call['function']['arguments']), dict):
                        raise ValueError('invalid arguments')
            except (ValueError, TypeError) as exc:
                raise DeepSeekReplyError(identity + '返回的工具调用不完整，尚未执行' + suffix, True) from exc
        elif self.finish == 'tool_calls':
            raise DeepSeekReplyError(identity + '未返回完整的工具调用，尚未执行' + suffix, True)
        elif not self.content.strip():
            reason = '只返回了思考记录，没有正文' if self.reasoning else '没有返回正文'
            raise DeepSeekReplyError(identity + reason + suffix, True)


async def response_packets(response):
    """Accept standard SSE (including data: without a space) and JSON replies."""
    if 'application/json' in response.headers.get('content-type', ''):
        await response.aread()
        try:
            yield response.json()
        except ValueError as exc:
            raise DeepSeekReplyError('DeepSeek 返回了无效的 JSON 响应', True) from exc
        return
    data = []
    lines = response.aiter_lines()
    async def drain_tail():
        async for _ in lines: pass
    async for line in lines:
        if line.startswith('data:'):
            data.append(line[5:].lstrip())
        elif not line and data:
            payload = '\n'.join(data); data = []
            if payload.strip() == '[DONE]':
                # Let httpx reach the HTTP body boundary so the connection can
                # be reused. A server that leaves SSE open must not delay a
                # completed answer; late transport failures do not undo DONE.
                try: await asyncio.wait_for(drain_tail(), .25)
                except (TimeoutError, httpx.TransportError): pass
                return
            try:
                yield json.loads(payload)
            except ValueError as exc:
                raise DeepSeekReplyError('DeepSeek 流式响应损坏，已停止处理', True) from exc
    if data:
        payload = '\n'.join(data)
        if payload.strip() != '[DONE]':
            try:
                yield json.loads(payload)
            except ValueError as exc:
                raise DeepSeekReplyError('DeepSeek 流式响应损坏，已停止处理', True) from exc
