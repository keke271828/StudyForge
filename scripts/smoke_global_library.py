"""Real scanned textbook acceptance; all writes stay under build/library-live-*.

`index` only runs local directory OCR. `read` additionally reads the visually
verified number-field scope using the configured native DeepSeek credential.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

workspace=Path(__file__).resolve().parents[1]
target=workspace/'build'/'library-live-20261010-2'
target.mkdir(parents=True,exist_ok=True)
os.environ['STUDYFORGE_DATA_DIR']=str(target/'data')
os.environ['PYTHONUTF8']='1'

from studyforge import library,library_worker
from studyforge.db import many,one,unj


async def wait_job(worker,job):
    worker.launch(job['id']);task=worker.tasks[job['id']];last=None
    while not task.done():
        row=one('SELECT * FROM library_jobs WHERE id=?',(job['id'],))
        stage=unj(row['result_json'],{}).get('stage',row['status'])
        if stage!=last:print(stage,flush=True);last=stage
        await asyncio.sleep(.5)
    await task
    result=library.public_job(one('SELECT * FROM library_jobs WHERE id=?',(job['id'],)))
    if result['status']!='completed':raise RuntimeError(result['error'] or result)
    return result


async def main():
    source=next(Path(r'C:\Users\Lenovo\Desktop\资料\STUDY\电子书').glob('高等代数*.pdf'))
    b=library.import_book(source,source.name)['book'];worker=library_worker.LibraryWorker()
    started=time.perf_counter()
    if not library.details(b['id'])['nodes']:
        directory=library_worker.create_job(b['id'],'toc',{'page_spec':'3-5','first_printed':1,'first_pdf':6})
        index=await wait_job(worker,directory)
    else:index=None
    detail=library.details(b['id'])
    (target/'目录识别原始结果.json').write_text(json.dumps(detail,ensure_ascii=False,indent=2),encoding='utf-8')
    case={'data_root':str(target/'data'),'book_id':b['id'],'source':str(source),'index_seconds':round(time.perf_counter()-started,3),
          'counts':{kind:sum(n['kind']==kind for n in detail['nodes']) for kind in ('chapter','section','exercises','appendix')},
          'model_reading_started':False}
    print(json.dumps(case,ensure_ascii=False),flush=True)
    if len(sys.argv)>1 and sys.argv[1]=='read':
        n=next(n for n in detail['nodes'] if n['kind']=='section' and '数域' in n['title'])
        # Verified against full original PDF pages 6 and 7. End before §2.
        n=library.update_node(n['id'],{'start_page':6,'end_page':7,'start_y':0,'end_y':.81,'confirmed':True})
        started=time.perf_counter()
        job=library_worker.new_read_job(b['id'],[n['id']],'deepseek',os.environ.get('STUDYFORGE_SMOKE_MODEL','deepseek-flash'),'none')
        result=await wait_job(worker,job)
        r=library.ready_reading(library.node(n['id']))
        (target/'数域_后台阅读索引.md').write_text(r['notes'],encoding='utf-8')
        chunks=many('SELECT * FROM library_chunks WHERE reading_id=? ORDER BY page',(r['id'],))
        (target/'数域_原页文字与图像核对.json').write_text(json.dumps(chunks,ensure_ascii=False,indent=2),encoding='utf-8')
        case.update(model_reading_started=True,read_seconds=round(time.perf_counter()-started,3),node_id=n['id'],reading_id=r['id'],
                    job=result,model_request_spans=many("SELECT label,provider,duration_ms,status FROM execution_spans WHERE job_id=? AND resource='model' ORDER BY queued_at",(job['id'],)),
                    unread_nodes=sum(x['reading'] is None for x in library.details(b['id'])['nodes']))
    (target/'case.json').write_text(json.dumps(case,ensure_ascii=False,indent=2),encoding='utf-8')
    print('证据保存在 '+str(target),flush=True)


if __name__=='__main__':asyncio.run(main())
