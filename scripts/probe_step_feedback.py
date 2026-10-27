"""Bounded live grading and reteaching samples, using isolated synthetic work."""
import asyncio
import hashlib
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
    from studyforge import ai,assessment,homework
    from studyforge.db import j
    from scripts.diagnose_deepseek_speed import traced_class
    ai.save_settings({'api_connection_mode':'direct','agent_tools_enabled':False,'agent_network_enabled':False,
        'background_learning_enabled':False,'model_concurrency':2,'library_reference_mode':'off'})
    native=traced_class();records=[];traces=[]
    class Native(native):
        # Grading without an AgentRuntime uses the non-streaming API. Observe
        # that real path too; stream-only instrumentation misses its attempts.
        def http_client(self):
            client=super().http_client()
            if getattr(client,'_step_feedback_metered',False):return client
            client._step_feedback_metered=True
            async def sent(request):
                body=json.loads(request.content)
                item={'body_sha256':hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                    'requested_model':body.get('model'),'effort':body.get('reasoning_effort'),'stream':body.get('stream'),
                    'started':time.perf_counter()}
                request.extensions['_step_probe']=item
            async def received(response):
                item=response.request.extensions.pop('_step_probe')
                item['status']=response.status_code;item['seconds']=time.perf_counter()-item.pop('started')
                await response.aread()
                if response.status_code==200:
                    packet=response.json();item['returned_model']=packet.get('model')
                    usage=packet.get('usage') or {}
                    item['usage']={k:usage[k] for k in ('prompt_tokens','completion_tokens','total_tokens') if type(usage.get(k)) is int}
                    message=(packet.get('choices') or [{}])[0].get('message') or {}
                    item['reasoning_characters']=len(message.get('reasoning_content') or '')
                    item['answer_characters']=len(message.get('content') or '')
                traces.append(item)
            client.event_hooks['request'].append(sent);client.event_hooks['response'].append(received)
            return client
    class Metered:
        model='deepseek-flash';effort='high'
        def __init__(self):self.client=Native(self.model,effort=self.effort)
        async def complete(self,system,user,**kwargs):
            start=time.perf_counter();answer=await self.client.complete(system,user,**kwargs)
            records.append({'system':system,'user':user,'answer':answer,'json':bool(kwargs.get('json_mode')),
                'seconds':time.perf_counter()-start})
            return answer
        def fork(self):return Metered()
        async def close(self):
            await self.client.close()
    cases=[
      {'id':'equivalent_proof','question':r'证明实数a,b满足a²+b²≥2ab，并给出等号条件。',
       'solution':r'由(a−b)²≥0展开移项，等号当且仅当a=b。',
       'rubric':'非负的合法依据40分，证明目标的等价关系40分，等号条件20分。接受等价正确证明，不因引入未使用的记号扣正确性分。',
       'answer':r'令u=a+b、v=a−b。由于v是实数，v²≥0，而a²+b²−2ab=v²，因此a²+b²≥2ab。等号当且仅当v=0，即a=b。',
       'expected':'100分；未使用的u不影响正确性。'},
      {'id':'partial_flux','question':r'空立方体处于匀强场E=E0 e_x，每面面积A>0，E0非零。写出闭合面通量，逐面计算，并判断零净通量能否推出E0=0。',
       'solution':r'Φ=E0∮e_x·dS；逐面为E0A,−E0A,0,0,0,0，总和零，不能由E0·0=0确定E0。',
       'rubric':'正确写出闭合面有向通量积分并合法提出常数E0：40分；正确逐面求和得净通量零：40分；说明零净通量不能推出E0=0：20分。三个评分点独立，仅明确满足该点评分，错误传播不另外扣分。',
       'answer':r'Φ=∮E·dS=E0∮e_x·dS，E0是常数所以能提出。剩下的面积积分是六个面的面积和6A，因此Φ=E0×6A。又因为空区域净通量为0，除以6A可得E0=0。',
       'expected':'40分；保留合法积分／提出常数的分，不把后面的错误倒扣成0分。'},
    ]
    results=[];worksheets={}
    for case in cases:
        question={'index':0,'topic':case['id'],'question':case['question']}
        solution={'index':0,'solution':case['solution'],'rubric':case['rubric']}
        worksheets[case['id']]={'questions_json':j([question]),'solutions_json':j([solution])}
        client=Metered();start=time.perf_counter();before=len(records)
        try:
            async with asyncio.timeout(240):
                grade=await assessment.verified_grade(client,[question],[solution],[case['answer']])
            results.append({'case':case,'status':'completed','grade':grade,'seconds':time.perf_counter()-start,
                'public_model_responses':len(records)-before})
        except Exception as exc:results.append({'case':case,'status':'failed','error_type':type(exc).__name__})
        finally:await client.close()
        (out/'results.json').write_text(j(results),encoding='utf-8')
        print(json.dumps({'case':case['id'],'status':results[-1]['status'],'responses':len(records)-before}),flush=True)
    # Historical difficulty is only a lead: the current written work supplies
    # the error location. This is not the learner's actual profile or score.
    for case_id in ('partial_flux',):
        case=next(c for c in cases if c['id']==case_id)
        result=next(r for r in results if r['case']['id']==case_id)
        if result['status']!='completed':continue
        client=Metered();start=time.perf_counter();before=len(records)
        row={'answers_json':j([case['answer']]),'options_json':j({'teaching':{'explanation_style':'balanced','output_language':'zh','learning_mode':'deep'},
            'profile':[{'topic':'高斯定律','observation':'我曾经不理解电通量是什么。','basis':'historical_question'}]})}
        try:
            async with asyncio.timeout(180):
                analysis=await homework.analyze(client,row,worksheets[case_id],result['grade'],[])
            result['remediation']={'status':'completed','analysis':analysis,'seconds':time.perf_counter()-start,
                'public_model_responses':len(records)-before}
        except Exception as exc:result['remediation']={'status':'failed','error_type':type(exc).__name__}
        finally:await client.close()
    (out/'results.json').write_text(j(results),encoding='utf-8')
    (out/'public-model-records.json').write_text(j(records),encoding='utf-8')
    (out/'request-metrics.json').write_text(j(traces),encoding='utf-8')
    (out/'manifest.json').write_text(j({'cases':len(cases),'responses':len(records),'http_attempts':len(traces),
        'production_data_modified':False,'model':'deepseek-flash','effort':'high',
        'results_sha256':hashlib.sha256((out/'results.json').read_bytes()).hexdigest()}),encoding='utf-8')
    print(json.dumps({'completed':True,'responses':len(records),'http_attempts':len(traces)}),flush=True)


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
