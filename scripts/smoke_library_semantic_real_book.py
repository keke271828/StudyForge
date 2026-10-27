"""Reuse the existing isolated scanned-book reading; no OCR or generation calls."""
import gc
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

base=Path(__file__).resolve().parents[1]
folder=base/'build'/(sys.argv[1] if len(sys.argv)>1 else 'library-semantic-real-book-20261010-1')
if folder.exists():raise SystemExit('Use a fresh evidence directory.')
(folder/'data').mkdir(parents=True)
with sqlite3.connect(base/'build/library-live-20261010-2/data/studyforge.sqlite3') as source:
    with sqlite3.connect(folder/'data/studyforge.sqlite3') as target:source.backup(target)
os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(base/'resources/library-semantic-e5')
sys.path.insert(0,str(base))
from studyforge import library,library_semantic as semantic

def working_set():
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD),*[(n,ctypes.c_size_t) for n in
                  ['peak','working','paged_peak','paged','nonpaged_peak','nonpaged','pagefile','pagefile_peak','private']]]
    kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=wintypes.HANDLE
    psapi=ctypes.WinDLL('psapi');psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    counters=Counters();counters.cb=ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb):raise ctypes.WinError()
    return {'working_set_bytes':counters.working,'peak_working_set_bytes':counters.peak}

semantic.set_enabled(True)
baseline=working_set();t=time.perf_counter();steps=0
while semantic.index_step():steps+=1
index_seconds=time.perf_counter()-t;loaded=working_set()
queries=[]
for query in ['数域为什么要求除数不为零','数域中加法与乘法的封闭性','为什么整数的集合不符合这些四则运算的要求']:
    t=time.perf_counter();found=library.search(query,mode='hybrid',with_meta=True);seconds=time.perf_counter()-t
    ready=next(n for n in found['nodes'] if n['state']=='read')
    node=library.node(ready['node_id']);book=library.book(node['book_id'])
    snap={'references':[{'node_id':node['id'],'purpose':'reference','source_version':library.version(book,node),
                         'semantic_hits':ready.get('semantic_hits',[])}],'candidates':[],'mode':'manual'}
    context=library.reference_content(snap,query)
    assert {e['page'] for e in context['evidence']} <= {6,7}
    queries.append({'query':query,'search_seconds':seconds,'search':found,'context':context})
semantic.set_enabled(False);gc.collect();released=working_set()
report={'passed':True,'model_calls':0,'new_ocr_pages':0,'index_seconds':index_seconds,'index_batches':steps,
        'index':semantic.status(),'queries':queries,'process_memory':{'before_model':baseline,'model_loaded':loaded,'disabled_and_released':released},
        'memory_limitations':'One isolated Python process; includes native modules, tokenizer and model. Not whole application peak memory.'}
(folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='queries'},ensure_ascii=False,indent=2),flush=True)
