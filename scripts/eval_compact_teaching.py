"""Capture real tutor/document inputs; compare a compact shared-policy candidate."""
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


async def main(name, experiment_module='scripts.teaching_focus_candidate'):
    out=ROOT/'build'/name
    if out.exists() and any(out.iterdir()):raise SystemExit('Use a fresh folder.')
    out.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(out/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(out/'isolated-model')
    from studyforge import ai,server,conversations
    from studyforge.db import create_project,execute,j,now,one,uid
    from studyforge.materials import read_original_sources
    from studyforge.teaching_policy import REASONING_TEACHING_RULES
    from importlib import import_module
    experiment=import_module(experiment_module)
    CASES,RULES,VERSION=experiment.CASES,experiment.RULES,experiment.VERSION
    from scripts.diagnose_deepseek_speed import traced_class
    ai.save_settings({'api_connection_mode':'direct','agent_tools_enabled':False,'agent_network_enabled':False,
        'background_learning_enabled':False,'model_concurrency':2,'library_reference_mode':'off'})
    cases=[]
    for case in CASES:
        project=create_project('紧凑教学对照 · '+case['id']);sid=uid();path=out/(case['id']+'.txt')
        path.write_text(case['source'],encoding='utf-8')
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (sid,project['id'],path.name,'.txt',str(path),'[]','ready',now()))
        captured=[]
        class Capture:
            model='deepseek-flash';effort='high'
            async def agent_stream(self,messages):
                captured.append(copy.deepcopy(messages));yield 'final','受控捕获，不是模型对照结果。'
            async def complete(self,system,user,**kwargs):
                captured.append([{'role':'system','content':system},{'role':'user','content':user}])
                return '## 系统性总结\n受控捕获，不是模型对照结果。'
        if case['role']=='tutor':
            chat=conversations.create(project['id'],'deepseek','deepseek-flash','high')
            for row in case.get('history',[]):execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),chat['id'],row['role'],row['content'],now()))
            with patch.object(server,'DeepSeekClient',lambda *a,**k:Capture()),patch.object(server,'client_for',lambda *a,**k:Capture()):
                response=await server._chat_response_impl(server.ChatIn(project_id=project['id'],conversation_id=chat['id'],
                    provider='deepseek',model='deepseek-flash',reasoning_effort='high',source_ids=[sid],text=case['question'],
                    explanation_style=case['style'],learning_mode=case['mode']))
                lines=[line async for line in response.body_iterator]
            assert captured and not any(b'"error"' in (s if isinstance(s,bytes) else s.encode()) for s in lines),lines
        else:
            row=one('SELECT * FROM sources WHERE id=?',(sid,));records=read_original_sources([row])
            digest,_=ai._assemble_source_digest(records,records,False)
            await ai.generate_explanation(Capture(),digest,3,[],style=case['style'],learning_mode=case['mode'],requirements=case['question'])
        assert len(captured)==1
        baseline=captured[0]
        assert baseline[0]['content'].count(REASONING_TEACHING_RULES)==1
        baseline_rules=getattr(experiment,'BASELINE_RULES',REASONING_TEACHING_RULES)
        baseline[0]['content']=baseline[0]['content'].replace(REASONING_TEACHING_RULES,baseline_rules,1)
        candidate=copy.deepcopy(baseline)
        candidate[0]['content']=candidate[0]['content'].replace(baseline_rules,RULES,1)
        assert baseline[1:]==candidate[1:]
        cases.append(case|{'requests':{'baseline':baseline,'compact':candidate}})
    (out/'cases.json').write_text(j({'candidate_version':VERSION,'cases':cases}),encoding='utf-8')
    cls=traced_class();results=[]
    for number,case in enumerate(cases):
        async def sample(arm):
            native=cls('deepseek-flash',effort='high');start=time.perf_counter()
            row={'case':case['id'],'arm':arm,'role':case['role'],'model':'deepseek-flash','effort':'high'}
            try:
                answer=''
                async with asyncio.timeout(240):
                    async for kind,value in native.agent_stream(case['requests'][arm]):
                        if kind=='final':answer=value
                assert answer.strip(),'No final answer'
                file=case['id']+'-'+arm+'-final.md';(out/file).write_text(answer,encoding='utf-8')
                row.update(status='completed',answer_file=file,output_characters=len(answer),answer_sha256=hashlib.sha256(answer.encode()).hexdigest())
            except Exception as exc:row.update(status='failed',error_type=type(exc).__name__)
            finally:await native.close()
            row.update(seconds=time.perf_counter()-start,input_characters=sum(len(r['content']) for r in case['requests'][arm]),
                model_requests=len(native.traces),http_attempts=[t.public() for t in native.traces])
            results.append(row);(out/'results.json').write_text(j(results),encoding='utf-8')
            print(json.dumps({k:row[k] for k in ('case','arm','status','seconds','model_requests')},ensure_ascii=True),flush=True)
        arms=['baseline','compact'] if number%2==0 else ['compact','baseline']
        await asyncio.gather(*(sample(arm) for arm in arms))


if __name__=='__main__':asyncio.run(main(*sys.argv[1:]))
