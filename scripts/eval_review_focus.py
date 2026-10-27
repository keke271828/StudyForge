"""Same audit with/without a local priority index; bounded real paired probes."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


async def main(name):
    folder=ROOT/'build'/name
    if folder.exists() and any(folder.iterdir()):raise SystemExit('Use a fresh folder.')
    folder.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
    from studyforge import ai,review
    from studyforge.db import create_project,create_job,update_job,many,j
    from studyforge.scheduling import execution_scope
    from scripts.diagnose_deepseek_speed import traced_class
    from scripts.review_focus_cases import cases
    from scripts import review_focus_candidate
    ai.save_settings({'api_connection_mode':'direct','model_concurrency':2,'task_parallel_enabled':True,
        'agent_tools_enabled':False,'agent_network_enabled':False,'background_learning_enabled':False})
    inputs=cases();(folder/'inputs.json').write_text(j(inputs),encoding='utf-8')
    project=create_project('核查原句定位候选对照');results=[];cls=traced_class()
    (folder/'source-hashes.json').write_text(j({file:hashlib.sha256((ROOT/file).read_bytes()).hexdigest() for file in
        ('studyforge/review.py','studyforge/algebra_hints.py','scripts/review_focus_candidate.py')}),encoding='utf-8')
    async def run(case,arm):
        raw=cls('deepseek-flash',effort='high');calls=[];focus,receipt=review_focus_candidate.prompt(case['document'])
        job=create_job(project['id'],'review_probe',{'case':case['id'],'arm':arm});start=time.perf_counter()
        class Adapter:
            model='deepseek-flash';effort='high'
            def fork(self):return self
            async def complete(self,system,user,**kwargs):
                if len(calls)>=2:raise RuntimeError('Bounded probe request limit')
                entry={'system':system,'original_user_sha256':hashlib.sha256(user.encode()).hexdigest(),
                    'user':user+(focus if arm=='focus' else '')};calls.append(entry)
                final=''
                async for kind,value in raw.agent_stream([{'role':'system','content':system},{'role':'user','content':entry['user']}],json_mode=True):
                    if kind=='final':final=value
                entry['response']=final;return final
        row={'case':case['id'],'arm':arm,'job_id':job,'expected_pass':case['expected_pass'],'targets':case['targets'],
            'focus_receipt':receipt if arm=='focus' else None}
        try:
            async with execution_scope(job_id=job,project_id=project['id'],label=case['id']+':'+arm):
                document,reports=await asyncio.wait_for(review.review_explanation(Adapter(),case['source'],case['document'],
                    mode='fast',learning_mode='deep',explanation_style='balanced',output_language='zh',
                    requirements=case['requirements'],summary_level=3),300)
            row.update(status='completed',reports=reports,final_document_file=case['id']+'-'+arm+'-final.md')
            (folder/row['final_document_file']).write_text(document,encoding='utf-8');update_job(job,'completed',100,{})
        except BaseException as exc:
            row.update(status='failed',error_type=type(exc).__name__);update_job(job,'failed',0,{},error=type(exc).__name__)
        finally:await raw.close()
        row.update(seconds=time.perf_counter()-start,model_requests=len(raw.traces),http_attempts=[trace.public() for trace in raw.traces],
            records_file=case['id']+'-'+arm+'-final-records.json',spans=many('SELECT resource,label,status,duration_ms FROM execution_spans WHERE job_id=?',(job,)))
        (folder/row['records_file']).write_text(j(calls),encoding='utf-8');results.append(row)
        (folder/'results.json').write_text(j(results),encoding='utf-8')
        print(json.dumps({'case':case['id'],'arm':arm,'status':row['status'],'seconds':round(row['seconds'],2),
            'model_requests':row['model_requests'],'verdicts':[report.get('passed') for report in row.get('reports',[])]},ensure_ascii=True),flush=True)
    for i,case in enumerate(inputs):
        arms=['baseline','focus'] if i%2==0 else ['focus','baseline']
        await asyncio.gather(*(run(case,arm) for arm in arms))


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
