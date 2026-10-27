"""Real Electron + paired TLS mobile fixture; no external model calls/user DB."""
import asyncio
import json
import os
from pathlib import Path
import socket
import sys

import fitz
import httpx
import uvicorn

root=Path(__file__).resolve().parents[1]
case_path=root/'build'/(sys.argv[1] if len(sys.argv)>1 else 'library-ui-20261010-1')/'case.json'
case_path.parent.mkdir(parents=True,exist_ok=True)
os.environ['STUDYFORGE_DATA_DIR']=str(case_path.parent/'data')
os.environ['STUDYFORGE_DESKTOP_TOKEN']='library-ui-owner'

from studyforge import ai,conversations,library,server
from studyforge.db import create_project,j
from studyforge.library_semantic import set_enabled as enable_semantic
enable_semantic(True)
from studyforge.mobile_access import StartIn

ai.save_settings({'chat_provider':'deepseek','background_learning_enabled':False,'agent_tools_enabled':False,
                  'agent_permission_mode':'read_only','chat_effort_deepseek':'none','model_concurrency':2})
p=create_project('书库引用验收');q=create_project('另一个独立项目')
c=conversations.create(p['id'],'deepseek');other=conversations.create(q['id'],'deepseek');conversations.activate(c['id'])
path=case_path.parent/'book.pdf'
with fitz.open() as doc:
    for i in range(3):
        page=doc.new_page();page.insert_text((50,80),f'The field is closed under addition, subtraction, multiplication and division by nonzero elements. Page {i+1}.')
        if i==0:page.insert_text((50,110),'Injectivity means that f(x)=f(y) implies x=y. Distinct inputs must produce distinct outputs.')
        page.insert_text((50,650),f'UNRELATED_BOTTOM_{i+1}: excluded from selected scope.')
    doc.set_toc([[1,'Algebra',1],[2,'Number fields',1],[2,'Polynomials',2],[2,'Unread vectors',3]])
    doc.save(path)
b=library.import_book(path,'全局教材_数域与多项式.pdf')['book']
nodes=library.details(b['id'])['nodes']
calls=[]
async def respond(request):
    if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'deepseek-flash'},{'id':'deepseek-pro'}]})
    payload=json.loads(request.content);calls.append(payload)
    system=payload['messages'][0]['content']
    if isinstance(system,list):system=j(system)
    if payload.get('response_format',{}).get('type')=='json_object':answer=j({'passed':True,'issues':[],'blocking_issues':[]})
    elif '阅读整理器' in system:answer='## 数域的阅读索引\n\n概念：对四则运算封闭，除法的除数不能为零。[来源：PDF 第 1 页]\n\n条件：不得把任意数集合说成数域。\n\n疑点：未提供其他章节，不推测后续。'
    else:answer='# 数域的讲解\n\n数域是一组对四则运算封闭的数，除法排除零除数。\n\n## 为什么要说明非零条件\n\n除法本身要求除数不为零，这个条件不能从定义中删掉。\n\n## 系统性总结\n\n定义、封闭性与非零除数要一起检查。'
    if payload.get('stream'):return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':answer},'finish_reason':'stop'}]})
original=httpx.AsyncClient
httpx.AsyncClient=lambda *a,**kw:original(transport=httpx.MockTransport(respond))
ai.get_secret=lambda name:'fixture-key' if name=='DEEPSEEK_API_KEY' else None

@server.app.get('/__library_test__/calls')
def model_calls():return {'calls':calls}
# Add test-only endpoints before the production static mount.
mount=next(route for route in server.app.routes if getattr(route,'name',None)=='web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
ports=[]
for _ in range(2):
    s=socket.socket();s.bind(('127.0.0.1',0));ports.append(s.getsockname()[1]);s.close()
case={'desktop_url':f'http://127.0.0.1:{ports[0]}','mobile_url':f'https://127.0.0.1:{ports[1]}','token':'library-ui-owner',
      'project_id':p['id'],'other_project_id':q['id'],'conversation_id':c['id'],'other_conversation_id':other['id'],
      'book_id':b['id'],'nodes':nodes}
async def start_mobile():
    while not getattr(server.app.state,'mobile_manager',None):await asyncio.sleep(.05)
    manager=server.app.state.mobile_manager
    await manager.start(StartIn(addresses=['127.0.0.1'],port=ports[1]))
    case.update(pairing_code=manager.code,certificate=manager.tls['ca'],fingerprint=manager.tls['fingerprint'])
    case_path.write_text(j(case),encoding='utf-8');print('READY '+str(case_path),flush=True)
async def main():
    starter=asyncio.create_task(start_mobile())
    await uvicorn.Server(uvicorn.Config(server.app,host='127.0.0.1',port=ports[0],log_level='warning')).serve()
    await asyncio.gather(starter,return_exceptions=True)
if __name__=='__main__':asyncio.run(main())
