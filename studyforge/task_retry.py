"""Durable, bounded retries for registered tasks, without replaying side effects."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
import traceback

import httpx

from .db import connect, execute, j, now, one, unj

DEFAULTS = {'task_auto_retry': True, 'task_retry_limit': 5}
TABLES = {'project': 'jobs', 'library': 'library_jobs'}


@dataclass
class Attempt:
    family: str
    job_id: str
    error: Exception | None = None
    unsafe_replay: bool = False
    failure_handled: bool = False


current_attempt = ContextVar('studyforge_retry_attempt', default=None)


def release_attempt_error(attempt):
    """Release failed-work frames after the durable retry decision is saved.

    Error type/message/HTTP cause remain usable by independent observers; only
    tracebacks and this attempt's strong reference are discarded. Never call
    before classify/retry_delay, or while its operation is still running.
    """
    pending = [attempt.error] if attempt and attempt.error else []
    if attempt:
        attempt.error = None
    seen = set()
    while pending:
        error = pending.pop()
        if not isinstance(error, BaseException) or id(error) in seen:
            continue
        seen.add(id(error))
        pending.extend([error.__cause__, error.__context__])
        nested = getattr(error, 'failures', ())
        if isinstance(nested, (list, tuple)):
            pending.extend(nested)
        if isinstance(error, BaseExceptionGroup):
            pending.extend(error.exceptions)
        if error.__traceback__:
            traceback.clear_frames(error.__traceback__)
            error.__traceback__ = None


class ContentProblem(ValueError):
    """A substantive quality defect after the workflow's own correction pass."""


def validate_settings(value):
    if 'task_auto_retry' in value and type(value['task_auto_retry']) is not bool:
        raise ValueError('任务自动重试必须是开关值')
    if 'task_retry_limit' in value and (type(value['task_retry_limit']) is not int or not 5 <= value['task_retry_limit'] <= 20):
        raise ValueError('自动重试次数须为 5 到 20 次，不包括首次执行')


def report_failure(error):
    attempt = current_attempt.get()
    if attempt: attempt.error = error


def mark_external_effect():
    # Only a FAILED, uncached step which may have changed a user file is unsafe
    # to replay. Successful steps are committed and reused on subsequent runs.
    from .scheduling import current_step
    step = current_step.get()
    if step is not None:
        step.replay_risk = True
        attempt=current_attempt.get();key=getattr(step,'cache_key',None)
        if attempt and attempt.family=='project' and key:
            execute('INSERT OR IGNORE INTO generation_steps VALUES (?,?,?,?)',
                    (attempt.job_id,'external-effect:'+key,j(True),now()))
    elif current_attempt.get(): current_attempt.get().unsafe_replay = True


def failed_step(step):
    if getattr(step, 'replay_risk', False) and current_attempt.get():
        current_attempt.get().unsafe_replay = True


def classify(error):
    """Return a public reason and whether another attempt can help."""
    nested = getattr(error, 'failures', None)
    if nested:
        decisions = [classify(item) for item in nested]
        return next((item for item in decisions if not item[0]), decisions[0])
    chain = []; seen = set(); item = error
    while isinstance(item, BaseException) and id(item) not in seen:
        seen.add(id(item)); chain.append(item); item = item.__cause__ or item.__context__
    if any(isinstance(item, ContentProblem) for item in chain):
        return False, '教学内容仍有实质质量问题，需要修订'
    from .review_versions import ReviewVersionConflict
    if any(isinstance(item,ReviewVersionConflict) for item in chain):
        return False,'题目版本或复习依据需要核对，重复模型请求无法修复'
    if any(isinstance(item, (FileNotFoundError, PermissionError)) for item in chain):
        return False, '原文件或权限需要处理'
    # Some compatible services use 429 for exhausted credit as well as a
    # temporary rate limit. Repeating an explicit billing failure cannot help.
    billing_codes = {'insufficient_quota', 'insufficient_balance', 'billing_hard_limit_reached'}
    if any(any(code in str(item).lower() for code in billing_codes) for item in chain):
        return False, '账户额度或余额需要处理'
    for item in chain:
        response = getattr(item, 'response', None)
        status = getattr(response, 'status_code', None)
        if status is not None:
            if status == 429 and isinstance(response, httpx.Response):
                try:
                    body = response.json()
                    detail = body.get('error', body) if isinstance(body, dict) else {}
                    codes = [detail.get('code'), detail.get('type')] if isinstance(detail, dict) else []
                    if any(str(code).lower() in billing_codes for code in codes):
                        return False, '账户额度或余额需要处理'
                except (ValueError, httpx.ResponseNotRead):
                    pass
            if status in (408, 425, 429) or 500 <= status <= 599: return True, '服务暂时异常或限流'
            if 400 <= status <= 499: return False, '账户、请求或网页访问限制需要处理'
    message = str(error).lower()
    statuses = re.findall(r'(?:http(?:statuserror)?\s*[:=]?\s*|status(?: code)?\s*[:=]?\s*|client error[\s\x27\"]*)([45]\d\d)', message)
    if statuses:
        status = int(statuses[0])
        return (True, '服务暂时异常或限流') if status in (408, 425, 429) or status >= 500 else (False, '账户、请求或网页访问限制需要处理')
    permanent = ('密钥', '余额不足', '额度不足', 'insufficient_quota', 'invalid api key',
                 'not found', '不存在', '已删除', '已改变', '已变更', '权限', '审批', '登录',
                 '不支持', '未启用', '无法排版公式', '无法识别的字符', '实质问题',
                 '审查未通过', '独立解题未通过', '缺少', '超过上下文', 'context length',
                 'out of memory', 'memoryerror', 'too large', '长度上限')
    # Transport wrappers often include the word 密钥 in general advice. Use an
    # underlying network exception first, but never override HTTP/auth errors.
    if any(isinstance(item, (httpx.TransportError, TimeoutError, ConnectionError)) for item in chain):
        return True, '网络连接中断或超时'
    if '没有返回内容' in message: return True, '模型返回空回复'
    if any(word in message for word in permanent): return False, '需要修正输入、配置或内容问题'
    if any(isinstance(item, json.JSONDecodeError) for item in chain): return True, '模型返回格式不完整'
    if any(getattr(item, 'retryable', False) for item in chain): return True, '模型响应未完成'
    if any(hasattr(item, 'retryable') and not item.retryable for item in chain): return False, '服务拒绝或输出上限需要调整'
    temporary = ('connecterror', 'readerror', 'remoteprotocolerror', 'timeout', '连接失败',
                 '无法连接', '网络错误', '网络连接', '请求失败', '请求超时', '超时', '响应中断',
                 '响应未完成', '空的结构化内容', '没有返回内容', '空内容', '空回复', '节点索引为空',
                 '无效 json', 'json 内容经一次格式修复', '截断', '服务繁忙', '过于频繁',
                 'temporarily unavailable', 'connection reset', 'connection aborted')
    if any(word in message for word in temporary): return True, '网络或模型响应暂未完成'
    return False, '此错误需要检查原因，重复执行无法确认能解决'


def public(family, job_id):
    row = one('SELECT * FROM task_retries WHERE family=? AND job_id=?', (family, job_id))
    if not row: return None
    return {key: row[key] for key in ('enabled', 'limit_count', 'retry_count', 'state', 'next_at', 'last_error', 'reason')}


def ensure(family, job_id):
    from .ai import settings
    config = DEFAULTS | settings()
    execute(f'INSERT OR IGNORE INTO task_retries(family,job_id,enabled,limit_count,updated_at) '
            f'SELECT ?,?,?,?,? WHERE EXISTS (SELECT 1 FROM {TABLES[family]} WHERE id=?)',
            (family, job_id, int(config['task_auto_retry']), config['task_retry_limit'], now(), job_id))
    return public(family, job_id)


def retry_delay(count, error):
    # Release all model/local slots during backoff; no polling request is sent.
    delay = min(120, 3 * 2 ** (count - 1))
    item = error; seen = set()
    while isinstance(item, BaseException) and id(item) not in seen:
        seen.add(id(item))
        response = getattr(item, 'response', None)
        if response is not None:
            value = response.headers.get('retry-after')
            if value:
                try: delay = max(delay, min(600, float(value)))
                except ValueError:
                    from email.utils import parsedate_to_datetime
                    try: delay = max(delay, min(600, (parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds()))
                    except (TypeError, ValueError): pass
        item = item.__cause__ or item.__context__
    return max(0, delay)


def schedule(family, job_id, error, *, unsafe=False, partial_result=None):
    ensure(family, job_id)
    table = TABLES[family]; retryable, reason = classify(error)
    if unsafe: retryable, reason = False, '本次未完成步骤可能已修改文件，需核对后继续，避免重复操作'
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute(f'SELECT status,progress,result_json,kind,CASE WHEN kind LIKE \'import%\' THEN '
                         f"json_extract(CASE WHEN json_valid(payload_json) THEN payload_json ELSE '{{}}' END,'$.source_id') "
                         f'ELSE NULL END AS source_id FROM {table} WHERE id=?', (job_id,)).fetchone()
        if not row or row['status'] in ('cancelled', 'completed'): return False
        if family == 'project' and db.execute('SELECT 1 FROM deleted_job_records WHERE job_id=?', (job_id,)).fetchone(): return False
        record = db.execute('SELECT * FROM task_retries WHERE family=? AND job_id=?', (family, job_id)).fetchone()
        if not record: return False
        count = record['retry_count']; allowed = bool(record['enabled']) and retryable and count < record['limit_count']
        state = 'waiting' if allowed else 'exhausted' if retryable and record['enabled'] else 'blocked' if record['enabled'] else 'disabled'
        if allowed:
            count += 1
            due = (datetime.now(timezone.utc) + timedelta(seconds=retry_delay(count, error))).isoformat()
        else: due = None
        error_text = f'{type(error).__name__}: {error}' if isinstance(error, BaseException) else str(error)
        db.execute('UPDATE task_retries SET retry_count=?,state=?,next_at=?,last_error=?,reason=?,updated_at=? WHERE family=? AND job_id=?',
                   (count, state, due, error_text[:1600], reason, now(), family, job_id))
        if allowed:
            result = unj(row['result_json'], {}) | (partial_result if isinstance(partial_result,dict) else {})
            result.pop('request_status', None)
            result['stage'] = f'等待自动重试 {count}/{record["limit_count"]} · 已完成步骤保留'
            result.pop('retry', None)
            status = 'paused' if row['status'] in ('paused', 'pausing') else 'queued'
            db.execute(f'UPDATE {table} SET status=?,progress=?,result_json=?,error=NULL,updated_at=? WHERE id=?',
                       (status, min(95, row['progress']), j(result), now(), job_id))
            if family == 'project' and row['kind'].startswith('import'):
                source_id = row['source_id']
                db.execute("UPDATE sources SET status='pending',error=NULL WHERE id=?", (source_id,))
        return allowed


def ready(family, job_id):
    record = public(family, job_id)
    return not record or not record['next_at'] or datetime.fromisoformat(record['next_at']) <= datetime.now(timezone.utc)


def begin(family, job_id):
    ensure(family, job_id)
    execute("UPDATE task_retries SET state='running',next_at=NULL,updated_at=? WHERE family=? AND job_id=?", (now(), family, job_id))


def finish(family, job_id, state):
    if state == 'failed': return  # Keep exhausted/blocked and their evidence.
    execute('UPDATE task_retries SET state=?,next_at=NULL,updated_at=? WHERE family=? AND job_id=?', (state, now(), family, job_id))


def reset(family, job_id):
    """Only an explicit manual retry starts a fresh allowance; resume never does."""
    ensure(family,job_id)
    execute("UPDATE task_retries SET retry_count=0,state='queued',next_at=NULL,last_error=NULL,reason=NULL,updated_at=? WHERE family=? AND job_id=?",
            (now(),family,job_id))


async def wait_project(job_id):
    from .generation_control import control_for
    while True:
        row = one('SELECT status FROM jobs WHERE id=?', (job_id,))
        if not row or row['status'] == 'cancelled' or one('SELECT 1 FROM deleted_job_records WHERE job_id=?', (job_id,)):
            raise asyncio.CancelledError()
        control = control_for(job_id)
        await control.checkpoint()
        if ready('project', job_id): return
        await asyncio.sleep(.25)


class NodeFailures(ValueError):
    def __init__(self, message, failures):
        super().__init__(message); self.failures = failures
