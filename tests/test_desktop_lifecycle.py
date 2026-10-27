import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from studyforge import server
from studyforge.ai import save_settings
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid
from studyforge.desktop_lifecycle import prepare_shutdown, recover_interrupted_jobs, task_status
from studyforge.generation_control import active_generations, control_for


@pytest.fixture(autouse=True)
def desktop_state(monkeypatch):
    monkeypatch.setenv('STUDYFORGE_DESKTOP_TOKEN', 'test-desktop-owner')
    monkeypatch.setattr(server.app.state, 'desktop_shutdown', False)
    monkeypatch.setattr(server.app.state, 'desktop_shutdown_result', None, raising=False)
    monkeypatch.setattr(server.app.state, 'memory_worker', None, raising=False)
    save_settings({'background_learning_enabled': False})
    yield
    active_generations.clear()


@pytest.mark.parametrize('status', ['queued', 'running', 'pausing'])
def test_restart_preserves_generation_inputs_progress_steps_and_partial_document(tmp_path, status):
    project = create_project('中断恢复')
    payload = {'model': 'selected-model', 'learning_mode': 'research', 'source_ids': ['original'],
               'instructions': '解释构造动机', 'dialogue_snapshot': {'messages': [{'content': '我的理解'}]}}
    job = create_job(project['id'], 'generate', payload)
    partial = tmp_path / '已经导出的讲解.docx'; partial.write_bytes(b'saved original artifact')
    artifact = server.add_artifact(project['id'], [], 'explanation', 'docx', '已经导出的讲解', partial,
                                   {'generation_job_id': job})
    execute('UPDATE jobs SET status=?,progress=85,result_json=?,error=? WHERE id=?',
            (status, j({'stage': '配套习题', 'artifacts': [artifact], 'request_status': '请求中'}), 'old', job))
    execute('INSERT INTO generation_steps VALUES (?,?,?,?)', (job, 'finished-step', j('完整已保存回复'), now()))
    assert recover_interrupted_jobs() == {'paused_generations': 1, 'interrupted_jobs': 0}
    restored = one('SELECT * FROM jobs WHERE id=?', (job,))
    assert restored['status'] == 'paused' and restored['progress'] == 85 and restored['error'] is None
    assert json.loads(restored['payload_json']) == payload
    result = json.loads(restored['result_json'])
    assert result['pause_requested'] and result['artifacts'] == [artifact] and 'request_status' not in result
    assert '未完成' in result['recovery_note'] and partial.read_bytes() == b'saved original artifact'
    assert len(many('SELECT * FROM artifacts')) == len(many('SELECT * FROM generation_steps')) == 1
    assert recover_interrupted_jobs() == {'paused_generations': 0, 'interrupted_jobs': 0}


@pytest.mark.parametrize('status', ['completed', 'failed', 'paused'])
def test_restart_leaves_finished_and_already_paused_work_unchanged(status):
    project = create_project('已有状态'); job = create_job(project['id'], 'generate', {})
    execute('UPDATE jobs SET status=?,progress=73,result_json=?,error=? WHERE id=?',
            (status, j({'saved': True}), 'prior-error', job))
    before = one('SELECT * FROM jobs WHERE id=?', (job,))
    recover_interrupted_jobs()
    assert one('SELECT * FROM jobs WHERE id=?', (job,)) == before


def test_interrupted_import_keeps_original_and_ready_sources(tmp_path):
    project = create_project('导入中断'); source = uid(); ready = uid()
    original = tmp_path / '原资料.txt'; original.write_text('原资料必须保留。', encoding='utf-8')
    for source_id, status in [(source, 'pending'), (ready, 'ready')]:
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
                (source_id, project['id'], original.name, '.txt', str(original), status, now()))
        job = create_job(project['id'], 'import', {'source_id': source_id})
        execute("UPDATE jobs SET status='running',progress=21 WHERE id=?", (job,))
    knowledge = create_job(project['id'], 'knowledge', {})
    counts = recover_interrupted_jobs()
    assert counts == {'paused_generations': 0, 'interrupted_jobs': 3}
    assert one('SELECT * FROM sources WHERE id=?', (source,))['status'] == 'error'
    assert one('SELECT * FROM sources WHERE id=?', (ready,))['status'] == 'ready'
    assert original.read_text(encoding='utf-8') == '原资料必须保留。'
    assert one('SELECT * FROM jobs WHERE id=?', (knowledge,))['status'] == 'failed'
    assert all('请重新发起' in row['error'] for row in many('SELECT error FROM jobs'))


def test_status_counts_all_projects_and_excludes_paused_jobs():
    for project_index, status in enumerate(['running', 'queued', 'pausing', 'paused', 'completed']):
        project = create_project(str(project_index)); job = create_job(project['id'], 'generate', {})
        execute('UPDATE jobs SET status=? WHERE id=?', (status, job))
    create_job(project['id'], 'import', {})
    assert task_status() == {'active_jobs': 4, 'generating': 3, 'memory_running': False, 'paused_generations': 1}


@pytest.mark.parametrize('token', [None, 'wrong', 'test-desktop-owner-extra'])
def test_only_own_desktop_may_read_status_or_prepare_shutdown(token):
    api = TestClient(server.app)
    headers = {'X-StudyForge-Desktop-Token': token} if token else {}
    assert api.get('/api/desktop/status', headers=headers).status_code == 403
    assert api.post('/api/desktop/shutdown', headers=headers).status_code == 403
    assert server.app.state.desktop_shutdown is False


def test_without_desktop_parent_the_shutdown_endpoint_is_unavailable(monkeypatch):
    monkeypatch.delenv('STUDYFORGE_DESKTOP_TOKEN')
    response = TestClient(server.app).post('/api/desktop/shutdown', headers={'X-StudyForge-Desktop-Token': 'test-desktop-owner'})
    assert response.status_code == 403


def test_owner_requests_still_reject_foreign_web_origins():
    api = TestClient(server.app)
    headers = {'X-StudyForge-Desktop-Token': 'test-desktop-owner', 'Origin': 'https://external.example'}
    assert api.post('/api/desktop/shutdown', headers=headers).status_code == 403
    assert not server.app.state.desktop_shutdown


def test_shutdown_is_idempotent_and_rejects_new_mutations(monkeypatch):
    calls = []
    async def prepare(worker):
        calls.append(worker)
        return {'paused_generations': 1, 'interrupted_jobs': 0}
    monkeypatch.setattr(server, 'prepare_shutdown', prepare)
    api = TestClient(server.app); headers = {'X-StudyForge-Desktop-Token': 'test-desktop-owner'}
    assert api.get('/api/desktop/status', headers=headers).json()['quitting'] is False
    first = api.post('/api/desktop/shutdown', headers=headers)
    assert first.status_code == 200 and first.json()['paused_generations'] == 1
    assert api.post('/api/desktop/shutdown', headers=headers).json() == first.json() and len(calls) == 1
    assert api.post('/api/projects', json={'name': '不能在退出时启动新工作'}).status_code == 503
    assert many('SELECT * FROM projects') == []
    assert api.get('/api/health').status_code == 200
    assert api.get('/api/desktop/status', headers=headers).json()['quitting'] is True


def test_shutdown_pauses_live_controller_and_retains_response_finished_before_exit():
    async def run():
        project = create_project('安全边界'); job = create_job(project['id'], 'generate', {})
        control = control_for(job); control.stage('在途请求', 44)
        entered, release = asyncio.Event(), asyncio.Event()
        async def operation():
            entered.set(); await release.wait(); return '已经完成的回复'
        step = asyncio.create_task(control.step('writer', 'same-input', operation))
        await entered.wait()
        closed = []
        class Worker:
            async def close(self): closed.append(True)
        result = await prepare_shutdown(Worker())
        assert closed == [True] and result['paused_generations'] == 1 and control.pause_requested
        assert one('SELECT status FROM jobs WHERE id=?', (job,))['status'] == 'paused'
        release.set()
        for _ in range(100):
            if many('SELECT * FROM generation_steps'): break
            await asyncio.sleep(.01)
        assert not step.done() and len(many('SELECT * FROM generation_steps')) == 1
        step.cancel()
        with pytest.raises(asyncio.CancelledError): await step
        control.finish()
        restored = control_for(job); restored.resume()
        async def forbidden(): pytest.fail('已保存回复不能重复请求')
        assert await restored.step('writer', 'same-input', forbidden) == '已经完成的回复'
        restored.finish()
    asyncio.run(run())


def test_lifespan_recovers_abrupt_exit_without_automatic_generation(monkeypatch):
    project = create_project('意外退出'); job = create_job(project['id'], 'generate', {'model': 'saved-model'})
    execute("UPDATE jobs SET status='running',progress=54 WHERE id=?", (job,))
    def forbidden(*args, **kwargs): pytest.fail('重开只能恢复状态，不能自动发起模型请求')
    monkeypatch.setattr(server, 'client_for', forbidden)
    with TestClient(server.app) as api:
        row = api.get('/api/jobs/' + job).json()
        assert row['status'] == 'paused' and row['progress'] == 54 and row['payload']['model'] == 'saved-model'
        assert server.app.state.desktop_shutdown is False
