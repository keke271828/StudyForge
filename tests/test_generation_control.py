import asyncio
import json

import pytest
from fastapi import HTTPException

from studyforge import server
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid
from studyforge.generation_control import active_generations, control_for


def material(tmp_path):
    project = create_project('暂停测试')
    source_id = uid()
    original = tmp_path / 'original.txt'; original.write_text('相关不能推出因果。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (source_id, project['id'], original.name, '.txt', str(original), '[]', 'ready', now()))
    return server.GenerateIn(project_id=project['id'], source_ids=[source_id], model='writer', generation_quality='custom')


async def wait_status(job_id, status):
    for _ in range(400):
        row = one('SELECT * FROM jobs WHERE id=?', (job_id,))
        if row['status'] == status: return row
        if row['status'] == 'failed': pytest.fail(row['error'])
        await asyncio.sleep(.01)
    pytest.fail(f'Task did not become {status}: {row}')


def test_pause_saves_in_flight_response_and_resume_continues(tmp_path, monkeypatch):
    value = material(tmp_path)
    calls = []
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        class Client:
            model = 'writer'
            async def complete(self, system, user, **kwargs):
                calls.append(user); entered.set(); await release.wait()
                return '# 讲解\n正文。\n\n## 系统性总结\n总结。'
        monkeypatch.setattr(server, 'client_for', lambda *args, **kwargs: Client())
        job_id = create_job(value.project_id, 'generate', value.model_dump())
        task = asyncio.create_task(server._generate_job(job_id, value))
        await entered.wait()
        result = await server.pause_generation(job_id)
        assert result['status'] == 'pausing' and len(calls) == 1
        release.set(); await wait_status(job_id, 'paused')
        assert not task.done() and many('SELECT * FROM artifacts') == []
        assert many('SELECT * FROM generation_steps WHERE job_id=?', (job_id,))
        await server.resume_generation(job_id); await task
        assert one('SELECT status FROM jobs WHERE id=?', (job_id,))['status'] == 'completed'
        assert len(calls) == 1 and len(many('SELECT * FROM artifacts')) == 1
        assert job_id not in active_generations
    asyncio.run(run())


@pytest.mark.parametrize('exercises', [False, True])
def test_restart_resume_reuses_responses_and_does_not_duplicate_artifacts(tmp_path, monkeypatch, exercises):
    value = material(tmp_path); value.exercises = exercises
    value.conversation_id=uid()
    execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)',
            (value.conversation_id,value.project_id,'codex','same-thread',now(),j(value.source_ids),'writer',None))
    calls = []
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        class Client:
            model = 'writer'
            async def complete(self, system, user, **kwargs):
                kind = 'exercise' if system == '出题' else 'explanation'; calls.append(kind)
                if (exercises and kind == 'exercise') or not exercises:
                    entered.set(); await release.wait()
                return '# 讲解\n正文。\n\n## 系统性总结\n总结。'
        async def generate_set(client, *args, **kwargs):
            await client.complete('出题', '原文')
            return uid(), []
        monkeypatch.setattr(server, 'client_for', lambda *args, **kwargs: Client())
        monkeypatch.setattr(server, 'generate_set', generate_set)
        monkeypatch.setattr(server, 'student_document', lambda *args: '# 无答案习题\n题目。')
        job_id = create_job(value.project_id, 'generate', value.model_dump() | {'mentor_snapshot': server.mentor_snapshot(value)})
        task = asyncio.create_task(server._generate_job(job_id, value))
        await entered.wait(); await server.pause_generation(job_id); release.set()
        await wait_status(job_id, 'paused')
        initial_artifacts = many('SELECT id FROM artifacts')
        assert len(initial_artifacts) == int(exercises)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert job_id not in active_generations
        # Resume with a fresh controller, as happens after restarting the app.
        await server.resume_generation(job_id)
        await wait_status(job_id, 'completed')
        assert calls == (['explanation', 'exercise'] if exercises else ['explanation'])
        assert len(many('SELECT * FROM artifacts')) == 1 + int(exercises)
        assert len(many('SELECT * FROM mentor_handoffs')) == 0
        assert len(many('SELECT * FROM generation_dialogue_outputs')) == 1
        assert len(many("SELECT * FROM messages WHERE conversation_id=? AND role='assistant'",(value.conversation_id,))) == 1
        if initial_artifacts: assert one("SELECT id FROM artifacts WHERE kind='explanation'")['id'] == initial_artifacts[0]['id']
    asyncio.run(run())


def test_resume_while_pause_pending_keeps_current_request(tmp_path, monkeypatch):
    value = material(tmp_path)
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        class Client:
            async def complete(self, *args, **kwargs):
                entered.set(); await release.wait()
                return '# 讲解\n正文。\n\n## 系统性总结\n总结。'
        monkeypatch.setattr(server, 'client_for', lambda *args, **kwargs: Client())
        job_id = create_job(value.project_id, 'generate', value.model_dump())
        task = asyncio.create_task(server._generate_job(job_id, value)); await entered.wait()
        await server.pause_generation(job_id); await server.resume_generation(job_id)
        release.set(); await task
        assert one('SELECT status FROM jobs WHERE id=?', (job_id,))['status'] == 'completed'
    asyncio.run(run())


def test_pause_waits_for_all_parallel_model_requests():
    async def run():
        project = create_project('并行审查暂停')
        job_id = create_job(project['id'], 'generate', {})
        control = control_for(job_id); control.stage('并行审查', 40)
        entered = [asyncio.Event(), asyncio.Event()]; release = [asyncio.Event(), asyncio.Event()]
        async def request(index):
            entered[index].set(); await release[index].wait(); return str(index)
        tasks = [asyncio.create_task(control.step('review', i, lambda i=i: request(i))) for i in range(2)]
        await asyncio.gather(*(event.wait() for event in entered))
        await server.pause_generation(job_id); release[0].set()
        for _ in range(100):
            if control.in_flight == 1: break
            await asyncio.sleep(.01)
        assert one('SELECT status FROM jobs WHERE id=?', (job_id,))['status'] == 'pausing'
        release[1].set(); await wait_status(job_id, 'paused')
        assert not any(task.done() for task in tasks)
        await server.resume_generation(job_id)
        assert await asyncio.gather(*tasks) == ['0', '1']
        control.finish()
    asyncio.run(run())


def test_non_generation_and_completed_tasks_cannot_pause():
    project = create_project('状态限制')
    read_job = create_job(project['id'], 'read', {})
    with pytest.raises(HTTPException) as error: asyncio.run(server.pause_generation(read_job))
    assert error.value.status_code == 400
    job_id = create_job(project['id'], 'generate', {})
    execute("UPDATE jobs SET status='completed' WHERE id=?", (job_id,))
    with pytest.raises(HTTPException) as error: asyncio.run(server.pause_generation(job_id))
    assert error.value.status_code == 409
