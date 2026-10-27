"""Coalesce concurrent native, objective image observations, never agent turns.

The producer stays in its own task. Cancellation publishes a retry signal;
waiters do not inherit its error, approval, dialogue or cancellation state.
Only hashes and small Futures enter the registry, not encoded image payloads.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import weakref

MAX_IMAGES = 128
MAX_SHARED_CHARACTERS = 32000
_RETRY = object()
_loops = weakref.WeakKeyDictionary()
_shared = ContextVar('native_shared_vision', default=None)


def reference(frame):
    return (str(Path(frame['path']).resolve()), frame['locator'], frame.get('ocr', ''))


@contextmanager
def track_reuse():
    values = set()
    token = _shared.set(values)
    try:
        yield values
    finally:
        _shared.reset(token)


@dataclass
class Flight:
    future: object
    step: object
    background: bool

    def blocked(self):
        # A running step may finish after pause. A not-yet-started owner must
        # not hold a foreground waiter hostage in a paused local/model queue.
        if self.step and self.step.started and getattr(self.step, 'native_image_sent', True):
            return False
        if self.step and self.step.control.pause_requested:
            return True
        if self.background:
            from .scheduling import library_foreground_busy
            return library_foreground_busy()
        return False


async def observe(client, frames, operation):
    """Return frame-ID -> text; process owned keys before waiting for overlaps.

    Called only by native image methods using fixed VISION_RULES and no tools.
    Same account, adapter, model, strength, project, locator, OCR and file bytes
    are required. Batch ID spelling/order is not an image's semantic identity.
    """
    from .ai import DeepSeekClient, vision_identity
    from .provider_clients import ServiceClient, GeminiClient
    from .config import data_dir
    from .materials import file_sha256
    from .scheduling import current_step, execution_context

    # Inheriting an image method does not prove that a custom transport is
    # tool-free. Only these reviewed native API transports may coalesce.
    if type(client) not in (DeepSeekClient, ServiceClient, GeminiClient):
        return await operation(frames)

    identifiers = [frame['id'] for frame in frames]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError('图片ID不可重复')
    step = current_step.get()
    if step and not step.owned():
        step = None
    meta = execution_context.get()
    runtime = getattr(client, 'agent_runtime', None)
    project = getattr(runtime, 'project_id', None) or meta.get('project_id')
    # Keep credential identity private and in-memory; never put keys in DB/UI.
    account = hashlib.sha256(str(getattr(client, 'key', '')).encode()).hexdigest()
    scope = [str(data_dir()), project, vision_identity(client), account]
    checksums = await asyncio.to_thread(lambda: [file_sha256(frame['path']) for frame in frames])
    keys = [hashlib.sha256(json.dumps([scope, reference(frame), checksum],
                 ensure_ascii=False, default=str).encode()).hexdigest()
            for frame, checksum in zip(frames, checksums)]
    unique = dict(zip(keys, frames))
    hashes = dict(zip(keys, checksums))
    registry = _loops.setdefault(asyncio.get_running_loop(), {})
    results = {}

    def release(key, flight, value=_RETRY):
        if registry.get(key) is flight:
            registry.pop(key, None)
        if not flight.future.done():
            flight.future.set_result(value)

    while len(results) < len(unique):
        owned, joins, untracked = {}, {}, []
        prior_waiting = step.waiting if step else False
        try:
            if step and not step.started:
                step.set_waiting(True)
                await step.control.checkpoint()
                step.set_waiting(prior_waiting)
            # No await between claims: partially overlapping batches cannot
            # each own a key and then deadlock waiting for the other producer.
            for key, frame in unique.items():
                if key in results:
                    continue
                existing = registry.get(key)
                if existing and existing.blocked():
                    if registry.get(key) is existing:
                        registry.pop(key)
                    existing = None
                if existing:
                    joins[key] = existing
                elif len(registry) < MAX_IMAGES:
                    owned[key] = Flight(asyncio.get_running_loop().create_future(), step,
                                         bool(meta.get('background_library')))
                    registry[key] = owned[key]
                else:
                    # Saturation preserves functionality and bounds coordinator
                    # memory. The normal model/image queues still bound payloads.
                    untracked.append(key)
            claimed = [*owned, *untracked]
            if claimed:
                value = await operation([unique[key] for key in claimed])
                if not isinstance(value, dict):
                    raise ValueError('逐图核对返回格式无效')
                actual = await asyncio.to_thread(lambda: {key: file_sha256(unique[key]['path']) for key in claimed})
                for key in claimed:
                    if actual[key] != hashes[key]:
                        raise ValueError('图像在分析期间变更')
                    text = value.get(unique[key]['id'])
                    # Missing IDs remain missing so the source reader can retry
                    # them singly. Oversized observations are not shared in RAM.
                    results[key] = text
                    if key in owned:
                        valid = isinstance(text, str) and bool(text.strip()) and len(text) <= MAX_SHARED_CHARACTERS
                        release(key, owned[key], text if valid else _RETRY)
            if joins:
                from .task_timing import phase
                if step and not step.started:
                    step.set_waiting(True)
                with phase('vision_wait', '等待其他任务的相同画面核对（不占模型名额）'):
                    for key, flight in joins.items():
                        while not flight.future.done() and not flight.blocked():
                            # Shield each shared Future: cancelling one waiter
                            # must not cancel the producer or other waiters.
                            if (flight.step and flight.step.started and getattr(flight.step, 'native_image_sent', True)) or (not flight.step and not flight.background):
                                await asyncio.shield(flight.future)
                                break
                            try:
                                await asyncio.wait_for(asyncio.shield(flight.future), .1)
                            except TimeoutError:
                                pass
                        value = flight.future.result() if flight.future.done() else _RETRY
                        if value is not _RETRY:
                            if await asyncio.to_thread(file_sha256, unique[key]['path']) != hashes[key]:
                                raise ValueError('图像在等待核对期间变更')
                            results[key] = value
                            tracker = _shared.get()
                            if tracker is not None:
                                tracker.add(reference(unique[key]))
        finally:
            for key, flight in owned.items():
                release(key, flight)
            if step and not step.started:
                step.set_waiting(prior_waiting)
    return {frame['id']: results[key] for frame, key in zip(frames, keys)
            if isinstance(results[key], str) and results[key].strip()}
