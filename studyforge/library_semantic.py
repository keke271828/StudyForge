"""Local, resumable semantic indexing of already authorized, completed pages.

No generation model, unselected extraction, chat memory, or online embeddings.
The pinned ONNX model is downloaded only by an explicit setup action.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import threading
import time
from pathlib import Path

from .config import data_dir
from .db import connect, execute, j, now, one, unj

REPO = 'Xenova/multilingual-e5-small'
REVISION = '761b726dd34fb83930e26aab4e9ac3899aa1fa78'
MODEL_KEY = 'e5-multilingual-int8-' + REVISION[:12] + '-192-prefix-mean-v1'
FILES = {
    'model.onnx': ('onnx/model_quantized.onnx', 118308185, 'f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193'),
    'tokenizer.json': ('tokenizer.json', 17082730, '0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39'),
}
_lock = threading.Lock()
_engine = None
_verified = {}
_last_used = 0.0


def model_root():
    custom = os.environ.get('STUDYFORGE_SEMANTIC_MODEL_DIR')
    if custom: return Path(custom).resolve()
    bundled = Path(__file__).resolve().parents[1] / 'resources' / 'library-semantic-e5'
    if not getattr(sys, 'frozen', False) and (all((bundled/name).is_file() for name in FILES) or not os.environ.get('STUDYFORGE_DATA_DIR')):
        return bundled
    return data_dir() / 'models' / 'library-semantic'


def enabled():
    row = one("SELECT value FROM workspace_state WHERE key='library_semantic_enabled'")
    return row is not None and row['value'] == 'true'


def set_enabled(value):
    execute("INSERT INTO workspace_state VALUES ('library_semantic_enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ('true' if value else 'false',))
    if not value: release_idle(force=True)
    return status()


def model_ready():
    from .materials import file_sha256
    root = model_root()
    for name, (_, size, sha) in FILES.items():
        path = root / name
        if not path.is_file(): return False
        stat = path.stat()
        if stat.st_size != size: return False
        identity = (str(path), stat.st_size, stat.st_mtime_ns)
        if identity not in _verified:
            if file_sha256(path) != sha: return False
            _verified[identity] = True
    return True


def download_state(value=None):
    if value is not None:
        execute("INSERT INTO workspace_state VALUES ('library_semantic_download',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (j(value),))
    row = one("SELECT value FROM workspace_state WHERE key='library_semantic_download'")
    return unj(row['value'], {}) if row else {}


def download_model(cancel=None):
    """Streaming fixed-revision files; verify size/hash before publishing."""
    import httpx
    from .materials import file_sha256
    root = model_root(); root.mkdir(parents=True, exist_ok=True)
    total = sum(f[1] for f in FILES.values()); complete = 0
    def consume(partial,size,status,headers,chunks):
        offset=partial.stat().st_size if partial.is_file() else 0
        if offset and status!=206:offset=0
        if offset and not headers.get('Content-Range','').startswith(f'bytes {offset}-'):
            raise ValueError('模型下载续传范围不正确，请重试')
        with partial.open('ab' if offset else 'wb') as stream:
            for chunk in chunks:
                if cancel and cancel.is_set():raise InterruptedError('下载已取消，已下载部分保留供续传')
                offset+=len(chunk)
                if offset>size:raise ValueError('模型下载长度不正确')
                stream.write(chunk)
                download_state({'state':'downloading','progress':int(100*(complete+offset)/total),'file':name})
    try:
        with httpx.Client(follow_redirects=True, timeout=20, trust_env=True) as client:
            for name, (remote, size, sha) in FILES.items():
                path = root / name
                if path.is_file() and path.stat().st_size == size and file_sha256(path) == sha:
                    complete += size; continue
                partial = path.with_suffix(path.suffix + '.partial')
                offset = partial.stat().st_size if partial.is_file() else 0
                if offset > size: partial.unlink(); offset = 0
                if offset < size:
                    url = f'https://huggingface.co/{REPO}/resolve/{REVISION}/{remote}'
                    try:
                        with client.stream('GET', url, headers={'Range': f'bytes={offset}-'} if offset else {}) as response:
                            response.raise_for_status()
                            consume(partial,size,response.status_code,response.headers,response.iter_bytes(1024*1024))
                    except httpx.TransportError:
                        # The standard-library stack also honors system trust
                        # and proxy settings. Never disable TLS verification.
                        from urllib.request import Request, urlopen
                        offset=partial.stat().st_size if partial.is_file() else 0
                        if cancel and cancel.is_set():raise InterruptedError('下载已取消，已下载部分保留供续传')
                        with urlopen(Request(url,headers={'Range':f'bytes={offset}-'} if offset else {}),timeout=30) as response:
                            consume(partial,size,response.status,response.headers,iter(lambda:response.read(1024*1024),b''))
                if partial.stat().st_size != size or file_sha256(partial) != sha:
                    partial.unlink(missing_ok=True)
                    raise ValueError('模型校验未通过，请重试下载')
                partial.replace(path); complete += size
        download_state({'state': 'ready', 'progress': 100})
    except InterruptedError as exc:
        download_state({'state': 'cancelled', 'error': str(exc)})
    except Exception as exc:
        download_state({'state': 'failed', 'error': type(exc).__name__ + ': ' + str(exc)})
        raise


class Encoder:
    def __init__(self):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2; options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        self.session = ort.InferenceSession(str(model_root() / 'model.onnx'), options, providers=['CPUExecutionProvider'])
        self.tokenizer = Tokenizer.from_file(str(model_root() / 'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=192)
        pad = self.tokenizer.token_to_id('<pad>')
        self.tokenizer.enable_padding(pad_id=pad if pad is not None else 0, pad_token='<pad>' if pad is not None else '[PAD]')
        self.root = model_root()

    def passages(self, row):
        # Calls are serialized by _lock. Sharing this tokenizer avoids keeping
        # two copies of its large multilingual vocabulary and merge tables.
        self.tokenizer.enable_truncation(max_length=184,stride=24)
        result = []
        for kind, text in [('original', row['original_text']), ('visual', row['visual_text'])]:
            if not text.strip(): continue
            encoding = self.tokenizer.encode(text)
            for part in [encoding, *encoding.overflowing]:
                offsets = [offset for offset, special in zip(part.offsets, part.special_tokens_mask) if not special and offset[1] > offset[0]]
                if not offsets: continue
                start, end = min(x[0] for x in offsets), max(x[1] for x in offsets)
                result.append((kind, start, end, text[start:end]))
        return result

    def encode(self, texts, query=False):
        import numpy as np
        self.tokenizer.enable_truncation(max_length=192)
        prefix='query: ' if query else 'passage: '
        parts = self.tokenizer.encode_batch([prefix+text for text in texts])
        inputs = {'input_ids': np.asarray([p.ids for p in parts], dtype=np.int64),
                  'attention_mask': np.asarray([p.attention_mask for p in parts], dtype=np.int64),
                  'token_type_ids': np.asarray([p.type_ids for p in parts], dtype=np.int64)}
        accepted = {x.name for x in self.session.get_inputs()}
        tokens = self.session.run(None, {k: v for k, v in inputs.items() if k in accepted})[0]
        mask = inputs['attention_mask'][..., None]
        pooled = (tokens * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
        vectors = pooled / np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
        return vectors.astype('<f4')


def encoder():
    global _engine, _last_used
    if not model_ready(): raise ValueError('本地语义模型尚未安装或校验未通过')
    if _engine is None or _engine.root != model_root(): _engine = Encoder()
    _last_used = time.monotonic()
    return _engine


def release_idle(force=False):
    global _engine
    if _lock.acquire(blocking=False):
        try:
            if force or time.monotonic() - _last_used > 30: _engine = None
        finally: _lock.release()


def eligible():
    from .library import eligible_readings
    return eligible_readings(metadata_only=True)[2]


def create_eligible(db, ids):
    db.execute('CREATE TEMP TABLE semantic_eligible(id TEXT PRIMARY KEY)')
    db.executemany('INSERT INTO semantic_eligible VALUES (?)', ((ident,) for ident in ids))


def status():
    readings = eligible(); ids = [r['id'] for r in readings.values()]
    with connect() as db:
        create_eligible(db, ids)
        counts = db.execute('SELECT COUNT(*) total,SUM(COALESCE(p.done,0)) done FROM library_chunks c JOIN semantic_eligible e ON e.id=c.reading_id '
                            'LEFT JOIN library_semantic_pages p ON p.reading_id=c.reading_id AND p.page=c.page AND p.model_key=?', (MODEL_KEY,)).fetchone()
    return {'enabled': enabled(), 'model_ready': model_ready(), 'model': REPO, 'download_bytes': sum(f[1] for f in FILES.values()),
            'indexed_pages': counts['done'] or 0, 'total_pages': counts['total'], 'download': download_state(),
            'error': (one("SELECT value FROM workspace_state WHERE key='library_semantic_error'") or {}).get('value', '')}


def index_step():
    """One small persisted batch; never extracts a page or marks a node read."""
    if not enabled() or not model_ready(): return False
    readings = eligible()
    with connect() as db:
        create_eligible(db, [r['id'] for r in readings.values()])
        row = db.execute('SELECT c.*,COALESCE(p.next_ordinal,0) next_ordinal FROM library_chunks c JOIN semantic_eligible e ON e.id=c.reading_id '
                         'LEFT JOIN library_semantic_pages p ON p.reading_id=c.reading_id AND p.page=c.page AND p.model_key=? '
                         'WHERE COALESCE(p.done,0)=0 ORDER BY c.reading_id,c.page LIMIT 1', (MODEL_KEY,)).fetchone()
        if row is None: return False
        row = dict(row)
    digest = hashlib.sha256(j([row['original_text'], row['visual_text']]).encode()).hexdigest()
    with _lock:
        model = encoder(); passages = model.passages(row)
        saved = one('SELECT * FROM library_semantic_pages WHERE reading_id=? AND page=? AND model_key=?', (row['reading_id'], row['page'], MODEL_KEY))
        start = saved['next_ordinal'] if saved and saved['text_hash'] == digest else 0
        batch = passages[start:start+4]
        vectors = model.encode([p[3] for p in batch]) if batch else []
    with connect() as db:
        if not start:
            db.execute('DELETE FROM library_embeddings WHERE reading_id=? AND page=? AND model_key=?', (row['reading_id'], row['page'], MODEL_KEY))
        for ordinal, ((kind, begin, end, text), vector) in enumerate(zip(batch, vectors), start):
            db.execute('INSERT OR REPLACE INTO library_embeddings VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (row['reading_id'], MODEL_KEY, row['page'], ordinal, kind, begin, end, hashlib.sha256(text.encode()).hexdigest(), len(vector), vector.tobytes()))
        next_ordinal = start + len(batch)
        db.execute('INSERT OR REPLACE INTO library_semantic_pages VALUES (?,?,?,?,?,?,?)',
                   (row['reading_id'], row['page'], MODEL_KEY, digest, next_ordinal, int(next_ordinal >= len(passages)), now()))
        db.execute("DELETE FROM workspace_state WHERE key='library_semantic_error'")
    return True


def matches(query, readings, limit=24):
    """Return advisory passage matches only within current valid reading IDs."""
    import numpy as np
    if not enabled() or not model_ready() or not readings: return [], 'unavailable'
    if not _lock.acquire(timeout=1.5): return [], 'busy'
    try:
        model = encoder()
        query_parts = model.passages({'original_text': query, 'visual_text': ''})
        if not query_parts: return [], 'no_match'
        vectors = model.encode([p[3] for p in query_parts],query=True)
    except Exception: return [], 'unavailable'
    finally: _lock.release()
    from .library_ranking import PassagePool
    pool = PassagePool(limit)
    with connect() as db:
        create_eligible(db, [r['id'] for r in readings.values()])
        rows = db.execute('SELECT v.* FROM library_embeddings v JOIN semantic_eligible e ON e.id=v.reading_id '
                          'JOIN library_semantic_pages p ON p.reading_id=v.reading_id AND p.page=v.page AND p.model_key=v.model_key '
                          'WHERE v.model_key=? AND p.done=1 ORDER BY v.reading_id,v.page,v.ordinal', (MODEL_KEY,))
        while batch := rows.fetchmany(128):
            good = [r for r in batch if r['dims'] == vectors.shape[1] and len(r['vector']) == vectors.shape[1]*4]
            if not good: continue
            matrix = np.stack([np.frombuffer(r['vector'], dtype='<f4') for r in good])
            scores = (matrix @ vectors.T).max(axis=1)
            for row, score in zip(good, scores):
                if not np.isfinite(score) or score < .76: continue
                value = dict(row); value.pop('vector'); value['semantic_score'] = float(score)
                pool.add(value)
    result = pool.result()
    return result, 'used' if result else 'no_match'


class SemanticWorker:
    def __init__(self):
        self.task = None; self.download_task = None; self.cancel_download = threading.Event()

    async def start(self):
        saved = download_state()
        if saved.get('state') == 'downloading': download_state({'state': 'interrupted', 'error': '上次下载中断，可继续下载'})
        self.task = asyncio.create_task(self.loop())

    async def loop(self):
        from .scheduling import execution_scope, library_foreground_busy, run_local
        while True:
            try:
                busy = one("SELECT id FROM library_jobs WHERE status IN ('queued','running','pausing') LIMIT 1")
                if enabled() and not busy and not library_foreground_busy():
                    async with execution_scope(priority=25, background_library=True):
                        await run_local('image', index_step, label='本地书库语义索引 · 不调用云端模型')
                release_idle(force=not enabled())
            except asyncio.CancelledError: raise
            except Exception as exc:
                execute("INSERT INTO workspace_state VALUES ('library_semantic_error',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (type(exc).__name__ + ': ' + str(exc),))
                await asyncio.sleep(5)
            await asyncio.sleep(1)

    async def download(self):
        if self.download_task and not self.download_task.done(): return
        self.cancel_download.clear()
        download_state({'state': 'downloading', 'progress': 0})
        async def operation():
            from .scheduling import execution_scope, run_local
            try:
                async with execution_scope(priority=15):
                    await run_local('network', download_model, self.cancel_download, label='下载本地检索模型')
            except Exception: pass  # Public persisted status carries the error.
        self.download_task = asyncio.create_task(operation())

    async def close(self):
        self.cancel_download.set()
        if self.task: self.task.cancel(); await asyncio.gather(self.task, return_exceptions=True)
        if self.download_task: await asyncio.gather(self.download_task, return_exceptions=True)
        release_idle(force=True)
