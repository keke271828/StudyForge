"""Run local contents discovery on a supplied PDF using isolated acceptance data."""
import asyncio
import os
import sys
import time
from pathlib import Path

workspace=Path(__file__).resolve().parents[1]
folder=(workspace/'build'/sys.argv[1]).resolve()
if not folder.is_relative_to((workspace/'build').resolve()):raise ValueError('验收目录必须在 build 内')
folder.mkdir(parents=True,exist_ok=True)
os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')

from studyforge import library,library_toc,library_worker
from studyforge.db import j,many,one,unj


async def main():
    source=Path(sys.argv[2])
    book=library.import_book(source,source.name)['book']
    if library.details(book['id'])['nodes']:raise ValueError('请使用新的隔离验收目录；不会清除已有目录')
    job=library_worker.create_job(book['id'],'toc',{'auto_discover':True,'scan_limit':32,'foreground':True})
    worker=library_worker.LibraryWorker(lambda p:(_ for _ in ()).throw(AssertionError('不应调用云模型')))
    start=time.perf_counter();worker.launch(job['id']);task=worker.tasks[job['id']]
    previous=None
    while not task.done():
        row=one('SELECT * FROM library_jobs WHERE id=?',(job['id'],))
        stage=unj(row['result_json'],{}).get('stage',row['status'])
        if stage!=previous:print(stage,flush=True);previous=stage
        await asyncio.sleep(.5)
    await task
    result=library.public_job(one('SELECT * FROM library_jobs WHERE id=?',(job['id'],)))
    nodes=library.details(book['id'])['nodes']
    report={'version':library_toc.VERSION,'book_id':book['id'],'source':str(source),'page_count':book['page_count'],
            'elapsed_seconds':round(time.perf_counter()-start,3),'job':result,'nodes':len(nodes),
            'chapters':[n['title'] for n in nodes if n['kind']=='chapter'],
            'model_requests':0,'readings':len(many('SELECT id FROM library_readings'))}
    (folder/'toc-real-report.json').write_text(j(report),encoding='utf-8')
    if result['status']!='completed':raise RuntimeError(result['error'])
    discovery=result['result'].get('toc_discovery',{})
    for page in discovery.get('candidate_pages',[]):
        (folder/f'original-toc-{page}.png').write_bytes(library.preview(book['id'],page))
    print(j({k:v for k,v in report.items() if k not in ('job','chapters')}|
            {'candidate_pages':discovery.get('candidate_pages'),'status':discovery.get('status')}),flush=True)


if __name__=='__main__':asyncio.run(main())
