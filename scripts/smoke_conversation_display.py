"""Isolated persisted conversation; layout checks must make zero model calls."""
import json
import os
import socket
from pathlib import Path

import httpx
import uvicorn

from studyforge import ai, conversations, server
from studyforge.db import create_project, execute, j, now, uid


def main():
    case_path=Path(os.environ['STUDYFORGE_DISPLAY_CASE'])
    ai.save_settings({'chat_provider':'deepseek','deepseek_model':'display-model',
                      'background_learning_enabled':False,'agent_tools_enabled':False,'ui_focus':False})
    ai.get_secret=lambda name:'fixture-key' if name=='DEEPSEEK_API_KEY' else None
    server.get_secret=ai.get_secret;server.shutil.which=lambda name:None
    requests={'model_calls':0}
    native=httpx.AsyncClient
    def respond(request):
        if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'display-model'}]})
        requests['model_calls']+=1
        raise RuntimeError('Layout controls must not call models')
    class Offline(native):
        def __init__(self,*args,**kwargs):kwargs['transport']=httpx.MockTransport(respond);super().__init__(*args,**kwargs)
    httpx.AsyncClient=Offline
    project=create_project('对话显示验收')
    chat=conversations.create(project['id'],'deepseek','display-model')
    conversations.update(chat['id'],project['id'],{'title':'从概念到证明的阅读对话'})
    content='# 从概念到证明\n\n> 原文：每一个结论都需要明确适用条件。\n\n'
    content+='\n\n'.join(f'## 第 {n} 个阅读步骤\n\n先说明符号的含义，再解释这一步为何成立。把目标、条件与构造方法连接起来，区分定义、推导与需要核对的事实。\n\n数学排版：$F=ma$；适用条件和量的单位需要一并检查。' for n in range(1,31))
    for role,text in [('user','我希望看懂证明每一步的构造动机。'),('assistant',content)]:
        execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),chat['id'],role,text,now()))
    @server.app.get('/__display_test__/state')
    def inspect():return requests
    mount=next(route for route in server.app.router.routes if getattr(route,'name',None)=='web')
    server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    case_path.write_text(j({'url':f'http://127.0.0.1:{port}','project':project['id'],'chat':chat['id']}),encoding='utf-8')
    uvicorn.run(server.app,host='127.0.0.1',port=port,log_level='warning')


if __name__=='__main__':main()
