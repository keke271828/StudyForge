"""Consistent update checkpoints; original materials remain in their data directory."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3

from .config import data_dir
from .db import connect, now, uid


def create_update_backup(current_version: str, target_version: str) -> dict:
    for value in (current_version, target_version):
        if not re.fullmatch(r'\d{1,6}\.\d{1,6}\.\d{1,6}', value):
            raise ValueError('更新备份版本号无效')
    root = data_dir()
    backup_id = uid()
    folder = root / 'update-backups' / backup_id
    folder.mkdir(parents=True)
    try:
        database_file = folder / 'studyforge.sqlite3'
        with connect() as source, sqlite3.connect(database_file) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('更新前数据库备份完整性检查失败')
            counts = {table: target.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                      for table in ('projects', 'sources', 'artifacts', 'messages', 'learning_insights', 'generation_steps')}
        files = [database_file]
        settings = root / 'settings.json'
        if settings.is_file():
            # Provider secrets are in Windows Credential Manager, not copied here.
            settings_value = json.loads(settings.read_text(encoding='utf-8-sig'))
            (folder / 'settings.json').write_text(json.dumps(settings_value, ensure_ascii=False, indent=2), encoding='utf-8')
            files.append(folder / 'settings.json')
        receipt = {'id': backup_id, 'created_at': now(), 'from_version': current_version,
                   'target_version': target_version, 'data_directory': str(root), 'counts': counts,
                   'files': {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in files},
                   'scope': '数据库和设置的一致性快照；原资料、成果及工作目录保留原位置，不在此快照内'}
        (folder / 'manifest.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'id': backup_id, 'path': str(folder), 'created_at': receipt['created_at'], 'scope': receipt['scope']}
    except BaseException:
        # Leave any incomplete snapshot for diagnosis, and never mark it ready.
        (folder / 'incomplete.txt').write_text('此备份未完成，不可用于恢复。', encoding='utf-8')
        raise
