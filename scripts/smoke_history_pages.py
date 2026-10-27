"""Production pages, controlled streams and corrections; all data is isolated."""
import asyncio
from scripts import smoke_message_history as base
from studyforge import library
from studyforge.db import execute, now, uid

fixture=base.fixture
fixture.enable_semantic(False)
for i in range(30,155):
    ident=uid();base.identifiers.append(ident)
    content=f'PAGE_RECORD_{i}：这是保留的历史消息。'+(r'公式 $1-1=0$。' if i%2 else '')
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',
        (ident,fixture.c['id'],'user' if i%2==0 else 'assistant',content,now()))
n=library.update_node(fixture.nodes[1]['id'],{'start_page':1,'end_page':1,'end_y':.5,'confirmed':True})
reading=uid();signature=library.reading_signature(fixture.b,n,'fixture','fixture','none')
execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,warnings_json,created_at,updated_at) '
    'VALUES (?,?,?,?,?,?,?,?,?,?,?)',(reading,n['id'],signature,'fixture','fixture','none','completed',
    'CORRECTION_RAW_RECORD：此段原始 AI 笔记会一直保留。公式 $1-1=0$。','[]',now(),now()))
execute('INSERT INTO library_chunks(reading_id,page,locator,original_text) VALUES (?,?,?,?)',
    (reading,1,'PDF 第 1 页','SOURCE_FOR_CORRECTION：含 1，并对减法封闭。'))
fixture.case.update(message_ids=base.identifiers,annotation_node=n['id'],annotation_reading=reading)

@fixture.server.app.post('/__history_test__/amend_older')
def amend_older():
    execute('UPDATE messages SET content=? WHERE id=?',
        ('AMENDED_OLDER_DURING_LOAD：翻页过程中更正的历史消息。',base.identifiers[50]))
    return {'id':base.identifiers[50]}

mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)
if __name__=='__main__':asyncio.run(fixture.main())
