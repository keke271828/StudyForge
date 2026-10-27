from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import hashlib
import weakref
from collections import OrderedDict
import os
import shutil
import time
from pathlib import Path
from typing import Any, AsyncIterator

from . import __version__
from .config import data_dir
from .runtime import background_process_options


NATIVE_CONTEXT_OVERRIDES = {
    'features.memories':False,'memories.use_memories':False,'memories.generate_memories':False,
    'features.external_agent_memory_import':False,'features.hooks':False,
}

FOREGROUND_EVENT_TIMEOUT = 1260
BACKGROUND_EVENT_TIMEOUT = 90


class CodexTurnError(RuntimeError):
    """Keep structured diagnostics while showing an actionable public message."""
    def __init__(self,details,status):
        self.details=details
        raw=details if isinstance(details,dict) else {}
        info=raw.get('codexErrorInfo') or {}
        message=raw.get('message') or str(details or f'Codex turn: {status}')
        info=info if isinstance(info,dict) else {}
        codes=[value.get('httpStatusCode') for value in info.values() if isinstance(value,dict)]
        if 429 in codes or ('429' in message and 'too many requests' in message.lower()):
            self.retryable=True
            message=('Codex 请求受到限流（HTTP 429），本次回复已停止。服务重试后仍未成功；'
                '请稍后重试，或减少同时运行的 Codex 任务。若持续出现，请检查 StudyForge 所用账号的 Codex 用量。')
        super().__init__(message)


def codex_executable() -> str:
    """Resolve npm's Windows shim to its native executable when available."""
    executable = shutil.which('codex')
    if not executable:
        raise RuntimeError('未找到 Codex CLI，请先安装并登录')
    if executable.lower().endswith(('.cmd', '.bat', '.ps1')):
        candidates = list(Path(executable).parent.glob(
            'node_modules/@openai/codex/node_modules/@openai/codex-win*/vendor/*/bin/codex.exe'))
        if candidates:
            executable = str(candidates[0])
    return executable


def learning_tool_config():
    """Disable native routes that could bypass the app's tool permissions."""
    import tomllib
    config = {'web_search': 'disabled', 'mcp_servers': {}, **NATIVE_CONTEXT_OVERRIDES}
    for feature in ('shell_tool', 'unified_exec', 'apply_patch_tool', 'apps', 'browser_use', 'browser_use_external',
                    'computer_use', 'image_generation', 'view_image', 'code_mode_host', 'js_repl', 'multi_agent', 'workspace_dependencies'):
        config[f'features.{feature}'] = False
    home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
    try:
        local_config = tomllib.loads((home / 'config.toml').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        local_config = {}
    for name in local_config.get('mcp_servers', {}): config[f'mcp_servers.{name}.enabled'] = False
    return config


class CodexBridge:
    """Codex sessions with shared learning tools enforced by the local runtime."""

    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.pending: dict[int, asyncio.Future] = {}
        self.events: asyncio.Queue[dict] = asyncio.Queue()
        self.counter = 0
        self.reader: asyncio.Task | None = None
        self.turn_lock = asyncio.Lock()
        self.tool_lock = asyncio.Lock()
        self.model_lease = None
        self.agent_runtime = None
        self.tool_tasks = set()
        self.live_threads = set()

    def _debug(self, direction: str, message: dict) -> None:
        filename = os.environ.get("STUDYFORGE_CODEX_DEBUG")
        if filename:
            with open(filename, "a", encoding="utf-8") as log:
                log.write(f"{direction} id={message.get('id')} method={message.get('method')} error={bool(message.get('error'))}\n")

    async def start(self) -> None:
        if self.proc and self.proc.returncode is None:
            return
        self.live_threads.clear()
        while not self.events.empty(): self.events.get_nowait()
        executable = codex_executable()
        # Disable native global memory before the server starts any background
        # worker, not merely when starting a learning thread. This only changes
        # this child process, never the user's Codex config or memory files.
        overrides=[arg for key,value in NATIVE_CONTEXT_OVERRIDES.items() for arg in ('-c',key+'='+str(value).lower())]
        self.proc = await asyncio.create_subprocess_exec(executable, "app-server", *overrides, stdin=asyncio.subprocess.PIPE,
                                                         stdout=asyncio.subprocess.PIPE,
                                                         stderr=asyncio.subprocess.DEVNULL,
                                                         limit=16 * 1024 * 1024, **background_process_options())
        self.reader = asyncio.create_task(self._read())
        await self.request("initialize", {"clientInfo": {"name": "studyforge", "title": "StudyForge", "version": __version__},
                                          'capabilities': {'experimentalApi': True}})
        await self._send({"method": "initialized", "params": {}})

    async def _send(self, message: dict) -> None:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("Codex App Server 未启动")
        self.proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
        self._debug("send", message)
        await self.proc.stdin.drain()

    async def _read(self) -> None:
        assert self.proc and self.proc.stdout
        while line := await self.proc.stdout.readline():
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._debug("recv", message)
            if "id" in message and "method" not in message:
                future = self.pending.pop(message["id"], None)
                if future and not future.done():
                    if "error" in message:
                        future.set_exception(RuntimeError(str(message["error"].get("message", message["error"]))))
                    else:
                        future.set_result(message.get("result", {}))
            elif "id" in message and "method" in message:
                method = message["method"]
                if method == 'item/tool/call':
                    task = asyncio.create_task(self._handle_tool(message, self.agent_runtime))
                    self.tool_tasks.add(task); task.add_done_callback(self.tool_tasks.discard)
                elif method == "item/permissions/requestApproval":
                    await self._send({"id": message["id"], "result": {"permissions": {}}})
                elif method.endswith("requestApproval"):
                    await self._send({"id": message["id"], "result": {"decision": "decline"}})
                else:
                    await self._send({"id": message["id"], "error": {"code": -32601, "message": "StudyForge 不支持此交互请求"}})
            else:
                await self.events.put(message)
        for future in self.pending.values():
            if not future.done():
                    future.set_exception(RuntimeError("Codex App Server 已退出"))
        await self.events.put({'method': 'studyforge/serverClosed', 'params': {}})

    async def _handle_tool(self, message, runtime):
        async with self.tool_lock:
            lease = self.model_lease
            if lease: await lease.suspend()
            try:
                await self._execute_tool(message, runtime, lease)
            finally:
                # Cancellation closes this connection. Do not start another
                # model request merely to acknowledge a cancelled tool.
                if lease and not asyncio.current_task().cancelling(): await lease.resume()

    async def _execute_tool(self, message, runtime, lease=None):
        params = message['params']
        await self.events.put({'method': 'studyforge/tool', 'params': {'threadId': params['threadId'],
                               'tool': params['tool'], 'status': 'running'}})
        try:
            result = await runtime.execute(params['tool'], params['arguments']) if runtime else {'error': '当前会话未启用学习工具'}
        except Exception as exc:
            result = {'error': str(exc)}
        if lease: await lease.resume()
        await self._send({'id': message['id'], 'result': {'success': 'error' not in result,
                          'contentItems': [{'type': 'inputText', 'text': json.dumps(result, ensure_ascii=False)}]}})
        await self.events.put({'method': 'studyforge/tool', 'params': {'threadId': params['threadId'],
            'tool': params['tool'], 'status': 'failed' if 'error' in result else 'completed',
            'result': {key: value for key, value in result.items() if key not in ('text', 'description', 'results')}}})

    async def request(self, method: str, params: dict) -> dict:
        self.counter += 1
        key = self.counter
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        await self._send({"method": method, "id": key, "params": params})
        return await asyncio.wait_for(future, timeout=30)

    async def list_models(self) -> list[dict]:
        await self.start()
        models, cursor, seen = [], None, set()
        for _ in range(20):
            params = {'limit': 50, 'includeHidden': False}
            if cursor is not None:
                params['cursor'] = cursor
            result = await self.request('model/list', params)
            page = result.get('data', result.get('models', []))
            if not isinstance(page, list):
                raise RuntimeError('Codex 返回了无效的模型目录')
            models.extend(page)
            cursor = result.get('nextCursor')
            if not cursor:
                return models
            if not isinstance(cursor, str) or cursor in seen:
                raise RuntimeError('Codex 模型目录分页异常，请刷新或更新 CLI')
            seen.add(cursor)
        raise RuntimeError('Codex 模型目录分页超过上限，未发布不完整目录')

    @asynccontextmanager
    async def cancellable_turn(self):
        async with self.turn_lock:
            try:
                yield
            except asyncio.CancelledError:
                # Stop this application's server and its tool requests before
                # releasing the lock. The next reply restores local history.
                await self.close()
                raise

    @asynccontextmanager
    async def scheduled_turn(self, runtime, body=None):
        from .scheduling import model_slot
        async with self.cancellable_turn(), model_slot('codex', runtime) as lease:
            self.model_lease = lease
            try:
                from .library_policy import model_request
                with model_request(body or {}, 'codex'): yield
            finally: self.model_lease = None

    async def next_turn_event(self, runtime):
        """Model inactivity is bounded; time awaiting the student's approval is not."""
        from .scheduling import execution_context
        timeout = BACKGROUND_EVENT_TIMEOUT if execution_context.get().get('priority', 0) > 0 else FOREGROUND_EVENT_TIMEOUT
        start = time.monotonic()
        initial_wait = runtime.approval_wait_seconds() if runtime else 0.0
        pending = asyncio.create_task(self.events.get())
        try:
            while True:
                waited = runtime.approval_wait_seconds() - initial_wait if runtime else 0.0
                remaining = timeout - (time.monotonic() - start - waited)
                if remaining <= 0:
                    raise asyncio.TimeoutError('Codex 响应超时，请检查本机会话状态')
                interval = min(1.0, remaining) if runtime and runtime.waiting_approvals else remaining
                done, _ = await asyncio.wait({pending}, timeout=interval)
                if done:
                    return pending.result()
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    async def stream_turn(self, prompt: str, remote_thread_id: str | None = None,
                          model: str | None = None, effort: str | None = None,
                          image_paths: list[str] | None = None, agent_runtime=None,
                          fallback_history: str = '') -> AsyncIterator[tuple[str, Any]]:
        async with self.scheduled_turn(agent_runtime, {'model': model, 'messages': [{'content': prompt},
            {'content': [{'type': 'localImage'} for _ in (image_paths or [])]}]}):
            self.agent_runtime = agent_runtime
            await self.start()
            tool_params = {'config': learning_tool_config()}
            from .db import uid
            from .dialogue_scope import CONTEXT_BOUNDARY
            workspace = agent_runtime.workspace if agent_runtime else data_dir() / 'assessment-workspace' / uid()
            workspace.mkdir(parents=True, exist_ok=True)
            prompt += CONTEXT_BOUNDARY
            signature = None
            if agent_runtime:
                agent_runtime.calls = 0
                from .agent_tools import tool_specs, AGENT_RULES, LEARNING_RECORD_TOOLS
                from .db import one
                from .ai import settings
                tool_params['dynamicTools'] = tool_specs(codex=True,names=None if settings().get('agent_tools_enabled',True) else LEARNING_RECORD_TOOLS)
                signature = hashlib.sha256(json.dumps({'tools': tool_params['dynamicTools'], 'ephemeral': True,
                                                        'workspace': str(workspace),'scope_key':agent_runtime.state_key()}, sort_keys=True).encode()).hexdigest()
                prompt += '\n' + AGENT_RULES + '\n工具环境：' + agent_runtime.context()
                if remote_thread_id and not one('SELECT thread_id FROM codex_agent_threads WHERE thread_id=? AND tool_signature=?', (remote_thread_id, signature)):
                    # Dynamic tools are immutable at thread creation. Restore the saved
                    # dialogue once when upgrading an old thread, then share the new ID.
                    remote_thread_id = None
                    yield 'tool', {'tool': 'session', 'status': 'completed', 'result': {'message': '已接入独立学习 Agent 会话，保留软件中的聊天记录'}}
            if remote_thread_id not in self.live_threads:
                # Ephemeral threads are deliberately absent from Codex history.
                # After a server restart, restore from the application's history.
                remote_thread_id = None
            if remote_thread_id: thread_id = remote_thread_id
            if not remote_thread_id:
                params = {"cwd": str(workspace), "sandbox": "read-only", "approvalPolicy": "never", 'ephemeral': True}
                params.update(tool_params)
                if model:
                    params["model"] = model
                result = await self.request("thread/start", params)
                if result['thread'].get('ephemeral') is not True:
                    raise RuntimeError('Codex 未确认临时会话模式，已停止运行；请更新 Codex CLI 后重试，避免学习对话进入外部历史记录')
                thread_id = result["thread"]["id"]
                self.live_threads.add(thread_id)
                if signature:
                    from .db import execute, now
                    execute('INSERT OR REPLACE INTO codex_agent_threads VALUES (?,?,?)', (thread_id, signature, now()))
                if fallback_history:
                    prompt += '\n当前学习对话的已保存消息（恢复上下文）：\n' + fallback_history
            yield "thread", thread_id
            turn_params = {"threadId": thread_id,
                           "input": [{"type": "text", "text": prompt}] +
                                    [{"type": "localImage", "path": path} for path in (image_paths or [])],
                           "sandboxPolicy": {"type": "readOnly"},
                           "approvalPolicy": "never"}
            if model:
                turn_params["model"] = model
            if effort:
                turn_params["effort"] = effort
            await self.request("turn/start", turn_params)
            final_messages = []
            while True:
                event = await self.next_turn_event(agent_runtime)
                params = event.get("params", {})
                if params.get("threadId") not in (None, thread_id):
                    continue
                if event.get('method') == 'studyforge/serverClosed':
                    raise RuntimeError('Codex 本机会话服务已退出，请检查登录状态后重试')
                if event.get("method") == "item/agentMessage/delta":
                    delta = params.get("delta")
                    if delta:
                        yield "delta", delta
                elif event.get('method') == 'studyforge/tool':
                    yield 'tool', {key: value for key, value in params.items() if key != 'threadId'}
                elif event.get("method") == "item/completed":
                    item = params.get("item", {})
                    if item.get("type") == "agentMessage" and item.get("phase") != "commentary":
                        if item.get("text"):
                            final_messages.append(item["text"])
                elif event.get("method") == "turn/completed":
                    turn = params.get("turn", {})
                    if turn.get("status") != "completed":
                        raise CodexTurnError(turn.get('error'),turn.get('status'))
                    if final_messages:
                        yield "final", "\n\n".join(final_messages)
                    break

    async def close(self) -> None:
        self.live_threads.clear()
        for task in list(self.tool_tasks): task.cancel()
        await asyncio.gather(*list(self.tool_tasks), return_exceptions=True)
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()
        if self.reader:
            self.reader.cancel()
            try:
                await self.reader
            except asyncio.CancelledError:
                pass


bridge = CodexBridge()
_chat_bridges = weakref.WeakKeyDictionary()


def bridge_for(conversation_id):
    # Separate event queues / tool routing for independent chats. A connection
    # is started lazily, only while its turn owns a global model slot.
    loop = asyncio.get_running_loop()
    if loop not in _chat_bridges: _chat_bridges[loop] = OrderedDict()
    pool = _chat_bridges[loop]
    if conversation_id not in pool: pool[conversation_id] = CodexBridge()
    pool.move_to_end(conversation_id)
    from .scheduling import configuration
    capacity = max(2, configuration()['model_concurrency'])
    for key, connection in list(pool.items()):
        if len(pool) <= capacity: break
        if key != conversation_id and not connection.turn_lock.locked():
            pool.pop(key)
            task = asyncio.create_task(connection.close())
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return pool[conversation_id]


async def close_chat_bridges():
    pool = _chat_bridges.pop(asyncio.get_running_loop(), {})
    connections = list(pool.values())
    await asyncio.gather(*(connection.close() for connection in connections), return_exceptions=True)
