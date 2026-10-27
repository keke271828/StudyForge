"""Desktop fixture: real scheduler and HTTP streaming, offline model replies."""
import asyncio
import json
import os
import socket
import time
from pathlib import Path

import httpx
import uvicorn

from studyforge import ai, server, conversations
from studyforge.db import create_project, execute, j, many, now, one, uid, unj
from studyforge.scheduling import execution_context


def main():
    case_path=Path(os.environ['STUDYFORGE_PARALLEL_CASE']);root=case_path.parent
    phase=int(os.environ.get('STUDYFORGE_PARALLEL_PHASE','1'))
    if phase==1:
        ai.save_settings({'chat_provider':'deepseek','agent_tools_enabled':False,'background_learning_enabled':False,
                          'auto_select_imports':False,'model_concurrency':2})
        project=create_project('并行调度验收');other=create_project('独立项目乙')
        chat=conversations.create(project['id'],'deepseek');conversations.activate(chat['id'])
        second=conversations.create(other['id'],'deepseek')
        ids=[]
        for label in ['A','B']:
            path=root/f'独立章节{label}.txt'
            path.write_text(f'{label}章：认识条件和概念。\n'+('每个判断需要说明证据与条件，明确变量的含义。\n'*2200),encoding='utf-8')
            sid=uid();ids.append(sid)
            execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (sid,project['id'],path.name,'.txt',str(path),'[]','ready',now()))
        case={'project':project['id'],'other':other['id'],'chat':chat['id'],'other_chat':second['id'],'sources':ids}
    else:case=json.loads(case_path.read_text(encoding='utf-8'))
    requests_path=root/'requests.json'
    calls=json.loads(requests_path.read_text(encoding='utf-8')) if requests_path.exists() else []
    counters={'active':0,'maximum':0}
    ai.get_secret=lambda name:'fixture-key' if name=='DEEPSEEK_API_KEY' else None
    server.get_secret=ai.get_secret;server.shutil.which=lambda name:None
    native=httpx.AsyncClient
    async def reply(request):
        if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'deepseek-flash'}]})
        body=json.loads(request.content);system=body['messages'][0]['content'];user=body['messages'][-1]['content']
        content=j(body['messages']);meta=dict(execution_context.get())
        kind='worksheet' if 'fixture_worksheet' in system else 'reading' if '通读理解资料' in system else 'lecture' if '教材式讲解' in system else 'summary' if meta.get('job_id') else 'chat'
        chapter=1 if '第 1/2' in user else 2 if '第 2/2' in user else None
        item={'kind':kind,'chapter':chapter,'job_id':meta.get('job_id'),'chat':meta.get('conversation_id'),
              'label':meta.get('label'),'start':time.time(),'end':None,
              'later_instruction':'后加指令不改旧任务' in content,'foreign_marker':'乙对话唯一问题' in content,
              'source_A':'A章：认识' in content,'source_B':'B章：认识' in content}
        calls.append(item);counters['active']+=1;counters['maximum']=max(counters['maximum'],counters['active'])
        requests_path.write_text(j(calls),encoding='utf-8')
        try:
            await asyncio.sleep(2.4 if kind=='lecture' and chapter==1 else 1.5 if kind=='lecture' else .35 if kind in ('worksheet','reading','summary') else 1.0)
            text=('## 阅读笔记\n明确条件、变量和概念。[来源：独立章节A.txt · 行 1-1601]' if kind=='reading' else
                  '# 学习讲解\n\n明确前提，解释概念、推导依据与适用边界。 [独立章节A.txt｜行 1-1601]\n\n## 系统性总结\n从条件出发组织论证，不把相关当作因果。' if kind in ('lecture','summary') else
                  '# 题单\n说明变量的含义。' if kind=='worksheet' else '导师回复：'+user[:90])
            return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':text},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
        finally:
            counters['active']-=1;item['end']=time.time();requests_path.write_text(j(calls),encoding='utf-8')
    class Offline(native):
        def __init__(self,*args,**kwargs):kwargs['transport']=httpx.MockTransport(reply);super().__init__(*args,**kwargs)
    httpx.AsyncClient=Offline
    async def exercises(client,pid,source_ids,digest,title,difficulty,**kwargs):
        await client.complete('fixture_worksheet','根据原文布置一道迁移题，私有求解和核查后保存。')
        ident=uid();questions=[{'index':0,'id':'q1','topic':'证据与条件','question':'说明如何区分相关与因果，给出需要的证据。','max_points':100}]
        solutions=[{'index':0,'id':'q1','answer':'私有答案验收标记','solution':'私有答案验收标记，完整提交并批改后开放。','rubric':[{'points':100,'criterion':'条件与论证'}]}]
        execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(ident,pid,j(source_ids),title,j(questions),j(solutions),difficulty,'assigned',now()))
        return ident,[{'stage':'离线替身求解与审查','passed':True}]
    server.generate_set=exercises
    @server.app.get('/__parallel_test__/state')
    def inspect():
        return counters|{'calls':calls,'jobs':many('SELECT * FROM jobs'),
                         'artifacts':many('SELECT * FROM artifacts'),'messages':many('SELECT * FROM messages'),
                         'conversations':many('SELECT id,source_ids_json FROM conversations')}
    mount=next(route for route in server.app.router.routes if getattr(route,'name',None)=='web')
    server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    case.update(url=f'http://127.0.0.1:{port}',phase=phase);case_path.write_text(j(case),encoding='utf-8')
    uvicorn.run(server.app,host='127.0.0.1',port=port,log_level='warning')


if __name__=='__main__':main()
