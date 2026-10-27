"""Offline providers, real desktop UI and exports. Never calls a paid model."""
import json
import os
import socket
import sys
from pathlib import Path

import httpx
import uvicorn

from studyforge import ai, conversations, server, providers, provider_clients
from studyforge import gemini_cli
from studyforge.db import create_project, j, many


def main():
    report=Path(os.environ['STUDYFORGE_PERMISSION_CASE'])
    keys, requests={},[]
    providers.get_secret=keys.get
    providers.set_secret=lambda name,value:keys.__setitem__(name,value)
    providers.delete_secret=lambda name:keys.pop(name,None)
    provider_clients.get_secret=keys.get
    gemini_cli.cli_command=lambda:[sys.executable,'-u',str(Path(__file__).with_name('fixture_gemini_cli.py'))]
    original_save=providers.save_service
    def save_fixture(value,identifier=None):
        row=original_save(value,identifier)
        if row['protocol']=='gemini_cli':
            profile,_=gemini_cli.prepare_profile(row['id'])
            (profile/'.gemini'/'oauth_creds.json').write_text('{"fixture_only":true}',encoding='utf-8')
        return row
    providers.save_service=save_fixture
    ai.save_settings({'chat_provider':'deepseek','background_learning_enabled':False,'agent_permission_mode':'approval',
                      'agent_tools_enabled':True,'task_parallel_enabled':True,'model_concurrency':2})
    project=create_project('第三方模型桌面验收')
    chat=conversations.create(project['id'],'deepseek')
    target=report.parent/'approved.txt';target.write_text('审批前原内容',encoding='utf-8')
    original=httpx.AsyncClient

    def respond(request):
        native='/v1beta' in request.url.path
        if request.method=='GET':
            return httpx.Response(200,json={'models':[{'name':'models/gemini-fixture-flash','supportedGenerationMethods':['generateContent']},
                {'name':'models/gemini-fixture-pro','supportedGenerationMethods':['generateContent']}]} if native else {'data':[{'id':'alpha-model'},{'id':'beta-model'}]})
        body=json.loads(request.content)
        rows=body['contents'] if native else body['messages']
        model=request.url.path.split('/models/')[-1].split(':')[0] if native else body['model']
        latest=next((row for row in reversed(rows) if row['role']=='user'),{})
        content=''.join(part.get('text','') for part in latest.get('parts',[])) if native else str(latest.get('content',''))
        finished=bool(latest.get('parts') and 'functionResponse' in latest['parts'][0]) if native else rows[-1]['role']=='tool'
        requests.append({'protocol':'gemini' if native else 'openai','model':model,'tool_result':finished,
                         'source_read': '尾部论据' in j(body), 'has_signature':'ui-native-signature' in j(body)})
        if content.startswith('审批写入测试') and not finished:
            arguments={'path':str(target),'text':'审批后已保存','overwrite':True}
            parts=[{'text':'请审批本次写入，原指令会继续等待。'}, {'thoughtSignature':'ui-native-signature','functionCall':{'id':'ui-call','name':'sf_write_text','args':arguments}}]
            delta={'content':'请审批本次写入，原指令会继续等待。','tool_calls':[{'index':0,'id':'ui-call','type':'function','function':{'name':'sf_write_text','arguments':j(arguments)}}]}
            finish='tool_calls'
        else:
            text='已按原指令保存文件。' if finished else (f'本次由 {model} 回答。\n\n# 相关与因果\n共同变化不足以证明因果。要解释这种关系，先明确相关指观测到一起变化，因果则要求说明干预一个因素如何改变另一个因素。\n\n## 为什么需要排除共同原因\n共同原因可以同时影响两个变量，造成相关。观察相关本身不能区分这些解释，需要设计能够区分它们的证据。\n\n## 外部效度与边界\n尾部论据指出实验仍有外部效度限制。实验的条件、样本和适用范围需要明确，避免把局部结论直接推广。\n\n## 系统性总结\n相关提供线索；因果论证要区分其他解释，并说明证据能支持到哪里。')
            parts=[{'text':text}];delta={'content':text};finish='stop'
        native_packet={'candidates':[{'content':{'role':'model','parts':parts},'finishReason':'STOP'}]}
        packet=native_packet if native else {'choices':[{'delta':delta,'finish_reason':finish}]}
        streaming='streamGenerateContent' in request.url.path if native else body.get('stream')
        if not streaming:
            if not native:packet['choices'][0]['message']=packet['choices'][0].pop('delta')
            return httpx.Response(200,json=packet)
        return httpx.Response(200,text='data: '+j(packet)+'\n\n',headers={'content-type':'text/event-stream'})

    class Offline(original):
        def __init__(self,*args,**kwargs):super().__init__(*args,**(kwargs|{'transport':httpx.MockTransport(respond)}))
    httpx.AsyncClient=Offline

    @server.app.get('/__model_service_test__/state')
    def state():
        log=report.parent/'cli-events.jsonl'
        cli_requests=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()] if log.exists() else []
        heartbeat=report.parent/'cli-heartbeat.txt'
        return {'requests':requests,'paid_model_calls':0,'file':target.read_text(encoding='utf-8'),
                'cli_requests':cli_requests,'cli_heartbeat':heartbeat.read_text() if heartbeat.exists() else None,
                'artifacts':many('SELECT id,kind,format,path,metadata_json FROM artifacts'),
                'jobs':many('SELECT id,kind,status,error,payload_json FROM jobs')}
    server.app.router.routes.insert(0, server.app.router.routes.pop())

    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    report.write_text(j({'url':f'http://127.0.0.1:{port}','project':project['id'],'chat':chat['id']}),encoding='utf-8')
    uvicorn.run(server.app,host='127.0.0.1',port=port,log_level='warning')


if __name__=='__main__':main()
