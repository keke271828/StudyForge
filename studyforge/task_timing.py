"""Small, source-free execution evidence for diagnosing slow local tasks."""
from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import time

from .db import execute, many, now, one, uid, unj
from .scheduling import execution_context

log = logging.getLogger(__name__)


def _live(job_id):
    return one('SELECT 1 FROM jobs WHERE id=? AND NOT EXISTS '
               '(SELECT 1 FROM deleted_job_records WHERE job_id=jobs.id)', (job_id,))


@contextmanager
def phase(resource, label):
    # to_thread propagates the task context. No model input, source body, file
    # path or answer is copied into the trace. Not a scheduler/resource lease.
    meta = execution_context.get()
    ident = None
    start = time.monotonic()
    if meta.get('job_id'):
        try:
            if _live(meta['job_id']):
                ident = uid()
                stamp = now()
                execute('INSERT INTO execution_spans SELECT ?,?,?,?,?,?,?,?,?,?,?,?,?,? WHERE EXISTS '
                        '(SELECT 1 FROM jobs WHERE id=? AND NOT EXISTS '
                        '(SELECT 1 FROM deleted_job_records WHERE job_id=jobs.id))',
                        (ident, 0, meta['job_id'], meta.get('project_id'), meta.get('conversation_id'),
                         resource, None, label, meta.get('priority', 0), 'running', stamp, stamp, None, 0, meta['job_id']))
        except Exception:
            ident = None
            log.debug('Unable to record local task phase', exc_info=True)
    status = 'completed'
    try:
        yield
    except BaseException as exc:
        status = 'cancelled' if type(exc).__name__ == 'CancelledError' else 'failed'
        raise
    finally:
        if ident:
            try:
                execute('UPDATE execution_spans SET status=?,ended_at=?,duration_ms=? WHERE id=? AND '
                        'EXISTS (SELECT 1 FROM jobs WHERE id=execution_spans.job_id AND NOT EXISTS '
                        '(SELECT 1 FROM deleted_job_records WHERE job_id=jobs.id))',
                        (status, now(), round((time.monotonic() - start) * 1000), ident))
            except Exception:
                log.debug('Unable to finish local task phase', exc_info=True)


def timed_call(resource, label, operation, *args, **kwargs):
    with phase(resource, label):
        return operation(*args, **kwargs)


def record_info(key,value):
    if key!='asr_execution':raise ValueError('不支持的本机任务信息')
    meta=execution_context.get()
    if not meta.get('job_id'):return
    from .db import j
    try:
        fields={'selected_model','actual_model','preferred_device','actual_device','compute_type',
                'fallback_reason','language','beam_size','audio_seconds'}
        info={name:item for name,item in value.items() if name in fields and
              (item is None or type(item) in (str,int,float,bool))}
        stamp=now()
        # Final workflow results can replace result_json. Retain this small
        # execution receipt beside timings, without copying a task snapshot.
        execute('INSERT INTO execution_spans SELECT ?,?,?,?,?,?,?,?,?,?,?,?,?,? WHERE EXISTS '
                '(SELECT 1 FROM jobs WHERE id=? AND NOT EXISTS '
                '(SELECT 1 FROM deleted_job_records WHERE job_id=jobs.id))',
                (uid(),0,meta['job_id'],meta.get('project_id'),meta.get('conversation_id'),'asr_info',None,
                 j(info),meta.get('priority',0),'completed',stamp,stamp,stamp,0,meta['job_id']))
    except Exception:log.debug('Unable to save ASR execution information',exc_info=True)


def _date(value):
    try:
        stamp = datetime.fromisoformat(value)
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _elapsed(start, end):
    left, right = _date(start), _date(end)
    return max(0, round((right - left).total_seconds() * 1000)) if left and right else 0


def detail(job_id):
    job = one("SELECT id,project_id,status,created_at,updated_at,json_extract(CASE WHEN json_valid(result_json) "
              "THEN result_json ELSE '{}' END,'$.vision_reuse') AS vision_reuse, json_extract(CASE WHEN json_valid(result_json) "
              "THEN result_json ELSE '{}' END,'$.asr_execution') AS asr_execution FROM jobs WHERE id=? AND NOT EXISTS "
              '(SELECT 1 FROM deleted_job_records WHERE job_id=jobs.id)', (job_id,))
    if not job:
        return None
    stamp = now()
    active = job['status'] in ('queued', 'running', 'pausing', 'paused')
    groups = {}
    asr_records=[]
    rows = many('SELECT resource,label,status,queued_at,started_at,ended_at,duration_ms FROM execution_spans '
                'WHERE job_id=? ORDER BY queued_at,rowid', (job_id,))
    for row in rows:
        if row['resource']=='asr_info':
            info=unj(row['label'],{})
            if isinstance(info,dict):asr_records.append(info)
            continue
        phase_name = ''
        for name in ('讲解撰写','讲解审查','全文总结'):
            if row['resource'] == 'model' and (row['label'] or '').startswith('[' + name + '] '):
                phase_name = name
                break
        group = groups.setdefault((row['resource'],phase_name), dict(resource=row['resource'], phase=phase_name, calls=0, active=0,
            queued=0, failed=0, interrupted=0, elapsed_ms=0, queue_ms=0))
        group['calls'] += 1
        group['active'] += row['status'] == 'running'
        group['queued'] += row['status'] == 'queued'
        group['failed'] += row['status'] == 'failed'
        group['interrupted'] += row['status'] == 'interrupted'
        group['queue_ms'] += _elapsed(row['queued_at'], row['started_at'] or row['ended_at'] or stamp)
        if row['started_at']:
            group['elapsed_ms'] += (max(0, row['duration_ms'] or 0) if row['ended_at'] and row['status'] != 'interrupted'
                                    else _elapsed(row['started_at'], row['ended_at'] or stamp))
    return dict(job_id=job_id, project_id=job['project_id'], status=job['status'], wall_ms=_elapsed(job['created_at'], stamp if active else job['updated_at']),
                vision_reuse=unj(job['vision_reuse'],None),
                asr_execution=asr_records[-1] if asr_records else unj(job['asr_execution'],None),
                asr_record_count=len(asr_records),
                as_of=stamp, resources=list(groups.values()), observed=bool(rows),
                scope='observed_spans', overlapping=True,
                note='各阶段可能并行或相互包含，阶段耗时不可相加当作总时长。模型阶段是名额占用时间，视觉调用还含图片准备与服务响应，不能视作纯推理时间；'
                     '本机语音/OCR耗时可能包含共享推理队列等待。暂停、审批、重试退避和未记录的旧步骤未单独分解。')
