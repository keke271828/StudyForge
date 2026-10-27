"""Extend the native quoted-followup fixture with a weak, explicitly usable node."""
from scripts import smoke_library_followup_ui as base
from studyforge import library
from studyforge.db import execute,now,uid

fixture=base.fixture
weak=library.update_node(fixture.nodes[2]['id'],{'start_page':2,'end_page':2,'confirmed':True})
rid=uid();page=library.extract_page(fixture.b,weak,2,ocr=False)
execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
    (rid,weak['id'],library.reading_signature(fixture.b,weak,'deepseek','manual-weak-reader','high'),
     'deepseek','manual-weak-reader','high','completed','',now(),now()))
execute('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',(rid,2,page['locator'],page['original_text'],'',page['image_path'],page['image_sha256']))
fixture.case.update(auto_context_check=True,weak_node_id=weak['id'],weak_reading_id=rid,weak_original=page['original_text'])
if __name__=='__main__':fixture.asyncio.run(fixture.main())
