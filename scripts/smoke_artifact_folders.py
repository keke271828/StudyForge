"""Native Outputs folder fixture, no real model calls or user data."""
import json
import os
import socket
from pathlib import Path

import httpx
import uvicorn
from fastapi import Query

from studyforge import ai, conversations, exercises, server
from studyforge.db import create_job, create_project, execute, j, now, one, uid, unj, update_job
from studyforge.exporters import export_document


def add_file(project_id, title):
    path = export_document('# '+title+'\n\n仅用于成果项目文件夹验收。', 'docx', title, uid()+'.docx')
    return server.add_artifact(project_id, [], 'explanation', 'docx', title, path)


def main():
    case_path = Path(os.environ['STUDYFORGE_ARTIFACT_FOLDERS_CASE'])
    ai.save_settings({'chat_provider':'deepseek', 'agent_tools_enabled':False, 'background_learning_enabled':False})
    if case_path.exists():
        case = json.loads(case_path.read_text(encoding='utf-8'))
    else:
        projects = [create_project(name) for name in ['哲学与社会科学', '数学与编程 <高级>', '一个很长的空项目文件夹名称，用于检查小窗口显示']]
        files = [add_file(projects[0]['id'], '概念定义'), add_file(projects[0]['id'], '论证方法'), add_file(projects[1]['id'], '算法与模型')]
        chats = []
        for project in projects:
            chat = conversations.create(project['id'], 'deepseek', 'deepseek-flash')
            chats.append(chat['id'])
            execute('INSERT INTO messages VALUES (?,?,?,?,?)', (uid(),chat['id'],'user',project['name']+'的独立对话',now()))
            conversations.update(chat['id'],project['id'],{'title':project['name']+'对话'})
        for index,item in enumerate(files):
            row=one('SELECT metadata_json FROM artifacts WHERE id=?',(item['id'],))
            execute('UPDATE artifacts SET metadata_json=? WHERE id=?',
                    (j(unj(row['metadata_json'])|{'conversation_id':chats[0 if index<2 else 1]}),item['id']))
        conversations.activate(chats[0])
        case = {'projects':projects, 'files':files, 'chats':chats}
    ai.get_secret = lambda key: 'fixture-key' if key == 'DEEPSEEK_API_KEY' else None
    server.get_secret = ai.get_secret
    native = httpx.AsyncClient
    stats={'calls':0,'format_repairs':0,'lecture_calls':0}
    async def no_network(topic):return []
    exercises.search_exercises=no_network
    def respond(request):
        if request.method == 'GET': return httpx.Response(200, json={'data':[{'id':'deepseek-flash'}]})
        stats['calls']+=1
        payload=json.loads(request.content)
        system=payload['messages'][0]['content']
        if '习题设计者' in system:
            if stats['format_repairs']==0:
                stats['format_repairs']=1;content='这不是合法 JSON'
            else:content=j({'questions':[{'question':'解释相关不能推出因果的原因。','solution':'PRIVATE_SOLUTION_DO_NOT_PUBLISH',
                       'rubric':'说明共同原因等条件','topic':'因果推断','source_url':''}]})
        elif '独立解题员' in system:content=j({'answers':[{'index':0,'solution':'PRIVATE_SOLUTION_DO_NOT_PUBLISH','issues':[]}]})
        elif '习题审查员' in system:content=j({'passed':True,'issues':[]})
        else:
            stats['lecture_calls']+=1
            raise AssertionError('Only exercises must not call a lecture model')
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':content},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    httpx.AsyncClient = lambda *a, **kw: native(transport=httpx.MockTransport(respond))

    @server.app.post('/__folder_fixture/file')
    def new_file(project_id: str = Query(), title: str = Query()):
        return add_file(project_id, title)

    @server.app.post('/__folder_fixture/task')
    def new_task(project_id: str = Query()):
        job = create_job(project_id, 'folder_fixture', {})
        update_job(job, 'paused', 40, {'stage':'文件夹任务验收'})
        return {'id':job}

    @server.app.get('/__folder_fixture/stats')
    def model_stats():return stats

    for route in list(server.app.routes):
        if getattr(route, 'path', '').startswith('/__folder_fixture/'):
            server.app.routes.remove(route)
            server.app.routes.insert(0, route)

    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    case['url'] = f'http://127.0.0.1:{port}'
    case_path.write_text(j(case), encoding='utf-8')
    uvicorn.run(server.app, host='127.0.0.1', port=port, log_level='warning')


if __name__ == '__main__': main()
