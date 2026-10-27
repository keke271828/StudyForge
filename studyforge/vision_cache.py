"""Bounded on-disk image readings; evidence stays tied to a model and image hash."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from .db import connect, now

MAX_CHARACTERS = 4_000_000
MAX_ENTRIES = 2048
MAX_BATCH = 64
TOUCH_SECONDS = 30


def lookup(key):
    return lookup_many([key]).get(key)


def lookup_many(keys):
    """Read one small batch; recent hits need no cache write or prune pass."""
    if len(keys) > MAX_BATCH: raise ValueError('画面缓存读取批次过大')
    keys = list(dict.fromkeys(keys))
    if not keys: return {}
    with connect() as database:
        rows = database.execute('SELECT cache_key,description,accessed_at FROM source_vision_cache WHERE cache_key IN ('+
            ','.join('?' for _ in keys)+')',tuple(keys)).fetchall()
        cutoff = (datetime.now(timezone.utc)-timedelta(seconds=TOUCH_SECONDS)).isoformat()
        stale = [row['cache_key'] for row in rows if row['accessed_at'] < cutoff]
        if stale:
            database.execute('UPDATE source_vision_cache SET accessed_at=? WHERE cache_key IN ('+
                ','.join('?' for _ in stale)+')', (now(),*stale))
        return {row['cache_key']:row['description'] for row in rows}


def remember(key, description, project_id=None, source_id=None):
    return key in remember_many([dict(key=key,description=description,project_id=project_id,source_id=source_id)])


def remember_many(rows):
    if len(rows) > MAX_BATCH: raise ValueError('画面缓存保存批次过大')
    rows=[row for row in rows if isinstance(row.get('description'),str) and row['description'].strip()
          and len(row['description']) <= 32000]
    if not rows:return set()
    saved=set()
    with connect() as database:
        database.execute('BEGIN IMMEDIATE')
        stamp=now()
        for row in rows:
            project,source=row.get('project_id'),row.get('source_id')
            # Registered project sources must still exist when the image call
            # completes. Global book nodes have no project and remain reusable.
            if project and source and not database.execute('SELECT 1 FROM sources WHERE id=? AND project_id=?',(source,project)).fetchone():continue
            if project and not database.execute('SELECT 1 FROM projects WHERE id=?',(project,)).fetchone():continue
            database.execute('INSERT INTO source_vision_cache '
                '(cache_key,description,characters,accessed_at,project_id,source_id) VALUES (?,?,?,?,?,?) '
                'ON CONFLICT(cache_key) DO UPDATE SET description=excluded.description,characters=excluded.characters,'
                'accessed_at=excluded.accessed_at,project_id=excluded.project_id,source_id=excluded.source_id',
                (row['key'],row['description'],len(row['description']),stamp,project,source))
            saved.add(row['key'])
        if saved:
            database.execute('DELETE FROM source_vision_cache WHERE cache_key IN (SELECT cache_key FROM '
                '(SELECT cache_key,ROW_NUMBER() OVER (ORDER BY accessed_at DESC,cache_key) AS position,'
                'SUM(characters) OVER (ORDER BY accessed_at DESC,cache_key ROWS UNBOUNDED PRECEDING) AS total '
                'FROM source_vision_cache) WHERE position>? OR total>?)',(MAX_ENTRIES,MAX_CHARACTERS))
    return saved


def clear():
    with connect() as database:
        database.execute('DELETE FROM source_vision_cache')


def clear_source(source_id,project_id=None):
    with connect() as database:
        database.execute('DELETE FROM source_vision_cache WHERE source_id=? OR '
            '(source_id IS NULL AND (project_id=? OR project_id IS NULL))',(source_id,project_id))


def clear_project(project_id):
    with connect() as database:
        database.execute('DELETE FROM source_vision_cache WHERE project_id=? OR '
            '(project_id IS NULL AND source_id IS NULL)',(project_id,))
