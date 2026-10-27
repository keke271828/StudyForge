"""Paired real audit probes; all original bytes and failed trials retained."""
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


async def main(name):
    folder=ROOT/'build'/name
    if (folder/'results.json').exists():raise SystemExit('Keep completed or failed trials; use a new folder.')
    assert (folder/'baseline-review.py').exists(),'Snapshot the previous review module before editing it.'
    os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
    from studyforge import ai,review
    from studyforge.db import create_project,create_job,j,update_job
    from studyforge.scheduling import execution_scope
    from scripts.diagnose_deepseek_speed import traced_class
    from scripts.eval_review_focus_v2 import cases as prior_cases
    from scripts.review_focus_cases import cases as first_cases
    specification=importlib.util.spec_from_file_location('studyforge._data_boundary_baseline',folder/'baseline-review.py')
    baseline=importlib.util.module_from_spec(specification);specification.loader.exec_module(baseline)
    inputs=[c for c in prior_cases() if c['id'] in ('delivered_high','weak_wrong','strong_correct')]
    inputs.append(next(c for c in first_cases() if c['id']=='correct_social_control'))
    (folder/'inputs.json').write_text(j(inputs),encoding='utf-8')
    ai.save_settings({'api_connection_mode':'direct','model_concurrency':2,'agent_tools_enabled':False,
        'agent_network_enabled':False,'background_learning_enabled':False,'task_parallel_enabled':True})
    project=create_project('讲解审核输入分隔对照');cls=traced_class();results=[]
    (folder/'source-hashes.json').write_text(j({p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
        ('studyforge/review.py','studyforge/review_input.py','studyforge/teaching_policy.py')}),encoding='utf-8')
    async def run(case,arm):
        native=cls('deepseek-flash',effort='high');calls=[]
        job=create_job(project['id'],'review_probe',{'case':case['id'],'arm':arm});start=time.perf_counter()
        class Adapter:
            model='deepseek-flash';effort='high'
            def fork(self):return self
            async def complete(self,system,user,**kwargs):
                if len(calls)>=2:raise RuntimeError('Bounded probe request limit')
                if arm=='separated':
                    from studyforge.review_input import MARKER
                    data=json.loads(user.split(MARKER,1)[1])
                    assert data['source_text']==case['source'] and data['explanation_text']==case['document']
                entry={'system':system,'user':user};calls.append(entry);answer=''
                async for kind,value in native.agent_stream([{'role':'system','content':system},{'role':'user','content':user}],json_mode=True):
                    if kind=='final':answer=value
                entry['response']=answer;return answer
        row={'case':case['id'],'arm':arm,'initial_label_pass':case['expected_pass'],'targets':case['targets']}
        try:
            module=review if arm=='separated' else baseline
            async with execution_scope(job_id=job,project_id=project['id'],label=case['id']+':'+arm):
                final,reports=await asyncio.wait_for(module.review_explanation(Adapter(),case['source'],case['document'],mode='fast',
                    learning_mode='deep',explanation_style='balanced',requirements=case['requirements'],summary_level=3),300)
            row.update(status='completed',reports=reports);(folder/(case['id']+'-'+arm+'-final.md')).write_text(final,encoding='utf-8')
            update_job(job,'completed',100,{})
        except BaseException as exc:
            row.update(status='failed',error_type=type(exc).__name__);update_job(job,'failed',0,{},error=type(exc).__name__)
        finally:await native.close()
        row.update(seconds=time.perf_counter()-start,model_requests=len(native.traces),http_attempts=[t.public() for t in native.traces])
        (folder/(case['id']+'-'+arm+'-records.json')).write_text(j(calls),encoding='utf-8')
        results.append(row);(folder/'results.json').write_text(j(results),encoding='utf-8')
        print(json.dumps({'case':case['id'],'arm':arm,'status':row['status'],'seconds':round(row['seconds'],2),
            'requests':row['model_requests'],'verdicts':[r.get('passed') for r in row.get('reports',[])]},ensure_ascii=True),flush=True)
    for i,case in enumerate(inputs):
        order=['baseline','separated'] if i%2==0 else ['separated','baseline']
        await asyncio.gather(*(run(case,arm) for arm in order))


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
