"""Permanent removal of recycled projects, with transactional records and owned files."""
from __future__ import annotations

import hashlib
import functools
import json
import re
import shutil
import threading
from pathlib import Path

from .config import data_dir
from .db import connect, j, uid, unj

_purge_lock = threading.RLock()


def _serialized(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        with _purge_lock:
            return function(*args, **kwargs)
    return wrapped


class PurgeConflict(ValueError):
    pass


def _quoted(name):
    return '"' + name.replace('"', '""') + '"'


def _project(database, project_id):
    row = database.execute('SELECT p.* FROM projects p JOIN removed_projects r ON r.project_id=p.id WHERE p.id=?', (project_id,)).fetchone()
    if not row:
        raise LookupError('项目不在回收站中；只能彻底删除已移入回收站的项目')
    return dict(row)


def _rows(database, table, project_id):
    return [dict(row) for row in database.execute(f'SELECT * FROM {_quoted(table)} WHERE project_id=?', (project_id,))]


def _paths(value):
    """Only recorded file fields are candidates, never paths mentioned in prose."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {'original_path', 'path', 'image_path', 'review_path', 'workspace', 'file_path'} and isinstance(item, str) and item:
                yield Path(item)
            elif isinstance(item, (dict, list)):
                yield from _paths(item)
    elif isinstance(value, list):
        for item in value:
            yield from _paths(item)


def _record_paths(row):
    yield from _paths(row)
    for key, value in row.items():
        if (key.endswith('_json') or key == 'response') and isinstance(value, str):
            try:
                yield from _paths(json.loads(value))
            except (ValueError, TypeError):
                pass


def _linked(path):
    return path.is_symlink() or path.is_junction()


def _tree(path):
    """Walk without descending through symbolic links or Windows junctions."""
    pending = [path]
    while pending:
        folder = pending.pop()
        for item in folder.iterdir():
            yield item
            if item.is_dir() and not _linked(item): pending.append(item)


def _safe_owned(path):
    root = data_dir()
    owned = [root / name for name in ('files', 'artifacts', 'tmp', 'agent-workspace', 'assessment-workspace')]
    path = path.absolute()
    for folder in owned:
        if path != folder and path.is_relative_to(folder):
            if any(_linked(item) for item in [path, *path.parents] if item.is_relative_to(root)):
                return None
            resolved = path.resolve()
            if not resolved.is_relative_to(folder) or resolved == folder:
                return None
            if path.is_dir() and any(_linked(item) for item in _tree(path)):
                return None
            return resolved
    return None


def _manifest(database, project_id):
    tables = ('sources', 'artifacts', 'agent_assets', 'agent_workspaces', 'agent_tool_events', 'jobs', 'homework_attempts')
    candidates, protected, external = set(), set(), set()
    for table in tables:
        for row in database.execute(f'SELECT * FROM {_quoted(table)}'):
            row = dict(row)
            for path in _record_paths(row):
                if row['project_id'] == project_id:
                    safe = _safe_owned(path)
                    if safe and safe.exists(): candidates.add(safe)
                    elif path.is_file(): external.add(str(path))
                else:
                    protected.add(path.resolve())
    # Steps can contain private review paths; they belong to the job, not to prose.
    for row in database.execute('SELECT s.*,j.project_id FROM generation_steps s JOIN jobs j ON j.id=s.job_id'):
        for path in _record_paths(dict(row)):
            if row['project_id'] == project_id:
                safe = _safe_owned(path)
                if safe and safe.exists(): candidates.add(safe)
            else: protected.add(path.resolve())
    for row in database.execute('SELECT o.path,j.project_id FROM job_file_outputs o JOIN jobs j ON j.id=o.job_id'):
        path = Path(row['path'])
        if row['project_id'] != project_id: protected.add(path.resolve()); continue
        safe = _safe_owned(path)
        if safe and safe.exists(): candidates.add(safe)
        parent = path.resolve().parent
        if parent.parent == data_dir()/'tmp'/'downloads' and re.fullmatch('[a-f0-9]{32}', parent.name):
            safe = _safe_owned(parent)
            if safe and safe.exists(): candidates.add(safe)
    # A cancelled export may create its file before an artifact was registered.
    for table in ('jobs', 'exercise_sets', 'sources'):
        for row in _rows(database, table, project_id):
            if not re.fullmatch('[a-f0-9]{32}', row['id']): continue
            patterns = [(data_dir()/'artifacts', row['id']+'-*'), (data_dir()/'artifacts'/'private-reviews', row['id']+'-*')]
            if table == 'sources': patterns.append((data_dir()/'files', row['id']+'.*'))
            for folder, pattern in patterns:
                if not folder.is_dir() or _linked(folder): continue
                for path in folder.glob(pattern):
                    safe = _safe_owned(path)
                    if safe and safe.exists(): candidates.add(safe)
    for source in database.execute('SELECT * FROM sources'):
        original = Path(source['original_path']).resolve()
        companions = candidates if source['project_id'] == project_id else protected
        for suffix in (original.suffix + '.video.json', '.frames'):
            safe = _safe_owned(original.with_suffix(suffix))
            if safe and safe.exists(): companions.add(safe)
        if original.is_file():
            stat = original.stat()
            token = hashlib.sha256(f'{original}\0{stat.st_size}\0{stat.st_mtime_ns}'.encode()).hexdigest()[:24]
            for kind in ('frames', 'audio', 'pdf-pages', 'docx-images', 'pptx-images', 'notebook', 'anki-images'):
                safe = _safe_owned(data_dir() / 'tmp' / f'{kind}-{token}')
                if safe and safe.exists(): companions.add(safe)
    # Legacy chat/job folders predate the workspace registry.
    keys = [row['scope_key'] for row in _rows(database, 'agent_dialogue_scopes', project_id)]
    for chat in _rows(database, 'conversations', project_id):
        keys.append(f"chat:{project_id}:{chat['id']}")
    for job in _rows(database, 'jobs', project_id):
        conversation_id = unj(job['payload_json'], {}).get('conversation_id')
        keys.append(f"job:{project_id}:{conversation_id}:{job['id']}:main")
    for key in keys:
        safe = _safe_owned(data_dir() / 'agent-workspace' / hashlib.sha256(key.encode()).hexdigest()[:32])
        if safe and safe.exists(): candidates.add(safe)
    shared = {path for path in candidates if any(other == path or other.is_relative_to(path) or path.is_relative_to(other) for other in protected)}
    candidates -= shared
    # Move directory parents once, preserving the whole original for rollback.
    paths = sorted((path for path in candidates if not any(parent in candidates for parent in path.parents)), key=str)
    file_count, byte_count = 0, 0
    for path in paths:
        for item in [path] if path.is_file() else _tree(path):
            if item.is_file(): file_count += 1; byte_count += item.stat().st_size
    return paths, {'file_count': file_count, 'file_bytes': byte_count,
                   'preserved_external_files': len(external), 'preserved_shared_paths': len(shared)}


def impact(project_id):
    with connect() as database:
        project = _project(database, project_id)
        _, files = _manifest(database, project_id)
        counts = {key: database.execute(f'SELECT COUNT(*) FROM {table} WHERE project_id=?', (project_id,)).fetchone()[0]
                  for key, table in [('conversation_count', 'conversations'), ('source_count', 'sources'),
                                     ('artifact_count', 'artifacts'), ('task_count', 'jobs'), ('profile_event_count', 'learning_events')]}
        counts['message_count'] = database.execute('SELECT COUNT(*) FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE project_id=?)', (project_id,)).fetchone()[0]
        return {'id': project_id, 'name': project['name'], **counts, **files}


def _deletion_rows(database, project_id):
    """Follow database ownership and FK dependents, including future child tables."""
    database.execute('CREATE TEMP TABLE sf_purge_rows(table_name TEXT,row_id INTEGER,PRIMARY KEY(table_name,row_id))')
    tables = [row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    columns = {table: {row[1] for row in database.execute(f'PRAGMA table_info({_quoted(table)})')} for table in tables}
    for table in tables:
        if 'project_id' in columns[table]:
            database.execute(f'INSERT OR IGNORE INTO sf_purge_rows SELECT ?,rowid FROM {_quoted(table)} WHERE project_id=?', (table, project_id))
    database.execute('INSERT INTO sf_purge_rows SELECT ?,rowid FROM projects WHERE id=?', ('projects', project_id))
    for table in ('agent_approvals', 'execution_spans'):
        database.execute(f'INSERT OR IGNORE INTO sf_purge_rows SELECT ?,rowid FROM {table} WHERE '
                         'conversation_id IN (SELECT id FROM conversations WHERE project_id=?) OR job_id IN (SELECT id FROM jobs WHERE project_id=?)', (table, project_id, project_id))
    database.execute("INSERT OR IGNORE INTO sf_purge_rows SELECT 'desktop_notices',rowid FROM desktop_notices WHERE json_extract(target_json,'$.project_id')=?", (project_id,))
    database.execute("INSERT OR IGNORE INTO sf_purge_rows SELECT 'codex_agent_threads',rowid FROM codex_agent_threads WHERE thread_id IN (SELECT remote_thread_id FROM conversations WHERE project_id=?)", (project_id,))
    relations = [(table, row) for table in tables for row in database.execute(f'PRAGMA foreign_key_list({_quoted(table)})')]
    owners = {'artifact_sources': 'artifact_id', 'generation_dialogue_outputs': 'job_id',
              'practice_repair_links': 'parent_set_id', 'practice_progression_links': 'parent_set_id',
              'review_items': 'origin_set_id'}
    while True:
        before = database.total_changes
        for table, fk in relations:
            parent, column, target = fk['table'], fk['from'], fk['to']
            if table in owners and column != owners[table]: continue
            if parent not in columns or target is None:
                raise PurgeConflict('数据关联结构无法核实，项目未删除')
            scope = ' AND (child.project_id IS NULL OR child.project_id=?)' if 'project_id' in columns[table] else ''
            params = (table, parent, project_id) if scope else (table, parent)
            database.execute(f'INSERT OR IGNORE INTO sf_purge_rows SELECT ?,child.rowid FROM {_quoted(table)} child '
                             f'JOIN {_quoted(parent)} parent ON child.{_quoted(column)}=parent.{_quoted(target)} '
                             'JOIN sf_purge_rows doomed ON doomed.table_name=? AND doomed.row_id=parent.rowid' + scope, params)
        if database.total_changes == before: break
    # Do not let an automatic FK cascade silently delete another project's rows.
    for table, fk in relations:
        if fk['on_delete'] in ('SET NULL', 'SET DEFAULT'): continue
        conflict = database.execute(f'SELECT 1 FROM {_quoted(table)} child JOIN {_quoted(fk["table"])} parent '
                    f'ON child.{_quoted(fk["from"])}=parent.{_quoted(fk["to"])} '
                    'JOIN sf_purge_rows doomed ON doomed.table_name=? AND doomed.row_id=parent.rowid '
                    'WHERE NOT EXISTS (SELECT 1 FROM sf_purge_rows included WHERE included.table_name=? AND included.row_id=child.rowid) LIMIT 1', (fk['table'], table)).fetchone()
        if conflict: raise PurgeConflict('存在需要先解除的跨项目引用，项目和文件均未删除')
    return tables


def _discard_staging(staging):
    if _safe_owned(staging) != staging: raise OSError('清理目录无法核实')
    # Retain the recovery manifest if deleting an occupied child fails.
    manifest = staging / 'manifest.json'
    for item in staging.iterdir():
        if item == manifest: continue
        if item.is_dir(): shutil.rmtree(item)
        else: item.unlink()
    manifest.unlink(missing_ok=True)
    staging.rmdir()


@_serialized
def purge(project_id, confirmation_name):
    """Stage deletions under the application root; a DB failure restores files."""
    moved, staging, committed = [], None, False
    try:
        with connect() as database:
            database.execute('BEGIN IMMEDIATE')
            project = _project(database, project_id)
            if confirmation_name != project['name']:
                raise ValueError('项目名称未匹配，请输入当前项目名称确认彻底删除')
            from .scheduling import local_work_pending
            if local_work_pending(project_id):
                raise PurgeConflict('本项目的本地文件处理仍在结束中；待其结束后再彻底删除，避免遗留文件')
            if database.execute("SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running','pausing','paused')", (project_id,)).fetchone():
                raise PurgeConflict('关联任务仍在停止中，请稍后再彻底删除')
            paths, result = _manifest(database, project_id)
            tables = _deletion_rows(database, project_id)
            topics = {unj(row['payload_json'], {}).get('topic') for row in _rows(database, 'learning_events', project_id)} - {None}
            event_ids = {row['id'] for row in _rows(database, 'learning_events', project_id)}
            for run in database.execute('SELECT id,event_ids_json,status FROM learning_runs').fetchall():
                ids = unj(run['event_ids_json'], [])
                if event_ids.intersection(ids):
                    remaining = [eid for eid in ids if eid not in event_ids]
                    database.execute('UPDATE learning_runs SET event_ids_json=?,status=?,error=NULL WHERE id=?',
                                     (j(remaining), 'interrupted' if run['status'] == 'running' else run['status'], run['id']))
            preferences = database.execute("SELECT value FROM workspace_state WHERE key='navigation_preferences'").fetchone()
            if preferences:
                value = unj(preferences['value'], {})
                value['expanded'] = [pid for pid in value.get('expanded', []) if pid != project_id]
                database.execute("UPDATE workspace_state SET value=? WHERE key='navigation_preferences'", (j(value),))
            database.execute("DELETE FROM workspace_state WHERE key='active_project' AND value=?", (project_id,))
            database.execute("INSERT INTO workspace_state VALUES ('profile_epoch',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (uid(),))
            database.execute('PRAGMA defer_foreign_keys=ON')
            for table in tables:
                database.execute(f'DELETE FROM {_quoted(table)} WHERE rowid IN (SELECT row_id FROM sf_purge_rows WHERE table_name=?)', (table,))
            for topic in topics:
                # The old aggregate must never resurrect evidence deleted with the project.
                if not database.execute("SELECT 1 FROM learning_events WHERE json_extract(payload_json,'$.topic')=? LIMIT 1", (topic,)).fetchone():
                    database.execute('DELETE FROM mastery WHERE topic=?', (topic,))
                    database.execute('DELETE FROM legacy_profile_exclusions WHERE topic=?', (topic,))
            if database.execute('PRAGMA foreign_key_check').fetchone():
                raise PurgeConflict('存在需要先解除的跨项目引用，项目和文件均未删除')
            if paths:
                staging = data_dir() / 'tmp' / ('project-purge-' + uid())
                if _safe_owned(staging) != staging: raise PurgeConflict('文件清理目录不安全，项目未删除')
                staging.mkdir(parents=True)
                (staging / 'manifest.json').write_text(j({'project_id': project_id,
                    'paths': [str(path) for path in paths]}), encoding='utf-8')
                for index, path in enumerate(paths):
                    if _safe_owned(path) != path: raise PurgeConflict('文件路径已变化，项目未删除')
                    destination = staging / str(index)
                    path.replace(destination)
                    moved.append((path, destination))
        committed = True
    except BaseException:
        for path, destination in reversed(moved):
            if _safe_owned(path) != path or path.exists(): raise OSError('原路径已变化，文件保留在恢复目录中，不能覆盖')
            destination.replace(path)
        if staging and staging.exists(): _discard_staging(staging)
        raise
    pending = False
    if committed and staging:
        try: _discard_staging(staging)
        except OSError: pending = True  # Opening the recycle bin retries only these owned folders.
    if committed:
        from .ai import clear_source_digest_cache
        clear_source_digest_cache(project_id=project_id)
    return {'id': project_id, 'deleted': True, **result, 'cleanup_pending': pending,
            'note': '项目及关联记录已彻底删除。' + ('部分文件被占用，下次打开回收站时重试清理。' if pending else '软件保存的独占文件副本已清理。') + '外部原文件和其他项目仍使用的文件保留。'}


@_serialized
def retry_cleanup():
    """Retry committed quarantine folders; never traverse a link or another folder."""
    root = data_dir() / 'tmp'
    if not root.is_dir() or _linked(root): return
    for folder in root.glob('project-purge-*'):
        if len(folder.name) != len('project-purge-') + 32 or any(c not in '0123456789abcdef' for c in folder.name[len('project-purge-'):]): continue
        if _safe_owned(folder) != folder: continue
        try:
            manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
            with connect() as database:
                exists = database.execute('SELECT 1 FROM projects WHERE id=?', (manifest['project_id'],)).fetchone()
            if exists:
                # A crash before commit leaves the original records. Recover their files.
                for index, name in enumerate(manifest['paths']):
                    original, staged = Path(name), folder / str(index)
                    if not staged.exists(): continue
                    if _safe_owned(original) != original or original.exists(): raise OSError('原路径不能安全恢复')
                    original.parent.mkdir(parents=True, exist_ok=True)
                    staged.replace(original)
            _discard_staging(folder)
        except (OSError, ValueError, KeyError, TypeError): pass


@_serialized
def cleanup_status():
    root = data_dir() / 'tmp'
    if not root.is_dir() or _linked(root): return {'pending_count': 0}
    pending = sum(1 for folder in root.glob('project-purge-*')
                  if len(folder.name) == len('project-purge-') + 32 and
                  all(c in '0123456789abcdef' for c in folder.name[len('project-purge-'):]) and _safe_owned(folder) == folder)
    return {'pending_count': pending}
