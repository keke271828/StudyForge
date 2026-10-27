"""Serve two isolated origins with simulated model directories and replies."""
import asyncio
import json
import os
import socket
from pathlib import Path

import httpx
import uvicorn

from studyforge import ai, server, conversations
from studyforge.codex_bridge import CodexBridge
from studyforge.db import create_project, execute, j, now, uid


def main():
    case_path = Path(os.environ['STUDYFORGE_MODELS_UI_CASE'])
    case_path.parent.mkdir(parents=True, exist_ok=True)
    ai.save_settings({'chat_provider':'deepseek', 'background_learning_enabled':False,
                      'agent_tools_enabled':False})
    ai.get_secret = lambda name:'test-key' if name=='DEEPSEEK_API_KEY' else None
    server.get_secret = ai.get_secret
    real_which = server.shutil.which
    server.shutil.which = lambda name:'mock-codex' if name=='codex' else real_which(name)
    recorded = {'model_requests':[], 'directory_requests':[], 'offline':False}
    def report():
        case_path.with_name('requests.json').write_text(j(recorded), encoding='utf-8')
    real_http = httpx.AsyncClient
    def respond(request):
        if request.method=='GET':
            assert str(request.url)=='https://api.deepseek.com/models'
            recorded['directory_requests'].append('deepseek'); report()
            if recorded['offline']: raise httpx.ConnectError('simulated offline')
            return httpx.Response(200,json={'data':[{'id':'deepseek-flash'},{'id':'deepseek-v4-pro'},{'id':'deepseek-v4-flash'}]})
        body=json.loads(request.content)
        recorded['model_requests'].append({'provider':'deepseek','model':body['model'],
            'effort':body.get('reasoning_effort'),'thinking':body.get('thinking')}); report()
        text='# 概念与论证\n\n原资料强调区分概念、论证与适用条件。\n\n## 系统性总结\n结合证据判断适用范围。'
        return httpx.Response(200, text='data: '+j({'choices':[{'delta':{'content':text},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    httpx.AsyncClient=lambda *a,**kw:real_http(transport=httpx.MockTransport(respond))
    async def start(self): pass
    async def request(self, method, params):
        assert method=='model/list'
        recorded['directory_requests'].append('codex'); report()
        if recorded['offline']: raise RuntimeError('simulated offline')
        if not params.get('cursor'):
            ids=['gpt-6.1-sol','gpt-6-astra','gpt-6-sol','gpt-6-luna']; cursor='second'
        else:
            ids=['gpt-5.6-sol','gpt-5.6-terra','gpt-5.6-luna','gpt-5.5']; cursor=None
        return {'data':[{'id':id,'model':id,'displayName':id,'isDefault':id=='gpt-6.1-sol',
                         'supportedReasoningEfforts':[{'reasoningEffort':value} for value in
                           (['low','high','max'] if 'luna' in id else ['low','medium','high','ultra'])]} for id in ids],
                'nextCursor':cursor}
    async def stream(self, prompt, remote_thread_id=None, model=None, effort=None, **kwargs):
        recorded['model_requests'].append({'provider':'codex','model':model,'effort':effort}); report()
        yield 'thread','mock-private-thread'
        yield 'final','# 导师回应\n先区分概念与论证，再核对适用条件。'
    CodexBridge.start=start; CodexBridge.request=request; CodexBridge.stream_turn=stream
    async def understand(*args): return []
    server.understand_material=understand
    project=create_project('模型选择验收'); source=uid()
    # Match the desktop's new-project flow: a project contains an explicit,
    # independently persisted conversation; empty projects do not invent one.
    conversation=conversations.create(project['id'],'deepseek','deepseek-flash')
    original=case_path.parent/'概念与论证.txt'
    original.write_text('学习时需要区分概念、论证与适用条件。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (source,project['id'],original.name,'.txt',str(original),'ready',now()))
    @server.app.get('/__model_test__/requests')
    def requests(): return recorded
    @server.app.post('/__model_test__/offline')
    def offline(): recorded['offline']=True; report(); return {'ok':True}
    # Test-only routes must precede the production static-file catch-all.
    web_mount = next(route for route in server.app.router.routes if getattr(route,'name',None)=='web')
    server.app.router.routes.remove(web_mount); server.app.router.routes.append(web_mount)
    ports=[]
    with socket.socket() as first, socket.socket() as second:
        first.bind(('127.0.0.1',0)); second.bind(('127.0.0.1',0))
        ports=[first.getsockname()[1],second.getsockname()[1]]
    case_path.write_text(j({'urls':[f'http://127.0.0.1:{port}' for port in ports],
                            'project_id':project['id'],'source_id':source,
                            'conversation_id':conversation['id']}), encoding='utf-8')
    report()
    async def serve():
        apps=[uvicorn.Server(uvicorn.Config(server.app,host='127.0.0.1',port=port,log_level='warning')) for port in ports]
        await asyncio.gather(*(app.serve() for app in apps))
    asyncio.run(serve())


if __name__=='__main__': main()
