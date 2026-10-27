"""Second bounded candidate: explicit weak/strong assumptions and receipts."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def cases():
    from scripts.review_focus_cases import delivered
    shared='本材料区分弱条件与强条件。只给闭区间包含关系时，端点可以取到；若另已知严格不等式，则可使用严格估计。比较构造只要求证明给定目标，不把某种可行选择当唯一。'
    return [delivered('4','delivered_high',['max_not_unique','equal_radius_not_enough','unequal_can_use_midpoint']),
        {'id':'weak_wrong','expected_pass':False,'targets':['closed_endpoint'],
         'source':shared+'本段仅知道两个独立实数x∈[0,1]和y∈[2,3]，没有数列收敛或严格内点前提。',
         'document':'# 端点判断\n\n本段只给 x 属于闭区间[0,1]、y 属于闭区间[2,3]，没有额外条件。因此必须有 $0<x<1$ 和 $2<y<3$，因为闭区间的端点也不能取到。\n\n## 系统性总结\n\n从闭区间包含可以推出严格内点估计。',
         'requirements':'只检查给定弱前提能推出什么，不补数列收敛定义，不出题。'},
        {'id':'weak_correct','expected_pass':True,'targets':[],
         'source':shared+'本段仅知道两个独立实数x∈[0,1]和y∈[2,3]，没有数列收敛或严格内点前提。',
         'document':'# 只从闭区间包含出发\n\n本段仅给出独立实数 $x\\in[0,1]$ 与 $y\\in[2,3]$，没有更强条件。因此 $0\\le x\\le1$，$2\\le y\\le3$。只凭这些包含关系，不能保证 $x<1$ 或 $y>2$，取 $x=1,y=2$ 就可反驳这种严格结论。\n\n## 系统性总结\n\n端点可取；不能从未提供的严格前提出发。',
         'requirements':'只解释本段明确给出的闭区间前提，不借用主证明或其他材料的更强条件，不出题。'},
        {'id':'strong_correct','expected_pass':True,'targets':[],
         'source':shared+'本段已知0<x<1与2<y<3，同时也有x∈[0,1]、y∈[2,3]。保留严格前提，不是把它改成只知闭区间。',
         'document':'# 严格前提仍保留\n\n本段明确已知 $0<x<1$ 与 $2<y<3$。这些数当然也属于相应闭区间，但这没有撤销严格前提。因此可以写 $x<1$、$y>2$；不能因为提到了闭区间就说这些严格估计不合法。\n\n## 系统性总结\n\n按全部实际给定条件判断，不擅自加条件，也不擅自删条件。',
         'requirements':'说明给定强前提允许使用严格估计，不将它误读成只有弱条件，不出题。'},
        {'id':'construction_correct','expected_pass':True,'targets':[],
         'source':'令N1与N2为正整数。目标仅为找到一个正整数N，使任意n>N同时满足n>N1和n>N2。N=max(N1,N2)可用，更大的整数也可。',
         'document':'# 选门槛\n\n取 $N=\\max(N_1,N_2)$，是一个可行且最小的统一门槛。这里必须保证所用下标越过两门槛，但N不必恰好等于最大值；由于两者是正整数，取 $N=N_1+N_2$ 也可，代价是门槛更大。\n\n## 系统性总结\n\n必要的是同时越过两门槛；取最大值是一种方便的最小选择，不是唯一可行选择。',
         'requirements':'只解释上述存在性目标，不要求唯一的N，不出题。'}]


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
    from scripts import review_focus_v2_candidate as candidate
    ai.save_settings({'api_connection_mode':'direct','model_concurrency':2,'task_parallel_enabled':True,
        'agent_tools_enabled':False,'agent_network_enabled':False,'background_learning_enabled':False})
    inputs=cases();(folder/'inputs.json').write_text(j(inputs),encoding='utf-8')
    (folder/'baseline-review.py').write_bytes((ROOT/'studyforge/review.py').read_bytes())
    project=create_project('明确前提与核对表候选');cls=traced_class();results=[]
    async def run(case,arm):
        raw=cls('deepseek-flash',effort='high');calls=[];text,receipt=candidate.prompt(case['document'])
        job=create_job(project['id'],'review_probe',{'case':case['id'],'arm':arm});start=time.perf_counter()
        class Adapter:
            model='deepseek-flash';effort='high'
            def fork(self):return self
            async def complete(self,system,user,**kwargs):
                if len(calls)>=2:raise RuntimeError('Bounded candidate request limit')
                entry={'system':system,'original_user_sha256':hashlib.sha256(user.encode()).hexdigest(),
                    'user':user+(text if arm=='candidate' else '')};calls.append(entry);final=''
                async for kind,value in raw.agent_stream([{'role':'system','content':system},{'role':'user','content':entry['user']}],json_mode=True):
                    if kind=='final':final=value
                entry['response']=final
                if arm=='candidate':candidate.validate(ai.parse_json_response(final),receipt)
                return final
        row={'case':case['id'],'arm':arm,'job_id':job,'expected_pass':case['expected_pass'],'targets':case['targets'],
            'focus_receipt':receipt if arm=='candidate' else None}
        try:
            async with execution_scope(job_id=job,project_id=project['id'],label=case['id']+':'+arm):
                document,reports=await asyncio.wait_for(review.review_explanation(Adapter(),case['source'],case['document'],mode='fast',
                    learning_mode='deep',explanation_style='balanced',requirements=case['requirements'],summary_level=3),300)
            row.update(status='completed',reports=reports,final_document_file=case['id']+'-'+arm+'-final.md')
            (folder/row['final_document_file']).write_text(document,encoding='utf-8');update_job(job,'completed',100,{})
        except BaseException as exc:
            row.update(status='failed',error_type=type(exc).__name__);update_job(job,'failed',0,{},error=type(exc).__name__)
        finally:await raw.close()
        row.update(seconds=time.perf_counter()-start,model_requests=len(raw.traces),http_attempts=[trace.public() for trace in raw.traces],
            records_file=case['id']+'-'+arm+'-final-records.json',spans=many('SELECT resource,label,status,duration_ms FROM execution_spans WHERE job_id=?',(job,)))
        (folder/row['records_file']).write_text(j(calls),encoding='utf-8');results.append(row);(folder/'results.json').write_text(j(results),encoding='utf-8')
        print(json.dumps({'case':case['id'],'arm':arm,'status':row['status'],'seconds':round(row['seconds'],2),
            'model_requests':row['model_requests'],'verdicts':[r.get('passed') for r in row.get('reports',[])]},ensure_ascii=True),flush=True)
    for i,case in enumerate(inputs):
        arms=['baseline','candidate'] if i%2==0 else ['candidate','baseline']
        await asyncio.gather(*(run(case,arm) for arm in arms))


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
