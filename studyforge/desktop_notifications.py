"""Durable, application-wide desktop events. No model calls or chat content."""
from datetime import datetime, timedelta, timezone

from .db import connect, j, now, unj

DEFAULTS = {
    'desktop_notifications_enabled': True,
    'desktop_notifications_sound': True,
    'desktop_notifications_foreground': True,
    'desktop_notifications_complete': True,
    'desktop_notifications_approval': True,
    'desktop_notifications_failure': True,
    'desktop_notifications_questionnaire': True,
    'desktop_notifications_chat': True,
    'desktop_notifications_update': True,
}


def validate_settings(value):
    for key in DEFAULTS:
        if key in value and type(value[key]) is not bool:
            raise ValueError('桌面通知设置必须是开关值')


def _text(value, limit):
    return ' '.join(str(value or '').split())[:limit]


def _context(db, project_id, conversation_id=None):
    project = db.execute('SELECT p.name FROM projects p WHERE p.id=? AND NOT EXISTS '
                         '(SELECT 1 FROM removed_projects r WHERE r.project_id=p.id)', (project_id,)).fetchone()
    if not project:
        return None
    title = project['name']
    if conversation_id:
        chat = db.execute('SELECT w.title FROM conversations c LEFT JOIN conversation_workspaces w ON w.conversation_id=c.id '
                          'WHERE c.id=? AND c.project_id=? AND NOT EXISTS '
                          '(SELECT 1 FROM deleted_conversations d WHERE d.conversation_id=c.id)',
                          (conversation_id, project_id)).fetchone()
        if not chat:
            return None
        title += ' / ' + (chat['title'] or '学习对话')
    return _text(title, 130)


def enqueue(db, key, category, title, detail, target, timestamp=None):
    """Called in the same transaction as a reply, or by the snapshot collector."""
    # INSERT OR IGNORE still advances SQLite's AUTOINCREMENT sequence. Check
    # the unique key first so idle polling does not keep writing to disk.
    if db.execute('SELECT 1 FROM desktop_notices WHERE notice_key=?', (key,)).fetchone():
        return
    context = _notice_context(db, target)
    if context is None:
        return
    db.execute('INSERT OR IGNORE INTO desktop_notices(notice_key,category,title,body,target_json,created_at) '
               'VALUES (?,?,?,?,?,?)', (key, category, _text(title, 100), context + '\n' + _text(detail, 240),
                                       j(target), timestamp or now()))


def _notice_context(db,target):
    if target.get('view')=='library' and target.get('book_id'):
        row=db.execute('SELECT title FROM library_books WHERE id=?',(target['book_id'],)).fetchone()
        return ('全局书库 / '+_text(row['title'],130)) if row else None
    return _context(db,target.get('project_id'),target.get('conversation_id'))


def _live(db, target, category, *, pending=False):
    if _notice_context(db,target) is None:
        return False
    if target.get('library_job_id'):
        row=db.execute('SELECT status FROM library_jobs WHERE id=? AND book_id=?',(target['library_job_id'],target.get('book_id'))).fetchone()
        if not row or row['status']=='cancelled':return False
        if pending and category=='failure' and row['status']!='failed':return False
    if target.get('job_id'):
        job = db.execute('SELECT status FROM jobs WHERE id=? AND NOT EXISTS '
                         '(SELECT 1 FROM deleted_job_records d WHERE d.job_id=jobs.id)', (target['job_id'],)).fetchone()
        if not job or job['status'] == 'cancelled':
            return False
        if pending and category == 'failure' and job['status'] != 'failed':
            return False
    if target.get('artifact_id') and not db.execute('SELECT 1 FROM artifacts WHERE id=?', (target['artifact_id'],)).fetchone():
        return False
    if pending and category == 'approval':
        row = db.execute('SELECT status FROM agent_approvals WHERE id=?', (target['approval_id'],)).fetchone()
        return bool(row and row['status'] == 'pending')
    if pending and category == 'questionnaire':
        row = db.execute('SELECT status FROM homework_attempts WHERE id=?', (target['homework_attempt_id'],)).fetchone()
        return bool(row and row['status'] == 'awaiting_causes')
    return True


def _collect(db):
    since = db.execute("SELECT value FROM workspace_state WHERE key='desktop_notices_since'").fetchone()[0]
    cutoff = max(since, (datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
    timestamp = now()
    for row in db.execute('SELECT * FROM artifacts WHERE created_at>=? ORDER BY created_at,id', (cutoff,)).fetchall():
        meta = unj(row['metadata_json'], {})
        target = {'view': 'artifacts', 'project_id': row['project_id'], 'conversation_id': meta.get('conversation_id'),
                  'artifact_id': row['id'], 'job_id': meta.get('reexport_job_id') or meta.get('generation_job_id')}
        if _live(db, target, 'complete'):
            enqueue(db, 'artifact:' + row['id'], 'complete', '成果已完成',
                    row['title'] + ' · ' + row['format'].upper() + '，点击查看。', target, row['created_at'])
    labels = {'export':'讲解格式另存','generate': '文档生成', 'import': '资料导入', 'import_url': '网址导入', 'import_video': '视频导入', 'url': '网址导入', 'read': '资料通读',
              'knowledge': '知识结构整理', 'homework': '作业批改', 'homework_grade': '作业批改', 'grade': '习题批改', 'coding': '编程作业'}
    for row in db.execute("SELECT * FROM jobs WHERE updated_at>=? AND status IN ('completed','failed')", (cutoff,)).fetchall():
        payload = unj(row['payload_json'], {})
        target = {'view': 'artifacts', 'project_id': row['project_id'], 'conversation_id': payload.get('conversation_id'), 'job_id': row['id']}
        if not _live(db, target, 'failure' if row['status'] == 'failed' else 'complete'):
            continue
        label = labels.get(row['kind'], '学习任务')
        if row['status'] == 'failed':
            enqueue(db, 'failed:' + row['id'] + ':' + row['updated_at'], 'failure', label + '未完成',
                    '点击查看错误详情并重试；已经保存的资料和成果仍保留。', target, row['updated_at'])
        elif not db.execute("SELECT 1 FROM artifacts WHERE json_extract(metadata_json,'$.generation_job_id')=?", (row['id'],)).fetchone():
            if row['kind'] in ('import', 'url', 'import_url', 'import_video'):
                target['view'] = 'sources'
            elif row['kind'] in ('read', 'knowledge'):
                target['view'] = 'study'
            enqueue(db, 'completed:' + row['id'], 'complete', label + '已完成', '点击回到对应项目查看。', target, row['updated_at'])
    actions = []
    for row in db.execute("SELECT * FROM agent_approvals WHERE status='pending'").fetchall():
        target = {'view': 'study', 'project_id': row['project_id'], 'conversation_id': row['conversation_id'],
                  'job_id': row['job_id'], 'approval_id': row['id']}
        if not _live(db, target, 'approval', pending=True):
            continue
        key = 'approval:' + row['id']; actions.append(key)
        enqueue(db, key, 'approval', 'AI 正在等待你的审批',
                '原任务已悬置。点击查看文件操作，再决定允许或拒绝。', target, timestamp)
    for row in db.execute("SELECT * FROM homework_attempts WHERE status='awaiting_causes'").fetchall():
        target = {'view': 'study', 'project_id': row['project_id'], 'conversation_id': row['conversation_id'],
                  'job_id': row['job_id'], 'homework_attempt_id': row['id']}
        if not _live(db, target, 'questionnaire', pending=True):
            continue
        key = 'causes:' + row['id']; actions.append(key)
        enqueue(db, key, 'questionnaire', '请填写错因问卷，批改文档正在等待',
                '原题与解析已经可看。填写后，导师会继续分析错因并生成针对性讲解。', target, timestamp)
    return actions


def feed():
    from .ai import settings
    config = settings()
    with connect() as db:
        actions = _collect(db)
        events = []
        for row in db.execute("SELECT * FROM desktop_notices WHERE status='pending' ORDER BY "
                              "CASE WHEN category IN ('approval','questionnaire') THEN 0 WHEN category='failure' THEN 1 ELSE 2 END,id LIMIT 200").fetchall():
            target = unj(row['target_json'], {})
            stale = row['category'] not in ('approval', 'questionnaire') and datetime.fromisoformat(row['created_at']) < datetime.now(timezone.utc) - timedelta(days=1)
            if stale or not _live(db, target, row['category'], pending=True):
                db.execute("UPDATE desktop_notices SET status='dismissed' WHERE id=?", (row['id'],))
                continue
            if len(events) < 40:
                events.append(_public(row))
        recent = [_public(row) | {'action_pending': row['notice_key'] in actions} for row in db.execute(
                  "SELECT * FROM desktop_notices ORDER BY CASE WHEN notice_key IN "
                  "(SELECT 'approval:'||id FROM agent_approvals WHERE status='pending' UNION ALL "
                  "SELECT 'causes:'||id FROM homework_attempts WHERE status='awaiting_causes') THEN 0 ELSE 1 END,id DESC LIMIT 50").fetchall()
                  if _live(db, unj(row['target_json'], {}), row['category'])]
    return {'events': events, 'recent': recent, 'active_actions': actions, 'settings': {key: config[key] for key in DEFAULTS}}


def _public(row):
    return {key: row[key] for key in ('id', 'notice_key', 'category', 'title', 'body', 'created_at', 'status')} | {'target': unj(row['target_json'], {})}


def acknowledge(ids, status):
    if status not in ('sent', 'skipped', 'failed') or len(ids) > 40 or any(type(ident) is not int or ident < 1 for ident in ids):
        raise ValueError('通知回执无效')
    with connect() as db:
        db.executemany("UPDATE desktop_notices SET status=?,delivered_at=? WHERE id=? AND (status='pending' OR (?='failed' AND status='sent'))",
                       [(status, now(), ident, status) for ident in ids])
    return {'ok': True}
