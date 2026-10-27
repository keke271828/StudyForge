import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from studyforge import server
from studyforge.ai import save_settings
from studyforge.db import create_project, create_job, execute, one
from studyforge.update_backup import create_update_backup
from studyforge.generation_control import active_generations


@pytest.fixture(autouse=True)
def isolated_controls():
    # Other test cases use different databases; their pending task handles
    # cannot refer to this test's data directory.
    active_generations.clear()
    yield
    active_generations.clear()


def test_update_snapshot_preserves_rows_and_does_not_copy_or_overwrite_originals(tmp_path):
    project = create_project('更新前学习记录')
    save_settings({'deepseek_model': 'chosen-model', 'background_learning_enabled': False})
    original = tmp_path / '原文件.txt'; original.write_text('绝不覆盖原资料。', encoding='utf-8')
    job = create_job(project['id'], 'generate', {'instructions': '保留原要求'})
    receipt = create_update_backup('0.3.4', '0.3.5'); folder = Path(receipt['path'])
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    for name, checksum in manifest['files'].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == checksum
    with sqlite3.connect(folder / 'studyforge.sqlite3') as snapshot:
        assert snapshot.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert snapshot.execute('SELECT name FROM projects').fetchone()[0] == project['name']
    assert json.loads((folder / 'settings.json').read_text(encoding='utf-8'))['deepseek_model'] == 'chosen-model'
    assert one('SELECT * FROM jobs WHERE id=?', (job,))['status'] == 'queued'
    assert original.read_text(encoding='utf-8') == '绝不覆盖原资料。'
    assert not (folder / original.name).exists() and manifest['counts']['projects'] == 1


@pytest.mark.parametrize('version', ['../outside', '1.0', '1.0.0;command', '0.3.5-beta'])
def test_invalid_backup_versions_cannot_name_directories(version):
    with pytest.raises(ValueError): create_update_backup('0.3.4', version)


def test_update_exit_pauses_generation_then_takes_a_consistent_snapshot(monkeypatch):
    monkeypatch.setenv('STUDYFORGE_DESKTOP_TOKEN', 'owner')
    monkeypatch.setattr(server.app.state, 'desktop_shutdown', False)
    monkeypatch.setattr(server.app.state, 'desktop_shutdown_result', None, raising=False)
    monkeypatch.setattr(server.app.state, 'memory_worker', None, raising=False)
    project = create_project('更新续作'); job = create_job(project['id'], 'generate', {'model': 'same-model'})
    execute("UPDATE jobs SET status='running',progress=72 WHERE id=?", (job,))
    response = TestClient(server.app).post('/api/desktop/shutdown?current_version=0.3.4&target_version=0.3.5',
                                         headers={'X-StudyForge-Desktop-Token': 'owner'})
    assert response.status_code == 200 and response.json()['paused_generations'] == 1
    with sqlite3.connect(Path(response.json()['backup']['path']) / 'studyforge.sqlite3') as snapshot:
        assert snapshot.execute('SELECT status,progress FROM jobs WHERE id=?', (job,)).fetchone() == ('paused', 72)
    assert one('SELECT status FROM jobs WHERE id=?', (job,))['status'] == 'paused'


def test_backup_failure_is_not_returned_as_a_successful_update_receipt(monkeypatch):
    monkeypatch.setenv('STUDYFORGE_DESKTOP_TOKEN', 'owner')
    monkeypatch.setattr(server.app.state, 'desktop_shutdown', False)
    monkeypatch.setattr(server.app.state, 'desktop_shutdown_result', None, raising=False)
    monkeypatch.setattr(server.app.state, 'memory_worker', None, raising=False)
    def failed(*args): raise OSError('disk full')
    monkeypatch.setattr('studyforge.update_backup.create_update_backup', failed)
    response = TestClient(server.app, raise_server_exceptions=False).post('/api/desktop/shutdown?current_version=0.3.4&target_version=0.3.5',
        headers={'X-StudyForge-Desktop-Token': 'owner'})
    assert response.status_code == 500 and server.app.state.desktop_shutdown_result is None
