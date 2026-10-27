"""Bound actual provider requests, with priority, cancellation and job evidence.

The limit applies to HTTP streams / Codex turns, not to entire workflows. A
tool call releases its Codex lease before invoking another model, so a limit
of one does not deadlock an agent that asks for image understanding.
"""
from __future__ import annotations

import asyncio
import contextvars
import time
import weakref
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

DEFAULTS = {'task_parallel_enabled': True, 'model_concurrency': 2,
            'generation_parallel': False}
RESOURCE_LIMITS = {'network': 4, 'media': 1, 'image_prepare': 1, 'image': 2, 'container': 1,
                   'document_export': 1, 'source_prepare': 1}
execution_context = contextvars.ContextVar('execution_context', default={})
current_step = contextvars.ContextVar('generation_step', default=None)
_schedulers = weakref.WeakKeyDictionary()
_local_work = {}


def local_work_pending(project_id):
    return any(owner.get('project_id') == project_id for owner in tuple(_local_work.values()))


def _track_local(task, metadata, on_finish=None, *, track_outputs=True):
    """Cancelled coroutines can leave file-producing threads alive."""
    _local_work[task] = dict(metadata)
    def finished(done):
        try:
            if done.cancelled() or done.exception() or not metadata.get('job_id') or not track_outputs: return
            from pathlib import Path
            from .config import data_dir
            from .db import connect
            def paths(value):
                if isinstance(value, Path): yield value
                elif isinstance(value, dict):
                    for key, item in value.items():
                        if key in ('path', 'original_path', 'image_path', 'review_path') and isinstance(item, str) and item: yield Path(item)
                        elif isinstance(item, (dict, list)): yield from paths(item)
                elif isinstance(value, (list, tuple)):
                    for item in value: yield from paths(item)
            outputs = {str(path.resolve()) for path in paths(done.result()) if path.resolve().is_relative_to(data_dir())}
            if outputs:
                with connect() as database:
                    for path in outputs:
                        database.execute('INSERT OR IGNORE INTO job_file_outputs SELECT ?,? WHERE EXISTS '
                                         '(SELECT 1 FROM jobs WHERE id=?)', (metadata['job_id'], path, metadata['job_id']))
        finally:
            try:
                if on_finish: on_finish(done)
            finally:
                _local_work.pop(task, None)
    task.add_done_callback(finished)


async def run_owned_io(operation, *args, **kwargs):
    """Keep IO parallel and privately track its files until the actual work stops."""
    task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    _track_local(task, execution_context.get())
    return await asyncio.shield(task)


def validate_settings(value):
    for key in ('task_parallel_enabled', 'generation_parallel'):
        if key in value and type(value[key]) is not bool:
            raise ValueError(f'{key} 必须是开关值')
    if 'model_concurrency' in value and (type(value['model_concurrency']) is not int
                                        or not 1 <= value['model_concurrency'] <= 8):
        raise ValueError('同时模型请求数须为 1 到 8 之间的整数')


def configuration():
    from .ai import settings
    return DEFAULTS | {key: value for key, value in settings().items() if key in DEFAULTS}


@asynccontextmanager
async def execution_scope(**values):
    token = execution_context.set(execution_context.get() | values)
    try:
        yield
    finally:
        execution_context.reset(token)


@dataclass(eq=False)
class StepState:
    control: object
    owner: object = field(default_factory=asyncio.current_task)
    waiting: bool = False
    started: bool = False

    def owned(self):
        return self.owner is asyncio.current_task()

    def set_waiting(self, value):
        self.waiting = value
        self.control.refresh_idle()


@dataclass(eq=False)
class Request:
    future: object
    metadata: dict
    queued: float
    step: object = None
    ident: str = ''
    started: float | None = None
    segment: int = 0

    def eligible(self):
        if self.step and not self.step.started and self.step.control.pause_requested: return False
        if self.metadata.get('background_library') and library_foreground_busy(): return False
        return True


def library_foreground_busy():
    """Do not begin another book step while foreground work owns attention.

    An already-started request may finish. Paused foreground jobs do not starve
    the library, and a queued foreground model request always wins admission.
    """
    from . import learning_memory
    from .job_control import active_jobs
    from .db import one
    if learning_memory._busy: return True
    for ident, task in list(active_jobs.items()):
        if task.done(): continue
        row = one('SELECT status FROM jobs WHERE id=?', (ident,))
        if row and row['status'] in ('queued','running'): return True
    loop = asyncio.get_running_loop()
    service = _schedulers.get(loop)
    return bool(service and any(item.metadata.get('priority',0)<10
        for limiter in service.limiters.values() for item in (*limiter.active,*limiter.pending)))


class Limiter:
    def __init__(self, scheduler, resource):
        self.scheduler, self.resource = scheduler, resource
        self.pending, self.active = [], set()

    @property
    def limit(self):
        # This read-only CPU/IO gate is always one, independent of model settings.
        # Avoid synchronous settings IO on every dispatch of a cheap validation.
        if self.resource == 'source_prepare': return RESOURCE_LIMITS['source_prepare']
        prefs = configuration()
        if not prefs['task_parallel_enabled']: return 1
        return prefs['model_concurrency'] if self.resource == 'model' else RESOURCE_LIMITS[self.resource]

    def dispatch(self):
        self.pending[:] = [item for item in self.pending if not item.future.cancelled()]
        while len(self.active) < self.limit:
            candidates = [item for item in self.pending if item.eligible()]
            if not candidates: break
            item = min(candidates, key=lambda value: (value.metadata.get('priority', 0), value.queued))
            self.pending.remove(item)
            if item.future.done(): continue
            item.started = time.monotonic()
            self.active.add(item)
            if item.step:
                item.step.started = True
                item.step.set_waiting(False)
            self.scheduler.record(item, self.resource, 'running')
            item.future.set_result(None)

    async def acquire(self, item):
        item.future = asyncio.get_running_loop().create_future()
        item.queued = time.monotonic()
        if item.step and not item.step.started: item.step.set_waiting(True)
        self.pending.append(item)
        self.scheduler.record(item, self.resource, 'queued')
        self.dispatch()
        try:
            await item.future
        except BaseException:
            if item in self.pending: self.pending.remove(item)
            if item in self.active: self.active.remove(item)
            self.scheduler.record(item, self.resource, 'cancelled')
            if item.step: item.step.set_waiting(False)
            self.dispatch()
            raise

    def release(self, item, status='completed'):
        if item in self.active:
            self.active.remove(item)
            self.scheduler.record(item, self.resource, status)
            self.dispatch()


class Lease:
    def __init__(self, scheduler, resource, metadata):
        self.limiter = scheduler.limiters[resource]
        step = current_step.get()
        if step and not step.owned(): step = None
        from .db import uid
        self.request = Request(None, metadata, time.monotonic(), step, uid())
        self.suspended = False

    async def __aenter__(self):
        await self.limiter.acquire(self.request)
        return self

    async def __aexit__(self, kind, value, traceback):
        self.limiter.release(self.request, 'cancelled' if kind is asyncio.CancelledError else
                             'failed' if kind else 'completed')

    async def suspend(self):
        if not self.suspended:
            self.limiter.release(self.request, 'tool_wait')
            self.suspended = True

    async def resume(self):
        if self.suspended:
            self.request.segment += 1
            self.request.started = None
            # This is a continuation of an already running turn, even if a
            # pause arrived while its tool was executing.
            await self.limiter.acquire(self.request)
            self.suspended = False


class Scheduler:
    def __init__(self):
        self.limiters = {name: Limiter(self, name) for name in ('model', *RESOURCE_LIMITS)}
        self.path_locks = weakref.WeakValueDictionary()

    def wake(self):
        for limiter in self.limiters.values(): limiter.dispatch()

    def record(self, item, resource, status):
        from .db import execute, now, one
        meta = item.metadata
        if resource == 'source_prepare' and not meta.get('job_id'): return
        label = meta.get('label', '')
        if resource == 'model' and meta.get('stage_label'):
            label = '[' + meta['stage_label'] + '] ' + label
        if meta.get('job_id') and one('SELECT 1 FROM deleted_job_records WHERE job_id=?', (meta['job_id'],)): return
        if meta.get('conversation_id') and one('SELECT 1 FROM deleted_conversations WHERE conversation_id=?', (meta['conversation_id'],)): return
        execute('INSERT INTO execution_spans '
                '(id,segment,job_id,project_id,conversation_id,resource,provider,label,priority,status,queued_at,started_at,ended_at,duration_ms) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id,segment) DO UPDATE SET '
                'status=excluded.status,started_at=COALESCE(execution_spans.started_at,excluded.started_at),'
                'ended_at=excluded.ended_at,duration_ms=excluded.duration_ms',
                (item.ident, item.segment, meta.get('job_id'), meta.get('project_id'), meta.get('conversation_id'),
                 resource, meta.get('provider'), label, meta.get('priority', 0), status,
                 now(), now() if item.started is not None else None,
                 now() if status not in ('queued', 'running') else None,
                 round((time.monotonic() - item.started) * 1000) if item.started is not None else 0))

    def snapshot(self):
        return {name: {'active': len(limiter.active), 'queued': len(limiter.pending), 'limit': limiter.limit}
                for name, limiter in self.limiters.items()}


def scheduler():
    loop = asyncio.get_running_loop()
    if loop not in _schedulers: _schedulers[loop] = Scheduler()
    return _schedulers[loop]


def wake_schedulers():
    for loop, service in list(_schedulers.items()):
        if not loop.is_closed(): loop.call_soon_threadsafe(service.wake)


def resource_slot(resource, provider=None, runtime=None, label=None):
    meta = dict(execution_context.get())
    if runtime:
        for key in ('job_id', 'project_id', 'conversation_id'):
            value = getattr(runtime, key, None)
            if value is not None: meta[key] = value
    if provider: meta['provider'] = provider
    if label: meta['label'] = label
    return Lease(scheduler(), resource, meta)


def model_slot(provider, runtime=None):
    return resource_slot('model', provider, runtime)


async def run_local(resource, operation, *args, runtime=None, label=None, track_outputs=True, **kwargs):
    """A cancelled await must not free a slot while its local thread still runs."""
    lease = resource_slot(resource, runtime=runtime, label=label)
    await lease.__aenter__()
    task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    completion = {'status': 'completed'}
    def finish(done):
        status = 'cancelled' if done.cancelled() else 'failed' if done.exception() else completion['status']
        lease.limiter.release(lease.request, status)
    _track_local(task, lease.request.metadata, finish, track_outputs=track_outputs)
    try:
        result = await asyncio.shield(task)
    except asyncio.CancelledError:
        completion['status'] = 'cancelled'
        raise
    except BaseException:
        lease.limiter.release(lease.request, 'failed')
        raise
    else:
        lease.limiter.release(lease.request)
        return result


@asynccontextmanager
async def file_write_slot(path):
    from pathlib import Path
    key = str(Path(path).resolve()).casefold()
    locks = scheduler().path_locks
    lock = locks.get(key)
    if lock is None: locks[key] = lock = asyncio.Lock()
    async with lock: yield
