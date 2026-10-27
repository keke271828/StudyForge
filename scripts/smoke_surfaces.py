"""Local desktop acceptance fixture; no inference, original files or user data changes."""
import os
import socket
from pathlib import Path

import httpx
import uvicorn

from studyforge import ai, server, conversations
from studyforge.config import artifacts_dir
from studyforge.db import create_project, execute, j, many, now, one, uid


def main():
    case_path=Path(os.environ['STUDYFORGE_SURFACES_CASE']);root=case_path.parent
    phase=int(os.environ.get('STUDYFORGE_SURFACES_PHASE','1'))
    if phase==1:
        ai.save_settings({'chat_provider':'deepseek','agent_tools_enabled':False,'background_learning_enabled':False})
        project=create_project('自由外观验收')
        chat=conversations.create(project['id'],'deepseek');conversations.activate(chat['id'])
        original=root/'结构与证明.txt';original.write_text('先列条件，再解释构造动机。',encoding='utf-8')
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
                (uid(),project['id'],original.name,'.txt',str(original),j([{'locator':'行 1','text':original.read_text(encoding='utf-8')}]),'ready',now()))
        artifact=artifacts_dir()/'成果验收.txt';artifact.write_text('系统总结：把条件与结论连接起来。',encoding='utf-8')
        server.add_artifact(project['id'],[],'external','txt','构造动机讲解',artifact)
        # The OS font is read once; the test uploads its separate fixture copy.
        font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'segoeui.ttf'
        (root/'验收字体.ttf').write_bytes(font.read_bytes())
    else:project=one('SELECT * FROM projects ORDER BY created_at LIMIT 1')
    ai.get_secret=lambda name:None;server.get_secret=ai.get_secret;server.shutil.which=lambda name:None
    native=httpx.AsyncClient;network={'model_calls':0}
    def mock(request):
        if request.method=='POST':network['model_calls']+=1
        return httpx.Response(500 if request.method=='POST' else 200,json={'data':[]})
    class Offline(native):
        def __init__(self,*args,**kwargs):
            kwargs['transport']=httpx.MockTransport(mock);super().__init__(*args,**kwargs)
    httpx.AsyncClient=Offline
    @server.app.get('/__surfaces_test__/state')
    def inspect():return network | {table:len(many('SELECT * FROM '+table)) for table in ['sources','jobs','learning_events','messages']}
    mount=next(route for route in server.app.router.routes if getattr(route,'name',None)=='web')
    server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    case_path.write_text(j({'url':f'http://127.0.0.1:{port}','phase':phase,'project':project['id']}),encoding='utf-8')
    uvicorn.run(server.app,host='127.0.0.1',port=port,log_level='warning')


if __name__=='__main__':main()
