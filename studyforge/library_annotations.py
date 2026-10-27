"""Version-specific user corrections. They never rewrite original AI notes."""
from .db import connect, now, one


class AnnotationConflict(ValueError):
    pass


def get(reading_id):
    row = one('SELECT suspect,comment,revision,updated_at FROM library_reading_annotations WHERE reading_id=?',
              (reading_id,))
    return dict(row, suspect=bool(row['suspect'])) if row else {
        'suspect': False, 'comment': '', 'revision': 0, 'updated_at': None}


def save(node_id, reading_id, suspect, comment, revision, reading_updated_at=None):
    from . import library
    with connect() as database:
        database.execute('BEGIN IMMEDIATE')
        current = database.execute('SELECT * FROM library_nodes WHERE id=?', (node_id,)).fetchone()
        if not current:raise ValueError('书库节点不存在或已删除')
        n = dict(current)
        reading = database.execute('SELECT * FROM library_readings WHERE id=? AND node_id=?', (reading_id,node_id)).fetchone()
        if not reading or reading['status'] != 'completed' or not library.valid_reading(reading,n,library.book(n['book_id'])):
            raise ValueError('阅读版本不属于当前节点或范围已失效，请重新打开笔记')
        if reading_updated_at is not None and reading_updated_at!=reading['updated_at']:
            raise AnnotationConflict('阅读内容已重新整理；请重新打开笔记再保存，未将旧草稿保存到新内容上')
        saved = database.execute('SELECT revision FROM library_reading_annotations WHERE reading_id=?', (reading_id,)).fetchone()
        if revision != (saved['revision'] if saved else 0):
            raise AnnotationConflict('这份校订已在另一处修改；请重新打开笔记再保存，未覆盖新的内容')
        stamp, text = now(), comment.strip()
        database.execute('INSERT INTO library_reading_annotations VALUES (?,?,?,?,?) '
            'ON CONFLICT(reading_id) DO UPDATE SET suspect=excluded.suspect,comment=excluded.comment,'
            'revision=excluded.revision,updated_at=excluded.updated_at',
            (reading_id,int(suspect),text,revision+1,stamp))
    # Return the version saved by this request. A later writer must not make this
    # response claim their revision with our old text and defeat optimistic edits.
    return {'suspect':bool(suspect),'comment':text,'revision':revision+1,'updated_at':stamp}
