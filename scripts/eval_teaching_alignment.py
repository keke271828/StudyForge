"""Compare frozen review requests, without changing teaching/app policies."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from scripts.teaching_alignment_candidate import RULES, VERSION, PAIR_RULES, PAIR_VERSION, cases

ROOT = Path(__file__).resolve().parents[1]
MARKER = '按所选风格检查具体的术语解释'


async def main(name, variant='first', selected=()):
    out = ROOT/'build'/name
    if (out/'inputs.json').exists(): raise SystemExit('Use a new folder to preserve earlier runs.')
    out.mkdir(parents=True, exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(out/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(out/'isolated-model')
    from studyforge import ai
    from studyforge.review import review_explanation
    ai.save_settings({'api_connection_mode':'direct','agent_tools_enabled':False,
        'agent_network_enabled':False,'background_learning_enabled':False,'model_concurrency':2})
    inputs = cases(ROOT)
    if selected:
        if set(selected)-inputs.keys(): raise SystemExit('Unknown case.')
        inputs={key:inputs[key] for key in selected}
    chosen_rules,chosen_version=(PAIR_RULES,PAIR_VERSION) if variant=='pairs' else (RULES,VERSION)
    for item in inputs.values():
        item['draft_sha256'] = hashlib.sha256(item['draft'].encode()).hexdigest()
    (out/'inputs.json').write_text(json.dumps(inputs, ensure_ascii=False, indent=2), encoding='utf-8')
    gate, rows = asyncio.Semaphore(2), []

    class Recorder:
        def __init__(self, client, arm, records): self.client,self.arm,self.records=client,arm,records
        async def complete(self, system, user, **kw):
            assert chosen_rules not in system, 'Experiment is already deployed; replay frozen requests instead.'
            if self.arm=='candidate':
                assert system.count(MARKER)==1
                system=system.replace(MARKER, chosen_rules+MARKER)
            item={'system':system,'user':user,'json_mode':kw.get('json_mode',False)}
            item['request_sha256']=hashlib.sha256(json.dumps(item,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            self.records.append(item)
            result=await self.client.complete(system,user,**kw)
            item['response']=result
            return result

    async def sample(key, arm):
        async with gate:
            client=ai.DeepSeekClient('deepseek-flash',effort='high')
            records=[]; wrapper=Recorder(client,arm,records)
            start=time.perf_counter(); case=inputs[key]
            row={'case':key,'arm':arm,'model':'deepseek-flash','effort':'high','tools':False,
                 'candidate_version':chosen_version,'sample_scope':'one_existing_fast_review_with_frozen_synthetic_or_saved_draft'}
            try:
                body,reports=await asyncio.wait_for(review_explanation(wrapper,case['source'],case['draft'],mode='fast',
                    learning_mode='deep',explanation_style='balanced',requirements=case['question'],summary_level=3),300)
                file=key+'-'+arm+'.md'; (out/file).write_text(body,encoding='utf-8',newline='')
                row.update(status='completed',output_file=file,output_sha256=hashlib.sha256(body.encode()).hexdigest(),
                           reports=reports,unchanged=body==case['draft'])
            except Exception as exc: row.update(status='failed',error=type(exc).__name__+': '+str(exc))
            finally:
                await client.close();row.update(seconds=round(time.perf_counter()-start,2),model_calls=len(records))
                (out/(key+'-'+arm+'-requests.json')).write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
                rows.append(row);(out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({k:v for k,v in row.items() if k!='reports'},ensure_ascii=True),flush=True)

    order=[]
    for i,key in enumerate(inputs):
        arms=(('candidate',) if variant=='pairs' else (('current','candidate') if i%2==0 else ('candidate','current')))
        order.extend((key,arm) for arm in arms)
    await asyncio.gather(*(sample(*args) for args in order))


if __name__=='__main__': asyncio.run(main(sys.argv[1], *(sys.argv[2:3] or ['first']), selected=sys.argv[3:]))
