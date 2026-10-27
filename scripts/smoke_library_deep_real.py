"""Two-page source-grounded index/deep comparison. --live uses existing credentials."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
parser=argparse.ArgumentParser()
parser.add_argument('case')
parser.add_argument('--source',required=True)
parser.add_argument('--live',action='store_true')
parser.add_argument('--model',default='deepseek-flash')
parser.add_argument('--effort',default='high')
parser.add_argument('--refresh-notes',action='store_true',help='Refresh only this isolated comparison; retain valid page observations')
parser.add_argument('--index-only',action='store_true',help='Recheck index brevity and retain the previously completed deep sample')
args=parser.parse_args()
target=ROOT/'build'/args.case;target.mkdir(parents=True,exist_ok=True)
os.environ['STUDYFORGE_DATA_DIR']=str(target/'data')
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(target/'isolated-model')

import fitz
from studyforge import ai,library,library_worker
from studyforge.db import execute,j,one

source=Path(args.source)
book=library.import_book(source,source.name)['book']
selected=next((n for n in library.details(book['id'])['nodes'] if n['title']=='§1 数域 · 两页精读核验'),None)
if not selected:
    selected=library.add_node(book['id'],'§1 数域 · 两页精读核验')
    selected=library.update_node(selected['id'],{'start_page':6,'end_page':7,'start_y':.2985,'end_y':.8109,'confirmed':True})
n=library.node(selected['id'])
with fitz.open(book['original_path']) as pdf:
    for page in (6,7):pdf[page-1].get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(target/f'original-pdf-{page}.png')
print('ORIGINAL_IMAGES_READY',flush=True)
if not args.live:
    print('Prepared only; no model requests.',flush=True);sys.exit(0)
if args.refresh_notes:
    # This directory is an isolated benchmark, never the user's learning DB.
    for filename in ('结构索引.md','重点精读.md','deep-real-report.json'):
        path=target/filename
        if path.exists() and not path.with_name('首次-'+filename).exists():path.with_name('首次-'+filename).write_bytes(path.read_bytes())
    execute("UPDATE library_readings SET status='interrupted' WHERE node_id=? AND depth='index'",(n['id'],))

ai.save_settings({'deepseek_model':args.model,'deepseek_vision_model':args.model,'background_learning_enabled':False,
                  'agent_tools_enabled':False,'model_concurrency':2})
calls=[]
class Tracked:
    def __init__(self,payload):self.base=library_worker.default_client(payload);self.depth=payload.get('depth','index')
    def __getattr__(self,name):return getattr(self.base,name)
    async def invoke(self,kind,operation):
        start=time.perf_counter()
        try:result=await operation();state='completed';return result
        except BaseException:state='failed';raise
        finally:calls.append({'depth':self.depth,'kind':kind,'seconds':round(time.perf_counter()-start,3),'status':state})
    async def complete(self,system,user,**kwargs):
        (target/f'request-{self.depth}-{len(calls)+1}.txt').write_text('SYSTEM\n'+system+'\n\nUSER\n'+user,encoding='utf-8')
        return await self.invoke('text',lambda:self.base.complete(system,user,**kwargs))
    async def analyze_images(self,frames):return await self.invoke('vision_batch',lambda:self.base.analyze_images(frames))
    async def analyze_image(self,*a,**kw):return await self.invoke('vision_single',lambda:self.base.analyze_image(*a,**kw))
    async def close(self):await self.base.close()


async def main():
    worker=library_worker.LibraryWorker(Tracked)
    results=[]
    focus='数域为什么要求四则运算封闭，为什么除法要排除零除数？请讲清这些条件各自解决什么困难，原文例子怎样检查，哪些看似自然的改法不成立。'
    for depth in (('index',) if args.index_only else ('index','deep')):
        start=time.perf_counter()
        job=library_worker.new_read_job(book['id'],[n['id']],'deepseek',args.model,args.effort,foreground=True,depth=depth,focus=focus if depth=='deep' else '')
        worker.launch(job['id']);task=worker.tasks[job['id']];last=None
        while not task.done():
            status=library.public_job(one('SELECT * FROM library_jobs WHERE id=?',(job['id'],)))
            stage=status['result'].get('stage',status['status'])
            if stage!=last:print(depth+': '+stage,flush=True);last=stage
            await asyncio.sleep(.5)
        await task
        result=library.public_job(one('SELECT * FROM library_jobs WHERE id=?',(job['id'],)))
        results.append({'depth':depth,'seconds':round(time.perf_counter()-start,3),'job':result})
        report={'source':str(source),'page_count':book['page_count'],'scope':{'start_page':6,'end_page':7,'start_y':.2985,'end_y':.8109},
                'provider':'deepseek','model':args.model,'effort':args.effort,'focus':focus,'calls':calls,'results':results,
                'timing_limit':'索引为首次读取；精读复用原页/OCR/图像观察，不能将总耗时差直接解释为模型变快。只抽查两页，未读取全书。'}
        (target/'deep-real-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if result['status']!='completed':raise RuntimeError(result.get('error') or 'Reading did not complete')
        reading_id=result['result']['nodes_completed'][0]['reading_id']
        reading=one('SELECT * FROM library_readings WHERE id=?',(reading_id,))
        (target/('结构索引.md' if depth=='index' else '重点精读.md')).write_text(reading['notes'],encoding='utf-8')
    index=(target/'结构索引.md').read_text(encoding='utf-8');deep=(target/'重点精读.md').read_text(encoding='utf-8')
    payload=json.dumps({'index':index,'deep':deep},ensure_ascii=False).replace('<','\\u003c')
    html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>原页结构索引与重点精读对照</title>
<link rel="stylesheet" href="../../web/vendor/katex.css"><style>body{margin:0;background:#edf2ea;color:#233d31;font:16px/1.9 "Microsoft YaHei",sans-serif}header,main{max-width:1350px;margin:auto;padding:28px}header{padding-bottom:8px}h1{font-size:28px}.intro{background:#fff;padding:18px;border-radius:14px}.columns{display:grid;grid-template-columns:1fr 1.6fr;gap:22px}article{background:#fff;border:1px solid #c4d0c0;border-radius:16px;padding:22px;min-width:0}.katex-display{overflow-x:auto}table{border-collapse:collapse;max-width:100%;display:block;overflow-x:auto}td,th{border:1px solid #c4d0c0;padding:7px}.originals{display:grid;grid-template-columns:1fr 1fr;gap:14px}.originals img{max-width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}@media(max-width:850px){.columns,.originals{grid-template-columns:1fr}header,main{padding:16px}}</style>
<header><h1>同一原页：结构索引与重点精读</h1><p class="intro">本次只读《高等代数》第六版“数域”的 PDF 6–7 页选区。DeepSeek / deepseek-flash / high；没有习题。左侧用于导航，右侧围绕条件与构造展开。模型回答未经自动“正确”认证；请对照下方原页检查。首次索引与缓存后的精读不能直接比较总耗时。</p></header>
<main><section class="columns"><article><h2>结构索引</h2><div id="index"></div></article><article><h2>重点精读</h2><div id="deep"></div></article></section><h2>原始 PDF 页面（完整展示，阅读只取上述选区）</h2><section class="originals"><figure><figcaption>PDF 第 6 页</figcaption><img src="original-pdf-6.png"></figure><figure><figcaption>PDF 第 7 页</figcaption><img src="original-pdf-7.png"></figure></section></main>
<script src="../../web/vendor/marked.js"></script><script src="../../web/vendor/purify.js"></script><script src="../../web/vendor/katex.js"></script><script src="../../web/lesson_render.js"></script><script>const sample=PAYLOAD;renderLessonText(document.getElementById('index'),sample.index);renderLessonText(document.getElementById('deep'),sample.deep);</script></html>'''.replace('PAYLOAD',payload)
    (target/'结构索引与重点精读对照.html').write_text(html,encoding='utf-8')
    print('COMPLETE '+str(target/'结构索引与重点精读对照.html'),flush=True)

if __name__=='__main__':asyncio.run(main())
