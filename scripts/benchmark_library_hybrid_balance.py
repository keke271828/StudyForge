"""Compare preserved query functions on isolated, controlled saved evidence."""
import heapq
import gc
import json
import os
from pathlib import Path
import sys
import time
import tracemalloc

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build'/sys.argv[1]
if OUT.exists(): raise SystemExit('Use a fresh evidence directory.')
OUT.mkdir(parents=True,exist_ok=True)
os.environ['STUDYFORGE_DATA_DIR']=str(OUT/'data')
sys.path.insert(0,str(ROOT/'tests'))

from studyforge import library,library_semantic as semantic
from studyforge.library_ranking import PassagePool
from test_library_retrieval import book,reading,snapshot
from test_library_hybrid_balance import QueryEncoder,indexed

BASE=ROOT/'build/knowledge-retrieval-20261021/baseline-functions'


def old_function(module,name):
    scope=dict(vars(module));scope['heapq']=heapq
    exec(compile((BASE/(name+'.py')).read_text(encoding='utf-8'),str(BASE/(name+'.py')),'exec'),scope)
    return scope[name]


new_matches,new_pages,new_window=semantic.matches,library.reference_chunks,library.text_window
semantic.model_ready=lambda:True
semantic.encoder=lambda:QueryEncoder()
old_matches=old_function(semantic,'matches')
old_pages=old_function(library,'reference_chunks')
old_window=old_function(library,'text_window')
semantic.set_enabled(True)
b=book(OUT,pages=9)
dominant='Dominant general mathematical background. '*80
other='Separate useful assumptions in a different chapter. '*2
n,rd=reading(b,'相似片段很多的章节',{1:dominant})
useful,ru=reading(b,'另一个相关小节',{2:other})
indexed(rd,1,dominant,.99,fragments=40);indexed(ru,2,other,.96)
candidate=[]
for phase,method in [('baseline',old_matches),('fixed',new_matches)]:
    semantic.matches=method
    start=time.perf_counter();hits,state=method('query_alias',semantic.eligible(),limit=6)
    search=library.search('query_alias',mode='hybrid')
    candidate.append({'phase':phase,'seconds':time.perf_counter()-start,'hits':hits,
        'search_nodes':search,'distinct_readings':len({h['reading_id'] for h in hits}),
        'distinct_pages':len({(h['reading_id'],h['page']) for h in hits}),'hit_count':len(hits)})
semantic.matches=new_matches

pages={i:'General related background. '+str(i) for i in range(1,10)}
pages[8]='DEFINITION_CONTEXT: state the domain before using the next theorem.'
pages[9]='EXACT_DOMAIN_CONDITION: do not divide by a zero denominator.'
n,rid=reading(b,'原文的适用条件',pages)
import hashlib
hits=[{'reading_id':rid,'page':p,'ordinal':0,'kind':'original','start_char':0,'end_char':len(pages[p]),
    'text_hash':hashlib.sha256(pages[p].encode()).hexdigest(),'semantic_score':.99-p*.01} for p in (3,4,5)]
snap=snapshot(b,[n]);snap['references'][0]['semantic_hits']=hits
page_results=[]
for phase,method,window in [('baseline',old_pages,old_window),('fixed',new_pages,new_window)]:
    library.reference_chunks,library.text_window=method,window
    result=library.reference_content(snap,'EXACT_DOMAIN_CONDITION',max_chars=5500)
    (OUT/(phase+'-reference.md')).write_text(result['text'],encoding='utf-8')
    page_results.append({'phase':phase,'pages':[r['page'] for r in result['evidence']],
        'exact_condition_in_context':'EXACT_DOMAIN_CONDITION' in result['text'],
        'adjacent_definition_in_context':'DEFINITION_CONTEXT' in result['text'],'result':result})
library.reference_chunks,library.text_window=new_pages,new_window

text=('SEMANTIC_BACKGROUND: related general discussion.\n'*100)+'\nEXACT_BOUNDARY_ASSUMPTION: retain the nonzero divisor.\n'
windows=[]
for phase,method in [('baseline',old_window),('fixed',new_window)]:
    excerpt,meta=method(text,library.terms('EXACT_BOUNDARY_ASSUMPTION'),850,anchor=0)
    windows.append({'phase':phase,'exact_condition_in_excerpt':'EXACT_BOUNDARY_ASSUMPTION' in excerpt,
        'excerpt':excerpt,'metadata':meta})

def pool_workload():
    pool=PassagePool(24);max_groups=max_current=0
    for group in range(10000):
        for ordinal in range(12):
            pool.add({'reading_id':f'group-{group:06}','page':ordinal//4,'ordinal':ordinal,
                'semantic_score':.99-(ordinal%4)*.01})
        max_groups=max(max_groups,len(pool.groups));max_current=max(max_current,len(pool.pages))
    result=pool.result()
    return {'groups':10000,'input_fragments':120000,'result_fragments':len(result),
        'maximum_retained_completed_groups':max_groups,'maximum_current_pages':max_current,
        'retained_passage_upper_bound':24*3+3}
start=time.perf_counter();pool=pool_workload();pool['seconds']=time.perf_counter()-start
gc.collect()  # Clear Python free lists before this allocation-only measurement.
tracemalloc.start();pool_workload();pool['python_peak_bytes']=tracemalloc.get_traced_memory()[1];tracemalloc.stop()

assert candidate[0]['distinct_readings']==1 and candidate[1]['distinct_readings']==2
assert not page_results[0]['exact_condition_in_context'] and page_results[1]['exact_condition_in_context']
assert page_results[1]['adjacent_definition_in_context']
assert not windows[0]['exact_condition_in_excerpt'] and windows[1]['exact_condition_in_excerpt']
assert pool['maximum_retained_completed_groups']<=24 and pool['maximum_current_pages']<=3
report={'passed':True,'cloud_model_requests':0,'new_ocr_pages':0,'vector_fixture':'controlled similarities, not model quality',
    'candidates':candidate,'page_context':page_results,'same_page_excerpt':windows,'candidate_buffer':pool,
    'limits':'Buffer peak is Python allocations for this helper only; not application RSS or OCR/ONNX memory.'}
(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':True,'candidate_buffer':pool,'report':str(OUT/'report.json')},ensure_ascii=False),flush=True)
