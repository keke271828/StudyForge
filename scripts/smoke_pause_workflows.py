"""Controlled native pause fixture: isolated files, no network or paid models."""
import asyncio
import json
import os
from pathlib import Path
import socket

import httpx
import uvicorn

from studyforge import ai, conversations, server
from studyforge.db import create_project, execute, j, many, now, one, uid, unj


def main():
    case_path=Path(os.environ['STUDYFORGE_PAUSE_CASE']);stats_path=case_path.with_name('model-calls.json')
    ai.save_settings({'chat_provider':'deepseek','deepseek_model':'pause-model','agent_tools_enabled':False,'background_learning_enabled':False})
    if case_path.exists():case=unj(case_path.read_text(encoding='utf-8'))
    else:
        projects=[create_project('暂停与恢复验收'),create_project('另一个独立项目')]
        chat=conversations.create(projects[0]['id'],'deepseek','pause-model')['id']
        source=uid();path=case_path.parent/'资料.txt'
        text='相关不能推出因果。需要检查共同原因。\n\n'+('\n\n'.join('第'+str(n)+'段：论证需要条件与证据。'+'相关关系与共同原因需要区分。'*550 for n in range(10)))
        path.write_text(text,encoding='utf-8')
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
                (source,projects[0]['id'],path.name,'.txt',str(path),'[]','ready',now()))
        quiz=uid()
        execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(quiz,projects[0]['id'],j([source]),'因果迁移题',
            j([{'index':0,'question':'为什么相关不足以证明因果？','topic':'因果'}]),
            j([{'index':0,'solution':'PRIVATE_REFERENCE','rubric':'指出共同原因及必要条件'}]),1,'assigned',now()))
        conversations.activate(chat)
        case={'projects':projects,'chat':chat,'source':source,'quiz':quiz}
    stats=unj(stats_path.read_text(encoding='utf-8')) if stats_path.exists() else {'calls':[]}
    holds={};release={};phase=os.environ['STUDYFORGE_PAUSE_PHASE']
    native=httpx.AsyncClient
    ai.get_secret=lambda key:'fixture-key' if key=='DEEPSEEK_API_KEY' else None
    server.get_secret=ai.get_secret
    original=server.read_original_sources(server.source_records([case['source']],case['projects'][0]['id']))[0]
    graph={'concepts':[{'id':'cause','name':'因果条件','domain':'逻辑','description':'相关不足以推出因果。','basis':'source',
                       'evidence':[{'source_id':case['source'],'locator':original['segments'][0]['locator'],'quote':'相关不能推出因果'}]}],'relations':[]}
    async def respond(request):
        if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'pause-model'}]})
        body=json.loads(request.content);system=body['messages'][0]['content']
        if '现在先通读理解资料' in system:kind='read';content='# 阅读笔记\n区分相关、因果和证据。'
        elif '【资料知识结构整理】' in system:kind='knowledge';content=j(graph)
        elif '批改者' in system:kind='quiz';content=j({'scores':[80],'feedback':['说明了共同原因'],'uncertainties':[]})
        elif '独立解题员' in system:kind='coding';content=j({'approach':'按合法输入核对函数值','passed':True,'blocking_issues':[],'notes':[]})
        elif '审查员' in system:kind='coding';content=j({'passed':True,'blocking_issues':[],'notes':[]})
        elif '编程教师' in system:
            kind='coding';content=j({'title':'线性函数','problem':'输入实数x，返回2x，使用MATLAB编写函数。','topic':'函数',
                'starter_code':'function y = twice(x)\n% TODO\nend','reference_code':'PRIVATE_REFERENCE','test_code':''})
        else:raise AssertionError('Unexpected fixture model prompt: '+system[:100])
        stats['calls'].append(kind);stats_path.write_text(j(stats),encoding='utf-8')
        should_hold=(phase=='1' and kind in ('read','coding','quiz') or phase=='2' and kind=='knowledge') and kind not in holds
        if should_hold:
            holds[kind]=True;release[kind]=asyncio.Event();await release[kind].wait()
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':content},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    httpx.AsyncClient=lambda *a,**k:native(transport=httpx.MockTransport(respond))

    @server.app.get('/__pause_fixture/state')
    def state():return {'calls':stats['calls'],'holds':list(release),
        'jobs':many('SELECT id,kind,status,progress FROM jobs'),'submissions':len(many('SELECT id FROM submissions')),
        'sets':len(many('SELECT id FROM exercise_sets')),'maps':len(many('SELECT id FROM knowledge_maps'))}
    @server.app.post('/__pause_fixture/release/{kind}')
    async def unlock(kind:str):
        release[kind].set();return {'released':kind}
    @server.app.get('/__pause_fixture/check-documents')
    def check_documents():
        from docx import Document
        rows=many("SELECT * FROM artifacts WHERE format='docx'")
        found={row['kind']:'\n'.join(p.text for p in Document(row['path']).paragraphs) for row in rows}
        assert 'exercise' in found and 'solutions' in found
        assert 'PRIVATE_REFERENCE' not in found['exercise'] and 'TODO' in found['exercise']
        assert 'PRIVATE_REFERENCE' in found['solutions']
        return {'docx_files':len(rows),'student_reference_hidden':True,'graded_solution_present':True}
    for route in list(server.app.routes):
        if getattr(route,'path','').startswith('/__pause_fixture/'):
            server.app.routes.remove(route);server.app.routes.insert(0,route)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    case['url']=f'http://127.0.0.1:{port}';case_path.write_text(j(case),encoding='utf-8')
    uvicorn.run(server.app,host='127.0.0.1',port=port,log_level='warning')


if __name__=='__main__':main()
