"""Keep original files and extracted images still used by another source."""
import os
from pathlib import Path

from .db import connect


def _key(value):
    if not isinstance(value,(str,Path)) or str(value).startswith(('http://','https://')):return None
    try:return os.path.normcase(str(Path(value).resolve()))
    except (ValueError,OSError):return None


def referenced_elsewhere(source_id, candidates):
    wanted={key for value in candidates if (key:=_key(value)) is not None};shared=set()
    if not wanted:return shared
    # Stream only path values, never load each source's full text into Python.
    with connect() as database:
        for row in database.execute('SELECT original_path FROM sources WHERE id!=?',(source_id,)):
            key=_key(row['original_path'])
            if key in wanted:shared.add(key)
        data="CASE WHEN item.type='object' THEN item.value ELSE '{}' END"
        for row in database.execute("SELECT json_extract("+data+",'$.meta.image_path') AS path "
            "FROM sources s,json_each(CASE WHEN json_valid(s.segments_json) THEN s.segments_json ELSE '[]' END) item "
            "WHERE s.id!=? AND json_type("+data+",'$.meta.image_path')='text'",(source_id,)):
            key=_key(row['path'])
            if key in wanted:shared.add(key)
    return shared


def shared(path, references):
    return _key(path) in references
