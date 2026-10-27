"""Many long shelf titles in an isolated real desktop/paired-mobile fixture."""
import asyncio

from scripts import smoke_library_ui as fixture
from studyforge.db import execute, now, uid
from studyforge import library

# UI-only catalogue aliases share the tiny fixture PDF; no user books or
# external model requests are used. Opening an alias returns an empty outline.
for index in range(1, 25):
    title = f'教材 {index:02d} · 高等数学与跨学科基础知识（长书名与小窗口滚动验收）'
    identifier = uid()
    execute('INSERT INTO library_books(id,title,filename,original_path,sha256,page_count,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?)',
            (identifier, title, title + '.pdf', fixture.b['original_path'], identifier.ljust(64, '0'), 3, now(), now()))

fixture.case['shelf_books'] = library.catalogue()

if __name__ == '__main__':
    asyncio.run(fixture.main())
