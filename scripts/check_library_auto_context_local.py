"""Same saved texts and real local E5 model; no download/OCR/cloud request."""
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'build/knowledge-retrieval-real-20261021-2'
OUT=ROOT/'build'/sys.argv[1]
if OUT.exists():raise SystemExit('Use a fresh output directory.')
(OUT/'data').mkdir(parents=True)
with sqlite3.connect(SOURCE/'data/studyforge.sqlite3') as source,sqlite3.connect(OUT/'data/studyforge.sqlite3') as dest:source.backup(dest)
os.environ['STUDYFORGE_DATA_DIR']=str(OUT/'data')
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(ROOT/'resources/library-semantic-e5')
from studyforge import conversations,library,library_semantic as semantic
from studyforge.db import create_project

assert semantic.model_ready(),'Only use an already installed local model.'
semantic.set_enabled(True)
scope=dict(vars(library))
for name in ('terms','relevance','page_matches','note_matches','search','reference_snapshot'):
    exec(compile((ROOT/'build/library-auto-context-20261021/baseline-functions'/f'{name}.py').read_text(encoding='utf-8'),f'preserved-{name}.py','exec'),scope)
old=scope['reference_snapshot'];new=library.reference_snapshot
p=create_project('本地模型自动参考对照');c=conversations.create(p['id'],'deepseek')['id'];library.set_preferences(c,p['id'],'auto',[])
cases=[{'query':row['query'],'expected_title':row['expected_title']} for row in json.loads((SOURCE/'report.json').read_text(encoding='utf-8'))['queries']]
cases += [{'query':'这里为什么成立？请详细解释。','expected_title':None},
          {'query':'Why does this proof work? Explain with concrete examples.','expected_title':None}]
rows=[]
try:
    for index,case in enumerate(cases):
        results={}
        for phase,method in ([('baseline',old),('fixed',new)] if index%2==0 else [('fixed',new),('baseline',old)]):
            snap=method(c,p['id'],case['query'])
            results[phase]={'titles':[library.node(ref['node_id'])['title'] for ref in snap['references']],
                            'unread_candidates':[row['title'] for row in snap['candidates']]}
        rows.append(dict(case,**results))
    retained=all(not row['expected_title'] or row['expected_title'] not in row['baseline']['titles'] or row['expected_title'] in row['fixed']['titles'] for row in rows)
    no_generic=all(not row['fixed']['titles'] and not row['fixed']['unread_candidates'] for row in rows if row['expected_title'] is None)
    report={'passed':retained and no_generic,'same_encoder':semantic.MODEL_KEY,'model_downloads':0,'cloud_requests':0,'new_ocr_pages':0,
            'queries':rows,'regression_in_previously_admitted_targets':not retained,'generic_queries_do_not_auto_attach':no_generic,
            'limits':'Five controlled saved texts and two discourse queries; not a full-library relevance benchmark.'}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    if not report['passed']:raise SystemExit(1)
finally:semantic.release_idle(force=True)
