"""Real desktop/paired-phone review workflow, using local model fixtures."""
import asyncio
import pymupdf as fitz

from scripts import smoke_library_ranges_ui as harness
from studyforge import library
from studyforge.db import execute,uid

fixture=harness.fixture
path=fixture.case_path.parent/'review-boundaries.pdf'
with fitz.open(fixture.case_path.parent/'range-boundaries.pdf') as doc:
    doc.set_metadata({'title':'Independent range-review acceptance'})
    doc.save(path)
book=library.import_book(path,'集中核对与部分继续阅读.pdf')['book']
chapter,last=uid(),uid()
outline=[{'id':chapter,'title':'Chapter 1 Basics','kind':'chapter','parent_id':None,'printed_page':1,'start_page':None,'provenance':{}},
         *[{'id':uid(),'title':title,'kind':'section','parent_id':chapter,'printed_page':page,'start_page':None,'provenance':{}}
           for title,page in [('1 Definitions',1),('2 Examplez',1),('3 Arguments',2)]],
         {'id':last,'title':'Chapter 2 Synthesis','kind':'chapter','parent_id':None,'printed_page':3,'start_page':None,'provenance':{}},
         {'id':uid(),'title':'4 Absent section','kind':'section','parent_id':last,'printed_page':3,'start_page':None,'provenance':{}}]
library.save_outline(book['id'],outline);execute('UPDATE library_books SET toc_pages=? WHERE id=?',('1',book['id']))
fixture.case.update(review_book_id=book['id'],review_nodes=library.details(book['id'])['nodes'])
if __name__=='__main__':asyncio.run(fixture.main())
