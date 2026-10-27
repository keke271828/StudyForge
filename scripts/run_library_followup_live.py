"""Replay six captured native-preparation requests; save final answers, no reasoning."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'build/library-followup-20261021'
if '--source' in sys.argv:SOURCE=ROOT/'build'/sys.argv[sys.argv.index('--source')+1]
NAMES=tuple(sys.argv[sys.argv.index('--cases')+1].split(',')) if '--cases' in sys.argv else ('math','gauss','causal')
OUT=ROOT/'build'/sys.argv[1]
if '--live' not in sys.argv:raise SystemExit('Pass --live to use the configured DeepSeek service.')
if OUT.exists():raise SystemExit('Use a fresh output folder.')
OUT.mkdir(parents=True)
os.environ['STUDYFORGE_DATA_DIR']=str(OUT/'data')
from studyforge import ai
from studyforge.db import j
ai.save_settings({'agent_tools_enabled':False,'background_learning_enabled':False,'model_concurrency':2})


async def main():
    pairs={phase:json.loads((SOURCE/phase/'requests.json').read_text(encoding='utf-8')) for phase in ('baseline','fixed')}
    tasks=[];results=[];gate=asyncio.Semaphore(2)
    async def sample(phase,request):
        async with gate:
            key=request['name']+'-'+phase;start=time.perf_counter();row={'case':request['name'],'phase':phase,
                'model':'deepseek-flash','effort':'high','original_reached_model':request['original_reached_model'],
                'input_file':key+'-request.json','answer_file':key+'.md','calls':[]}
            (OUT/row['input_file']).write_text(j(request['messages']),encoding='utf-8')
            class Client(ai.DeepSeekClient):
                async def stream_packets(self,body):
                    log={'sha256':hashlib.sha256(j(body).encode()).hexdigest(),'file':key+'-body-'+str(len(row['calls'])+1)+'.json'}
                    row['calls'].append(log);(OUT/log['file']).write_text(j(body),encoding='utf-8')
                    async for packet in super().stream_packets(body):
                        if 'first_packet_seconds' not in row:row['first_packet_seconds']=round(time.perf_counter()-start,3)
                        if packet.get('usage'):log['usage']=packet['usage']
                        yield packet
            client=None
            try:
                client=Client('deepseek-flash',effort='high');final=''
                async with asyncio.timeout(360):
                    async for kind,item in client.agent_stream(request['messages']):
                        if kind=='delta' and item and 'first_text_seconds' not in row:row['first_text_seconds']=round(time.perf_counter()-start,3)
                        if kind=='final':final=item
                if not final.strip():raise RuntimeError('No substantive final text returned.')
                (OUT/row['answer_file']).write_text(final,encoding='utf-8');row.update(status='completed',characters=len(final))
            except Exception as exc:row.update(status='failed',error=type(exc).__name__+': '+str(exc))
            finally:
                if client:await client.close()
                row['seconds']=round(time.perf_counter()-start,3);results.append(row)
                (OUT/'report.json').write_text(j(results),encoding='utf-8');print(j({k:v for k,v in row.items() if k!='calls'}),flush=True)
    for index,name in enumerate(NAMES):
        for phase in (('baseline','fixed') if index%2==0 else ('fixed','baseline')):
            tasks.append(sample(phase,next(row for row in pairs[phase] if row['name']==name)))
    await asyncio.gather(*tasks)


if __name__=='__main__':asyncio.run(main())
