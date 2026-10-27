"""Persistent, stable project/chat navigation; removing a project is recoverable."""
from __future__ import annotations

from .db import connect, execute, j, many, now, one, unj


def removed(project_id):
    return bool(project_id and one('SELECT 1 FROM removed_projects WHERE project_id=?', (project_id,)))


def require_project(project_id):
    row = one('SELECT * FROM projects WHERE id=?', (project_id,))
    if not row or removed(project_id):
        raise ValueError('项目不存在或已移入回收站')
    return row


def projects():
    return many('SELECT p.*,COALESCE(n.pinned,0) AS pinned,COALESCE(n.position,0) AS position '
                'FROM projects p LEFT JOIN project_navigation n ON n.project_id=p.id '
                'WHERE NOT EXISTS (SELECT 1 FROM removed_projects r WHERE r.project_id=p.id) '
                'ORDER BY pinned DESC,position,p.created_at DESC,p.id')


def title(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120 or any(ord(c) < 32 for c in value):
        raise ValueError('名称须为 1 到 120 字符的单行文本')
    return value.strip()


def item(kind, item_id):
    if kind == 'project':
        return require_project(item_id)
    if kind != 'conversation':
        raise ValueError('不支持的侧边栏项目类型')
    from .conversations import detail
    row = one('SELECT project_id FROM conversations WHERE id=?', (item_id,))
    if not row:
        raise ValueError('学习对话不存在')
    require_project(row['project_id'])
    return detail(item_id, row['project_id'])


def update_item(kind, item_id, name=None, pinned=None):
    row = item(kind, item_id)
    if name is not None:
        name = title(name)
    if pinned is not None and type(pinned) is not bool:
        raise ValueError('置顶须为开关值')
    table, key = ('project_navigation', 'project_id') if kind == 'project' else ('conversation_navigation', 'conversation_id')
    with connect() as database:
        if name is not None:
            if kind == 'project':
                database.execute('UPDATE projects SET name=? WHERE id=?', (name, item_id))
            else:
                database.execute('UPDATE conversation_workspaces SET title=?,title_manual=1 WHERE conversation_id=?', (name, item_id))
        if pinned is not None:
            database.execute(f'INSERT INTO {table}({key},pinned) VALUES (?,?) ON CONFLICT({key}) DO UPDATE SET pinned=excluded.pinned', (item_id, int(pinned)))
    return item(kind, item_id)


def preferences():
    saved = one("SELECT value FROM workspace_state WHERE key='navigation_preferences'")
    active = one("SELECT value FROM workspace_state WHERE key='active_project'") if not saved else None
    value = unj(saved['value'], {}) if saved else {'expanded':[active['value']] if active else []}
    return {'sort': value.get('sort', 'manual'), 'expanded': value.get('expanded', [])}


def save_preferences(changes):
    if 'sort' in changes and changes['sort'] not in {'manual', 'recent', 'name'}:
        raise ValueError('排序方式无效')
    if 'expanded' in changes and (not isinstance(changes['expanded'], list) or len(changes['expanded']) > 2000
            or any(not isinstance(value, str) or len(value) > 100 for value in changes['expanded'])):
        raise ValueError('项目展开列表无效')
    values = preferences() | {key: value for key, value in changes.items() if key in {'sort', 'expanded'}}
    execute("INSERT INTO workspace_state VALUES ('navigation_preferences',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (j(values),))
    return values


def reorder(kind, ids, project_id=None):
    if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids) or len(ids) != len(set(ids)):
        raise ValueError('排序列表无效')
    if kind == 'project':
        expected = {row['id'] for row in projects()}
        table, key = 'project_navigation', 'project_id'
    elif kind == 'conversation':
        require_project(project_id)
        expected = {row['id'] for row in many('SELECT id FROM conversations c WHERE project_id=? '
                    'AND NOT EXISTS (SELECT 1 FROM deleted_conversations d WHERE d.conversation_id=c.id)', (project_id,))}
        table, key = 'conversation_navigation', 'conversation_id'
    else:
        raise ValueError('排序项目类型无效')
    if set(ids) != expected:
        raise ValueError('列表已变化，请刷新后排序；不能跨项目移动对话')
    with connect() as database:
        for position, item_id in enumerate(ids):
            database.execute(f'INSERT INTO {table}({key},position) VALUES (?,?) ON CONFLICT({key}) DO UPDATE SET position=excluded.position', (item_id, position))
    save_preferences({'sort': 'manual'})


def tree():
    from . import conversations
    folders = projects()
    counts = many("SELECT project_id,json_extract(payload_json,'$.conversation_id') AS conversation_id,COUNT(*) AS n "
                  "FROM jobs WHERE status IN ('queued','running','pausing','paused') GROUP BY project_id,conversation_id")
    drafts = {row['conversation_id']: bool(row['draft']) for row in many('SELECT conversation_id,draft FROM conversation_workspaces')}
    for folder in folders:
        folder['conversations'] = conversations.list_project(folder['id'])['conversations']
        folder['latest_message_at'] = max((chat['updated_at'] for chat in folder['conversations']), default=folder['created_at'])
        folder_counts = [row for row in counts if row['project_id'] == folder['id']]
        folder['pending_count'] = sum(row['n'] for row in folder_counts)
        for chat in folder['conversations']:
            chat['pending_count'] = sum(row['n'] for row in folder_counts if row['conversation_id'] == chat['id'])
            chat['has_draft'] = drafts.get(chat['id'], False)
    return {'projects': folders, 'preferences': preferences()}


def impact(kind, item_id):
    row = item(kind, item_id)
    project_id = row['id'] if kind == 'project' else row['project_id']
    where, params = ('project_id=?', (project_id,)) if kind == 'project' else (
        "project_id=? AND json_extract(payload_json,'$.conversation_id')=?", (project_id, item_id))
    jobs = one(f"SELECT COUNT(*) AS n FROM jobs WHERE {where} AND status IN ('queued','running','pausing','paused')", params)['n']
    result = {'kind': kind, 'id': item_id, 'project_id': project_id, 'name': row.get('name') or row['title'], 'pending_count': jobs}
    if kind == 'project':
        result.update(conversation_count=one('SELECT COUNT(*) AS n FROM conversations c WHERE project_id=? AND NOT EXISTS (SELECT 1 FROM deleted_conversations d WHERE d.conversation_id=c.id)', (project_id,))['n'],
                      source_count=one('SELECT COUNT(*) AS n FROM sources WHERE project_id=?', (project_id,))['n'],
                      artifact_count=one('SELECT COUNT(*) AS n FROM artifacts WHERE project_id=?', (project_id,))['n'])
    else:
        result['message_count'] = one('SELECT COUNT(*) AS n FROM messages WHERE conversation_id=?', (item_id,))['n']
    return result


def recycle():
    return many('SELECT p.id,p.name,r.removed_at,(SELECT COUNT(*) FROM sources WHERE project_id=p.id) AS source_count,'
                '(SELECT COUNT(*) FROM artifacts WHERE project_id=p.id) AS artifact_count FROM projects p '
                'JOIN removed_projects r ON r.project_id=p.id ORDER BY r.removed_at DESC,p.id')


def restore(project_id):
    if not one('SELECT 1 FROM projects WHERE id=?', (project_id,)):
        raise ValueError('项目不存在')
    execute('DELETE FROM removed_projects WHERE project_id=?', (project_id,))
    return require_project(project_id)


def request_project_id(path, query):
    """Reject archived resource URLs, even when callers retained an old ID."""
    parts = path.strip('/').split('/')
    if len(parts) < 3 or parts[0] != 'api':
        return None
    if parts[1] == 'projects':
        if len(parts) == 4 and parts[3] == 'restore':
            return None
        return parts[2]
    if parts[1:3] == ['agent', 'assets'] and len(parts) > 3:
        row = one('SELECT project_id FROM agent_assets WHERE id=?', (parts[3],))
        return row['project_id'] if row else None
    tables = {'conversations': 'conversations', 'sources': 'sources', 'artifacts': 'artifacts', 'jobs': 'jobs',
              'categories': 'source_categories', 'exercises': 'exercise_sets', 'coding': 'exercise_sets',
              'lesson-feedback': 'lesson_questionnaires', 'knowledge': 'knowledge_maps'}
    if parts[1:3] == ['knowledge', 'reading']:
        table, resource_id = 'reading_sessions', parts[3] if len(parts) > 3 else ''
    elif parts[1:3] == ['lesson-feedback', 'by-job']:
        table, resource_id = 'jobs', parts[3] if len(parts) > 3 else ''
    else:
        table, resource_id = tables.get(parts[1]), parts[2]
    if not table:
        return None
    # Collection actions such as /coding/generate carry project_id in their body
    # and already use require_project; only resolve real stored resource IDs.
    row = one(f'SELECT project_id FROM {table} WHERE id=?', (resource_id,))
    if not row and table == 'lesson_questionnaires':
        row = one('SELECT project_id FROM lesson_content_checks WHERE id=?', (resource_id,))
    return row['project_id'] if row else query.get('project_id')
