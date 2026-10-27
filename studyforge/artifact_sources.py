"""Reference generated files in their own project, without copying/reimporting."""
from pathlib import Path

from .config import artifacts_dir
from .db import connect, j, one, uid
from .parsers import PARSERS


def sync_project(project_id: str) -> None:
    # This is a cheap link operation. Full file parsing occurs only when read.
    if not one('SELECT a.id FROM artifacts a LEFT JOIN artifact_sources r ON r.artifact_id=a.id '
               'WHERE a.project_id=? AND r.artifact_id IS NULL LIMIT 1', (project_id,)):
        return
    with connect() as database:
        database.execute('BEGIN IMMEDIATE')
        rows = database.execute('SELECT a.id,a.path,a.title,a.format,a.created_at FROM artifacts a LEFT JOIN artifact_sources r '
                                'ON r.artifact_id=a.id WHERE a.project_id=? AND r.artifact_id IS NULL', (project_id,)).fetchall()
        for row in rows:
            path = Path(row['path']).resolve()
            if not path.is_relative_to(artifacts_dir().resolve()) or not path.is_file():
                continue
            readable = path.suffix.lower() in PARSERS
            source_id = uid()
            database.execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,error,created_at) '
                             'VALUES (?,?,?,?,?,?,?,?,?)',
                             (source_id, project_id, row['title'] + '.' + row['format'], path.suffix.lower(), str(path),
                              j([]), 'ready' if readable else 'error',
                              None if readable else '此成果格式暂不支持内容引用，可在成果页下载原文件', row['created_at']))
            database.execute('INSERT INTO artifact_sources VALUES (?,?)', (row['id'], source_id))


def remove_link(database, artifact_id: str) -> None:
    row = database.execute('SELECT source_id FROM artifact_sources WHERE artifact_id=?', (artifact_id,)).fetchone()
    if row:
        database.execute('DELETE FROM sources WHERE id=?', (row['source_id'],))


def rename_link(database, artifact_id: str, name: str) -> None:
    database.execute('UPDATE sources SET name=? WHERE id=(SELECT source_id FROM artifact_sources WHERE artifact_id=?)',
                     (name, artifact_id))
