"""Cancel registered work and prevent removed jobs from publishing late results."""
import asyncio
import inspect

from .db import execute, j, now, one, unj, update_job

active_jobs = {}


def execution_metadata(job_id):
    # Routing needs no source, dialogue snapshot, answer or export body. Let
    # SQLite project only the small ownership fields before any task awaits.
    payload = "CASE WHEN json_valid(payload_json) THEN payload_json ELSE '{}' END"
    return one(f'SELECT project_id,kind,json_extract({payload},\'$.conversation_id\') AS conversation_id,'
               f'json_extract({payload},\'$._mobile_device_id\') AS mobile_device_id FROM jobs WHERE id=?', (job_id,)) or {}


def retry_operation(job_id):
    """Recreate an awaitable from the original saved intent, never live chat."""
    from pathlib import Path
    from . import server
    row = one('SELECT kind,payload_json FROM jobs WHERE id=?', (job_id,))
    if not row: raise ValueError('任务已删除')
    payload = unj(row['payload_json'], {})
    if row['kind'] == 'generate': return server._generate_job(job_id, server.GenerateIn.model_validate(payload))
    if row['kind'] == 'read': return server._read_job(job_id, server.ReadIn.model_validate(payload))
    if row['kind'] == 'knowledge': return server._knowledge_job(job_id, server.KnowledgeIn.model_validate(payload))
    if row['kind'] == 'export': return server.document_exports.run_job(job_id)
    if row['kind'] == 'import':
        source = one('SELECT * FROM sources WHERE id=?', (payload['source_id'],))
        if not source: raise ValueError('资料已删除')
        return server._import_job(job_id, source['id'], Path(source['original_path']))
    if row['kind'] in ('import_video', 'import_url'):
        return server._url_job(job_id, payload['source_id'], payload['url'], video_url=payload.get('video_url'))
    from .workflows import PAUSABLE_KINDS
    if row['kind'] in PAUSABLE_KINDS: return server._assessment_job(job_id)
    raise ValueError('此任务没有可恢复的执行入口')


def start_job(job_id, operation, *, retry_factory=None):
    existing = active_jobs.get(job_id)
    if existing and not existing.done():
        if inspect.iscoroutine(operation): operation.close()
        return existing
    async def run():
        from .scheduling import execution_scope
        from .mobile_context import remote_device
        routing = execution_metadata(job_id)
        token = remote_device.set(routing.get('mobile_device_id'))
        pending = None if callable(operation) else operation
        attempt = None
        try:
            async with execution_scope(job_id=job_id, project_id=routing.get('project_id'),
                                       conversation_id=routing.get('conversation_id'), label=routing.get('kind', '')):
                from . import task_retry
                factory = retry_factory or (operation if callable(operation) else lambda: retry_operation(job_id))
                task_retry.ensure('project', job_id)
                while True:
                    await task_retry.wait_project(job_id)
                    task_retry.begin('project', job_id)
                    attempt = task_retry.Attempt('project', job_id)
                    attempt_token = task_retry.current_attempt.set(attempt)
                    output = None
                    try:
                        work = pending if pending is not None else factory()
                        pending = None
                        output = await work
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        attempt.error = exc
                        current = one('SELECT progress,result_json FROM jobs WHERE id=?', (job_id,))
                        if current: update_job(job_id, 'failed', current['progress'], unj(current['result_json'], {}), error=f'{type(exc).__name__}: {exc}')
                    finally:
                        task_retry.current_attempt.reset(attempt_token)
                    try:
                        current = one('SELECT status,error FROM jobs WHERE id=?', (job_id,))
                        if not current: return output
                        retry = task_retry.public('project',job_id)
                        if retry and retry['state']=='waiting' and current['status'] in ('queued','paused','pausing'):
                            continue
                        if current['status'] == 'failed':
                            problem = attempt.error or current['error'] or '任务未完成'
                            if not attempt.failure_handled and task_retry.schedule('project', job_id, problem, unsafe=attempt.unsafe_replay): continue
                        else: task_retry.finish('project', job_id, current['status'])
                        return output
                    finally:
                        # Retry reasons, timing and partial outputs are already
                        # persisted. Do not hold a failed model's stack through
                        # backoff/pause or the next independent attempt.
                        task_retry.release_attempt_error(attempt)
                        current = problem = work = output = None
        finally:
            if attempt:
                from .task_retry import release_attempt_error
                release_attempt_error(attempt)
            if not callable(operation) and pending is not None: pending.close()
            from .generation_control import active_generations
            control = active_generations.get(job_id)
            if control: control.finish()
            remote_device.reset(token)
    task = asyncio.create_task(run())
    active_jobs[job_id] = task
    def finished(done):
        if active_jobs.get(job_id) is done: active_jobs.pop(job_id, None)
        if not done.cancelled(): done.exception()
        if inspect.iscoroutine(operation) and inspect.getcoroutinestate(operation)==inspect.CORO_CREATED: operation.close()
    task.add_done_callback(finished)
    return task


async def cancel_job(job_id):
    row = one("SELECT status,progress,result_json,kind,CASE WHEN kind LIKE 'import%' THEN "
              "json_extract(CASE WHEN json_valid(payload_json) THEN payload_json ELSE '{}' END,'$.source_id') "
              "ELSE NULL END AS source_id FROM jobs WHERE id=?", (job_id,))
    if not row: raise ValueError('任务不存在')
    if row['status'] in ('queued','running','pausing','paused'):
        result = unj(row['result_json'], {}) | {'stage':'任务已取消，已完成的成果保留'}
        update_job(job_id, 'cancelled', row['progress'], result)
        from .task_retry import finish
        finish('project', job_id, 'cancelled')
        from .generation_control import active_generations
        control = active_generations.get(job_id)
        if control:
            control.cancel_requested = True
            control.resume_event.set()
        task = active_jobs.get(job_id)
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if control: control.finish()
        source_id = row['source_id']
        if source_id and row['kind'].startswith('import'):
            execute("UPDATE sources SET status='error',error='解析任务已取消；原文件保留，可删除资料或重新导入' WHERE id=? AND status='pending'", (source_id,))
    return one('SELECT status FROM jobs WHERE id=?', (job_id,))['status']


async def remove_job(job_id):
    status = await cancel_job(job_id)
    execute('INSERT OR IGNORE INTO deleted_job_records VALUES (?,?)', (job_id, now()))
    execute('DELETE FROM generation_steps WHERE job_id=?', (job_id,))
    execute('DELETE FROM execution_spans WHERE job_id=?', (job_id,))
    return {'job_id':job_id, 'status':status, 'deleted':True,
            'note':'任务已从列表移除；进行中的工作已取消，已完成成果和原资料保留'}
