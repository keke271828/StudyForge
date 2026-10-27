"""Isolated synthetic load: persisted text only; no OCR or model calls."""
import gc
import json
import os
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

folder=Path(__file__).resolve().parents[1]/'build'/(sys.argv[1] if len(sys.argv)>1 else 'library-retrieval-load-20261010-1')
folder.mkdir(parents=True,exist_ok=True)
os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import fitz
from studyforge import library
from studyforge.db import connect,j,many,now,uid

if library.catalogue():raise SystemExit('Use a fresh load directory to preserve reproducible timings.')
query='uniform_convergence'
chinese_query='一致收敛时为什么仍要检查极限与积分交换的条件'
chinese_concept='一致收敛；极限与积分交换需要检查条件。'
body=('这是用于检索负载的合成背景文字，不是人工核验过的教材。\n'*90)
books=[];nodes=[];readings=[]
for index in range(10):
    path=folder/f'Synthetic textbook {index+1}.pdf'
    with fitz.open() as doc:
        for page in range(400):
            p=doc.new_page();p.insert_text((40,60),f'SYNTHETIC {index+1}, PAGE {page+1}; not a real OCR reading.')
        doc.save(path)
    b=library.import_book(path,path.name)['book'];books.append(b)
    n=library.add_node(b['id'],f'合成章节 {index+1}')
    n=library.update_node(n['id'],{'start_page':1,'end_page':400,'confirmed':True});nodes.append(n)
    reading=uid();readings.append(reading);stamp=now()
    with connect() as db:
        db.execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,created_at,updated_at) '
                   'VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (reading,n['id'],library.reading_signature(b,n,'fixture','fixture','none'),'fixture','fixture','none','completed',
                    '合成索引，仅作算法负载验收。',stamp,stamp))
        rows=[]
        for page in range(1,401):
            text=body+'\n'+query+'\n'+chinese_concept
            if index==9 and page==400:text+='\n'+query+' '+query+' decisive exception.\n'+chinese_concept+chinese_concept
            rows.append((reading,page,f'PDF 第 {page} 页',text,'',None,None))
        db.executemany('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',rows)
    print(f'Synthetic book {index+1}/10 saved',flush=True)

times=[]
for _ in range(5):
    start=time.perf_counter();found=library.search(query,12);times.append(time.perf_counter()-start)
    assert found[0]['node_id']==nodes[-1]['id'] and found[0]['matched_pages'][0]['page']==400
chinese_times=[]
for _ in range(3):
    start=time.perf_counter();chinese_found=library.search(chinese_query,12);chinese_times.append(time.perf_counter()-start)
    assert chinese_found[0]['node_id']==nodes[-1]['id'] and chinese_found[0]['matched_pages'][0]['page']==400

query_terms=library.terms(query)
def old_reference_page_loading():
    # The previous implementation loaded every page of this node into Python.
    chunks=many('SELECT * FROM library_chunks WHERE reading_id=? ORDER BY page',(readings[-1],))
    return sorted(chunks,key=lambda c:(-library.relevance(query_terms,c['original_text']+'\n'+c['visual_text']),c['page']))[:3]

def memory_trial(operation):
    gc.collect();tracemalloc.start();start=time.perf_counter()
    result=operation();elapsed=time.perf_counter()-start
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    return {'seconds':elapsed,'python_peak_bytes':peak,'pages':[p['page'] for p in result]}

baseline=memory_trial(old_reference_page_loading)
current=memory_trial(lambda:library.reference_chunks(readings[-1],query_terms))
assert 400 in current['pages'] and 399 in current['pages']
assert current['python_peak_bytes']<baseline['python_peak_bytes']
report={'passed':True,'fixture':'10 synthetic books, 400 pages each; persisted text, not OCR or AI understanding',
        'books':10,'pages':4000,'base_page_characters':len(body+'\n'+query+'\n'+chinese_concept),'model_calls':0,
        'search_seconds':times,'search_median_seconds':statistics.median(times),
        'chinese_query':chinese_query,'chinese_search_seconds':chinese_times,'chinese_search_median_seconds':statistics.median(chinese_times),
        'late_match':{'book':'Synthetic textbook 10','page':400,'node_id':found[0]['node_id']},
        'previous_all_page_loading':baseline,'current_streamed_page_loading':current,
        'python_peak_reduction_percent':100*(1-current['python_peak_bytes']/baseline['python_peak_bytes']),
        'limitations':'Python allocations in this retrieval operation only; excludes native RSS, OCR, model image buffers and document generation.'}
(folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False),flush=True)
