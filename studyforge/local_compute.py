"""Share native inference models and keep their CPU/RAM separate from cloud work."""
from __future__ import annotations

import gc
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

HEAVY_SUFFIXES = {'.pdf', '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif',
                  '.mp4', '.mov', '.mkv', '.webm', '.avi', '.mp3', '.wav', '.m4a',
                  '.ogg', '.flac', '.aac'}
IDLE_SECONDS = 120
_lock = threading.RLock()
_models = {}
_timer = None
_last_used = 0.0


def cpu_threads():
    # Leave capacity for Chromium input, scrolling, decoding and the OS.
    return max(1, min(4, (os.cpu_count() or 2) // 2))


def requires_local_compute(path):
    return Path(path).suffix.lower() in HEAVY_SUFFIXES


async def run_source_io(operation, *args, paths, runtime=None, label='解析资料', **kwargs):
    from .scheduling import run_local, run_owned_io
    if any(requires_local_compute(path) for path in paths):
        return await run_local('media', operation, *args, runtime=runtime, label=label, **kwargs)
    return await run_owned_io(operation, *args, **kwargs)


def clear_idle_models():
    """Never evict a native engine while its generator/call still uses it."""
    global _timer
    with _lock:
        if time.monotonic() - _last_used < IDLE_SECONDS:
            return
        _models.clear()
        _timer = None
    gc.collect()


@contextmanager
def inference_slot():
    """One shared OCR/ASR inference, including direct tools and PDF page selections."""
    global _timer, _last_used
    with _lock:
        if _timer:
            _timer.cancel()
            _timer = None
        try:
            yield
        finally:
            _last_used = time.monotonic()
            _timer = threading.Timer(IDLE_SECONDS, clear_idle_models)
            _timer.daemon = True
            _timer.start()


def cached_model(family, name, factory):
    # Caller holds inference_slot for the whole inference, not only initialization.
    with _lock:
        entry = _models.get(family)
        if entry and entry[0] == name:
            return entry[1]
        # Local inference is serialized. Switching from ASR to OCR (or changing
        # the chosen model) must release the idle engine before loading the next,
        # rather than retaining the ASR weights throughout a long OCR phase.
        if _models:
            _models.clear()
            entry = None
            gc.collect()
        model = factory()
        _models[family] = (name, model)
        return model
