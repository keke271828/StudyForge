"""Real isolated tutor and DOCX job using the bounded rational tool."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    {'id':'cancelled_hole','title':'约分之后，原函数在1处仍未定义','role':'tutor',
     'source':'给定原函数f(x)=(x*x-1)/(x-1)，变量为实数，原式分母不能为零。另给g(x)=x+1。',
     'question':'我约分得到(x²−1)/(x−1)=x+1，所以两个函数完全相同，x=1也能直接取2吧？请用核验工具检查后讲清楚，别布置习题。'},
    {'id':'changing_factors','title':'各因子变化，乘积仍可恒定；保留原给定范围','role':'lecture',
     'source':'数学示意：t>0，u(t)=t，v(t)=1/t，P(t)=u(t)v(t)。这里只讨论有理式数学关系，不代表真实化学装置。',
     'question':'请用核验工具核对t*(1/t)=1，讲清u和v都变化为什么不能推出乘积必变；保留原给定的t>0。把这段整理成可独立读懂的讲解，最后总结，不出题，不套用真实反应装置。'},
]


async def main(name):
    out=ROOT/'build'/name
    if out.exists() and any(out.iterdir()):raise SystemExit('Use a fresh folder.')
    out.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(out/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(out/'isolated-model')
    from studyforge import ai, conversations, server
    from studyforge.agent_tools import AgentRuntime
    from studyforge.db import create_project,execute,j,many,now,one,uid
    from scripts.diagnose_deepseek_speed import traced_class
    ai.save_settings({'api_connection_mode':'direct','agent_tools_enabled':True,'agent_permission_mode':'read_only',
        'agent_network_enabled':False,'agent_web_video_enabled':False,'background_learning_enabled':False,
        'library_reference_mode':'off','model_concurrency':2,'agent_max_tool_calls':6})
    (out/'cases.json').write_text(j(CASES),encoding='utf-8')
    base=traced_class(); results=[];active_clients=[];math_calls=[]
    class Recorded(base):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);self.final_texts=[];active_clients.append(self)
        async def agent_stream(self,messages,json_mode=False):
            async for kind,value in super().agent_stream(messages,json_mode=json_mode):
                if kind=='final':self.final_texts.append(value)
                yield kind,value
    original_math=AgentRuntime.sf_check_math
    async def record_math(runtime,args):
        result=await original_math(runtime,args)
        math_calls.append({'arguments':args.model_dump(),'result':result})
        return result
    for case in CASES:
        active_clients.clear();math_calls.clear();started=time.perf_counter()
        project=create_project('隔离真实有理式教学：'+case['id'])
        chat=conversations.create(project['id'],'deepseek','deepseek-flash','high')
        source=out/(case['id']+'.txt');source.write_text(case['source'],encoding='utf-8');sid=uid()
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (sid,project['id'],source.name,'.txt',str(source),'ready',now()))
        row={'case':case['id'],'role':case['role'],'model':'deepseek-flash','effort':'high','source_file':source.name}
        try:
            with patch.object(ai,'DeepSeekClient',Recorded),patch.object(server,'DeepSeekClient',Recorded),patch.object(AgentRuntime,'sf_check_math',record_math):
                async with asyncio.timeout(360):
                    if case['role']=='tutor':
                        response=await server._chat_response(server.ChatIn(project_id=project['id'],conversation_id=chat['id'],
                            provider='deepseek',model='deepseek-flash',reasoning_effort='high',source_ids=[sid],
                            text=case['question'],explanation_style='balanced',learning_mode='deep'))
                        stream=[chunk async for chunk in response.body_iterator]
                        errors=[json.loads(line)['value'] for chunk in stream for line in chunk.decode().splitlines()
                                if line.strip() and json.loads(line)['type']=='error']
                        if errors:raise RuntimeError(str(errors))
                        answer=one("SELECT content FROM messages WHERE conversation_id=? AND role='assistant' ORDER BY rowid DESC",(chat['id'],))['content']
                    else:
                        started_job=await server.generate(server.GenerateIn(project_id=project['id'],conversation_id=chat['id'],
                            provider='deepseek',model='deepseek-flash',reasoning_effort='high',source_ids=[sid],
                            instructions=case['question'],review_mode='express',output_format='docx',explanation_style='balanced'))
                        while True:
                            job=one('SELECT * FROM jobs WHERE id=?',(started_job['job_id'],))
                            if job['status'] in ('completed','failed'):
                                if job['status']!='completed':raise RuntimeError(job['error'])
                                break
                            await asyncio.sleep(.1)
                        artifact=one("SELECT * FROM artifacts WHERE kind='explanation' AND project_id=?",(project['id'],))
                        destination=out/'变化因子与恒定乘积_实际讲解.docx'
                        shutil.copyfile(artifact['path'],destination);row['docx_file']=destination.name
                        answer=one('SELECT m.content FROM generation_dialogue_outputs g JOIN messages m ON m.id=g.message_id WHERE g.job_id=?',
                                   (started_job['job_id'],))['content']
            assert answer.strip()
            filename=case['id']+'-final.md';(out/filename).write_text(answer,encoding='utf-8')
            row.update(status='completed',answer_file=filename,characters=len(answer),answer_sha256=hashlib.sha256(answer.encode()).hexdigest())
        except Exception as exc:
            row.update(status='failed',error_type=type(exc).__name__,error=str(exc))
        finally:
            for client in active_clients:
                await client.close()
        row.update(seconds=time.perf_counter()-started,model_requests=sum(len(c.traces) for c in active_clients),
                   http_attempts=[t.public() for c in active_clients for t in c.traces],math_calls=list(math_calls),
                   no_mastery_scores=not many('SELECT * FROM mastery'),no_exercise_sets=not many('SELECT * FROM exercise_sets'))
        (out/(case['id']+'-public-final-calls.json')).write_text(j([text for c in active_clients for text in c.final_texts]),encoding='utf-8')
        for client in active_clients:client.request_bodies.clear()
        results.append(row);(out/'results.json').write_text(j(results),encoding='utf-8')
        print(json.dumps({k:row[k] for k in ('case','status','seconds','model_requests')},ensure_ascii=True),flush=True)


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
