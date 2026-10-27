"""Real local tool/approval loop in isolated data; no billable AI calls."""
import asyncio
import os
import socket
from pathlib import Path

import httpx
import uvicorn
from fastapi import HTTPException

from studyforge import ai,conversations,server
from studyforge.agent_tools import AgentRuntime
from studyforge.db import create_project,j


def main():
    report=Path(os.environ['STUDYFORGE_PERMISSION_CASE']);outside=report.parent/'permission-target.txt'
    ai.save_settings({'chat_provider':'deepseek','background_learning_enabled':False,'agent_permission_mode':'read_only'})
    ai.get_secret=lambda name:'fixture-key' if name=='DEEPSEEK_API_KEY' else None
    server.get_secret=ai.get_secret;server.shutil.which=lambda name:None
    calls={'model_calls':0};native=httpx.AsyncClient
    def response(request):
        if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'permission-model'}]})
        calls['model_calls']+=1;raise RuntimeError('No model calls permitted in this smoke test')
    class Offline(native):
        def __init__(self,*a,**kw):kw['transport']=httpx.MockTransport(response);super().__init__(*a,**kw)
    httpx.AsyncClient=Offline
    project=create_project('权限模式与审批验收');chat=conversations.create(project['id'],'deepseek','permission-model')
    second=conversations.create(project['id'],'deepseek','permission-model');conversations.activate(chat['id'])
    operations={}
    @server.app.post('/__permission_test__/operation')
    async def operation(value:dict):
        runtime=AgentRuntime(project['id'],conversation_id=chat['id'],on_event=lambda event:None)
        async def execute():
            return await runtime.execute('sf_write_text',{'path':str(outside),'text':value['text'],'overwrite':True})
        key=str(len(operations));operations[key]=asyncio.create_task(execute());return {'id':key,'path':str(outside)}
    @server.app.get('/__permission_test__/state')
    async def inspect():
        return calls|{'content':outside.read_text(encoding='utf-8') if outside.exists() else None,
                      'operations':{key:task.result() if task.done() else {'pending':True} for key,task in operations.items()}}
    mount=next(r for r in server.app.router.routes if getattr(r,'name',None)=='web');server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    report.write_text(j({'url':f'http://127.0.0.1:{port}','project':project['id'],'chat':chat['id'],'second':second['id']}),encoding='utf-8')
    uvicorn.run(server.app,host='127.0.0.1',port=port,log_level='warning')


if __name__=='__main__':main()
