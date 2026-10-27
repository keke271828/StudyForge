"""Sixteen bounded audit components on four frozen synthetic fixtures.

Freeze independent solutions to compare auditors, not learner performance.
Final audit JSON is private developer QA; no model reasoning is saved.
"""
import asyncio
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


class AuditComplete(Exception):pass


def frozen_long_case():
    """Recover only literals from a saved synthetic audit request, never eval."""
    records=json.loads((ROOT/'build/lesson-check-real-20261015-3/private-final-model-records.json').read_text(encoding='utf-8'))
    user=records[3]['user']
    source=user.split('\n资料：\n',1)[1].split('\n独立解法：',1)[0]
    independent=ast.literal_eval(user.split('\n独立解法：',1)[1].split('\n独立解题疑点编号：',1)[0])
    questions=ast.literal_eval(user.split('\n题目与解答：\n',1)[1])
    return {'id':'frozen_long_math','title':'真实长输入：原正确数学检查题','expected_pass':True,'expected_problems':[],
        'source':source,'independent':independent,'questions':questions,
        'policy':user.split('\n',1)[1].split('\n资料：\n',1)[0]}


async def main(name,subset=None):
    folder=ROOT/'build'/name
    if (folder/'results.json').exists():raise SystemExit('Use a new output folder; preserve prior trials.')
    folder.mkdir(parents=True,exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
    from studyforge import ai,review
    from scripts import exercise_review_policy_candidate as policy
    from studyforge.db import create_project,create_job,update_job
    from studyforge.scheduling import execution_scope
    from scripts.diagnose_deepseek_speed import traced_class
    from scripts.exercise_review_cases import CASES
    cases=[frozen_long_case()] if subset=='long' else [case for case in CASES if case['id']=='subtle_answer_leak'] if subset=='leak' else CASES
    ai.save_settings({'api_connection_mode':'direct','model_concurrency':1,'agent_tools_enabled':False,
        'agent_network_enabled':False,'background_learning_enabled':False})
    project=create_project('隔离习题核查方案对照');cls=traced_class();results=[]
    (folder/'inputs.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'configuration.json').write_text(json.dumps({'model':'deepseek-flash','connection_mode':'direct',
        'independent_solutions':'frozen_synthetic','tools':False,'planned_audit_component_requests':len(cases)*(3 if subset else 4),
        'production_default_changed':False,'source_sha256':{file:hashlib.sha256((ROOT/file).read_bytes()).hexdigest() for file in (
            'studyforge/review.py','scripts/exercise_review_policy_candidate.py','scripts/exercise_review_cases.py')}},indent=2),encoding='utf-8')
    for index,case in enumerate(cases):
        plans=['dual_high','combined_high'] if subset else ['dual_high','combined_high','combined_low']
        plans=plans[index%3:]+plans[:index%3]
        concerns=[]
        for answer in case['independent']['answers']:
            for issue in answer['issues']:
                concerns.append({'index':answer['index'],'problem':issue,'category':'statement','concern_id':len(concerns)})
        for plan in plans:
            strategy='dual' if plan=='dual_high' else 'combined';effort='low' if plan=='combined_low' else 'high'
            client=cls('deepseek-flash',effort=effort);calls=[];job=create_job(project['id'],'review_probe',{'case':case['id'],'plan':plan})
            prefix=case['id']+'-'+plan;row={'case':case['id'],'plan':plan,'job_id':job,'expected_pass':case['expected_pass']}
            class Adapter:
                async def complete(self,system,user,**kwargs):
                    if '你是独立解题员' in system:return json.dumps(case['independent'],ensure_ascii=False)
                    if len(calls)>=len(policy.stages(strategy)):raise AuditComplete()
                    if strategy=='dual':
                        assert system==policy.AUDIT_SYSTEM,'Current production audit template drifted'
                        stage,criterion=policy.stages('dual')[len(calls)]
                        assert user==policy.request(stage,criterion,case['policy'],case['source'],case['independent'],concerns,case['questions'])
                    entry={'system':system,'user':user,'json_mode':kwargs.get('json_mode',False)};calls.append(entry)
                    start=time.perf_counter();final=''
                    try:
                        async for kind,value in client.agent_stream([{'role':'system','content':system},{'role':'user','content':user}],json_mode=kwargs.get('json_mode',False)):
                            if kind=='final':final=value
                        entry['response']=final;return final
                    finally:entry['seconds']=time.perf_counter()-start
            start=time.perf_counter();adapter=Adapter()
            try:
                async def run():
                    if strategy=='dual':
                        try:await review.review_exercises(adapter,case['source'],copy.deepcopy(case['questions']),context_policy=case['policy'])
                        except AuditComplete:pass # Stop before content revision; only compare the two auditors.
                    else:
                        stage,criterion=policy.stages('combined')[0]
                        await adapter.complete(policy.AUDIT_SYSTEM,policy.request(stage,criterion,case['policy'],case['source'],case['independent'],concerns,case['questions']),json_mode=True)
                async with execution_scope(job_id=job,project_id=project['id'],label='习题核查方案对照'):
                    await asyncio.wait_for(run(),300)
                parsed=[ai.parse_json_response(entry['response']) for entry in calls]
                assert len(parsed)==len(policy.stages(strategy))
                row.update(status='completed',model_reports=parsed)
                update_job(job,'completed',100,{})
            except Exception as exc:
                row.update(status='failed',error_type=type(exc).__name__);update_job(job,'failed',0,{},error=type(exc).__name__)
            finally:await client.close()
            row.update(seconds=round(time.perf_counter()-start,3),audit_component_calls=len(calls),
                http_attempts=[trace.public() for trace in client.traces],record_file=prefix+'-private-records.json')
            (folder/row['record_file']).write_text(json.dumps(calls,ensure_ascii=False,indent=2),encoding='utf-8')
            results.append(row);(folder/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'case':case['id'],'plan':plan,'status':row['status'],'seconds':row['seconds'],
                'audit_component_calls':row['audit_component_calls'],'http_attempts':len(row['http_attempts']),
                'passed_fields':[entry.get('passed') for entry in row.get('model_reports',[])]},ensure_ascii=True),flush=True)


if __name__=='__main__':asyncio.run(main(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else None))
