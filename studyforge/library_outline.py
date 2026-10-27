"""Atomic directory moves. Node IDs and authorized reading scopes never change."""
from __future__ import annotations

import hashlib

from .db import connect, j, now, uid, unj


class OutlineConflict(ValueError):
    """Another window changed this directory after the user chose a move."""


def revision(nodes):
    values = sorted(((n['id'], n['parent_id'], n['position']) for n in nodes), key=lambda n: (n[2], n[0]))
    return hashlib.sha256(j(values).encode('utf-8')).hexdigest()


def _forest(nodes):
    by_id = {n['id']: n for n in nodes}
    children = {None: [], **{ident: [] for ident in by_id}}
    for n in sorted(nodes, key=lambda n: (n['position'], n['id'])):
        if n['parent_id'] not in children or n['parent_id'] == n['id']:
            raise ValueError('原目录层级无效，请先核对目录归属')
        children[n['parent_id']].append(n['id'])
    _ordered(by_id, children)  # Detect a disconnected cycle before any writes.
    return by_id, children


def _ordered(by_id, children):
    result, seen = [], set()
    stack = list(reversed(children[None]))
    while stack:
        ident = stack.pop()
        if ident in seen: raise ValueError('目录不能包含循环归属')
        seen.add(ident); result.append(ident)
        stack.extend(reversed(children[ident]))
    if len(result) != len(by_id): raise ValueError('目录不能包含循环归属')
    return result


def _store(db, book_id, by_id, children, parent_changes=None):
    timestamp, changes = now(), []
    parent_changes = parent_changes or {}
    for original in by_id.values():
        provenance=unj(original.get('provenance_json','{}'),{})
        saved=dict(provenance)
        saved.setdefault('directory_order',original['position'])
        saved.setdefault('directory_parent_id',original['parent_id'])
        saved.setdefault('directory_kind',original['kind'])
        if saved!=provenance:
            db.execute('UPDATE library_nodes SET provenance_json=? WHERE id=?',(j(saved),original['id']))
    for position, ident in enumerate(_ordered(by_id, children)):
        old = by_id[ident]; parent = parent_changes.get(ident, old['parent_id'])
        kind = 'section' if parent else 'chapter'
        if (position, parent, kind) != (old['position'], old['parent_id'], old['kind']):
            changes.append((position, parent, kind, timestamp, ident))
        by_id[ident] = old | {'position': position, 'parent_id': parent, 'kind': kind}
    if changes:
        db.executemany('UPDATE library_nodes SET position=?,parent_id=?,kind=?,updated_at=? WHERE id=?', changes)
        db.execute('UPDATE library_books SET updated_at=? WHERE id=?', (timestamp, book_id))
    return len(changes), revision(by_id.values())


def _load(db, book_id):
    if not db.execute('SELECT id FROM library_books WHERE id=?', (book_id,)).fetchone():
        raise ValueError('书籍不存在或已删除')
    return [dict(n) for n in db.execute('SELECT * FROM library_nodes WHERE book_id=? ORDER BY position,id', (book_id,))]


def add(book_id, title, parent_id=None):
    title = str(title).strip()
    if not title: raise ValueError('节点标题不能为空')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        nodes = _load(db, book_id)
        by_id, children = _forest(nodes)
        if parent_id is not None and parent_id not in by_id: raise ValueError('父节点不属于本书')
        ident = uid(); position = len(nodes)
        kind = 'section' if parent_id else 'chapter'
        db.execute('INSERT INTO library_nodes(id,book_id,parent_id,position,title,kind,provenance_json,updated_at) '
                   'VALUES (?,?,?,?,?,?,?,?)',
                   (ident, book_id, parent_id, position, title, kind, j({'method': 'manual'}), now()))
        by_id[ident] = {'id': ident, 'parent_id': parent_id, 'position': position, 'kind': kind,
                        'provenance_json': j({'method': 'manual'})}
        children[ident] = []; children[parent_id].append(ident)
        _store(db, book_id, by_id, children)
        db.execute("UPDATE library_books SET status='indexed',updated_at=? WHERE id=?", (now(), book_id))
    return ident


def move(book_id, node_id, parent_id, before_id, expected_revision):
    """Move a whole subtree, inserting before a sibling or last in its parent."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        nodes = _load(db, book_id)
        if revision(nodes) != expected_revision:
            raise OutlineConflict('目录已在另一窗口更新；请刷新目录后重新选择移动位置')
        by_id, children = _forest(nodes)
        if node_id not in by_id: raise ValueError('请选择本书的有效目录节点')
        if parent_id is not None and parent_id not in by_id: raise ValueError('目标归属不属于本书')
        cursor = parent_id
        while cursor is not None:
            if cursor == node_id: raise ValueError('不能把章节移到自身或其下级节点中')
            cursor = by_id[cursor]['parent_id']
        if before_id is not None and (before_id == node_id or before_id not in children[parent_id]):
            raise ValueError('目标位置必须是目标归属下的其他同级节点')
        old_parent = by_id[node_id]['parent_id']; siblings = children[old_parent]
        index = siblings.index(node_id)
        undo = {'node_id': node_id, 'parent_id': old_parent,
                'before_id': siblings[index + 1] if index + 1 < len(siblings) else None}
        siblings.remove(node_id)
        destination = children[parent_id]
        destination.insert(destination.index(before_id) if before_id else len(destination), node_id)
        changed, current = _store(db, book_id, by_id, children, {node_id: parent_id})
    return {'revision': current, 'changed': changed, 'undo': undo}
