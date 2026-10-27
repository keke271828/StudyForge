"""One bounded real model trial; source, marks and self-report are synthetic."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time


async def run(name,replay_path=None):
    folder=Path(__file__).resolve().parents[1]/'build'/name;folder.mkdir(parents=True,exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
    from studyforge import ai,repair_learning,server
    from studyforge.db import j,many,one,unj
    from scripts.repair_learning_fixture import seed
    case=seed(folder)
    ai.save_settings({'agent_network_enabled':False,'agent_tools_enabled':False,'background_learning_enabled':False})
    client=ai.DeepSeekClient('deepseek-flash',effort='high');calls=[]
    prefix=json.loads(Path(replay_path).read_text(encoding='utf-8'))[:4] if replay_path else []
    class Recorded:
        async def complete(self,system,user,**kwargs):
            start=time.perf_counter()
            if len(calls)<len(prefix):
                result=prefix[len(calls)]['final_response'];origin='replayed_initial_candidate_and_checks'
            else:result=await client.complete(system,user,**kwargs);origin='new_model_response'
            calls.append({'system':system,'user':user,'final_response':result,'origin':origin,'seconds':round(time.perf_counter()-start,2)})
            (folder/'private-model-calls.json').write_text(j(calls),encoding='utf-8');return result
        async def close(self):pass
    async def factory(*args,**kwargs):return Recorded()
    server.assessment_client=factory
    start=time.perf_counter();report={'synthetic_baseline':True,'model':'deepseek-flash','effort':'high'}
    try:
        result=await asyncio.wait_for(server.repair_practice(case['set_id'],server.AssessmentAIIn(
            provider='deepseek',model='deepseek-flash',reasoning_effort='high',conversation_id=case['conversation_id'])),600)
        row=one('SELECT * FROM exercise_sets WHERE id=?',(result['exercise_set']['id'],))
        (folder/'student.json').write_text(j(result['exercise_set']),encoding='utf-8')
        (folder/'private-solutions.json').write_text(row['solutions_json'],encoding='utf-8')
        doc=one('SELECT path FROM artifacts WHERE id=?',(result['artifact']['id'],))
        report.update(status='completed',questions=len(result['exercise_set']['questions']),word_file=doc['path'],
            basis=result['exercise_set']['repair']['targets'][0]['basis'],difficulty=result['exercise_set']['difficulty'])
    except Exception as exc:report.update(status='failed',error=str(exc) or type(exc).__name__)
    finally:
        await client.close();report.update(model_calls=sum(c['origin']=='new_model_response' for c in calls),
            replayed_calls=sum(c['origin']!='new_model_response' for c in calls),seconds=round(time.perf_counter()-start,2))
        if prefix:report['scope']='Replay the failed trial initial candidate and first checks; new model responses verify revision and rechecks, not a fresh independent design trial'
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=True),flush=True)


if __name__=='__main__':asyncio.run(run(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else None))
