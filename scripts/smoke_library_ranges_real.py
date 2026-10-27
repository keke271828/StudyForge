"""Local heading-location acceptance on the supplied scanned algebra textbook.

Copies the PDF into isolated build data. OCRs only directory/boundary pages,
never calls a cloud model or touches the user's active learning database.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

root=Path(__file__).resolve().parents[1]
target=root/'build'/(sys.argv[1] if len(sys.argv)>1 else 'library-ranges-real-20261011');target.mkdir(exist_ok=True)
os.environ['STUDYFORGE_DATA_DIR']=str(target/'data')
from studyforge import library,library_ranges,library_worker
from studyforge.db import j,many,one,unj


async def wait(worker,job):
    worker.launch(job['id']);task=worker.tasks[job['id']];previous=None
    while not task.done():
        row=one('SELECT * FROM library_jobs WHERE id=?',(job['id'],))
        stage=unj(row['result_json'],{}).get('stage',row['status'])
        if stage!=previous:print(stage,flush=True);previous=stage
        await asyncio.sleep(.5)
    await task
    result=library.public_job(one('SELECT * FROM library_jobs WHERE id=?',(job['id'],)))
    if result['status']!='completed':raise RuntimeError(result)
    return result


async def main():
    source=next(Path('C:/Users/Lenovo/Desktop/资料/STUDY/电子书').glob('高等代数 第六版*.pdf'))
    book=library.import_book(source,source.name)['book']
    worker=library_worker.LibraryWorker(lambda p:(_ for _ in ()).throw(AssertionError('No model call authorized for this acceptance')))
    started=time.perf_counter()
    if not many('SELECT id FROM library_nodes WHERE book_id=?',(book['id'],)):
        toc=library_worker.create_job(book['id'],'toc',{'page_spec':'3-5','foreground':True})
        await wait(worker,toc)
    toc_seconds=time.perf_counter()-started
    nodes=library.details(book['id'])['nodes']
    selected=[n for n in nodes if n['kind']=='chapter'][:1]
    selected+= [n for n in nodes if n['parent_id']==selected[0]['id'] and n['kind']=='section'][:2]
    started=time.perf_counter()
    job=library_ranges.range_job(book['id'],[n['id'] for n in selected],foreground=True,allow_ai=False)
    result=await wait(worker,job);elapsed=time.perf_counter()-started
    report={'original_path':str(source),'book_id':book['id'],'page_count':book['page_count'],
            'toc_seconds':round(toc_seconds,3),'range_seconds':round(elapsed,3),
            'nodes':library.details(book['id'])['nodes'],'job':result,'cloud_requests':0}
    (target/'report.json').write_text(j(report),encoding='utf-8')
    # Render the original boundary pages for independent visual review.
    import fitz
    with fitz.open(book['original_path']) as pdf:
        pages=set()
        for r in result['result']['ranges']:
            for key in ('start','next_heading'):
                if r[key]:pages.add(r[key]['page'])
        for page in sorted(pages):pdf[page-1].get_pixmap(matrix=fitz.Matrix(1.1,1.1)).save(target/f'boundary-{page}.png')
    print(j({'report':str(target/'report.json'),'range_seconds':round(elapsed,3),'result':result['result']}),flush=True)


if __name__=='__main__':asyncio.run(main())
