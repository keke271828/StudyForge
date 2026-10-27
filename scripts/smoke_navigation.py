"""Real local backend with isolated projects; network inference is forbidden."""
import json
import os
import socket
from pathlib import Path

import httpx
import uvicorn

from studyforge import ai, server, conversations, learning_memory
from studyforge.config import artifacts_dir, files_dir
from studyforge.db import create_project, execute, j, now, uid


def main():
    case_path=Path(os.environ['STUDYFORGE_NAVIGATION_CASE'])
    if case_path.exists():
        case=json.loads(case_path.read_text(encoding='utf-8'))
    else:
        ai.save_settings({'chat_provider':'deepseek','agent_tools_enabled':False,'background_learning_enabled':False,'auto_select_imports':False})
        a,b,c=[create_project(name) for name in ['数学与证明','哲学与社会科学','临时练习']]
        chats=[conversations.create(a['id'],'deepseek') for _ in range(3)]
        foreign=conversations.create(b['id'],'deepseek');empty=conversations.create(c['id'],'deepseek')
        sources=[]
        for n in range(40):
            path=case_path.parent/f'证明材料-{n:02}.txt';path.write_text(f'第 {n} 份原资料。先理解假设，再组织论证。',encoding='utf-8')
            sid=uid();sources.append(sid)
            execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (sid,a['id'],path.name,'.txt',str(path),j([{'locator':'行 1','text':path.read_text(encoding='utf-8')}]),'ready',now()))
        for n,chat in enumerate(chats):
            conversations.update(chat['id'],a['id'],{'title':['构造动机','归纳与边界','独立论证'][n],'draft':'继续解释这里的动机' if n==0 else ''})
            for k in range(20):
                execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),chat['id'],'user' if k%2==0 else 'assistant',f'第 {k} 条讨论：条件与证明方法。',now()))
        conversations.update(chats[0]['id'],a['id'],{'source_ids':[sources[18]]})
        conversations.update(foreign['id'],b['id'],{'title':'规训概念'})
        path=artifacts_dir()/'项目成果.txt';path.write_text('系统性总结：区分假设与结论。',encoding='utf-8')
        artifact=server.add_artifact(b['id'],[],'external','txt','概念辨析',path)
        conversations.activate(chats[0]['id'])
        disposable=create_project('回收站彻底删除验收')
        disposable_chat=conversations.create(disposable['id'],'deepseek')
        owned=files_dir()/(uid()+'.txt');owned.write_text('只清理这个项目副本。',encoding='utf-8')
        external=case_path.parent/'保留用户原文件.txt';external.write_text('保留原文件。',encoding='utf-8')
        for imported in (owned,external):
            execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (uid(),disposable['id'],imported.name,'.txt',str(imported),'[]','ready',now()))
        learning_memory.assessment_record('ui:quiz','高斯定律','做题',60,'软件测试的作答','作答评分为60',a['id'])
        conversations.activate(chats[0]['id'])
        case={'project':a['id'],'other':b['id'],'temporary':c['id'],'chats':[row['id'] for row in chats],
              'foreign':foreign['id'],'empty':empty['id'],'source':sources[18],'artifact':artifact['id'],
              'purge':disposable['id'],'purge_name':disposable['name'],'owned':str(owned),'external':str(external)}
    ai.get_secret=lambda name:None;server.get_secret=ai.get_secret;server.shutil.which=lambda name:None
    native=httpx.AsyncClient;network={'model_calls':0,'catalog_calls':0}
    def mock(request):
        key='model_calls' if request.method=='POST' else 'catalog_calls';network[key]+=1
        return httpx.Response(500 if request.method=='POST' else 200,json={'data':[]})
    class Offline(native):
        def __init__(self,*args,**kwargs):
            kwargs['transport']=httpx.MockTransport(mock);super().__init__(*args,**kwargs)
    httpx.AsyncClient=Offline
    @server.app.get('/__navigation_test__/state')
    def inspect(): return network
    @server.app.get('/__navigation_test__/teaching-context')
    def teaching_context(): return {'context':learning_memory.profile_context('高斯定律')}
    mount=next(route for route in server.app.router.routes if getattr(route,'name',None)=='web')
    server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    case['url']=f'http://127.0.0.1:{port}'
    case['phase']=int(os.environ.get('STUDYFORGE_NAVIGATION_PHASE','1'))
    case_path.write_text(j(case),encoding='utf-8')
    uvicorn.run(server.app,host='127.0.0.1',port=port,log_level='warning')


if __name__=='__main__': main()
