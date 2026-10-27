"""Opt-in HTTPS mobile gateway; the desktop API remains bound to loopback.

Only this gateway is exposed to the LAN. It authenticates paired devices and
forwards a small allowlist to the in-process desktop app. No desktop-owner
token, model key, settings API, filesystem route or raw database is exposed.
"""
from __future__ import annotations

import asyncio
import base64
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, StrictBool

from .config import data_dir
from .db import connect, execute, j, many, now, one, uid, unj
from .mobile_context import remote_device

COOKIE = '__Host-studyforge-mobile'
UPLOAD_LIMIT = 512 * 1024 * 1024
ID = r'[a-f0-9]{32}'
SAFE_ROUTES = [
    ('GET', r'/api/library/(?:books|jobs|search)'), ('POST', r'/api/library/books'),
    ('GET', r'/api/library/nodes/suggest'),
    ('GET', r'/api/library/semantic'), ('PUT', r'/api/library/semantic'),
    ('GET', r'/api/library/policy'), ('PUT', r'/api/library/policy'),
    ('GET', r'/api/library/models'), ('PUT', r'/api/library/models'),
    ('GET', rf'/api/library/books/{ID}(?:/page)?'),
    ('POST', rf'/api/library/books/{ID}/(?:toc|read|nodes|ranges)'),
    ('POST', rf'/api/library/books/{ID}/outline/move'),
    ('POST', rf'/api/library/books/{ID}/ranges/confirm'),
    ('PUT', rf'/api/library/nodes/{ID}'), ('GET', rf'/api/library/nodes/{ID}/notes'),
    ('PUT', rf'/api/library/nodes/{ID}/notes/{ID}/annotation'),
    ('POST', rf'/api/library/jobs/{ID}/(?:pause|resume|cancel)'),
    ('GET', rf'/api/library/conversations/{ID}(?:/references)?'), ('PUT', rf'/api/library/conversations/{ID}'),
    ('POST', rf'/api/library/conversations/{ID}/references'),
    ('GET', rf'/api/library/conversations/{ID}/history'),
    ('DELETE', rf'/api/library/conversations/{ID}/history'),
    ('GET', r'/api/projects'), ('POST', r'/api/projects'),
    ('GET', rf'/api/projects/{ID}/(?:conversations|sources|categories|jobs|artifacts|exercises|homework|lesson-feedback)'),
    ('GET', rf'/api/projects/{ID}/learning-goals'),
    ('POST', rf'/api/projects/{ID}/learning-goals/{ID}/check'),
    ('POST', rf'/api/projects/{ID}/conversations'),
    ('GET', rf'/api/conversations/{ID}(?:/messages)?'), ('PUT', rf'/api/conversations/{ID}'),
    ('POST', r'/api/import/file'), ('POST', r'/api/import/url'),
    ('GET', rf'/api/sources/{ID}/page'), ('POST', rf'/api/sources/{ID}/parse'),
    ('POST', r'/api/read'), ('POST', r'/api/read/restore'), ('POST', r'/api/generate'),
    ('GET', rf'/api/jobs/{ID}(?:/timing)?'), ('POST', rf'/api/jobs/{ID}/(?:pause|resume|retry)'),
    ('GET', rf'/api/artifacts/{ID}/download'), ('GET', rf'/api/agent/assets/{ID}/image'),
    ('POST', rf'/api/(?:artifacts|jobs)/{ID}/export'),
    ('POST', rf'/api/messages/{ID}/export'),
    ('GET', rf'/api/messages/{ID}/passage'),
    ('GET', r'/api/agent/approvals'), ('POST', rf'/api/agent/approvals/{ID}'),
    ('GET', r'/api/learning-modes'), ('GET', r'/api/codex/models'), ('GET', r'/api/deepseek/models'),
    ('GET', rf'/api/providers/svc_{ID}/models'),
    ('GET', rf'/api/exercises/{ID}(?:/submissions)?'),
    ('POST', rf'/api/exercises/{ID}/(?:submit|extract-answers|hint|feynman|repair|advance)'),
    ('GET', rf'/api/homework/{ID}'), ('POST', rf'/api/homework/{ID}/(?:causes|retry)'),
    ('GET', rf'/api/homework/{ID}/reading'),
    ('GET', rf'/api/exercises/{ID}/repair-options'),
    ('PUT', rf'/api/homework/{ID}/draft'),
    ('POST', rf'/api/coding/{ID}/(?:preview|submit)'),
    ('GET', rf'/api/lesson-feedback/{ID}/(?:dialogue|sections|passage)'), ('GET', rf'/api/lesson-feedback/by-job/{ID}'),
    ('POST', rf'/api/lesson-feedback/{ID}/(?:submit|check|content-check)'),
]


def private_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        return address.version == 4 and (address.is_loopback or any(address in ipaddress.ip_network(net)
            for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')))
    except ValueError:
        return False


def lan_addresses() -> list[str]:
    values = []
    try:
        values = [item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    return sorted({value for value in values if private_address(value) and not value.startswith('127.')})


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def allowed(method: str, path: str) -> bool:
    import re
    return any(method == verb and re.fullmatch(pattern, path) for verb, pattern in SAFE_ROUTES)


def request_limit(path: str) -> tuple[int, str]:
    """Include multipart framing; the target endpoint checks actual file size."""
    import re
    framing = 64 * 1024
    if path in ('/api/import/file','/api/library/books'):
        return UPLOAD_LIMIT + framing, '手机单次上传文件上限为 512 MB'
    if re.fullmatch(rf'/api/exercises/{ID}/extract-answers', path):
        return 100 * 1024 * 1024 + framing, '作答识别文件最大 100 MB'
    if re.fullmatch(rf'/api/coding/{ID}/(?:preview|submit)', path):
        return 2 * 1024 * 1024 + framing, '代码文件最大 2 MB'
    return 2 * 1024 * 1024, '单次文字请求最大 2 MB，大型资料请通过文件上传'


def public_device(row: dict) -> dict:
    return {key: row[key] for key in ('id', 'name', 'status', 'created_at', 'last_seen', 'expires_at')}


class PairIn(BaseModel):
    code: str = Field(min_length=8, max_length=8, pattern=r'^\d{8}$')
    name: str = Field(min_length=1, max_length=60)


class MobileChatIn(BaseModel):
    request_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{16,80}$')
    request: dict


class MobileFeedbackIn(BaseModel):
    request_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{16,80}$')
    project_id: str = Field(pattern=rf'^{ID}$')
    conversation_id: str = Field(pattern=rf'^{ID}$')


class StartIn(BaseModel):
    addresses: list[str] = Field(default_factory=list, max_length=16)
    port: int = Field(default=18765, ge=1024, le=65535)
    auto_start: StrictBool = False
    enable_tailscale: StrictBool = False
    remember_days: int = Field(default=365, ge=30, le=365)


class ConnectionPreferences(BaseModel):
    auto_start: StrictBool
    remember_days: int = Field(default=365, ge=30, le=365)


class PairDecision(BaseModel):
    approved: StrictBool


class MobileManager:
    def __init__(self, desktop_app):
        self.desktop_app = desktop_app
        self.web = Path(__file__).resolve().parent.parent / 'web'
        self.server = None
        self.server_task = None
        self.chat_tasks: dict[str, asyncio.Task] = {}
        self.proxy_tasks = set()
        self.code = ''
        self.code_expires = 0.0
        self.attempts = defaultdict(deque)
        self.addresses = []
        self.port = 18765
        self.tls = None
        self.lock = asyncio.Lock()
        self.enable_tailscale = False
        self.tailnet = {'installed': False, 'connected': False, 'addresses': [], 'message': '正在检测固定地址'}
        self.network_checked = -100.0
        self.network_lock = asyncio.Lock()
        self.network_task = None
        self.gateway = self._gateway()

    def config(self):
        file = data_dir() / 'mobile' / 'connection.json'
        try:
            return json.loads(file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {'auto_start': False, 'port': 18765, 'enable_tailscale': False, 'remember_days': 365}

    async def refresh_network(self, *, force=False):
        async with self.network_lock:
            if force or time.monotonic() - self.network_checked > 15:
                from .mobile_network import read_status
                self.tailnet = await asyncio.to_thread(read_status)
                self.network_checked = time.monotonic()
        await self.refresh_certificate()
        return self.tailnet

    async def refresh_certificate(self):
        if not (self.server and self.server.started and self.server_task and not self.server_task.done()):
            return
        extra = [address for address in self.tailnet.get('addresses', [])
                 if self.enable_tailscale and address not in self.addresses]
        expires = (self.tls or {}).get('expires_at')
        renewing = bool(expires and expires < (datetime.now(timezone.utc) + timedelta(days=7)).isoformat())
        if not extra and not renewing:
            return
        async with self.lock:
            if not (self.server and self.server.started and self.server_task and not self.server_task.done()):
                return
            from .mobile_tls import certificates
            addresses = list(dict.fromkeys(self.addresses + extra))
            issuing = asyncio.create_task(asyncio.to_thread(certificates, data_dir() / 'mobile' / 'tls', addresses))
            try:
                tls = await asyncio.shield(issuing)
            except asyncio.CancelledError:
                await issuing  # Finish writing the chain before a restart can issue another.
                raise
            # Uvicorn shares this SSLContext with its listeners. Existing TLS
            # sessions continue; new connections receive the refreshed leaf.
            self.server.config.ssl.load_cert_chain(tls['certificate'], tls['key'])
            self.tls, self.addresses = tls, addresses

    async def monitor_network(self):
        while True:
            await asyncio.sleep(15)
            try:
                await self.refresh_network(force=True)
                self.network_error = None
            except (ValueError, OSError, RuntimeError) as exc:
                self.network_error = str(exc)

    def remember_days(self):
        try:
            return min(365, max(30, int(self.config().get('remember_days', 365))))
        except (TypeError, ValueError):
            return 365

    def save_preferences(self, value: ConnectionPreferences):
        file = data_dir() / 'mobile' / 'connection.json'
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(j(self.config() | value.model_dump()), encoding='utf-8')
        return self.status()

    async def restore(self):
        execute("UPDATE mobile_chats SET status='failed',error='电脑后台已重启；已完成的对话保留，请重新发送尚未完成的问题',updated_at=? WHERE status IN ('queued','running')", (now(),))
        config = self.config()
        if config.get('auto_start'):
            try:
                await self.start(StartIn(addresses=lan_addresses(), port=config.get('port', 18765), auto_start=True,
                    enable_tailscale=config.get('enable_tailscale', False), remember_days=self.remember_days()))
            except (OSError, RuntimeError, ValueError) as exc:
                self.start_error = str(exc)

    def status(self):
        running = bool(self.server and self.server.started and self.server_task and not self.server_task.done())
        stamp = now()
        execute("UPDATE mobile_devices SET status='expired' WHERE status IN ('pending','approved') AND expires_at<?", (stamp,))
        return {'gateway_version': 2, 'running': running, 'addresses': self.addresses or lan_addresses(), 'port': self.port,
            'urls': [f'https://{address}:{self.port}/' for address in self.addresses] if running else [],
            'pairing_code': self.code if time.monotonic() < self.code_expires and running else '',
            'pairing_seconds': max(0, int(self.code_expires - time.monotonic())) if running else 0,
            'devices': [public_device(row) for row in many('SELECT * FROM mobile_devices ORDER BY created_at DESC')],
            'fingerprint': (self.tls or {}).get('fingerprint'), 'auto_start': self.config().get('auto_start', False),
            'enable_tailscale': self.enable_tailscale if running else self.config().get('enable_tailscale', False),
            'tailscale': self.tailnet, 'remember_days': self.remember_days(),
            'preferred_address': next((address for address in self.tailnet.get('addresses', [])
                                       if self.enable_tailscale and address in self.addresses), None),
            'network_error': getattr(self, 'network_error', None),
            'upload_limit': UPLOAD_LIMIT, 'error': getattr(self, 'start_error', None)}

    async def start(self, options: StartIn):
        async with self.lock:
            if self.server_task and not self.server_task.done():
                return self.status()
            await self.refresh_network(force=True)
            fixed = self.tailnet.get('addresses', []) if options.enable_tailscale else []
            addresses = list(dict.fromkeys(options.addresses or lan_addresses()))
            if any(not private_address(address) and address not in fixed for address in addresses):
                raise ValueError('请选择电脑的局域网 IPv4 地址；请先连接 Wi-Fi 或有线网络')
            addresses = list(dict.fromkeys(addresses + fixed))
            if not addresses:
                raise ValueError('没有可用连接地址，请连接 Wi-Fi，或先登录 Tailscale')
            from .mobile_tls import certificates
            self.tls = await asyncio.to_thread(certificates, data_dir() / 'mobile' / 'tls', addresses)
            self.addresses, self.port, self.enable_tailscale = addresses, options.port, options.enable_tailscale
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                listener.bind(('0.0.0.0', self.port))
                listener.listen(128)
                listener.setblocking(False)
            except OSError as exc:
                listener.close()
                raise ValueError(f'手机连接端口 {self.port} 无法使用，请改用其他端口：{exc}') from exc
            import uvicorn
            config = uvicorn.Config(self.gateway, host='0.0.0.0', port=self.port, lifespan='off', log_level='warning',
                access_log=False, proxy_headers=False, ssl_certfile=self.tls['certificate'], ssl_keyfile=self.tls['key'],
                ssl_version=__import__('ssl').PROTOCOL_TLS_SERVER, limit_concurrency=32, timeout_keep_alive=15)
            self.server = uvicorn.Server(config)
            # A second server shares the desktop event loop; only the outer
            # desktop server owns OS signal handlers.
            from contextlib import contextmanager
            @contextmanager
            def no_signals():
                yield
            self.server.capture_signals = no_signals
            self.server_task = asyncio.create_task(self.server.serve(sockets=[listener]))
            for _ in range(100):
                if self.server.started:
                    break
                if self.server_task.done():
                    listener.close()
                    raise RuntimeError('手机 HTTPS 服务未启动，请查看后台日志')
                await asyncio.sleep(.03)
            else:
                self.server.should_exit = True
                await asyncio.gather(self.server_task, return_exceptions=True)
                raise RuntimeError('手机 HTTPS 服务启动超时')
            file = data_dir() / 'mobile' / 'connection.json'
            file.write_text(j({'auto_start': options.auto_start, 'port': self.port,
                               'enable_tailscale': options.enable_tailscale, 'remember_days': options.remember_days}), encoding='utf-8')
            self.start_error = None
            self.new_code()
            self.network_task = asyncio.create_task(self.monitor_network())
            return self.status()

    def new_code(self):
        self.code = f'{secrets.randbelow(100000000):08d}'
        self.code_expires = time.monotonic() + 300
        return self.code

    async def stop(self, *, shutdown=False):
        async with self.lock:
            self.code, self.code_expires = '', 0
            if self.network_task:
                self.network_task.cancel()
                await asyncio.gather(self.network_task, return_exceptions=True)
                self.network_task = None
            if self.server:
                self.server.should_exit = True
            for task in list(self.chat_tasks.values()) + list(self.proxy_tasks):
                task.cancel()
            await asyncio.gather(*self.chat_tasks.values(), *self.proxy_tasks, return_exceptions=True)
            if self.server_task:
                try:
                    await asyncio.wait_for(asyncio.shield(self.server_task), 8)
                except asyncio.TimeoutError:
                    self.server_task.cancel()
                    await asyncio.gather(self.server_task, return_exceptions=True)
            self.server = self.server_task = None
            execute("UPDATE mobile_devices SET status='denied' WHERE status IN ('pending','approved')")
            if not shutdown:
                file = data_dir() / 'mobile' / 'connection.json'
                if file.exists():
                    file.write_text(j(self.config() | {'auto_start': False}), encoding='utf-8')
            return self.status()

    def request_pair(self, value: PairIn, address: str):
        bucket = self.attempts[address]
        while bucket and bucket[0] < time.monotonic() - 300:
            bucket.popleft()
        if len(bucket) >= 8:
            raise HTTPException(429, '配对尝试过多，请稍后再试或在电脑上刷新配对码')
        bucket.append(time.monotonic())
        if time.monotonic() >= self.code_expires or not self.code or not hmac.compare_digest(value.code, self.code):
            raise HTTPException(403, '配对码错误或已过期，请查看电脑上的手机连接面板')
        if len(many("SELECT id FROM mobile_devices WHERE status='active' AND expires_at>?", (now(),))) >= 8:
            raise HTTPException(409, '最多保留 8 台手机，请先在电脑上移除不用的设备')
        self.code, self.code_expires = '', 0
        ident, ticket = uid(), secrets.token_urlsafe(32)
        timestamp = now()
        expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        execute('INSERT INTO mobile_devices VALUES (?,?,?,?,?,?,?,?,?)',
                (ident, value.name.strip(), 'pending', None, hash_token(ticket), timestamp, timestamp, expiry, address))
        return {'device_id': ident, 'ticket': ticket, 'status': 'pending', 'message': '请在电脑的手机连接面板确认这台设备'}

    def decide(self, ident: str, approved: bool):
        with connect() as database:
            changed = database.execute("UPDATE mobile_devices SET status=? WHERE id=? AND status='pending' AND expires_at>?",
                ('approved' if approved else 'denied', ident, now())).rowcount
        if not changed:
            raise HTTPException(409, '配对请求已处理或过期')
        return self.status()

    async def revoke(self, ident: str):
        execute("UPDATE mobile_devices SET status='revoked',token_hash=NULL,ticket_hash=NULL WHERE id=?", (ident,))
        cancelled = []
        for row in many("SELECT id FROM mobile_chats WHERE device_id=? AND status IN ('queued','running')", (ident,)):
            if task := self.chat_tasks.get(row['id']):
                task.cancel()
                cancelled.append(task)
        await asyncio.gather(*cancelled, return_exceptions=True)
        return self.status()

    def authenticate(self, token: str | None):
        if not token:
            raise HTTPException(401, '请先与电脑配对', headers={'X-StudyForge-Mobile-Session':'required'})
        device = one("SELECT * FROM mobile_devices WHERE token_hash=? AND status='active' AND expires_at>?",
                     (hash_token(token), now()))
        if not device:
            raise HTTPException(401, '手机连接已失效或被电脑撤销，请重新配对', headers={'X-StudyForge-Mobile-Session':'expired'})
        stamp = datetime.now(timezone.utc)
        expiry = (stamp + timedelta(days=self.remember_days())).isoformat()
        renew = (device['expires_at'] < (stamp + timedelta(days=self.remember_days() - 1)).isoformat() or
                 device['expires_at'] > (stamp + timedelta(days=self.remember_days() + 1)).isoformat())
        if renew:
            with connect() as database:
                changed = database.execute("UPDATE mobile_devices SET last_seen=?,expires_at=? "
                    "WHERE id=? AND status='active' AND token_hash=? AND expires_at>?",
                    (stamp.isoformat(), expiry, device['id'], hash_token(token), stamp.isoformat())).rowcount
            if not changed:
                raise HTTPException(401, '手机连接已被撤销，请重新配对', headers={'X-StudyForge-Mobile-Session':'expired'})
            device['expires_at'] = expiry
            device['_renew_cookie'] = True
        elif device['last_seen'] < (stamp - timedelta(minutes=1)).isoformat():
            execute('UPDATE mobile_devices SET last_seen=? WHERE id=?', (stamp.isoformat(), device['id']))
        device['last_seen'] = stamp.isoformat()
        return device

    async def start_chat(self, device, value: MobileChatIn):
        from . import server, conversations
        try:
            request = server.ChatIn.model_validate(value.request)
            if not request.conversation_id:
                raise ValueError('请先打开一个学习对话')
            conversations.detail(request.conversation_id, request.project_id)
            from .message_focus import resolve
            resolve(request.reply_reference,request.project_id,request.conversation_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        digest = hash_token(j(request.model_dump()))
        return self._enqueue_reply(device, value.request_id, digest, request.project_id,
                                   request.conversation_id, request=request)

    async def start_feedback(self, device, questionnaire_id: str, value: MobileFeedbackIn):
        from . import conversations, lesson_feedback
        from .navigation import require_project
        try:
            questionnaire = lesson_feedback.get_questionnaire(questionnaire_id)
            if (questionnaire['project_id'], questionnaire['conversation_id']) != (value.project_id, value.conversation_id):
                raise ValueError('请在这份讲解的原项目、原对话中请求补讲')
            require_project(value.project_id)
            conversations.detail(value.conversation_id, value.project_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        def check_ready():
            current = lesson_feedback.get_questionnaire(questionnaire_id)
            if current['status'] != 'submitted':
                raise HTTPException(400, '请先填写并提交理解问卷')
            if not lesson_feedback.public_questionnaire(current)['ready']:
                raise HTTPException(409, '讲解尚未交付，反馈已保留；交付后可以补讲')
            if current['reply_status'] in ('running', 'completed'):
                raise HTTPException(409, '导师正在补讲或补讲已完成，请查看原学习对话')

        digest = hash_token(j({'kind': 'lesson_feedback', 'questionnaire_id': questionnaire_id,
                               'project_id': value.project_id, 'conversation_id': value.conversation_id}))
        return self._enqueue_reply(device, value.request_id, digest, value.project_id,
            value.conversation_id, questionnaire_id=questionnaire_id, check_ready=check_ready)

    def _enqueue_reply(self, device, request_key, digest, project_id, conversation_id, *,
                       request=None, questionnaire_id=None, check_ready=None):
        from . import server
        with connect() as database:
            database.execute('BEGIN IMMEDIATE')
            existing = database.execute('SELECT * FROM mobile_chats WHERE device_id=? AND request_key=?',
                (device['id'], request_key)).fetchone()
            if existing:
                if existing['request_hash'] != digest:
                    raise HTTPException(409, '同一发送编号不能用于不同问题')
                return {'run_id': existing['id'], 'status': existing['status'], 'reused': True}
            busy = database.execute("SELECT id FROM mobile_chats WHERE conversation_id=? AND status IN ('queued','running')",
                                    (conversation_id,)).fetchone()
            if busy or conversation_id in server.active_chat_conversations:
                raise HTTPException(409, '这个对话正在回复，请等待或切换其他对话')
            if check_ready:
                check_ready()
            ident, timestamp = uid(), now()
            state = {'label': '准备补讲' if questionnaire_id else '准备回复'}
            if questionnaire_id:
                state.update(kind='lesson_feedback', questionnaire_id=questionnaire_id)
            database.execute('INSERT INTO mobile_chats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (ident, device['id'], request_key, digest, project_id, conversation_id,
                 'queued', '', j(state), None, timestamp, timestamp, 0))
        task = asyncio.create_task(self._chat(ident, device['id'], request, questionnaire_id))
        self.chat_tasks[ident] = task
        def finished(done):
            self.chat_tasks.pop(ident, None)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
        return {'run_id': ident, 'status': 'queued', 'reused': False}

    async def _chat(self, ident, device_id, request=None, questionnaire_id=None):
        from . import server
        token = remote_device.set(device_id)
        content, state, error = '', {'label': '导师正在补讲' if questionnaire_id else '导师正在回复'}, None
        if questionnaire_id:
            state.update(kind='lesson_feedback', questionnaire_id=questionnaire_id)
        execute("UPDATE mobile_chats SET status='running',state_json=?,updated_at=? WHERE id=?", (j(state), now(), ident))
        iterator = None
        last_save, buffer, last_saved_content = 0, '', ''
        try:
            response = await server.feedback_followup(questionnaire_id) if questionnaire_id else await server.chat_stream(request)
            iterator = response.body_iterator
            async for chunk in iterator:
                buffer += chunk.decode('utf-8') if isinstance(chunk, bytes) else chunk
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if not line:
                        continue
                    event = json.loads(line)
                    kind, value = event['type'], event['value']
                    if kind == 'delta':
                        content += value
                    elif kind == 'replace':
                        content = value
                    elif kind == 'error':
                        error = str(value)
                    elif kind == 'status':
                        state['label'] = str(value)[:500]
                    elif kind == 'job':
                        state['job_id'] = value
                    elif kind == 'tool':
                        state['tool'] = value
                        state['label'] = value.get('label', '正在处理学习任务')
                    # A status packet may consume the throttle immediately before
                    # the first text. Publish that text even if the provider then
                    # waits a long time before delivering another packet.
                    if time.monotonic() - last_save >= .15 or kind in ('tool', 'done', 'error', 'job', 'replace') or (content and not last_saved_content):
                        execute('UPDATE mobile_chats SET content=?,state_json=?,error=?,updated_at=?,revision=revision+1 WHERE id=?',
                                (content, j(state), error, now(), ident))
                        last_save = time.monotonic()
                        last_saved_content = content
            status = 'failed' if error else 'completed'
        except asyncio.CancelledError:
            status, error = 'cancelled', '本次回复已停止；已经完成的生成任务仍可在任务列表查看'
        except Exception as exc:
            status, error = 'failed', str(getattr(exc, 'detail', exc))
        finally:
            try:
                if iterator and hasattr(iterator, 'aclose'):
                    await iterator.aclose()
            except Exception as exc:
                status, error = 'failed', str(exc)
            finally:
                remote_device.reset(token)
        execute('UPDATE mobile_chats SET status=?,content=?,state_json=?,error=?,updated_at=?,revision=revision+1 WHERE id=?',
                (status, content, j(state), error, now(), ident))

    async def _forward(self, request: Request):
        """Stream uploads/downloads without buffering entire files in RAM."""
        queue = asyncio.Queue(maxsize=8)
        started = asyncio.get_running_loop().create_future()
        stream = request.stream().__aiter__()
        total, received = 0, False
        body_limit, limit_message = request_limit(request.url.path)
        device_id = request.state.mobile_device['id']
        async def receive():
            nonlocal total, received
            if received:
                await asyncio.Future()  # StreamingResponse disconnect listener.
            try:
                chunk = await anext(stream)
            except StopAsyncIteration:
                received = True
                return {'type': 'http.request', 'body': b'', 'more_body': False}
            total += len(chunk)
            if total > body_limit:
                raise HTTPException(413, limit_message)
            return {'type': 'http.request', 'body': chunk, 'more_body': True}
        async def send(message):
            if message['type'] == 'http.response.start':
                if not started.done():
                    started.set_result(message)
            elif message['type'] == 'http.response.body':
                if message.get('body'):
                    await queue.put(message['body'])
                if not message.get('more_body', False):
                    await queue.put(None)
        async def invoke():
            token = remote_device.set(device_id)
            try:
                headers = [(key, value) for key, value in request.scope['headers'] if key.lower() in
                    {b'content-type', b'content-length', b'accept', b'range', b'if-range'}]
                scope = {**request.scope, 'scheme': 'http', 'server': ('127.0.0.1', 8765),
                    'client': ('127.0.0.1', 12345), 'headers': headers, 'root_path': '',
                    'state': {}, 'studyforge.mobile_device': device_id}
                await self.desktop_app(scope, receive, send)
            except Exception as exc:
                if not started.done():
                    started.set_exception(exc)
                else:
                    await queue.put(None)
            finally:
                remote_device.reset(token)
        task = asyncio.create_task(invoke())
        self.proxy_tasks.add(task)
        task.add_done_callback(self.proxy_tasks.discard)
        try:
            start = await started
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
        async def body():
            try:
                while (chunk := await queue.get()) is not None:
                    yield chunk
                await task
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        response = StreamingResponse(body(), status_code=start['status'])
        response.raw_headers = [(key, value) for key, value in start.get('headers', []) if key.lower() not in
                                {b'set-cookie', b'server', b'transfer-encoding'}]
        return response

    def _gateway(self):
        app = FastAPI(title='StudyForge Mobile', docs_url=None, redoc_url=None, openapi_url=None)

        @app.middleware('http')
        async def security(request, call_next):
            # Accept the overlay only when this PC's installed Tailscale client
            # provided an address and the owner enabled that connection mode.
            peer = request.client.host if request.client else ''
            from .mobile_network import tailnet_address
            tailnet_ready = self.enable_tailscale and any(address in self.addresses for address in self.tailnet.get('addresses', []))
            if not private_address(peer) and not (tailnet_ready and tailnet_address(peer)):
                return JSONResponse({'detail': '请通过局域网或已启用的 Tailscale 私人连接访问'}, status_code=403)
            if request.url.scheme != 'https':
                return JSONResponse({'detail': '手机连接必须使用 HTTPS'}, status_code=403)
            if request.url.hostname not in self.addresses + ['127.0.0.1', 'localhost']:
                return JSONResponse({'detail': '连接地址不属于这台电脑'}, status_code=403)
            origin = request.headers.get('origin')
            if origin and origin != f'https://{request.url.netloc}':
                return JSONResponse({'detail': '拒绝其他网页发起的操作'}, status_code=403)
            if request.headers.get('sec-fetch-site') == 'cross-site' and request.method not in ('GET', 'HEAD'):
                return JSONResponse({'detail': '请从手机学习页面发起操作'}, status_code=403)
            try:
                try:
                    length = int(request.headers.get('content-length', '0'))
                except ValueError:
                    raise HTTPException(400, '请求长度无效')
                body_limit, limit_message = request_limit(request.url.path)
                if length < 0 or length > body_limit:
                    raise HTTPException(413, limit_message)
                if request.url.path.startswith('/api/') or request.url.path in ('/mobile/logout', '/mobile/session'):
                    request.state.mobile_device = self.authenticate(request.cookies.get(COOKIE))
                response = await call_next(request)
                device = getattr(request.state, 'mobile_device', {})
                if device.get('_renew_cookie') and request.url.path != '/mobile/logout':
                    response.set_cookie(COOKIE, request.cookies[COOKIE], max_age=self.remember_days() * 86400,
                                        httponly=True, secure=True, samesite='strict', path='/')
            except HTTPException as exc:
                marker={key:value for key,value in (exc.headers or {}).items() if key.lower()=='x-studyforge-mobile-session'}
                response = JSONResponse({'detail': exc.detail}, status_code=exc.status_code, headers=marker)
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['Referrer-Policy'] = 'no-referrer'
            # Only the bundled guide can be embedded by this same mobile origin.
            # Other pages and API responses keep their existing frame restriction.
            guide_page = request.url.path == '/help/guide.html'
            response.headers['X-Frame-Options'] = 'SAMEORIGIN' if guide_page else 'DENY'
            response.headers['Content-Security-Policy'] = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; "
                + ("frame-ancestors 'self'" if guide_page else "frame-ancestors 'none'"))
            return response

        @app.get('/mobile/session')
        async def session(request: Request):
            return {'device': public_device(request.state.mobile_device), 'remember_days': self.remember_days()}

        @app.post('/mobile/logout')
        async def logout(request: Request):
            await self.revoke(request.state.mobile_device['id'])
            response = JSONResponse({'ok': True})
            response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='strict')
            return response

        @app.post('/mobile/pair')
        async def pair(value: PairIn, request: Request):
            return self.request_pair(value, request.client.host)

        @app.get('/mobile/pair/{ident}')
        async def pair_status(ident: str, request: Request):
            ticket = request.headers.get('x-mobile-pair-ticket', '')
            row = one('SELECT * FROM mobile_devices WHERE id=? AND ticket_hash=?', (ident, hash_token(ticket))) if ticket else None
            if not row or row['expires_at'] < now():
                raise HTTPException(403, '配对请求已失效，请在电脑上重新生成配对码')
            response = JSONResponse({'status': row['status'], 'device_id': ident})
            if row['status'] == 'approved':
                secret = secrets.token_urlsafe(48)
                expiry = (datetime.now(timezone.utc) + timedelta(days=self.remember_days())).isoformat()
                with connect() as database:
                    changed = database.execute("UPDATE mobile_devices SET status='active',token_hash=?,ticket_hash=NULL,expires_at=? "
                        "WHERE id=? AND status='approved' AND ticket_hash=?", (hash_token(secret), expiry, ident, hash_token(ticket))).rowcount
                if not changed:
                    raise HTTPException(409, '配对已被使用，请直接打开学习页面')
                response = JSONResponse({'status': 'active', 'device_id': ident})
                response.set_cookie(COOKIE, secret, max_age=self.remember_days() * 86400, httponly=True, secure=True, samesite='strict', path='/')
            return response

        @app.get('/mobile/certificate.cer')
        async def certificate():
            if not self.tls:
                raise HTTPException(404, '请先在电脑启用手机连接')
            return FileResponse(self.tls['ca'], media_type='application/pkix-cert', filename='StudyForge-手机连接证书.cer')

        @app.get('/api/mobile/config')
        async def mobile_config():
            from .conversations import workspace
            from .ai import default_provider, settings
            from .providers import list_services, default_model
            from .learning_modes import mode_catalog
            from .exporters import EXPORTERS
            config = settings()
            services = [{'id': name, 'name': label, 'default_model': default_model(name), 'configured': True}
                        for name, label in [('codex', 'Codex'), ('deepseek', 'DeepSeek')]] + [{'id': row['id'], 'name': row['name'], 'default_model': default_model(row['id']),
                         'configured': row.get('configured', True)} for row in list_services() if row.get('enabled', True)]
            return {'provider': default_provider(), 'services': services, 'modes': mode_catalog(), 'desktop_workspace': workspace(),
                'formats': sorted(EXPORTERS), 'upload_limit': UPLOAD_LIMIT,
                'defaults': {key: config.get(key) for key in ('default_output_format', 'review_mode',
                    'learning_mode', 'explanation_style', 'output_language')},
                'permission_mode': 'read_only' if config.get('agent_permission_mode') == 'read_only' else 'approval'}

        @app.post('/api/mobile/chat')
        async def chat(value: MobileChatIn, request: Request):
            return await self.start_chat(request.state.mobile_device, value)

        @app.post('/api/mobile/lesson-feedback/{questionnaire_id}/followup')
        async def feedback(questionnaire_id: str, value: MobileFeedbackIn, request: Request):
            return await self.start_feedback(request.state.mobile_device, questionnaire_id, value)

        @app.get('/api/mobile/chats')
        async def active_chats(request: Request):
            rows = many("SELECT id,project_id,conversation_id,status,state_json FROM mobile_chats WHERE device_id=? "
                "AND status IN ('queued','running') ORDER BY created_at", (request.state.mobile_device['id'],))
            return {'runs': [{key: row[key] for key in ('id', 'project_id', 'conversation_id', 'status')} |
                             {'state': unj(row['state_json'], {})} for row in rows]}

        @app.get('/api/mobile/chat/{ident}')
        async def chat_status(ident: str, request: Request):
            row = one('SELECT * FROM mobile_chats WHERE id=? AND device_id=?', (ident, request.state.mobile_device['id']))
            if not row:
                raise HTTPException(404, '回复不属于这台设备')
            return {key: row[key] for key in ('id','project_id','conversation_id','status','content','error','updated_at','revision')} | {
                'state': unj(row['state_json'], {})}

        @app.post('/api/mobile/chat/{ident}/stop')
        async def stop_chat(ident: str, request: Request):
            row = one('SELECT id FROM mobile_chats WHERE id=? AND device_id=?', (ident, request.state.mobile_device['id']))
            if not row:
                raise HTTPException(404, '回复不属于这台设备')
            if task := self.chat_tasks.get(ident):
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            execute("UPDATE mobile_chats SET status='cancelled',error='本次回复已停止',updated_at=?,revision=revision+1 "
                    "WHERE id=? AND status IN ('queued','running')", (now(), ident))
            return {'ok': True}

        @app.api_route('/api/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
        async def forward(path: str, request: Request):
            if not allowed(request.method, request.url.path):
                raise HTTPException(403, '手机端不能执行此操作，请在电脑端管理设置和文件权限')
            return await self._forward(request)

        @app.get('/{path:path}')
        async def static(path: str):
            if not path:
                return FileResponse(self.web / 'mobile' / 'index.html')
            # Do not mount the desktop bundle, local files or dynamic paths.
            if path in ('app.js', 'homework.js', 'lesson-feedback.js', 'learning-check.js', 'style.css', 'manifest.webmanifest', 'sw.js', 'icon.svg', 'icon-192.png', 'icon-512.png'):
                return FileResponse(self.web / 'mobile' / path)
            if path in ('operation_errors.js', 'operation_errors.css', 'source_scope.js', 'source_scope.css', 'lesson_render.js', 'lesson_passage.js', 'lesson_passage.css', 'message_history.js', 'task_retry.js', 'source_evidence.js', 'source_evidence.css', 'teaching_review.js', 'teaching_review.css', 'refresh_state.js', 'task_timing.js', 'task_timing.css', 'user_guide.js', 'user_guide.css', 'library.js','library_models.js','library.css','library_policy.js','library_mentions.js','library_mentions.css','document_exports.js','document_exports.css','source_selection.js','message_focus.js','message_focus.css',
                        'homework_reader.js', 'homework_reader.css', 'repair_picker.js', 'repair_picker.css', 'practice_hints.js','practice_hints.css', 'help/guide.html', 'help/guide.js', 'help/guide.css'):
                return FileResponse(self.web / path)
            if path.startswith('vendor/'):
                target = (self.web / path).resolve()
                if target.is_relative_to((self.web / 'vendor').resolve()) and target.is_file():
                    return FileResponse(target)
            raise HTTPException(404, '页面不存在')
        return app


def register_routes(app):
    """Desktop-only management: Electron forwards its process-owner token."""
    from fastapi import Header

    def manager(token):
        from .server import require_desktop_owner
        require_desktop_owner(token)
        value = getattr(app.state, 'mobile_manager', None)
        if not value:
            raise HTTPException(503, '请重启最新版软件后连接手机')
        return value

    @app.get('/api/mobile/status')
    async def status(x_studyforge_desktop_token: str | None = Header(default=None)):
        value = manager(x_studyforge_desktop_token)
        await value.refresh_network()
        return value.status()

    @app.post('/api/mobile/network-refresh')
    async def network_refresh(x_studyforge_desktop_token: str | None = Header(default=None)):
        value = manager(x_studyforge_desktop_token)
        await value.refresh_network(force=True)
        return value.status()

    @app.put('/api/mobile/preferences')
    async def preferences(value: ConnectionPreferences, x_studyforge_desktop_token: str | None = Header(default=None)):
        return manager(x_studyforge_desktop_token).save_preferences(value)

    @app.post('/api/mobile/start')
    async def start(value: StartIn, x_studyforge_desktop_token: str | None = Header(default=None)):
        try:
            return await manager(x_studyforge_desktop_token).start(value)
        except (ValueError, OSError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/mobile/stop')
    async def stop(x_studyforge_desktop_token: str | None = Header(default=None)):
        return await manager(x_studyforge_desktop_token).stop()

    @app.post('/api/mobile/pairing')
    async def code(x_studyforge_desktop_token: str | None = Header(default=None)):
        value = manager(x_studyforge_desktop_token)
        if not value.status()['running']:
            raise HTTPException(409, '请先启用手机连接')
        value.new_code()
        return value.status()

    @app.post('/api/mobile/devices/{ident}/approve')
    async def approve(ident: str, value: PairDecision, x_studyforge_desktop_token: str | None = Header(default=None)):
        return manager(x_studyforge_desktop_token).decide(ident, value.approved)

    @app.delete('/api/mobile/devices/{ident}')
    async def revoke(ident: str, x_studyforge_desktop_token: str | None = Header(default=None)):
        return await manager(x_studyforge_desktop_token).revoke(ident)

    @app.get('/api/mobile/certificate')
    async def certificate(x_studyforge_desktop_token: str | None = Header(default=None)):
        value = manager(x_studyforge_desktop_token)
        if not value.tls:
            raise HTTPException(409, '请先启用手机连接')
        return {'data': base64.b64encode(Path(value.tls['ca']).read_bytes()).decode(), 'fingerprint': value.tls['fingerprint']}

    @app.get('/api/mobile/qr')
    async def qr(address: str, x_studyforge_desktop_token: str | None = Header(default=None)):
        value = manager(x_studyforge_desktop_token)
        if address not in value.addresses or not value.status()['running']:
            raise HTTPException(400, '连接地址不可用')
        import qrcode
        import qrcode.image.svg
        import io
        url = f'https://{address}:{value.port}/'
        if value.code and time.monotonic() < value.code_expires:
            url += '#pair=' + value.code
        result = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, border=3)
        buffer = io.BytesIO()
        result.save(buffer)
        return {'svg': buffer.getvalue().decode('utf-8'), 'url': url}
