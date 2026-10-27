"""Real chat/approval HTTP flow with simulated providers; no paid model calls."""
import asyncio
import json
import os
import re
import socket
from pathlib import Path

import httpx
import uvicorn

from studyforge import ai, conversations, server, codex_bridge
from studyforge.codex_bridge import CodexBridge
from studyforge.db import create_project, j, many, uid


def main():
    report = Path(os.environ['STUDYFORGE_PERMISSION_CASE'])
    targets = {key:report.parent/(key+'.txt') for key in ('target','first','second','codex')}
    targets['target'].write_text('原内容', encoding='utf-8')
    targets['codex'].write_text('Codex原内容', encoding='utf-8')
    ai.save_settings({'chat_provider':'deepseek','deepseek_model':'approval-model','codex_model':'approval-model',
        'background_learning_enabled':False,'agent_permission_mode':'approval','agent_tools_enabled':True,
        'task_parallel_enabled':True,'model_concurrency':1,'ui_focus':False})
    ai.get_secret = lambda name:'fixture-key' if name=='DEEPSEEK_API_KEY' else None
    server.get_secret = ai.get_secret
    server.shutil.which = lambda name:None
    project = create_project('聊天悬置与审批续接验收')
    chat = conversations.create(project['id'], 'deepseek', 'approval-model')
    other = conversations.create(project['id'], 'deepseek', 'approval-model')
    codex = conversations.create(project['id'], 'codex', 'approval-model')
    conversations.activate(chat['id'])
    calls, replies = [], []

    def operations(text):
        def write(key, value):
            return 'sf_write_text', {'path':str(targets[key]),'text':value,'overwrite':True}
        if '连续审批测试' in text:
            return [write('first','第一步完成'), write('second','第二步完成')]
        if 'Codex拒绝测试' in text:
            return [write('codex','不应写入的Codex内容')]
        if 'Codex批准测试' in text:
            return [write('codex','Codex批准后自动完成')]
        if '拒绝测试' in text:
            return [write('target','不应写入的内容')]
        if '批准测试' in text:
            return [write('target','批准后自动完成')]
        return []

    original = httpx.AsyncClient

    def respond(request):
        if request.method=='GET':
            return httpx.Response(200, json={'data':[{'id':'approval-model'}]})
        body = json.loads(request.content)
        rows = body['messages']
        index = next(n for n in range(len(rows)-1,-1,-1) if rows[n]['role']=='user')
        instruction = rows[index]['content']
        completed = [row for row in rows[index+1:] if row['role']=='tool']
        steps = operations(instruction)
        calls.append({'provider':'deepseek','instruction':instruction.splitlines()[0],'round':len(completed)})
        if len(completed)<len(steps):
            tool, args = steps[len(completed)]
            delta = {'content':'我会发起本次文件操作审批，并等待你的决定。',
                     'tool_calls':[{'index':0,'id':uid(),'type':'function','function':{'name':tool,'arguments':j(args)}}]}
            reason = 'tool_calls'
        else:
            denied = any('error' in json.loads(row['content']) for row in completed)
            delta = {'content':'你拒绝了本次操作，原文件保持不变。' if denied else
                              '原指令已完成，文件已实际保存。' if completed else '另一个对话可以正常回复，审批中的任务仍在等待。'}
            reason = 'stop'
        return httpx.Response(200, text='data: '+j({'choices':[{'delta':delta,'finish_reason':reason}]})+'\n\ndata: [DONE]\n\n')

    class Offline(original):
        def __init__(self, *args, **kwargs):
            kwargs['transport'] = httpx.MockTransport(respond)
            super().__init__(*args, **kwargs)
    httpx.AsyncClient = Offline

    # Exercise the actual bridge tool-handler and response path, without spawning Codex.
    pending = {}
    async def start(self):
        pass
    async def request(self, method, params):
        if method=='thread/start':
            return {'thread':{'id':uid(),'ephemeral':True}}
        if method=='turn/start':
            text = params['input'][0]['text']
            instruction = re.search(r'用户：([^\n]+)', text).group(1)
            tool, args = operations(instruction)[0]
            ident = uid()
            pending[ident] = (params['threadId'], instruction)
            calls.append({'provider':'codex','instruction':instruction,'round':0})
            task = asyncio.create_task(self._handle_tool({'id':ident,'params':{'threadId':params['threadId'],
                'tool':tool,'arguments':args}}, self.agent_runtime))
            self.tool_tasks.add(task)
            task.add_done_callback(self.tool_tasks.discard)
        return {}
    async def send(self, message):
        thread, instruction = pending.pop(message['id'])
        replies.append({'provider':'codex','instruction':instruction,'success':message['result']['success']})
        text = '原指令已完成，文件已实际保存。' if message['result']['success'] else '你拒绝了本次操作，原文件保持不变。'
        await self.events.put({'method':'item/completed','params':{'threadId':thread,'item':{'type':'agentMessage','text':text}}})
        await self.events.put({'method':'turn/completed','params':{'threadId':thread,'turn':{'status':'completed'}}})
    CodexBridge.start, CodexBridge.request, CodexBridge._send = start, request, send
    codex_bridge.FOREGROUND_EVENT_TIMEOUT = .4
    async def models(force=False):
        return {'models':[{'id':'approval-model','name':'审批验收模型','efforts':['high'],
                          'default_effort':None,'is_default':True}],'source':'fixture','recommended_generation':None}
    server.model_catalog.get_models = models

    @server.app.get('/__chat_approval_test__/state')
    async def inspect():
        return {'paid_model_calls':0,'calls':calls,'codex_tool_replies':replies,
            'active_chats':sorted(server.active_chat_conversations),
            'files':{key:path.read_text(encoding='utf-8') if path.exists() else None for key,path in targets.items()},
            'messages':{row['id']:many('SELECT role,content FROM messages WHERE conversation_id=? ORDER BY rowid', (row['id'],)) for row in (chat,other,codex)}}

    mount = next(route for route in server.app.router.routes if getattr(route,'name',None)=='web')
    server.app.router.routes.remove(mount)
    server.app.router.routes.append(mount)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        port = sock.getsockname()[1]
    report.write_text(j({'url':f'http://127.0.0.1:{port}','project':project['id'],
                        'chat':chat['id'],'other':other['id'],'codex':codex['id']}), encoding='utf-8')
    uvicorn.run(server.app, host='127.0.0.1', port=port, log_level='warning')


if __name__=='__main__':
    main()
