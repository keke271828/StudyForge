"""Persist interrupted work without claiming an unfinished operation succeeded."""
from __future__ import annotations

import asyncio

from .db import connect, j, many, now, unj
from .generation_control import active_generations
from .workflows import resumable, PAUSABLE_KINDS


def recover_interrupted_jobs(reason='软件退出或重启中断了此任务') -> dict:
    counts = {'paused_generations':0, 'interrupted_jobs':0}
    with connect() as database:
        database.execute("UPDATE execution_spans SET status='interrupted',ended_at=? WHERE status IN ('queued','running','tool_wait')", (now(),))
        rows = database.execute("SELECT * FROM jobs WHERE status IN ('queued','running','pausing')").fetchall()
        for row in rows:
            result = unj(row['result_json'], {})
            result.pop('request_status', None)
            if resumable(row):
                result.update(pause_requested=True, recovery_reason=reason,
                              recovery_note='已保存的生成步骤可复用；未完成的请求可能需要重新执行。')
                database.execute("UPDATE jobs SET status='paused',result_json=?,error=NULL,updated_at=? WHERE id=?",
                                 (j(result),now(),row['id']))
                counts['paused_generations'] += 1
            else:
                database.execute("UPDATE jobs SET status='failed',result_json=?,error=?,updated_at=? WHERE id=?",
                                 (j(result),reason+'，请重新发起。原资料和已完成成果保留。',now(),row['id']))
                counts['interrupted_jobs'] += 1
                payload = unj(row['payload_json'], {})
                if row['kind'].startswith('import') and payload.get('source_id'):
                    database.execute("UPDATE sources SET status='error',error=? WHERE id=? AND status='pending'",
                                     (reason+'；原文件保留，可重新导入。',payload['source_id']))
        database.execute("UPDATE lesson_questionnaires SET reply_status='failed',error='补讲因软件退出或重启中断，可以重试',updated_at=? WHERE reply_status='running'",(now(),))
        database.execute("UPDATE lesson_content_checks SET reply_status='failed',error='核对因软件退出或重启中断，可以重试',updated_at=? WHERE reply_status='running'",(now(),))
        database.execute("UPDATE agent_approvals SET status='cancelled',error='软件重启后须对新的操作重新审批',resolved_at=? WHERE status IN ('pending','approved')",(now(),))
        # A killed worker cannot run submission_guard's finally block. Release
        # only locks owned by ended/interrupted jobs; other callers keep theirs.
        database.execute("DELETE FROM practice_submission_locks WHERE EXISTS (SELECT 1 FROM jobs "
                         "WHERE practice_submission_locks.token LIKE jobs.id||':%' "
                         "AND jobs.status IN ('paused','failed','cancelled','completed'))")
    return counts


async def prepare_shutdown(worker=None) -> dict:
    # Completed model steps were already committed. The next launch requires
    # an explicit resume; quitting need not wait minutes for a provider reply.
    for control in list(active_generations.values()):
        control.pause()
    if worker:
        try:
            await asyncio.wait_for(worker.close(),timeout=2)
        except asyncio.TimeoutError:
            pass
    return recover_interrupted_jobs('软件已完全退出')


def task_status() -> dict:
    jobs = many("SELECT kind,status,progress FROM jobs WHERE status IN ('queued','running','pausing')")
    return {'active_jobs':len(jobs), 'generating':sum(row['kind'] in PAUSABLE_KINDS for row in jobs),
            'memory_running':bool(many("SELECT id FROM learning_runs WHERE status='running' LIMIT 1")),
            'paused_generations':sum(row['kind'] in PAUSABLE_KINDS for row in many("SELECT kind FROM jobs WHERE status='paused'"))}
