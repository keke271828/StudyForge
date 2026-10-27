"""Large real native PDF fixture; model responses mocked, isolated desktop/phone."""
import asyncio

import fitz
from scripts import smoke_library_ui as fixture
from studyforge import library
from studyforge.db import execute, many, uid
from studyforge.library_semantic import set_enabled

set_enabled(False)


def make(name, confirmed):
    path=fixture.case_path.parent/(name+'.pdf')
    with fitz.open() as pdf:
        for number in range(1,317):
            page=pdf.new_page()
            page.insert_text((50,110),f'Section {number:04d} Knowledge')
            page.insert_text((50,180),'Original definition, assumptions and a short derivation. '+name)
            page.insert_text((280,805),str(number))
        pdf.save(path)
    book=library.import_book(path,name+'.pdf')['book']
    library.save_outline(book['id'],[{'id':uid(),'title':f'Section {number:04d} Knowledge',
        'kind':'section','parent_id':None,'start_page':number,'printed_page':number,
        'provenance':{'method':'fixture_native_pdf'}} for number in range(1,317)])
    if confirmed:execute('UPDATE library_nodes SET end_page=start_page,end_y=1,confirmed=1 WHERE book_id=?',(book['id'],))
    return book


desktop=make('Desktop-316-nodes',True)
phone=make('Phone-316-nodes',False)
fixture.case.update(bulk_read_book_id=desktop['id'],bulk_range_book_id=phone['id'])


def extracted(book,node,page):
    return {'page':page,'scanned':False,'image_path':'fixture-unused.png','image_sha256':str(page),
            'locator':f'PDF 第 {page} 页','original_text':'Original definition, conditions and derivation.'}


library.extract_page=extracted
original=fixture.respond
track={'active':0,'peak':0,'completed':0}


async def respond(request):
    if request.method!='POST':return await original(request)
    track['active']+=1;track['peak']=max(track['peak'],track['active'])
    try:
        await asyncio.sleep(.035)
        result=await original(request)
        track['completed']+=1
        return result
    finally:track['active']-=1


fixture.respond=respond


@fixture.server.app.get('/__library_test__/batch-stats')
def stats():
    return dict(track,calls=len(fixture.calls),readings=len(many("SELECT id FROM library_readings WHERE status='completed'")))


mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)

if __name__=='__main__':asyncio.run(fixture.main())
