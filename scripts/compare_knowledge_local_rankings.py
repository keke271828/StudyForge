"""Same saved corpus and real local encoder, preserved vs current retrieval."""
import heapq
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build'/sys.argv[1]
if OUT.exists(): raise SystemExit('Use a fresh evidence directory.')
(OUT/'data').mkdir(parents=True)
SOURCE=ROOT/'build/knowledge-retrieval-real-20261021-2'
with sqlite3.connect(SOURCE/'data/studyforge.sqlite3') as original:
    with sqlite3.connect(OUT/'data/studyforge.sqlite3') as copy: original.backup(copy)
os.environ['STUDYFORGE_DATA_DIR']=str(OUT/'data')
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(ROOT/'resources/library-semantic-e5')
from studyforge import library,library_semantic as semantic

new=semantic.matches
scope=dict(vars(semantic));scope['heapq']=heapq
exec(compile((ROOT/'build/knowledge-retrieval-20261021/baseline-functions/matches.py').read_text(encoding='utf-8'),'preserved-matches.py','exec'),scope)
old=scope['matches']
semantic.set_enabled(True)
cases=json.loads((SOURCE/'report.json').read_text(encoding='utf-8'))['queries']
rows=[]
for index,case in enumerate(cases):
    results={}
    for phase,method in ([('baseline',old),('fixed',new)] if index%2==0 else [('fixed',new),('baseline',old)]):
        semantic.matches=method
        found=library.search(case['query'],mode='hybrid',with_meta=True)
        rank=next((i+1 for i,n in enumerate(found['nodes']) if n['title']==case['expected_title']),None)
        results[phase]={'expected_rank':rank,'returned_titles':[n['title'] for n in found['nodes']],
            'semantic_positions':sum(len(n['semantic_hits']) for n in found['nodes'])}
    rows.append({'query':case['query'],'expected_title':case['expected_title'],**results})
semantic.matches=new;semantic.set_enabled(False)
report={'passed':all(r['fixed']['expected_rank'] and r['fixed']['expected_rank']<=3 for r in rows),
    'cloud_model_requests':0,'new_index_batches':0,'queries':rows,'unique_queries':5,'local_search_runs':10,
    'limits':'Five controlled saved texts, one local model, not a general quality or speed ranking.'}
(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
if not report['passed']:raise SystemExit(1)
