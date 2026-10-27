"""Isolated real desktop/mobile UI service with controlled model timing."""
import asyncio
import sys
from pathlib import Path

import fitz
from pydantic import BaseModel

from scripts import smoke_library_ui as fixture
from studyforge import learning_memory,library
from studyforge.db import execute,uid

folder=fixture.case_path.parent
path=folder/'range-boundaries.pdf'
with fitz.open() as document:
    for i in range(4):
        page=document.new_page()
        if i==0:page.insert_text((50,120),'Contents: Chapter 1 Basics .... 1; Chapter 2 Synthesis .... 3')
        if i==1:
            for y,text in [(120,'Chapter 1 Basics'),(220,'1 Definitions'),(260,'DEF_ONLY: closure requires nonzero divisors.'),
                           (520,'2 Examples'),(560,'EXAMPLE_ONLY: compare number systems.')]:page.insert_text((50,y),text)
        if i==2:
            page.insert_text((50,220),'3 Arguments');page.insert_text((50,260),'PROOF_ONLY: compare assumptions.')
        if i==3:
            page.insert_text((50,120),'Chapter 2 Synthesis');page.insert_text((50,260),'SYNTHESIS_ONLY: summarize conditions.')
        if i>0:page.insert_text((280,805),str(i))
    document.save(path)
book=library.import_book(path,'自动定位与前台阅读.pdf')['book']
parent=uid()
nodes=[{'id':parent,'title':'Chapter 1 Basics','kind':'chapter','parent_id':None,'printed_page':1,'start_page':None,'provenance':{}},
       *[{'id':uid(),'title':title,'kind':'section','parent_id':parent,'printed_page':page,'start_page':None,'provenance':{}}
         for title,page in [('1 Definitions',1),('2 Examples',1),('3 Arguments',2)]],
       {'id':uid(),'title':'Chapter 2 Synthesis','kind':'chapter','parent_id':None,'printed_page':3,'start_page':None,'provenance':{}}]
library.save_outline(book['id'],nodes);execute('UPDATE library_books SET toc_pages=? WHERE id=?',('1',book['id']))
fixture.case.update(range_book_id=book['id'],range_nodes=library.details(book['id'])['nodes'])
stats={'active':0,'peak':0,'requests':0};original=fixture.respond

async def delayed(request):
    if request.method=='GET':return await original(request)
    stats['active']+=1;stats['requests']+=1;stats['peak']=max(stats['peak'],stats['active'])
    try:
        await asyncio.sleep(.4)
        return await original(request)
    finally:stats['active']-=1

fixture.respond=delayed

class BusyIn(BaseModel):
    busy:bool

@fixture.server.app.post('/__library_test__/foreground')
def busy(value:BusyIn):
    learning_memory._busy=int(value.busy)
    from studyforge.scheduling import wake_schedulers
    wake_schedulers()
    return {'busy':bool(learning_memory._busy)}

@fixture.server.app.get('/__library_test__/timing')
def timing():return stats

mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)

if __name__=='__main__':asyncio.run(fixture.main())
