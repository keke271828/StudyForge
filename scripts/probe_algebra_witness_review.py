"""Same fast-review requests, with/without a newly recovered local witness."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
FORMULA=r'$$a+\frac{b-a}{2}=\frac{a+b}{2}=\frac{3a+b-4}{2}$$'
CASES=[
    {'name':'unconditional','source':'设a,b为任意实数，a<b。两点中点为(a+b)/2。没有a=2的限制。',
     'document':'# 中点改写\n\n设a<b，中点的计算为：\n\n'+FORMULA+'\n\n## 系统性总结\n上述等式对任意a<b成立。'},
    {'name':'conditional','source':'本例已知a=2，且b>a。这里只核对这个给定条件下的代数变形。',
     'document':'# 在给定条件下的中点改写\n\n本例明确已知a=2、b>a。第一个等号为一般恒等式，第二个等号使用a=2：\n\n'+FORMULA+'\n\n## 系统性总结\n末步使用a=2，不宣称对任意a成立，也不声称b>a是等式的必要条件。'},
]


async def main():
    if '--live' not in sys.argv:raise SystemExit('Pass --live for the configured model.')
    out=ROOT/'build'/sys.argv[1]
    if out.exists():raise SystemExit('Use a fresh output folder.')
    out.mkdir(parents=True);os.environ['STUDYFORGE_DATA_DIR']=str(out/'data')
    from studyforge import ai,algebra_hints,review
    from studyforge.db import j
    ai.save_settings({'agent_tools_enabled':False,'background_learning_enabled':False,'model_concurrency':2})
    namespace={'__name__':'studyforge.old_algebra_hints','__package__':'studyforge'}
    baseline=ROOT/'build/algebra-witness-20261021/baseline-algebra-hints.py'
    exec(compile(baseline.read_text(encoding='utf-8'),str(baseline),'exec'),namespace)
    requests=[]
    for case in CASES:
        for arm in ('baseline','fixed'):
            captured=[]
            class Capture:
                async def complete(self,system,user,**kwargs):
                    captured.append({'system':system,'user':user});return j({'passed':True,'issues':[]})
            with patch.object(algebra_hints,'candidates',namespace['candidates'] if arm=='baseline' else algebra_hints.candidates):
                await review.review_explanation(Capture(),case['source'],case['document'],mode='fast',
                    explanation_style='balanced',requirements='只核对所写中点改写，区分一般恒等与给定条件，不出题。',summary_level=3)
            assert len(captured)==1
            requests.append(case|{'arm':arm,'request':captured[0]})
    (out/'inputs.json').write_text(j(requests),encoding='utf-8')
    results=[];gate=asyncio.Semaphore(2)
    async def sample(case):
        async with gate:
            key=case['name']+'-'+case['arm'];started=time.perf_counter()
            row={'case':case['name'],'arm':case['arm'],'model':'deepseek-flash','effort':'high','calls':[]}
            class Client(ai.DeepSeekClient):
                async def _post(self,body,timeout=240,retry=True):
                    assert not row['calls'],'Keep one model request, with no repair/retry.'
                    public=copy.deepcopy(body)
                    for message in public['messages']:message.pop('reasoning_content',None)
                    file=key+'-request.json';(out/file).write_text(j(public),encoding='utf-8')
                    call={'file':file,'sha256':hashlib.sha256(j(public).encode()).hexdigest()};row['calls'].append(call)
                    packet=await super()._post(body,timeout,retry=False)
                    if packet.get('usage'):call['usage']=packet['usage']
                    return packet
            client=Client('deepseek-flash',effort='high')
            try:
                async with asyncio.timeout(300):
                    answer=await client.complete(**case['request'],json_mode=True)
                file=key+'.json';(out/file).write_text(answer,encoding='utf-8')
                result=ai.parse_json_response(answer)
                if type(result.get('passed')) is not bool or not isinstance(result.get('issues'),list):raise ValueError('Invalid review shape.')
                row.update(status='completed',answer_file=file,passed=result['passed'],issues=result['issues'])
            except Exception as exc:row.update(status='failed',error=type(exc).__name__+': '+str(exc))
            finally:
                await client.close();row['seconds']=round(time.perf_counter()-started,3)
                results.append(row);(out/'report.json').write_text(j(results),encoding='utf-8')
                print(j({k:v for k,v in row.items() if k not in ('calls','issues')}),flush=True)
    await asyncio.gather(*(sample(case) for case in requests))


if __name__=='__main__':asyncio.run(main())
