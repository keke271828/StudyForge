"""One real single-target native design/solve/review trial; no real learner data."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


async def main(name,max_requests=6):
    if type(max_requests) is not int or not 4<=max_requests<=10:raise ValueError('Use four to ten requests.')
    folder=(ROOT/'build'/name).resolve()
    if folder.parent!=(ROOT/'build').resolve() or folder.exists():raise SystemExit('Use a fresh direct build subfolder.')
    folder.mkdir();os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
    from studyforge import ai,server
    from studyforge.db import j,one
    from tests.test_repair_selection import two_errors
    case,_,_=two_errors(folder)
    ai.save_settings({'agent_network_enabled':False,'agent_tools_enabled':False,'background_learning_enabled':False,'api_connection_mode':'direct'})
    calls=[]
    class Capture(ai.DeepSeekClient):
        async def _post(self,body,timeout=240,retry=True):
            if len(calls)>=max_requests:raise RuntimeError('Bounded evaluation request cap reached.')
            entry={'number':len(calls)+1,'model':body.get('model')};calls.append(entry)
            started=time.perf_counter();index=len(calls)
            # Full designs and solutions are private audit data, not public report links.
            (folder/f'private-request-{index}.json').write_text(j(body),encoding='utf-8')
            try:
                packet=await super()._post(body,timeout,retry=False)
                raw=packet.get('choices',[{}])[0].get('message',{}).get('content','')
                (folder/f'private-response-{index}.json').write_text(raw,encoding='utf-8')
                entry.update(usage=packet.get('usage'),status='completed')
                return packet
            except Exception as exc:entry.update(status='failed',error=type(exc).__name__);raise
            finally:entry['seconds']=round(time.perf_counter()-started,3)
    client=Capture('deepseek-flash',effort='high')
    async def factory(*args,**kwargs):return client
    server.assessment_client=factory
    options=server.repair_options(case['set_id']);started=time.perf_counter()
    report={'model':'deepseek-flash','effort':'high','synthetic_baseline':True,'parent_errors':2,'requested_original_indices':[0],
            'request_cap':max_requests}
    try:
        async with asyncio.timeout(300):
            result=await server.repair_practice(case['set_id'],server.RepairIn(provider='deepseek',model='deepseek-flash',
                reasoning_effort='high',conversation_id=case['conversation_id'],question_indices=[0],
                expected_submission_id=options['expected_submission_id'],expected_context_signature=options['expected_context_signature']))
        public=result['exercise_set'];assert len(public['questions'])==1 and public['repair']['targets'][0]['index']==0
        assert not public.get('solutions')
        (folder/'student-worksheet.json').write_text(j(public),encoding='utf-8')
        source=one('SELECT path FROM artifacts WHERE id=?',(result['artifact']['id'],))['path']
        target=folder/'只练高斯定律_真实模型样例_无答案.docx';shutil.copyfile(source,target)
        report.update(status='completed',questions=1,word_file=str(target),difficulty=public['difficulty'],
            basis=public['repair']['targets'][0]['basis'])
    except Exception as exc:report.update(status='failed',error=type(exc).__name__+': '+str(exc))
    finally:
        await client.close();report.update(seconds=round(time.perf_counter()-started,3),model_requests=len(calls),calls=calls)
        (folder/'report.json').write_text(j(report),encoding='utf-8');print(j({key:value for key,value in report.items() if key!='calls'}),flush=True)


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
