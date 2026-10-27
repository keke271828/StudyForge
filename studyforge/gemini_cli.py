"""Google-account bridge using the official CLI and a dedicated local profile.

The CLI only returns decisions/text. StudyForge executes requested tools itself,
so the chat's read-only/approval/full-access policy remains authoritative.
"""
from __future__ import annotations

import asyncio
import json
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .config import data_dir
from .provider_clients import ServiceClient
from .deepseek_protocol import DeepSeekReplyError
from .gemini_stream import ContentStream, cli_error
from .scheduling import model_slot

_profile_lock = RLock()


def atomic_text(path, text):
    with _profile_lock:
        descriptor, name = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                handle.write(text)
            os.replace(name, path)
        finally: Path(name).unlink(missing_ok=True)


def cli_command():
    node = shutil.which('node')
    def entry(package):
        try:
            meta = json.loads((package/'package.json').read_text(encoding='utf-8'))
            binary = meta.get('bin', {})
            relative = binary.get('gemini') if isinstance(binary, dict) else binary
            script = (package/relative).resolve()
            if script.is_relative_to(package.resolve()) and script.is_file(): return script
        except (OSError, ValueError, TypeError): pass
        return None
    installed = entry(data_dir()/'gemini-cli-runtime'/'node_modules'/'@google'/'gemini-cli')
    if node and installed: return [node, str(installed)]
    launcher = shutil.which('gemini')
    if launcher:
        path = Path(launcher)
        if path.suffix.lower() in ('.cmd', '.bat', '.ps1'):
            script = entry(path.parent/'node_modules'/'@google'/'gemini-cli')
            if node and script: return [node, str(script)]
            return None  # Never shell-interpolate prompts or execute an opaque wrapper.
        return [str(path)]
    return None


def profile_dir(identifier): return data_dir()/'gemini-accounts'/identifier


def status(identifier):
    cached = (profile_dir(identifier)/'.gemini'/'oauth_creds.json').is_file()
    return {'cli_available': bool(cli_command()), 'configured': cached,
            'auth_status': '授权已缓存；可检测连接确认有效性' if cached else '请登录 Google 账号',
            'supports_vision': False}


def prepare_profile(identifier):
    root = profile_dir(identifier)
    folder = root/'.gemini'; folder.mkdir(parents=True, exist_ok=True)
    policy = root/'deny-native-tools.toml'
    atomic_text(policy, '[[rule]]\ntoolName = "*"\ndecision = "deny"\npriority = 999\n')
    # No inherited extensions, MCP servers, GEMINI.md, memory or shell tools.
    # OAuth stays owned by Google's CLI in this profile, not the application API.
    config = {'security': {'auth': {'selectedType': 'oauth-personal'}, 'folderTrust': {'enabled': False}},
              'tools': {'core': ['__studyforge_no_native_tools__']}, 'mcp': {'allowed': []}, 'mcpServers': {},
              'policyPaths': [str(policy)], 'adminPolicyPaths': [str(policy)],
              'context': {'fileName': '__STUDYFORGE_NO_CONTEXT__.md'},
              'general': {'enableAutoUpdate': False, 'enableAutoUpdateNotification': False},
              'experimental': {'enableAgents': False, 'autoMemory': False}, 'skills': {'enabled': False},
              'advanced': {'ignoreLocalEnv': True}, 'hooksConfig': {'enabled': False}, 'useWriteTodos': False}
    atomic_text(folder/'settings.json', json.dumps(config))
    # System layer is highest priority: keep the no-tools guard even after login.
    guard = root/'studyforge-system.json'
    atomic_text(guard, json.dumps(config))
    env = dict(os.environ)
    for name in list(env):
        if name in ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS',
                    'GOOGLE_GENAI_USE_VERTEXAI', 'GEMINI_SYSTEM_MD', 'GEMINI_CLI_SYSTEM_DEFAULTS_PATH'):
            env.pop(name, None)
    env.update(GEMINI_CLI_HOME=str(root), GEMINI_CLI_SYSTEM_SETTINGS_PATH=str(guard),
               GEMINI_CLI_SURFACE='StudyForge', NO_COLOR='1', GEMINI_FORCE_ENCRYPTED_FILE_STORAGE='false')
    return root, env


_install_lock = asyncio.Lock()
_login_processes = {}


async def install_cli():
    async with _install_lock:
        if cli_command(): return {'installed': True, 'message': '官方 Gemini CLI 已可用'}
        node, npm = shutil.which('node'), shutil.which('npm')
        if not node or not npm: raise ValueError('请先安装 Node.js 20 或更新版本，再点击安装 Gemini CLI')
        npm_script = Path(npm).parent/'node_modules'/'npm'/'bin'/'npm-cli.js'
        if not npm_script.is_file(): raise ValueError('未找到 npm 的运行入口，请检查 Node.js 安装')
        destination = data_dir()/'gemini-cli-runtime'; destination.mkdir(exist_ok=True)
        process = await asyncio.create_subprocess_exec(node, str(npm_script), 'install', '--prefix', str(destination),
            '--no-audit', '--no-fund', '@google/gemini-cli', cwd=str(destination),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
        try:
            await asyncio.wait_for(process.wait(), 300)
            if process.returncode or not cli_command(): raise RuntimeError('安装未完成，请检查 npm 网络或代理后重试')
        except BaseException:
            if process.returncode is None:
                process.kill(); await process.wait()
            raise
        return {'installed': True, 'message': '官方 Gemini CLI 已安装在软件资料目录，无需全局安装'}


def login(identifier):
    from .providers import get_service
    if get_service(identifier)['protocol'] != 'gemini_cli': raise ValueError('仅 Gemini 账号服务可发起登录')
    command = cli_command()
    if not command: raise ValueError('请先安装官方 Gemini CLI')
    existing = _login_processes.get(identifier)
    if existing and existing.poll() is None: return {'message': '登录窗口已打开，请在该窗口完成登录'}
    root, env = prepare_profile(identifier)
    process = subprocess.Popen(command+['-e', 'none'], cwd=str(root), env=env,
        **({'creationflags': subprocess.CREATE_NEW_CONSOLE} if os.name == 'nt' else {}))
    _login_processes[identifier] = process
    return {'message': '已打开官方 Gemini 登录窗口。按提示登录 Google 账号，完成后关闭该窗口，再检测连接'}


def remove_profile(identifier):
    from .providers import secret_name
    secret_name(identifier)  # Same validated ID as the service registry.
    process = _login_processes.get(identifier)
    if process and process.poll() is None: raise ValueError('请先关闭此服务的官方 Gemini 登录窗口')
    base = (data_dir()/'gemini-accounts').resolve()
    target = profile_dir(identifier)
    if target.is_symlink(): target.unlink(); return
    resolved = target.resolve()
    if resolved == base or not resolved.is_relative_to(base): raise ValueError('账号授权目录越界，已停止清理')
    if resolved.exists(): shutil.rmtree(resolved)


def logout(identifier):
    from .providers import get_service
    if get_service(identifier, enabled=False)['protocol'] != 'gemini_cli': raise ValueError('仅 Gemini 账号服务可退出登录')
    remove_profile(identifier)
    return {'message': '已清除软件内此账号的本地授权与 CLI 缓存，可重新登录；学习对话和成果保留'}


ENVELOPE = '''你是 StudyForge 的模型执行端，输入对象包含 messages（完整任务/对话）和 tools（可请求的工具）。
遵循 messages 中的教学要求和权限说明。你不能直接使用 Gemini CLI 的文件、终端、联网或记忆功能。
要使用工具，只在下面的 JSON 对象中提出请求，由 StudyForge 审批并执行；工具结果会作为 role=tool 发回。
只输出一个 JSON 对象：{"content":"面向用户的完整回复正文", "tool_calls":[{"name":"工具名","arguments":{}}]}。
不需要工具时 tool_calls 为空列表；正文可以包含 Markdown/LaTeX。若任务要求 JSON，将该任务 JSON 作为 content 字符串返回。
不输出本协议的说明，不编造工具已经执行。'''


def cli_packet(text):
    from .ai import parse_json_response
    try:
        result = parse_json_response(text)
        content, calls = result['content'], result.get('tool_calls', [])
        if not isinstance(content, str) or not isinstance(calls, list): raise ValueError('invalid envelope')
        values = []
        for index, call in enumerate(calls):
            if not isinstance(call, dict) or not isinstance(call.get('name'), str) or not isinstance(call.get('arguments'), dict):
                raise ValueError('invalid call')
            values.append({'index': index, 'id': uuid4().hex, 'type': 'function',
                           'function': {'name': call['name'], 'arguments': json.dumps(call['arguments'], ensure_ascii=False)}})
    except (ValueError, TypeError, KeyError) as exc:
        raise DeepSeekReplyError('Gemini 账号返回的结构化内容不完整，尚未执行工具', True) from exc
    return {'choices': [{'message': {'content': content, 'tool_calls': values}, 'finish_reason': 'tool_calls' if values else 'stop'}]}


class GeminiCliClient(ServiceClient):
    protocol_version = 4

    async def run_cli(self, body, timeout=240, on_text=None):
        from .providers import get_service
        get_service(self.provider)
        command = cli_command()
        if not command: raise RuntimeError('Gemini CLI 尚未安装，请在 AI 服务管理中安装并登录 Google 账号')
        if self.model.startswith('-'): raise ValueError('Gemini 模型调用名不能以选项符号开头')
        if not status(self.provider)['configured']: raise RuntimeError('请先在 AI 服务管理中登录 Google 账号')
        root, env = prepare_profile(self.provider)
        scope = getattr(self.agent_runtime, 'scope_key', None) or uuid4().hex
        working = root/'runs'/hashlib.sha256(scope.encode()).hexdigest()[:32]
        working.mkdir(parents=True, exist_ok=True)
        prompt = ENVELOPE+'\n任务输入：\n'+json.dumps({'messages': body['messages'], 'tools': body.get('tools', [])}, ensure_ascii=False)
        # Pass the long source through stdin, never Windows command-line arguments.
        process = await asyncio.create_subprocess_exec(*command, '-m', self.model, '-e', 'none',
            '--approval-mode', 'plan', '--output-format', 'stream-json', '-p', '按标准输入中的协议执行本次学习任务。',
            cwd=str(working), env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=2*1024*1024,
            **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
        stderr = bytearray()
        async def write_input():
            try:
                process.stdin.write(prompt.encode('utf-8'))
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError): pass
            finally: process.stdin.close()
        async def read_errors():
            while chunk := await process.stderr.read(4096):
                stderr.extend(chunk)
                if len(stderr)>8192: del stderr[:-8192]
        workers = [asyncio.create_task(write_input()), asyncio.create_task(read_errors())]
        try:
            text, streamed, completed, diagnostic, size = [], [], False, '', 0
            decoder = ContentStream()
            async with asyncio.timeout(timeout):
                async for line in process.stdout:
                    size += len(line)
                    if size>8*1024*1024: raise DeepSeekReplyError('Gemini 账号响应过大，请分章节生成')
                    try: packet = json.loads(line)
                    except (ValueError, UnicodeDecodeError): continue  # CLI startup messages are not model events.
                    if not isinstance(packet, dict): continue
                    if completed: raise DeepSeekReplyError('Gemini CLI 在结束标记后继续输出，已停止交付', True)
                    if packet.get('type') == 'tool_use':
                        raise RuntimeError('Gemini CLI 尝试直接执行工具，已停止；请更新官方 CLI，软件权限不会自动放宽')
                    if packet.get('type') == 'message' and packet.get('role') == 'assistant':
                        fragment = packet.get('content', '')
                        if not isinstance(fragment, str): raise DeepSeekReplyError('Gemini 账号返回了无效正文', True)
                        text.append(fragment)
                        if on_text and (delta := decoder.feed(fragment)):
                            streamed.append(delta); await on_text(delta)
                    if packet.get('type') == 'error': diagnostic = json.dumps(packet, ensure_ascii=False)
                    if packet.get('type') == 'result':
                        completed = packet.get('status') == 'success'
                        if not completed: raise cli_error(packet.get('error') or diagnostic)
                await process.wait()
                await asyncio.gather(*workers)
            if process.returncode: raise cli_error(diagnostic+' '+stderr.decode('utf-8', errors='replace'), process.returncode)
            if not completed: raise DeepSeekReplyError('Gemini CLI 未返回完整结束标记', True)
            result = cli_packet(''.join(text))
            if not result['choices'][0]['message']['content'].startswith(''.join(streamed)):
                raise DeepSeekReplyError('Gemini 账号的最终正文与流式内容不一致，尚未执行工具', True)
            return result
        except asyncio.TimeoutError as exc: raise RuntimeError('Gemini 账号请求超时，请检查网络或缩小单次任务') from exc
        except ValueError as exc: raise DeepSeekReplyError('Gemini 账号输出记录过大或格式不正确，请分章节生成') from exc
        finally:
            if process.returncode is None:
                process.kill(); await process.wait()
            for worker in workers:
                if not worker.done(): worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    async def _post(self, body, timeout=240, retry=True):
        async with model_slot(self.provider, self.agent_runtime):
            from .library_policy import model_request
            with model_request(body, self.provider): return await self.run_cli(body, timeout)

    async def stream_packets(self, body):
        # Publish only the content string. Calls wait for the complete envelope.
        queue = asyncio.Queue(maxsize=16)
        async def publish(text): await queue.put(('text', text))
        async def request():
            try: await queue.put(('final', await self.run_cli(body, on_text=publish)))
            except Exception as exc: await queue.put(('error', exc))
        worker = asyncio.create_task(request())
        streamed = []
        try:
            while True:
                kind, value = await queue.get()
                if kind == 'error': raise value
                if kind == 'text':
                    streamed.append(value)
                    yield {'choices':[{'delta':{'content':value}, 'finish_reason':None}]}
                else:
                    value['choices'][0]['message']['content'] = value['choices'][0]['message']['content'][len(''.join(streamed)):]
                    yield value
                    break
        finally:
            if not worker.done(): worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    async def analyze_image(self, path, locator, ocr_text=''):
        raise RuntimeError('Gemini 账号入口暂不直接读取图片；图片与视频画面分析请选择 Gemini API 服务')
