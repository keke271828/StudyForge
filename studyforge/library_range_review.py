"""Explicit, atomic approval of observed boundary proposals, never guessed scopes."""
from . import library
from .db import connect, j, now, unj
from .library_outline import OutlineConflict
from .library_ranges import node_signature
from .library_batches import SELECTION_LIMIT


def proposal(node):
    evidence = unj(node['provenance_json'], {}).get('auto_range', {})
    crop = evidence.get('crop')
    if (node['confirmed'] or not crop or not evidence.get('start')
            or evidence.get('title') != node['title']
            or any(node.get(k) != v for k, v in crop.items())):
        return None
    # An unknown following heading cannot be substituted with end-of-book.
    if not evidence.get('next_heading') and not evidence.get('terminal', False):
        return None
    return evidence


def confirm(book_id, revisions):
    if not revisions or len(revisions) > SELECTION_LIMIT:
        raise ValueError(f'请选择已核对的范围建议（一次最多 {SELECTION_LIMIT} 个）')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        book = db.execute('SELECT * FROM library_books WHERE id=?', (book_id,)).fetchone()
        if not book:
            raise ValueError('书籍不存在或已删除')
        nodes = {n['id']: dict(n) for n in db.execute('SELECT * FROM library_nodes WHERE book_id=?', (book_id,))}
        if set(revisions) - nodes.keys():
            raise ValueError('只能确认本书的节点')
        busy = set().union(*(set(unj(r['payload_json'], {}).get('node_ids', [])) for r in db.execute(
            "SELECT payload_json FROM library_jobs WHERE book_id=? AND kind IN ('read','ranges') "
            "AND status IN ('queued','running','pausing','paused')", (book_id,))))
        if busy & revisions.keys():
            raise ValueError('这些节点仍在阅读或定位，请等待完成或取消原任务再核对')
        for ident, revision in revisions.items():
            node = nodes[ident]
            if node_signature(node) != revision:
                raise OutlineConflict('范围在另一窗口中发生改变，请重新打开核对；本次没有确认任何节点')
            if not proposal(node):
                raise ValueError(f"{node['title']}没有完整的原页边界建议，请先自动定位或手动校正")
            library.validate_scope(dict(book), node['start_page'], node['end_page'], node['start_y'], node['end_y'])
        for ident in revisions:
            provenance = unj(nodes[ident]['provenance_json'], {})
            provenance['range_review'] = {'confirmed_at': now(), 'basis': 'user_reviewed_observed_boundaries'}
            db.execute('UPDATE library_nodes SET confirmed=1,provenance_json=?,updated_at=? WHERE id=?',
                       (j(provenance), now(), ident))
    return {'confirmed_node_ids': list(revisions)}
