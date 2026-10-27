"""One bounded paired teaching experiment, with public text and no reasoning saved."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OLD=('核对除法、符号、最小值和退化情形；这些条件在具体例子、补充解释与总结中仍然有效。'
     '例子、类比和解释本身也须成立，只支持它们实际说明的结论；')
NEW=('推导和例子中的每个关键结论都有所需条件；除法、正负与退化情形在解释和总结中也成立。'
     '自拟例子就地说明额外设定，现实近似说明近似条件；先算通再接回原问题。'
     '不要把观察结果说成产生该结果的机制，也不要把方便选择写成唯一必要方法。')


async def main():
    if '--live' not in sys.argv:raise SystemExit('Pass --live for the configured service.')
    out=ROOT/'build'/sys.argv[1]
    if out.exists():raise SystemExit('Use a fresh folder.')
    out.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(out/'data')
    from studyforge import ai
    from studyforge.db import j
    ai.save_settings({'agent_tools_enabled':False,'background_learning_enabled':False,'model_concurrency':2})
    inputs=json.loads((ROOT/'build/library-auto-context-20261021/fixed-final/requests.json').read_text(encoding='utf-8'))
    cases=[]
    for row in inputs:
        before=copy.deepcopy(row['messages']);after=copy.deepcopy(before)
        assert after[0]['content'].count(OLD)==1
        after[0]['content']=after[0]['content'].replace(OLD,NEW,1)
        assert before[1:]==after[1:]
        cases.append({'name':row['name'],'question':row['question'],'quote':row['quote'],
                      'requests':{'baseline':before,'candidate':after}})
    (out/'cases.json').write_text(j(cases),encoding='utf-8')
    (out/'policy.json').write_text(j({'old':OLD,'candidate':NEW,'integrated':False}),encoding='utf-8')
    results=[];gate=asyncio.Semaphore(2)
    async def sample(case,arm):
        async with gate:
            key=case['name']+'-'+arm;start=time.perf_counter()
            row={'case':case['name'],'arm':arm,'model':'deepseek-flash','effort':'high','calls':[]}
            class Client(ai.DeepSeekClient):
                async def stream_packets(self,body):
                    assert not row['calls'],'One model request per sample; keep failures.'
                    public=copy.deepcopy(body)
                    for message in public['messages']:message.pop('reasoning_content',None)
                    file=key+'-request.json';(out/file).write_text(j(public),encoding='utf-8')
                    call={'file':file,'sha256':hashlib.sha256(j(public).encode()).hexdigest()};row['calls'].append(call)
                    async for packet in super().stream_packets(body):
                        if 'first_packet_seconds' not in row:row['first_packet_seconds']=round(time.perf_counter()-start,3)
                        if packet.get('usage'):call['usage']=packet['usage']
                        yield packet
            client=Client('deepseek-flash',effort='high');answer=''
            try:
                async with asyncio.timeout(300):
                    async for kind,value in client.agent_stream(case['requests'][arm]):
                        if kind=='delta' and value and 'first_text_seconds' not in row:row['first_text_seconds']=round(time.perf_counter()-start,3)
                        if kind=='final':answer=value
                if not answer.strip():raise RuntimeError('No substantive final text.')
                file=key+'.md';(out/file).write_text(answer,encoding='utf-8')
                row.update(status='completed',answer_file=file,characters=len(answer))
            except Exception as exc:row.update(status='failed',error=type(exc).__name__+': '+str(exc))
            finally:
                await client.close();row['seconds']=round(time.perf_counter()-start,3)
                results.append(row);(out/'report.json').write_text(j(results),encoding='utf-8')
                print(j({k:v for k,v in row.items() if k!='calls'}),flush=True)
    tasks=[]
    for number,case in enumerate(cases):
        tasks.extend(sample(case,arm) for arm in (('baseline','candidate') if number%2==0 else ('candidate','baseline')))
    await asyncio.gather(*tasks)


if __name__=='__main__':asyncio.run(main())
