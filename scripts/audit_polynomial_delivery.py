"""Use the existing fast review on a real, deliberately unedited lecture."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


async def main(name):
    out=ROOT/'build'/name
    if out.exists() and any(out.iterdir()):raise SystemExit('Use a fresh folder.')
    out.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(out/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(out/'isolated-model')
    from studyforge import ai
    from studyforge.db import j
    from studyforge.review import review_explanation
    from scripts.diagnose_deepseek_speed import traced_class
    ai.save_settings({'api_connection_mode':'direct','agent_tools_enabled':False,'agent_network_enabled':False,
        'background_learning_enabled':False,'model_concurrency':2})
    probe=ROOT/'build/polynomial-agent-real-20261016-1'
    source=r'一维给定模型m x″=−kx，其中m,k为正常数，v=x′。能量表达式E=mv²/2+kx²/2，x,v沿时间变化。'
    question=next(r['question'] for r in json.loads((probe/'results.json').read_text(encoding='utf-8')) if r['role']=='lecture')
    document=(probe/'lecture-final.md').read_text(encoding='utf-8')
    cls=traced_class();clients=[];records=[]
    class Adapter:
        def __init__(self):self.native=cls('deepseek-flash',effort='high');clients.append(self)
        def fork(self):return Adapter()
        async def close(self):await self.native.close()
        async def complete(self,system,user,**kwargs):
            if sum(len(c.native.traces) for c in clients)>=2:raise RuntimeError('Bounded fast-review request limit')
            messages=[{'role':'system','content':system},{'role':'user','content':user}];answer=''
            async for kind,value in self.native.agent_stream(messages,json_mode=kwargs.get('json_mode',False)):
                if kind=='final':answer=value
            records.append({'system':system,'user':user,'response':answer});return answer
    client=Adapter();start=time.perf_counter();result={}
    try:
        async with asyncio.timeout(240):
            revised,reports=await review_explanation(client,source,document,mode='fast',learning_mode='deep',
                explanation_style='balanced',requirements=question,summary_level=3)
        (out/'原样初稿.md').write_text(document,encoding='utf-8')
        (out/'快速核查后.md').write_text(revised,encoding='utf-8')
        result={'status':'completed','reports':reports,'source':source,'requirements':question,'characters_before':len(document),
            'characters_after':len(revised),'changed':revised!=document}
    except Exception as exc:result={'status':'failed','error_type':type(exc).__name__}
    finally:
        for c in clients:await c.close()
    result.update(seconds=time.perf_counter()-start,model_requests=sum(len(c.native.traces) for c in clients),
        http_attempts=[t.public() for c in clients for t in c.native.traces])
    (out/'results.json').write_text(j(result),encoding='utf-8')
    (out/'public-model-records.json').write_text(j(records),encoding='utf-8')
    print(json.dumps({'status':result['status'],'model_requests':result['model_requests'],'seconds':round(result['seconds'],2)},ensure_ascii=True),flush=True)


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
