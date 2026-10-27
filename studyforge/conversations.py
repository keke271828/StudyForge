"""Local, persistent project conversations, independent of model thread lifetime."""
from __future__ import annotations

import re

from .db import connect, execute, j, many, now, one, uid, unj
from .learning import reading_context, source_fingerprint, reading_content_matches
from .learning_modes import resolve_mode
from .teaching_styles import resolve_style, resolve_language, resolve_review_mode, save_conversation_preferences


def automatic_title(text: str) -> str:
    title = re.sub(r'\s+', ' ', text).strip().lstrip('# ')[:36]
    return title or '新对话'


def is_deleted(conversation_id):
    if not conversation_id: return False
    from .navigation import removed
    row = one('SELECT project_id FROM conversations WHERE id=?', (conversation_id,))
    return bool(one('SELECT conversation_id FROM deleted_conversations WHERE conversation_id=?', (conversation_id,)) or row and removed(row['project_id']))


def touch(conversation_id: str, text: str = '') -> None:
    row = one('SELECT * FROM conversations WHERE id=?', (conversation_id,))
    if not row:
        return
    first = one("SELECT content FROM messages WHERE conversation_id=? AND role='user' "
                'ORDER BY created_at,rowid LIMIT 1', (conversation_id,))
    title = automatic_title((first or {}).get('content') or text)
    timestamp = now()
    execute('INSERT INTO conversation_workspaces(conversation_id,title,updated_at,opened_at) VALUES (?,?,?,?) '
            'ON CONFLICT(conversation_id) DO UPDATE SET updated_at=excluded.updated_at, '
            "title=CASE WHEN title_manual=0 AND title='新对话' THEN excluded.title ELSE title END",
            (conversation_id, title, timestamp, timestamp))


def backfill(project_id: str) -> None:
    # Recover legacy histories without creating model requests or discarding messages.
    for row in many('SELECT c.* FROM conversations c LEFT JOIN conversation_workspaces w '
                    'ON w.conversation_id=c.id WHERE c.project_id=? AND w.conversation_id IS NULL', (project_id,)):
        first = one("SELECT content FROM messages WHERE conversation_id=? AND role='user' ORDER BY created_at,rowid LIMIT 1", (row['id'],))
        last = one('SELECT created_at FROM messages WHERE conversation_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1', (row['id'],))
        stamp = (last or row)['created_at']
        execute('INSERT OR IGNORE INTO conversation_workspaces(conversation_id,title,updated_at,opened_at) VALUES (?,?,?,?)',
                (row['id'], automatic_title((first or {}).get('content', '')), stamp, stamp))
        if not one('SELECT conversation_id FROM conversation_learning_modes WHERE conversation_id=?', (row['id'],)):
            from .learning_modes import save_conversation_mode
            save_conversation_mode(row['id'], resolve_mode())
    for row in many('SELECT c.id FROM conversations c LEFT JOIN conversation_teaching_styles s '
                    'ON s.conversation_id=c.id WHERE c.project_id=? AND s.conversation_id IS NULL', (project_id,)):
        save_conversation_preferences(row['id'])


def create(project_id: str, provider: str, model=None, effort=None, model_choice=None, explanation_style=None,
           output_language=None, review_mode=None, *, activate_workspace=True) -> dict:
    from .navigation import require_project
    require_project(project_id)
    style = resolve_style(explanation_style)
    language, review = resolve_language(output_language), resolve_review_mode(review_mode)
    conversation_id, timestamp = uid(), now()
    execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)',
            (conversation_id, project_id, provider, None, timestamp, '[]', model, effort))
    touch(conversation_id)
    execute('INSERT INTO conversation_navigation(conversation_id,position) SELECT ?,COALESCE(MIN(n.position),0)-1 '
            'FROM conversation_navigation n JOIN conversations c ON c.id=n.conversation_id WHERE c.project_id=?', (conversation_id, project_id))
    from .learning_modes import save_conversation_mode
    save_conversation_mode(conversation_id, resolve_mode())
    save_conversation_preferences(conversation_id, explanation_style=style, output_language=language, review_mode=review)
    if model_choice is not None:
        execute('UPDATE conversation_workspaces SET model_choice=? WHERE conversation_id=?', (model_choice, conversation_id))
    if activate_workspace:
        activate(conversation_id)
    return detail(conversation_id, project_id)


def activate(conversation_id: str) -> None:
    if is_deleted(conversation_id): raise ValueError('学习对话已删除')
    row = one('SELECT project_id FROM conversations WHERE id=?', (conversation_id,))
    if not row:
        raise ValueError('学习对话不存在')
    timestamp = now()
    touch_if_missing(conversation_id, row['project_id'])
    with connect() as database:
        database.execute('UPDATE conversation_workspaces SET opened_at=? WHERE conversation_id=?', (timestamp, conversation_id))
        database.execute('INSERT INTO project_workspaces VALUES (?,?,?) ON CONFLICT(project_id) DO UPDATE SET '
                         'conversation_id=excluded.conversation_id,updated_at=excluded.updated_at',
                         (row['project_id'], conversation_id, timestamp))
        database.execute("INSERT INTO workspace_state VALUES ('active_project',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (row['project_id'],))


def touch_if_missing(conversation_id, project_id):
    if not one('SELECT conversation_id FROM conversation_workspaces WHERE conversation_id=?', (conversation_id,)):
        backfill(project_id)


def workspace() -> dict:
    saved = one("SELECT value FROM workspace_state WHERE key='active_project'")
    project_id = saved['value'] if saved else None
    if project_id and not one('SELECT id FROM projects WHERE id=?', (project_id,)):
        project_id = None
    from .navigation import removed
    if removed(project_id): project_id = None
    return {'project_id': project_id}


def list_project(project_id: str) -> dict:
    from .navigation import require_project
    require_project(project_id)
    backfill(project_id)
    rows = many('SELECT c.id,c.project_id,c.provider,c.model,c.reasoning_effort,c.created_at, '
                'w.title,w.updated_at,w.opened_at,COALESCE(n.pinned,0) AS pinned,COALESCE(n.position,0) AS position, '
                '(SELECT content FROM messages m WHERE m.conversation_id=c.id ORDER BY m.created_at DESC,m.rowid DESC LIMIT 1) AS last_message, '
                '(SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS message_count '
                'FROM conversations c JOIN conversation_workspaces w ON w.conversation_id=c.id '
                'LEFT JOIN conversation_navigation n ON n.conversation_id=c.id '
                'WHERE c.project_id=? AND NOT EXISTS (SELECT 1 FROM deleted_conversations WHERE conversation_id=c.id) '
                'ORDER BY pinned DESC,position,c.created_at DESC,c.id', (project_id,))
    for row in rows:
        row['last_message'] = re.sub(r'\s+', ' ', row['last_message'] or '')[:100]
    active = one('SELECT conversation_id FROM project_workspaces WHERE project_id=?', (project_id,))
    active_id = (active or {}).get('conversation_id')
    if not any(row['id'] == active_id for row in rows):
        active_id = rows[0]['id'] if rows else None
    return {'conversations': rows, 'active_conversation_id': active_id}


def detail(conversation_id: str, project_id: str, *, history_limit=None, history_start=None,
           include_history=True) -> dict:
    if is_deleted(conversation_id): raise ValueError('学习对话已删除')
    row = one('SELECT * FROM conversations WHERE id=? AND project_id=?', (conversation_id, project_id))
    if not row:
        raise ValueError('学习对话不存在或不属于当前项目')
    touch_if_missing(conversation_id, project_id)
    if not one('SELECT conversation_id FROM conversation_teaching_styles WHERE conversation_id=?', (conversation_id,)):
        save_conversation_preferences(conversation_id)
    meta = one('SELECT * FROM conversation_workspaces WHERE conversation_id=?', (conversation_id,))
    sources = unj(row['source_ids_json'], [])
    valid = [sid for sid in sources if one("SELECT id FROM sources WHERE id=? AND project_id=? AND status IN ('ready','stored')", (sid, project_id))]
    if valid != sources:
        execute('UPDATE conversations SET source_ids_json=?,remote_thread_id=NULL WHERE id=?', (j(valid), conversation_id))
        execute('DELETE FROM agent_dialogue_state WHERE conversation_id=?', (conversation_id,))
    from .learning_goals import focused
    goal=focused(project_id,conversation_id)
    if not include_history:
        history = {'messages': [], 'history_omitted': True}
    elif history_limit is not None or history_start:
        from .message_history import page
        display = page(conversation_id, project_id, limit=history_limit, start=history_start)
        history = {'messages': display['messages'], 'history': display['history']}
    else:
        from .message_focus import attach
        history = {'messages': attach(many('SELECT id,role,content,created_at FROM messages WHERE conversation_id=? ORDER BY created_at,rowid', (conversation_id,)),conversation_id)}
    return dict(row, source_ids=valid, **{k: meta[k] for k in ('title', 'draft', 'reading_id', 'model_choice', 'updated_at')},
                learning_goal={k:goal[k] for k in ('id','name','intent','paused')} if goal else None,
                learning_mode=resolve_mode(None, conversation_id), explanation_style=resolve_style(None, conversation_id),
                output_language=resolve_language(None, conversation_id), review_mode=resolve_review_mode(None, conversation_id),
                **history,
                removed_source_ids=[sid for sid in sources if sid not in valid])


def update(conversation_id: str, project_id: str, changes: dict, *, include_history=True) -> dict:
    if is_deleted(conversation_id): raise ValueError('学习对话已删除')
    row = detail(conversation_id, project_id, include_history=False)
    if 'explanation_style' in changes:
        changes['explanation_style'] = resolve_style(changes['explanation_style'])
    if 'output_language' in changes:
        changes['output_language'] = resolve_language(changes['output_language'])
    if 'review_mode' in changes:
        changes['review_mode'] = resolve_review_mode(changes['review_mode'])
    if 'source_ids' in changes:
        ids = list(dict.fromkeys(changes['source_ids']))
        for source_id in ids:
            if not one("SELECT id FROM sources WHERE id=? AND project_id=? AND status IN ('ready','stored')", (source_id, project_id)):
                raise ValueError('所选资料不存在、尚未解析或不属于当前项目')
        changes['source_ids'] = ids
    if 'reading_id' in changes and changes['reading_id']:
        reading = one('SELECT * FROM reading_sessions WHERE id=? AND project_id=?', (changes['reading_id'], project_id))
        if not reading or sorted(unj(reading['source_ids_json'], [])) != sorted(changes.get('source_ids', row['source_ids'])):
            raise ValueError('通读记录与当前对话资料不匹配')
    changed_scope = ('source_ids' in changes and sorted(changes['source_ids']) != sorted(row['source_ids'])) or (
        'provider' in changes and changes['provider'] != row['provider'])
    with connect() as database:
        for name in ('provider', 'model', 'reasoning_effort'):
            if name in changes:
                database.execute(f'UPDATE conversations SET {name}=? WHERE id=?', (changes[name], conversation_id))
        if 'source_ids' in changes:
            database.execute('UPDATE conversations SET source_ids_json=? WHERE id=?', (j(changes['source_ids']), conversation_id))
        if changed_scope:
            database.execute('UPDATE conversations SET remote_thread_id=NULL WHERE id=?', (conversation_id,))
            database.execute('DELETE FROM agent_dialogue_state WHERE conversation_id=?', (conversation_id,))
            database.execute('UPDATE conversation_workspaces SET reading_id=NULL WHERE conversation_id=?', (conversation_id,))
        for name in ('draft', 'reading_id', 'model_choice'):
            if name in changes:
                database.execute(f'UPDATE conversation_workspaces SET {name}=? WHERE conversation_id=?', (changes[name], conversation_id))
        if 'title' in changes:
            title = changes['title'].strip()
            if not title:
                raise ValueError('对话名称不能为空')
            database.execute('UPDATE conversation_workspaces SET title=?,title_manual=1 WHERE conversation_id=?', (title, conversation_id))
    if 'learning_mode' in changes:
        from .learning_modes import save_conversation_mode
        save_conversation_mode(conversation_id, changes['learning_mode'])
    preferences = {field: changes[field] for field in ('explanation_style', 'output_language', 'review_mode') if field in changes}
    if preferences: save_conversation_preferences(conversation_id, **preferences)
    return detail(conversation_id, project_id, include_history=include_history)


def delete_history(conversation_id, project_id):
    detail(conversation_id, project_id)
    with connect() as database:
        database.execute('DELETE FROM lesson_questionnaires WHERE conversation_id=?', (conversation_id,))
        database.execute('DELETE FROM generation_dialogue_outputs WHERE conversation_id=?', (conversation_id,))
        database.execute('DELETE FROM mentor_handoffs WHERE conversation_id=?', (conversation_id,))
        database.execute('DELETE FROM agent_dialogue_state WHERE conversation_id=?', (conversation_id,))
        database.execute('DELETE FROM agent_tool_events WHERE conversation_id=?', (conversation_id,))
        database.execute('DELETE FROM execution_spans WHERE conversation_id=?', (conversation_id,))
        database.execute("UPDATE learning_events SET payload_json='{}',status='completed' WHERE conversation_id=?", (conversation_id,))
        database.execute('DELETE FROM messages WHERE conversation_id=?', (conversation_id,))
        database.execute("UPDATE conversation_workspaces SET draft='',reading_id=NULL WHERE conversation_id=?", (conversation_id,))
        database.execute("UPDATE conversations SET remote_thread_id=NULL,source_ids_json='[]' WHERE id=?", (conversation_id,))
        database.execute('INSERT INTO deleted_conversations VALUES (?,?)', (conversation_id, now()))
        database.execute('UPDATE project_workspaces SET conversation_id=NULL WHERE conversation_id=?', (conversation_id,))
        for row in database.execute("SELECT id,payload_json FROM jobs WHERE json_extract(payload_json,'$.conversation_id')=?", (conversation_id,)).fetchall():
            payload = unj(row['payload_json'], {})
            for field in ('dialogue_snapshot','mentor_snapshot'):
                if field in payload:
                    payload[field]['messages'] = []
                    payload[field].get('mentor',{}).pop('remote_thread_id',None)
            for field in ('instructions','resolved_requirements'):
                payload.pop(field, None)
            database.execute('UPDATE jobs SET payload_json=? WHERE id=?', (j(payload), row['id']))
            database.execute('DELETE FROM generation_steps WHERE job_id=?', (row['id'],))


def reading_task(project_id, conversation_id, source_ids, provider, model, effort):
    """Restore exact-chat progress without loading private task bodies or rereading files."""
    if not conversation_id or not source_ids:
        return None
    from . import task_progress
    sources=j(sorted(set(source_ids)))
    payload="CASE WHEN json_valid(payload_json) THEN payload_json ELSE '{}' END"
    row=one('SELECT '+task_progress.columns()+" FROM jobs WHERE project_id=? AND kind='read' "
        f"AND json_extract({payload},'$.conversation_id')=? "
        f"AND json_extract({payload},'$.provider')=? "
        f"AND COALESCE(json_extract({payload},'$.model'),'')=? "
        f"AND COALESCE(json_extract({payload},'$.reasoning_effort'),'')=? "
        f"AND json_type({payload},'$.source_ids')='array' "
        f"AND NOT EXISTS (SELECT 1 FROM json_each({payload},'$.source_ids') WHERE value NOT IN (SELECT value FROM json_each(?))) "
        f"AND NOT EXISTS (SELECT 1 FROM json_each(?) WHERE value NOT IN (SELECT value FROM json_each({payload},'$.source_ids'))) "
        'AND NOT EXISTS (SELECT 1 FROM deleted_job_records WHERE job_id=jobs.id) '
        'ORDER BY created_at DESC,rowid DESC LIMIT 1',
        (project_id,conversation_id,provider,model or '',effort or '',sources,sources))
    if not row or row['status'] not in ('queued','running','pausing','paused','failed'):
        return None
    task_progress.expand(row)
    from .task_recovery import capabilities
    row['recovery']=capabilities([row]).get(row['id'])
    row['can_pause']=bool(unj(row['payload_json'],{}).get('source_ids'))
    row['payload']=task_progress.public_payload(unj(row.pop('payload_json'),{}))
    row['result']=unj(row.pop('result_json'),{})
    from .task_retry import public
    row['retry']=public('project',row['id'])
    return row


def cached_reading(project_id, source_ids, provider, model, effort):
    if not source_ids:
        return None
    candidates = many('SELECT source_ids_json FROM reading_sessions WHERE project_id=?', (project_id,))
    if not any(sorted(unj(row['source_ids_json'], [])) == sorted(source_ids) for row in candidates):
        return None
    # Revalidate bytes and extracted assets, but never call a model on restore.
    from .materials import read_original_sources
    records = []
    for sid in source_ids:
        row = one("SELECT * FROM sources WHERE id=? AND project_id=? AND status='ready'", (sid, project_id))
        if not row:
            return None
        records.append(dict(row, segments=unj(row['segments_json'], [])))
    originals = read_original_sources(records)
    row = one('SELECT * FROM reading_sessions WHERE project_id=? AND fingerprint=? AND provider=? '
              "AND COALESCE(model,'')=? AND COALESCE(reasoning_effort,'')=? ORDER BY created_at DESC LIMIT 1",
              (project_id, source_fingerprint(originals), provider, model or '', effort or ''))
    if not row or not reading_content_matches(unj(row['source_reading_json'], []), originals):
        return None
    return {'status': 'completed', 'reading_id': row['id'], 'notes': reading_context(unj(row['notes_json'], [])),
            'cached': True, 'source_reading': unj(row['source_reading_json'], [])}
