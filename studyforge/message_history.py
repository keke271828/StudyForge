"""Bounded display pages. Model context and the legacy full-history API stay intact."""
from __future__ import annotations

import base64
import json

from .db import connect


def cursor(conversation_id, row):
    return base64.urlsafe_b64encode(json.dumps([conversation_id, row['created_at'], row['_order']],
        separators=(',', ':')).encode()).decode().rstrip('=')


def boundary(value, conversation_id):
    try:
        if not isinstance(value, str) or len(value) > 1024:
            raise ValueError()
        scope, stamp, ordinal = json.loads(base64.b64decode(value + '=' * (-len(value) % 4),
            altchars=b'-_', validate=True))
        if scope != conversation_id or not isinstance(stamp, str) or len(stamp) > 80 \
                or type(ordinal) is not int or not 0 < ordinal < 2 ** 63:
            raise ValueError()
        return stamp, ordinal
    except (ValueError, TypeError, UnicodeError):
        raise ValueError('聊天分页位置已失效，请重新打开当前对话') from None


def page(conversation_id, project_id, *, limit=None, before=None, start=None, since=None):
    if limit is not None and not 1 <= limit <= 200:
        raise ValueError('每页聊天数量须为 1–200')
    if since is not None and since < 0:
        raise ValueError('聊天版本号无效')
    if before and start:
        raise ValueError('不能同时指定向前翻页和已显示范围')
    cut = boundary(before or start, conversation_id) if before or start else None
    with connect() as database:
        # Revision, rows and the older-page marker describe one read snapshot.
        database.execute('BEGIN')
        if not database.execute('SELECT id FROM conversations WHERE id=? AND project_id=? '
                'AND NOT EXISTS (SELECT 1 FROM deleted_conversations WHERE conversation_id=?)',
                (conversation_id, project_id, conversation_id)).fetchone():
            raise LookupError('学习对话不存在或不属于当前项目')
        version = database.execute('SELECT revision FROM conversation_history_versions WHERE conversation_id=?',
                                   (conversation_id,)).fetchone()
        revision = version['revision'] if version else 0
        if since == revision and not before:
            return {'not_modified': True, 'history': {'revision': revision}}
        clauses = ['conversation_id=?']
        arguments = [conversation_id]
        if cut:
            comparison, equality = ('<', '<') if before else ('>', '>=')
            clauses.append(f'(created_at {comparison} ? OR (created_at=? AND rowid {equality} ?))')
            arguments.extend([cut[0], cut[0], cut[1]])
        tail = limit is not None and not start
        order = 'created_at DESC,rowid DESC' if tail else 'created_at,rowid'
        suffix = ' LIMIT ?' if tail else ''
        if tail:
            arguments.append(limit)
        rows = [dict(row) for row in database.execute('SELECT id,role,content,created_at,rowid AS _order '
                'FROM messages WHERE ' + ' AND '.join(clauses) + ' ORDER BY ' + order + suffix, arguments)]
        if tail:
            rows.reverse()
        from .message_focus import attach
        rows=attach(rows,conversation_id,database)
        first = rows[0] if rows else None
        anchor = (first['created_at'], first['_order']) if first else cut if start else None
        has_older = bool(anchor and database.execute('SELECT 1 FROM messages WHERE conversation_id=? '
            'AND (created_at<? OR (created_at=? AND rowid<?)) LIMIT 1',
            (conversation_id, anchor[0], anchor[0], anchor[1])).fetchone())
        return {'messages': rows, 'not_modified': False, 'history': {'revision': revision,
            'has_older': has_older, 'oldest_cursor': cursor(conversation_id, first) if first else start}}
