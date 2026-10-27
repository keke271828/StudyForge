"""Actual passage selection -> shared chat -> original reference on both clients."""
import hashlib
from scripts import smoke_library_ui as fixture
from studyforge import library,library_history
from studyforge.db import execute,j,many,now,uid

fixture.enable_semantic(False)
fixture.server.discussion_completed=lambda *a:None
n=library.update_node(fixture.nodes[1]['id'],{'title':'数域与四则运算','start_page':1,'end_page':1,'confirmed':True})
rid=uid()
execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
    (rid,n['id'],library.reading_signature(fixture.b,n,'deepseek','saved-source-reader','high'),
     'deepseek','saved-source-reader','high','completed','',now(),now()))
page=library.extract_page(fixture.b,n,1,ocr=False)
execute('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',(rid,1,page['locator'],page['original_text'],'',page['image_path'],page['image_sha256']))
library.set_preferences(fixture.c['id'],fixture.p['id'],'auto',[])
quote='数域中可以把零当作除数。';full='先前的AI回答，可能有误：\n'+quote
mid=uid();execute('INSERT INTO messages VALUES (?,?,?,?,?)',(mid,fixture.c['id'],'assistant',full,now()))
fixture.case.update(target_message_id=mid,target_quote=quote,node_id=n['id'],reading_id=rid,
    original_text=page['original_text'],original_sha256=hashlib.sha256(page['original_text'].encode()).hexdigest())


@fixture.server.app.get('/__followup_test__/state')
def state():
    receipts=library_history.history(fixture.c['id'],fixture.p['id'])['entries']
    return {'calls':fixture.calls,'history':receipts,'users':many("SELECT content FROM messages WHERE role='user' AND conversation_id=? ORDER BY created_at,rowid",(fixture.c['id'],)),
            'events':len(many('SELECT * FROM learning_events')),'mastery':len(many('SELECT * FROM mastery'))}


mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)
if __name__=='__main__':fixture.asyncio.run(fixture.main())
