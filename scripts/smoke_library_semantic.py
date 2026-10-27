"""Real local ONNX retrieval; controlled excerpts + existing scanned-book records."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

base=Path(__file__).resolve().parents[1]
folder=base/'build'/(sys.argv[1] if len(sys.argv)>1 else 'library-semantic-live-20261010-1')
folder.mkdir(parents=True,exist_ok=True)
os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(base/'resources/library-semantic-e5')
sys.path.insert(0,str(base))

import fitz
from studyforge import library,library_semantic as semantic
from studyforge.db import connect,execute,j,now,uid

assert semantic.model_ready(),'Install the pinned model before running the live gate.'
assert not library.catalogue(),'Use a new evidence folder.'
semantic.set_enabled(True)
path=folder/'fixture.pdf'
with fitz.open() as doc:
    for i in range(5):doc.new_page().insert_text((50,70),f'Controlled excerpt {i+1}')
    doc.save(path)
b=library.import_book(path,'多领域检索受控样本.pdf')['book']
texts=[
    ('映射的性质','Injectivity means that f(x)=f(y) implies x=y. Distinct inputs must produce distinct outputs.'),
    ('学习与记忆','Retrieval practice improves retention by actively recalling information without looking at the source, rather than repeatedly rereading.'),
    ('社会科学方法','相关关系不代表因果关系。两个变量可能都受到第三个共同因素影响，因此仅凭相关无法确定因果方向。'),
    ('开放系统的调节','负反馈是输出变化引发反向调节，从而减弱最初的扰动；这种机制能够帮助维持系统稳定。'),
    ('证明中的邻域',('This page contains unrelated introductory prose about notation.\n'*65)+'A convergent sequence has a unique limit: choose disjoint open neighborhoods around two distinct proposed limits, using half their distance, so no tail term can lie in both.')
]
nodes=[]
for page,(title,text) in enumerate(texts,1):
    n=library.add_node(b['id'],title)
    n=library.update_node(n['id'],{'start_page':page,'end_page':page,'confirmed':True})
    ident=uid();signature=library.reading_signature(b,n,'fixture','fixture','none')
    execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
            (ident,n['id'],signature,'fixture','fixture','none','completed',now(),now()))
    execute('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',(ident,page,f'PDF 第 {page} 页',text,'',None,None))
    nodes.append(n)
unread=library.add_node(b['id'],'尚未阅读的一一映射')
started=time.perf_counter();steps=0
while semantic.index_step():steps+=1
index_seconds=time.perf_counter()-started
questions=[
    ('Where can I learn about one-to-one functions?',0),
    ('Testing myself from memory instead of going over the text again',1),
    ('两个现象一起出现就能说谁导致谁吗',2),
    ('一个变化被系统的反向响应抵消是什么机制',3),
    ('Why can a sequence not settle on two separate destinations?',4),
]
results=[]
for query,index in questions:
    keyword=library.search(query,mode='keyword')
    t=time.perf_counter();hybrid=library.search(query,mode='hybrid',with_meta=True);seconds=time.perf_counter()-t
    expected=nodes[index]['id']
    snap={'references':[{'node_id':expected,'purpose':'reference','source_version':library.version(b,nodes[index]),
                        'semantic_hits':next((r['semantic_hits'] for r in hybrid['nodes'] if r['node_id']==expected),[])}],
          'mode':'manual','candidates':[]}
    context=library.reference_content(snap,query,max_chars=2100)
    results.append({'query':query,'expected_title':texts[index][0],
                    'keyword_expected_rank':next((i+1 for i,r in enumerate(keyword) if r['node_id']==expected),None),
                    'hybrid_expected_rank':next((i+1 for i,r in enumerate(hybrid['nodes']) if r['node_id']==expected),None),
                    'seconds':seconds,'search':hybrid,'context':context})
    print(query,'keyword rank',results[-1]['keyword_expected_rank'],'hybrid rank',results[-1]['hybrid_expected_rank'],flush=True)
restricted=library.search(questions[0][0],node_ids=[nodes[1]['id']],mode='hybrid')
assert all(r['node_id']==nodes[1]['id'] for r in restricted)
assert not semantic.eligible().get(unread['id'])
semantic.set_enabled(False)
disabled=library.search(questions[0][0],mode='hybrid',with_meta=True)
semantic.set_enabled(True)
assert not disabled['semantic_used']
unrelated=[]
for query in ['What is the weather in the city?','What did I eat for breakfast yesterday?']:
    hits=library.search(query,mode='hybrid',with_meta=True)
    unrelated.append({'query':query,'search':hits})
    assert not any(n['automatic_reference'] for n in hits['nodes'])
report={'passed':all(r['hybrid_expected_rank'] is not None and r['hybrid_expected_rank']<=3 for r in results),'model_calls':0,
        'model':semantic.REPO,'model_revision':semantic.REVISION,'model_key':semantic.MODEL_KEY,
        'fixture':'five controlled passages, not a general teaching-quality benchmark',
        'index_seconds':index_seconds,'index_batches':steps,'index':semantic.status(),
        'queries':results,'unrelated_queries':unrelated,'manual_scope_preserved':True,'unread_not_indexed':True,'disabled_uses_keyword':True,
        'top1_count':sum(r['hybrid_expected_rank']==1 for r in results),'top3_count':sum(r['hybrid_expected_rank'] is not None and r['hybrid_expected_rank']<=3 for r in results)}
(folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('REPORT',folder/'report.json','passed',report['passed'],flush=True)
if not report['passed']:raise SystemExit(1)
