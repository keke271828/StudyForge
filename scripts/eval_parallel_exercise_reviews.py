"""Real serial/parallel/cap-one checks with the same two audit prompts."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


class StopBeforeRepair(Exception):pass


async def main(name):
    folder=ROOT/'build'/name
    if (folder/'results.json').exists():raise SystemExit('Use a new folder.')
    folder.mkdir(parents=True,exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
    from studyforge import ai,review
    from studyforge.db import create_project,create_job,update_job,many
    from studyforge.scheduling import execution_scope
    from scripts.diagnose_deepseek_speed import traced_class
    from scripts.exercise_review_cases import CASES
    case=next(case for case in CASES if case['id']=='subtle_answer_leak')
    cls=traced_class();project=create_project('隔离双核查并行实测');results=[]
    (folder/'input.json').write_text(json.dumps(case,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'source-hashes.json').write_text(json.dumps({file:hashlib.sha256((ROOT/file).read_bytes()).hexdigest() for file in
        ('studyforge/review.py','studyforge/ai.py','studyforge/generation_control.py','studyforge/scheduling.py')},indent=2),encoding='utf-8')
    for label,parallel,limit in [('serial_two',False,2),('parallel_two',True,2),('parallel_one',True,1)]:
        ai.save_settings({'api_connection_mode':'direct','model_concurrency':limit,'task_parallel_enabled':True,
            'background_learning_enabled':False,'agent_tools_enabled':False,'agent_network_enabled':False})
        calls=[];clients=[];job=create_job(project['id'],'audit_probe',{'parallel':parallel,'limit':limit})
        class Client:
            model='deepseek-flash';effort='high'
            def __init__(self):self.raw=cls(self.model,effort=self.effort);clients.append(self)
            def fork(self):return Client()
            async def close(self):await self.raw.close()
            async def complete(self,system,user,**kwargs):
                if '你是独立解题员' in system:return json.dumps(case['independent'],ensure_ascii=False)
                if '你是习题审查员' not in system:raise StopBeforeRepair()
                stage=user.split('。',1)[0];entry={'stage':stage,'system':system,'user':user};calls.append(entry)
                before=len(self.raw.traces);start=time.perf_counter();final=''
                try:
                    async for kind,value in self.raw.agent_stream([{'role':'system','content':system},{'role':'user','content':user}],json_mode=True):
                        if kind=='final':final=value
                    entry['response']=final;return final
                finally:
                    entry['seconds']=time.perf_counter()-start
                    entry['http_attempts']=[trace.public() for trace in self.raw.traces[before:]]
        parent=Client();start=time.perf_counter();row={'label':label,'parallel':parallel,'limit':limit,'job_id':job}
        try:
            async def run():
                try:await review.review_exercises(parent,case['source'],case['questions'],context_policy=case['policy'],parallel=parallel)
                except StopBeforeRepair:pass
            async with execution_scope(job_id=job,project_id=project['id'],label=label):await asyncio.wait_for(run(),240)
            row['reports']=[ai.parse_json_response(call['response']) for call in calls]
            row['status']='completed';update_job(job,'completed',100,{})
        except Exception as exc:row.update(status='failed',error_type=type(exc).__name__);update_job(job,'failed',0,{},error=type(exc).__name__)
        finally:await asyncio.gather(*(client.close() for client in clients),return_exceptions=True)
        row.update(wall_s=time.perf_counter()-start,audit_calls=len(calls),
            calls=calls,spans=many('SELECT resource,queued_at,started_at,ended_at,duration_ms,status FROM execution_spans WHERE job_id=?',(job,)))
        results.append(row);(folder/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'label':label,'status':row['status'],'seconds':round(row['wall_s'],3),'calls':len(calls),
            'passed_fields':[report['passed'] for report in row.get('reports',[])]},ensure_ascii=True),flush=True)


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
