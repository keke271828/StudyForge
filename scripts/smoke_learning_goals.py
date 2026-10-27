"""Native UI acceptance fixture. All records and files live in an isolated directory."""
import asyncio
import json
import os
import socket
from pathlib import Path

import httpx
import uvicorn
from docx import Document

from studyforge import ai, conversations, exercises, knowledge, server
from studyforge.db import create_project, execute, j, many, now, one, uid
from studyforge.learning import source_fingerprint
from studyforge.materials import read_original_sources


def main():
    case_path=Path(os.environ['STUDYFORGE_GOALS_CASE']);root=case_path.parent
    phase=int(os.environ.get('STUDYFORGE_GOALS_PHASE','1'))
    if phase==1:
        ai.save_settings({'chat_provider':'deepseek','deepseek_model':'route-model','agent_tools_enabled':False,
            'background_learning_enabled':False,'agent_network_enabled':False,'model_concurrency':2,'auto_select_imports':False})
        project=create_project('广泛了解与重点精学');other=create_project('另一项目')
        path=root/'原文.txt';path.write_text('描述性判断说明事实是什么。规范性判断讨论应该怎样。仅凭一种做法很普遍，不能推出它应当被接受；需要补充评价原则。原文不主张所有普遍做法都不可接受。',encoding='utf-8')
        source=uid();execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (source,project['id'],path.name,'.txt',str(path),j([{'locator':'旧预览','text':'DO_NOT_READ_PREVIEW'}]),'ready',now()))
        chat=conversations.create(project['id'],'deepseek','route-model');second=conversations.create(project['id'],'deepseek','route-model')
        execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),second['id'],'user','PRIVATE_SECOND_CHAT',now()))
        originals=read_original_sources(server.source_records([source],project['id']));reading=uid()
        execute('INSERT INTO reading_sessions VALUES (?,?,?,?,?,?,?,?,?,?)',(reading,project['id'],j([source]),source_fingerprint(originals),
            'deepseek','route-model',None,j([{'part':1,'text':'已有阅读笔记，后续仍须读原文。'}]),j([r['read_manifest'] for r in originals]),now()))
        evidence={'source_id':source,'locator':originals[0]['segments'][0]['locator'],'quote':'描述性判断说明事实是什么'}
        raw={'concepts':[
            {'id':'description','name':'描述性判断','domain':'哲学','description':'说明事实的判断，不直接给出评价原则。','basis':'source','evidence':[evidence]},
            {'id':'norm','name':'规范性判断','domain':'哲学','description':'讨论应该怎样，需要评价原则。','basis':'source','evidence':[dict(evidence,quote='规范性判断讨论应该怎样')]}],
            'relations':[{'from_id':'description','to_id':'norm','kind':'prerequisite','reason':'教学建议：先区分事实与评价','basis':'teaching','boundary':'这不是唯一学习顺序','evidence':[evidence]}]}
        normalized=knowledge.normalize_part(raw,knowledge.evidence_index(originals),1)
        graph=dict(normalized,version=knowledge.VERSION,note='验收原文引文已匹配；掌握仍需证据。',processed_parts=1,source_reading=[r['read_manifest'] for r in originals])
        knowledge.save_map(one('SELECT * FROM reading_sessions WHERE id=?',(reading,)),graph,'deepseek','route-model',None)
        conversations.update(chat['id'],project['id'],{'source_ids':[source],'reading_id':reading})
        conversations.activate(chat['id'])
        case={'project':project['id'],'other':other['id'],'chat':chat['id'],'second':second['id'],'source':source,'reading':reading}
    else:case=json.loads(case_path.read_text(encoding='utf-8'))
    requests_path=root/'requests.json';calls=json.loads(requests_path.read_text(encoding='utf-8')) if requests_path.exists() else []
    ai.get_secret=lambda name:'fixture-key' if name=='DEEPSEEK_API_KEY' else None
    server.get_secret=ai.get_secret
    gate=asyncio.Event()
    if phase!=1:gate.set()
    native=httpx.AsyncClient
    async def reply(request):
        if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'route-model'}]})
        body=json.loads(request.content);system=body['messages'][0]['content'];user=body['messages'][-1]['content']
        kind=('solve' if '独立解题员' in system else 'review' if '习题审查员' in system else
              'design' if '习题设计者' in system else 'grade' if '批改者' in system or '评分复核者' in system else 'chat')
        calls.append({'kind':kind,'model':body['model'],'system':system,'user':user});requests_path.write_text(j(calls),encoding='utf-8')
        if kind=='design':
            await gate.wait()
            text=j({'questions':[{'question':q,'topic':'描述与规范（哲学）','assessment_dimension':dimension,
                'solution':'PRIVATE_REFERENCE：事实前提仍需要评价原则才能支持规范结论。','rubric':'区分事实与评价50分，说明前提与条件50分','source_url':''}
                for q,dimension in zip(['用自己的话区分事实判断与规范判断。','解释“很多人这样做，所以应该这样做”的推理缺口。','一种做法普遍存在，但材料没有评价原则，分析能否推出它应该被接受，以及需要补充什么。'],['concept','reasoning','transfer'])]})
        elif kind=='solve':text=j({'answers':[{'index':i,'solution':'规范结论需要评价原则，不能从普遍性独立推出。','issues':[]} for i in range(3)]})
        elif kind=='review':text=j({'passed':True,'issues':[]})
        elif kind=='grade':text=j({'scores':[100,100,100],'feedback':['解释充分，符合评分点']*3,'uncertainties':[]})
        else:text='事实判断说明“是什么”，规范判断讨论“应当怎样”。二者之间需要评价前提；现在的学习目标要求解释这处论证理由，并检查条件。'
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':text},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    class Offline(native):
        def __init__(self,*args,**kwargs):kwargs['transport']=httpx.MockTransport(reply);super().__init__(*args,**kwargs)
    httpx.AsyncClient=Offline
    async def no_search(*a):return []
    exercises.search_exercises=no_search
    @server.app.post('/__goals_test__/release')
    def release():gate.set();return {'ok':True}
    @server.app.get('/__goals_test__/state')
    def inspect():
        artifacts=many('SELECT * FROM artifacts')
        for artifact in artifacts:artifact['paragraphs']='\n'.join(p.text for p in Document(artifact['path']).paragraphs)
        return {'calls':calls,'artifacts':artifacts,'attempts':server.project_homework(case['project']),
                'checks':many('SELECT * FROM learning_goal_checks'),'submissions':many('SELECT * FROM submissions')}
    mount=next(route for route in server.app.router.routes if getattr(route,'name',None)=='web')
    server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    case.update(url=f'http://127.0.0.1:{port}',phase=phase);case_path.write_text(j(case),encoding='utf-8')
    uvicorn.run(server.app,host='127.0.0.1',port=port,log_level='warning')


if __name__=='__main__':main()
