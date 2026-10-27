"""Pause at safe boundaries and retain completed model steps for resumption."""
from __future__ import annotations

import asyncio
import json

from .db import execute, j, now, one, unj, update_job
from .scheduling import StepState, current_step, execution_scope, wake_schedulers
from .json_digest import sha256 as json_sha256


active_generations: dict[str, 'GenerationControl'] = {}


class GenerationControl:
    def __init__(self, job_id):
        self.job_id = job_id
        row = one('SELECT status FROM jobs WHERE id=?', (job_id,))
        self.pause_requested = row['status'] in ('pausing', 'paused')
        self.resume_event = asyncio.Event()
        if not self.pause_requested: self.resume_event.set()
        self.idle_event = asyncio.Event(); self.idle_event.set()
        self.in_flight = 0
        self.cancel_requested = False
        self.operations = set()

    def refresh_idle(self):
        working = any(not (step.waiting and not step.started) for step in self.operations)
        if working: self.idle_event.clear()
        else:
            self.idle_event.set()
            if self.pause_requested and not self.cancel_requested:
                row = one('SELECT status,progress,result_json FROM jobs WHERE id=?', (self.job_id,))
                if row and row['status'] in ('running', 'queued', 'pausing'):
                    update_job(self.job_id, 'paused', row['progress'],
                               dict(unj(row['result_json'], {}), pause_requested=True))

    def stage(self, name, progress, result=None):
        row=one('SELECT status,progress,result_json FROM jobs WHERE id=?',(self.job_id,))
        if not row or row['status'] == 'cancelled' or self.cancel_requested: return
        progress=max(progress,row['progress'])
        payload = {**unj(row['result_json'], {}), **(result or {}), 'stage': name}
        if self.pause_requested: payload['pause_requested'] = True
        update_job(self.job_id, ('paused' if self.idle_event.is_set() else 'pausing') if self.pause_requested else 'running', progress, payload)

    def pause(self):
        self.pause_requested = True
        self.resume_event.clear()
        row = one('SELECT progress,result_json FROM jobs WHERE id=?', (self.job_id,))
        update_job(self.job_id, 'pausing', row['progress'], dict(unj(row['result_json'], {}), pause_requested=True))
        self.refresh_idle()
        wake_schedulers()

    def resume(self):
        self.pause_requested = False
        row = one('SELECT progress,result_json FROM jobs WHERE id=?', (self.job_id,))
        result = unj(row['result_json'], {}); result.pop('pause_requested', None)
        update_job(self.job_id, 'running', row['progress'], result)
        self.resume_event.set()
        wake_schedulers()

    async def checkpoint(self):
        row = one('SELECT status FROM jobs WHERE id=?', (self.job_id,))
        if self.cancel_requested or not row or row['status'] == 'cancelled': raise asyncio.CancelledError()
        if self.pause_requested:
            # Parallel reviewers already in flight may finish before pausing.
            await self.idle_event.wait()
            if self.pause_requested:
                row = one('SELECT progress,result_json FROM jobs WHERE id=?', (self.job_id,))
                update_job(self.job_id, 'paused', row['progress'], dict(unj(row['result_json'], {}), pause_requested=True))
                await self.resume_event.wait()
                if self.cancel_requested: raise asyncio.CancelledError()

    async def step(self, scope, signature, operation, *, cache_response=None):
        await self.checkpoint()
        key = await asyncio.to_thread(json_sha256, [scope, signature])
        await self.checkpoint()
        cached = one('SELECT response FROM generation_steps WHERE job_id=? AND step_key=?', (self.job_id, key))
        if cached:
            response = unj(cached['response'])
        else:
            step = StepState(self)
            step.cache_key = key
            step.replay_risk = bool(one('SELECT 1 FROM generation_steps WHERE job_id=? AND step_key=?',
                                        (self.job_id,'external-effect:'+key)))
            self.operations.add(step)
            token = current_step.set(step)
            self.in_flight += 1; self.refresh_idle()
            try:
                async with execution_scope(job_id=self.job_id, label=scope):
                    response = await operation()
                if cache_response is None or cache_response(response):
                    execute('INSERT OR REPLACE INTO generation_steps VALUES (?,?,?,?)',
                            (self.job_id, key, j(response), now()))
            except Exception:
                from .task_retry import failed_step
                failed_step(step)
                raise
            finally:
                current_step.reset(token)
                self.operations.discard(step)
                self.in_flight -= 1
                self.refresh_idle()
        # Retain the completed response even when a pause arrived mid-request.
        await self.checkpoint()
        return response

    def finish(self):
        active_generations.pop(self.job_id, None)


def control_for(job_id):
    if job_id not in active_generations: active_generations[job_id] = GenerationControl(job_id)
    return active_generations[job_id]


class PausableClient:
    def __init__(self, client, control, scope='writer'):
        self.client, self.control, self.scope = client, control, scope

    def __getattr__(self, name): return getattr(self.client, name)

    async def complete(self, system, user, **kwargs):
        signature = [getattr(self.client, 'model', None), getattr(self.client, 'effort', None), system, user,
                     json.loads(json.dumps(kwargs, default=str))]
        def valid(response):
            if kwargs.get('json_mode'):
                from .ai import parse_json_response
                try: parse_json_response(response)
                except (ValueError,TypeError,AttributeError): return False
            return True
        response = await self.control.step(self.scope, signature,
            lambda: self.client.complete(system,user,**kwargs), cache_response=valid)
        if not valid(response): self.discard_response(system,user,**kwargs)
        return response

    def discard_response(self, system, user, **kwargs):
        signature = [getattr(self.client, 'model', None), getattr(self.client, 'effort', None), system, user,
                     json.loads(json.dumps(kwargs, default=str))]
        key = json_sha256([self.scope, signature])
        from .task_retry import current_attempt
        if current_attempt.get() and one('SELECT 1 FROM generation_steps WHERE job_id=? AND step_key=?',
                                         (self.control.job_id,'external-effect:'+key)):
            current_attempt.get().unsafe_replay = True
        execute('DELETE FROM generation_steps WHERE job_id=? AND step_key=?', (self.control.job_id, key))

    async def analyze_image(self, path, locator, original=''):
        from .materials import file_sha256
        from .ai import vision_identity
        signature = [vision_identity(self.client),
                     str(path), await asyncio.to_thread(file_sha256, path), locator, original]
        return await self.control.step(self.scope + ':image', signature,
                                       lambda: self.client.analyze_image(path, locator, original))

    async def analyze_images(self, frames):
        from .materials import file_sha256
        from .ai import vision_identity
        signature = [vision_identity(self.client),
                     [[frame['id'], str(frame['path']), await asyncio.to_thread(file_sha256, frame['path']),
                       frame['locator'], frame.get('ocr', '')] for frame in frames]]
        return await self.control.step(self.scope + ':images', signature,
                                       lambda: self.client.analyze_images(frames))

    def fork(self, scope=None):
        fork = getattr(self.client, 'fork', None)
        return PausableClient(fork(), self.control, scope or self.scope) if callable(fork) else PausableClient(self.client, self.control, scope or self.scope)

    async def close(self):
        close=getattr(self.client,'close',None)
        if close: await close()
