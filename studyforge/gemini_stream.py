"""Decode only the public content string from the CLI's private envelope."""
from __future__ import annotations

import json

from .deepseek_protocol import DeepSeekReplyError


class ContentStream:
    """One pass over JSON fragments; tool arguments never become visible text.

    Fenced or nonstandard output falls back to the final envelope validator.
    The final reply must also match the streamed prefix before tools can run.
    """
    def __init__(self):
        self.mode = 'root'
        self.key = ''
        self.key_text = ''
        self.escaped = False
        self.unicode_digits = None
        self.high_surrogate = None
        self.skip_depth = 0
        self.skip_string = False

    def fail(self):
        raise DeepSeekReplyError('Gemini 账号的正文转义不完整或无效，尚未执行工具', True)

    def character(self, char):
        code = ord(char)
        if self.high_surrogate is not None:
            if not 0xDC00 <= code <= 0xDFFF: self.fail()
            char = chr(0x10000 + ((self.high_surrogate - 0xD800) << 10) + code - 0xDC00)
            self.high_surrogate = None
        elif 0xD800 <= code <= 0xDBFF:
            self.high_surrogate = code
            return ''
        elif 0xDC00 <= code <= 0xDFFF: self.fail()
        return char

    def feed(self, fragment):
        output = []
        for char in fragment:
            if self.mode == 'off': break
            if self.mode == 'root':
                if char.isspace(): continue
                self.mode = 'key_start' if char == '{' else 'off'
            elif self.mode == 'key_start':
                if char.isspace(): continue
                if char == '"':
                    self.key_text = '"'; self.escaped = False; self.mode = 'key'
                else: self.mode = 'off'
            elif self.mode == 'key':
                self.key_text += char
                if self.escaped: self.escaped = False
                elif char == '\\': self.escaped = True
                elif char == '"':
                    try: self.key = json.loads(self.key_text)
                    except ValueError: self.mode = 'off'; continue
                    self.mode = 'colon'
            elif self.mode == 'colon':
                if char.isspace(): continue
                self.mode = 'value' if char == ':' else 'off'
            elif self.mode == 'value':
                if char.isspace(): continue
                if self.key == 'content':
                    self.mode = 'content' if char == '"' else 'off'
                    self.escaped = False
                else:
                    self.mode = 'skip'
                    self.skip_depth = 0; self.skip_string = False; self.escaped = False
                    self.skip_character(char)
            elif self.mode == 'skip': self.skip_character(char)
            elif self.mode == 'content':
                if self.unicode_digits is not None:
                    if char not in '0123456789abcdefABCDEF': self.fail()
                    self.unicode_digits += char
                    if len(self.unicode_digits) == 4:
                        output.append(self.character(chr(int(self.unicode_digits, 16))))
                        self.unicode_digits = None
                elif self.escaped:
                    self.escaped = False
                    if char == 'u': self.unicode_digits = ''
                    else:
                        escapes = {'"':'"', '\\':'\\', '/':'/', 'b':'\b', 'f':'\f', 'n':'\n', 'r':'\r', 't':'\t'}
                        if char not in escapes: self.fail()
                        output.append(self.character(escapes[char]))
                elif char == '\\': self.escaped = True
                elif char == '"':
                    if self.high_surrogate is not None: self.fail()
                    self.mode = 'off'
                elif ord(char) < 32: self.fail()
                else: output.append(self.character(char))
        return ''.join(output)

    def skip_character(self, char):
        if self.skip_string:
            if self.escaped: self.escaped = False
            elif char == '\\': self.escaped = True
            elif char == '"': self.skip_string = False
        elif char == '"': self.skip_string = True
        elif char in '[{': self.skip_depth += 1
        elif char in ']}':
            if self.skip_depth == 0: self.mode = 'off'
            else: self.skip_depth -= 1
        elif char == ',' and self.skip_depth == 0: self.mode = 'key_start'


def cli_error(diagnostic='', exit_code=None):
    """Classify diagnostics without echoing credentials, prompts or account data."""
    text = str(diagnostic).lower()
    if any(word in text for word in ('invalid_grant', 'unauthorized', 'unauthenticated', 'reauth',
                                     'authentication', 'login required', 'oauth', '401')):
        reason = 'Google 授权缺失或已失效，请在 AI 服务管理中退出并重新登录账号'
    elif any(word in text for word in ('resource_exhausted', 'quota', 'rate limit', '429', 'capacity')):
        reason = '账号额度不足或服务限流，请检查账号额度，稍后重试或选择其他可用模型'
    elif any(word in text for word in ('not_found', 'not found', 'unknown model', 'invalid model', '404')):
        reason = '所选模型不可用，请核对模型调用名，或改用账号支持的 auto、pro、flash'
    elif any(word in text for word in ('permission_denied', 'forbidden', '403', 'project_id', 'project id')):
        reason = '账号没有相应服务权限，请检查 Google 账号权限及所需的 Cloud 项目配置'
    elif any(word in text for word in ('econn', 'enotfound', 'etimedout', 'fetch failed', 'network', 'proxy', 'ssl', 'certificate', 'timeout')):
        reason = '网络连接、代理或证书异常，请检查网络及代理后重试'
    elif exit_code == 42:
        reason = '模型参数或 CLI 配置不被接受，请核对调用名及官方 CLI 版本'
    elif exit_code == 53:
        reason = '官方 CLI 达到执行轮次上限，请缩小本次任务后重试'
    else:
        reason = '请求未完成，请检测连接并检查账号授权、模型、额度与网络'
    return RuntimeError('Gemini 账号请求失败：'+reason+(f'（退出码 {exit_code}）' if exit_code else ''))
