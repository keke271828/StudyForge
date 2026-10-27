"""Local reading windows and transactional, request-level daily accounting.

Reported provider totals and conservative reservations are kept distinct. A
soft admission budget cannot promise an exact service-side billing ceiling.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import re

from .db import connect, execute, j, now, one, uid, unj

DEFAULTS = {'window_enabled': False, 'start': '00:00', 'end': '00:00',
            'weekdays': list(range(7)), 'daily_tokens': 0}
KEY = 'library_reading_policy'


def local_now():
    return datetime.now().astimezone()


def configuration(database=None):
    row = (database.execute('SELECT value FROM workspace_state WHERE key=?', (KEY,)).fetchone()
           if database else one('SELECT value FROM workspace_state WHERE key=?', (KEY,)))
    return DEFAULTS | (unj(row['value'], {}) if row else {})


def save(value):
    if set(value) - set(DEFAULTS): raise ValueError('存在未知的后台阅读设置')
    merged = configuration() | value
    if type(merged['window_enabled']) is not bool: raise ValueError('阅读时段必须是开关值')
    for key in ('start', 'end'):
        if not isinstance(merged[key], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', merged[key]):
            raise ValueError('阅读时段须为 HH:MM 格式')
    days = merged['weekdays']
    if not isinstance(days, list) or not days or any(type(day) is not int or not 0 <= day <= 6 for day in days):
        raise ValueError('至少选择一个有效的阅读星期')
    merged['weekdays'] = sorted(set(days))
    if type(merged['daily_tokens']) is not int or not 0 <= merged['daily_tokens'] <= 50_000_000:
        raise ValueError('每日 token 预算须为 0 至 50000000 的整数，0 表示不限制')
    execute('INSERT INTO workspace_state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY, j(merged)))
    from .scheduling import wake_schedulers
    wake_schedulers()
    return status()


def window_allowed(prefs, moment):
    if not prefs['window_enabled']: return True
    start, end = prefs['start'], prefs['end']
    minute = moment.strftime('%H:%M')
    if start == end: return moment.weekday() in prefs['weekdays']
    if start < end: return moment.weekday() in prefs['weekdays'] and start <= minute < end
    # Overnight belongs to the day on which the window started.
    if minute >= start: return moment.weekday() in prefs['weekdays']
    if minute < end: return (moment - timedelta(days=1)).weekday() in prefs['weekdays']
    return False


def next_opening(prefs, moment):
    if not prefs['window_enabled'] or window_allowed(prefs, moment): return moment.isoformat()
    hour, minute = map(int, prefs['start'].split(':'))
    for offset in range(9):
        candidate = (moment + timedelta(days=offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate > moment and candidate.weekday() in prefs['weekdays']: return candidate.isoformat()


def totals(database, day):
    row = database.execute('SELECT COALESCE(SUM(charged_tokens),0) charged,'
        "COALESCE(SUM(CASE WHEN status='inflight' THEN reserved_tokens ELSE 0 END),0) reserved,"
        'COALESCE(SUM(reported_tokens),0) reported,'
        "COALESCE(SUM(CASE WHEN reported_tokens IS NULL AND status<>'inflight' THEN charged_tokens ELSE 0 END),0) estimated,"
        "COUNT(*) requests,SUM(CASE WHEN status='uncertain' THEN 1 ELSE 0 END) uncertain "
        'FROM library_model_usage WHERE day=?', (day,)).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}


def admission(prefs, usage, moment, required=1, *, ignore_window=False):
    if not ignore_window and not window_allowed(prefs, moment):
        return {'kind': 'window', 'message': '等待允许的阅读时段 · 已完成步骤已保存',
                'next_at': next_opening(prefs, moment), 'required_tokens': required}
    limit = prefs['daily_tokens']
    if limit and usage['charged'] + usage['reserved'] + required > limit:
        too_large = required > limit
        return {'kind': 'request_budget' if too_large else 'daily_budget',
                'message': ('下一步预留量超过每日预算，请提高预算或缩小阅读范围' if too_large else
                            '等待每日额度 · 已完成步骤已保存，结算或次日恢复后继续'),
                'next_at': None if too_large or usage['reserved'] else next_opening(prefs, (moment + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)),
                'required_tokens': required}
    return None


def status():
    moment = local_now()
    with connect() as database:
        prefs = configuration(database); usage = totals(database, moment.date().isoformat())
        recent = [dict(row) for row in database.execute('SELECT u.*,b.title book_title FROM library_model_usage u '
            'LEFT JOIN library_jobs q ON q.id=u.job_id LEFT JOIN library_books b ON b.id=q.book_id '
            'ORDER BY u.started_at DESC,u.rowid DESC LIMIT 12')]
    return {'settings': prefs, 'day': moment.date().isoformat(), 'local_time': moment.isoformat(),
            'usage': usage, 'wait': admission(prefs, usage, moment), 'recent': recent,
            'remaining': max(0, prefs['daily_tokens'] - usage['charged'] - usage['reserved']) if prefs['daily_tokens'] else None}


class ReadingDeferred(Exception):
    def __init__(self, wait):
        self.wait = wait
        super().__init__(wait['message'])


def check_window():
    from .scheduling import execution_context
    if execution_context.get().get('library_foreground'):return
    moment = local_now(); prefs = configuration()
    if not window_allowed(prefs, moment):
        raise ReadingDeferred({'kind': 'window', 'message': '等待允许的阅读时段 · 已完成步骤已保存',
            'next_at': next_opening(prefs, moment), 'required_tokens': 1})


def wait_for_job(row):
    if row['kind'] not in ('read','ranges'): return None
    required = (unj(row['result_json'], {}).get('policy_wait') or {}).get('required_tokens', 1)
    moment = local_now()
    with connect() as database:
        return admission(configuration(database), totals(database, moment.date().isoformat()), moment, required,
                         ignore_window=bool(unj(row['payload_json'],{}).get('foreground')))


def mark_wait(ident, wait):
    with connect() as database:
        row = database.execute('SELECT status,result_json FROM library_jobs WHERE id=?', (ident,)).fetchone()
        if not row or row['status'] not in ('running', 'queued'): return
        result = unj(row['result_json'], {})
        if row['status'] == 'queued' and result.get('policy_wait') == wait: return
        result.update(policy_wait=wait, stage=wait['message'])
        database.execute("UPDATE library_jobs SET status='queued',error=NULL,result_json=?,updated_at=? WHERE id=? AND status IN ('running','queued')", (j(result), now(), ident))


def estimate(body):
    # Never encode/copy base64 images just to estimate usage.
    size = 1024
    for message in body.get('messages', []):
        content = message.get('content', '')
        if isinstance(content, str): size += len(content.encode('utf-8'))
        elif isinstance(content, list):
            for part in content:
                if part.get('type') == 'text': size += len(str(part.get('text', '')).encode('utf-8'))
                elif part.get('type') in ('image_url', 'localImage'): size += 4096
    return size + max(8192, body.get('max_tokens') or 0)


def reported_total(packet):
    if not isinstance(packet, dict): return None
    native = packet.get('usageMetadata') or {}
    usage = packet.get('usage') or {}
    if not isinstance(native, dict) or not isinstance(usage, dict): return None
    value = native.get('totalTokenCount', usage.get('total_tokens'))
    return value if type(value) is int and value >= 0 else None


class Meter:
    def __init__(self, ident=None): self.ident = ident; self.reported = None
    def accept(self, packet):
        value = reported_total(packet)
        if self.ident and value is not None: self.reported = value


@contextmanager
def model_request(body, provider):
    """One reservation per actual attempt, after its shared model slot opens."""
    from .scheduling import execution_context
    context = execution_context.get()
    if not context.get('library_reading') or not context.get('job_id'):
        yield Meter(); return
    moment = local_now(); required = estimate(body); ident = uid()
    with connect() as database:
        database.execute('BEGIN IMMEDIATE')
        prefs = configuration(database); usage = totals(database, moment.date().isoformat())
        wait = admission(prefs, usage, moment, required,ignore_window=bool(context.get('library_foreground')))
        if wait: raise ReadingDeferred(wait)
        row = database.execute('SELECT status FROM library_jobs WHERE id=?', (context['job_id'],)).fetchone()
        if not row or row['status'] == 'cancelled':
            import asyncio
            raise asyncio.CancelledError()
        database.execute('INSERT INTO library_model_usage(id,day,job_id,provider,model,reserved_tokens,status,started_at) VALUES (?,?,?,?,?,?,?,?)',
            (ident, moment.date().isoformat(), context['job_id'], provider, body.get('model'), required, 'inflight', now()))
    meter = Meter(ident); succeeded = False
    try:
        yield meter; succeeded = True
    finally:
        # An unreported/failed request may still have been billed: retain its
        # reservation rather than releasing budget and retrying without limit.
        charged = meter.reported if meter.reported is not None else required
        state = 'reported' if meter.reported is not None else 'estimated' if succeeded else 'uncertain'
        execute("UPDATE library_model_usage SET charged_tokens=?,reported_tokens=?,status=?,finished_at=? WHERE id=? AND status='inflight'",
                (charged, meter.reported, state, now(), ident))


def recover_requests():
    execute("UPDATE library_model_usage SET charged_tokens=reserved_tokens,status='uncertain',finished_at=? WHERE status='inflight'", (now(),))
