"""Actual generation UI and paired HTTPS download; controlled model only."""
import hashlib
import json
import re
import time

from docx import Document
from scripts import smoke_library_ui as fixture
from scripts.chapter_continuity_cases import seed,split,document
from studyforge import lesson_quality
from studyforge.db import execute,j,many,now,one,uid,unj
from studyforge.learning import source_fingerprint
from studyforge.materials import read_original_sources
from studyforge.scheduling import current_step

fixture.enable_semantic(False)
fixture.ai.save_settings({'library_reference_mode':'off','generation_parallel':True})
fixture.server.discussion_completed=lambda *a:None
fixture.server.explanation_batches=split
events=[]
independent_entries={}
for kind,project,chat in [('dependent',fixture.p,fixture.c),('independent',fixture.q,fixture.other)]:
    ids=seed(project['id'],kind)
    records=read_original_sources([one('SELECT * FROM sources WHERE id=?',(sid,)) for sid in ids])
    rid=uid()
    execute('INSERT INTO reading_sessions VALUES (?,?,?,?,?,?,?,?,?,?)',(rid,project['id'],j(ids),source_fingerprint(records),
        'deepseek','deepseek-flash',None,j([{'part':1,'text':'人工验收笔记，只作导航，不证明学习掌握。'}]),j([r['read_manifest'] for r in records]),now()))
    fixture.conversations.update(chat['id'],project['id'],{'source_ids':ids,'reading_id':rid})
    fixture.case[kind]={'project_id':project['id'],'conversation_id':chat['id'],'source_ids':ids,'reading_id':rid}


async def respond(request):
    if request.method=='GET':return fixture.httpx.Response(200,json={'data':[{'id':'deepseek-flash'}]})
    payload=json.loads(request.content);fixture.calls.append(payload)
    system,user=payload['messages'][0]['content'],payload['messages'][-1]['content']
    step=current_step.get();job_id=step.control.job_id if step else None
    row=one('SELECT project_id,kind,payload_json FROM jobs WHERE id=?',(job_id,))
    kind='dependent' if row['project_id']==fixture.p['id'] else 'independent'
    if '只补写整篇文章的系统性总结' in system:
        role,part,previous='summary',0,False
        answer='## 系统性总结\n整合两部分的定义、条件和推导；完整正文在前面保留。'
    elif payload.get('response_format',{}).get('type')=='json_object':
        role,part,previous='review',int(re.findall(r'DRAFT_PART_(\d+)',user)[-1]),False
        answer=j({'passed':True,'issues':[]})
    elif row['kind']=='read':
        role,part,previous='reading',0,False
        answer='人工资料的受控阅读笔记。'
    else:
        role,part='draft',int(re.search(r'这是长资料第 (\d+)/',user)[1])
        previous='部分的已完成讲解，用于续接' in user or '已写内容衔接' in user
        assert '【所选资料身份JSON】' in user
        answer=document(part,previous)
    events.append({'job_id':job_id,'case':kind,'role':role,'part':part,'phase':'start','at':time.monotonic(),'previous':previous})
    if kind=='independent' and role=='draft' and unj(row['payload_json']).get('parallel'):
        entered=independent_entries.setdefault(job_id,fixture.asyncio.Event())
        if part==2:entered.set()
        elif part==1:await fixture.asyncio.wait_for(entered.wait(),5)
    await fixture.asyncio.sleep(.3 if part==1 else .08)
    events.append({'job_id':job_id,'case':kind,'role':role,'part':part,'phase':'end','at':time.monotonic(),'previous':previous})
    return fixture.httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')


fixture.httpx.AsyncClient=lambda *a,**kw:fixture.original(transport=fixture.httpx.MockTransport(respond))


@fixture.server.app.get('/__chapter_test__/state')
def state():
    jobs=[]
    for row in many("SELECT * FROM jobs WHERE kind='generate' ORDER BY created_at,rowid"):
        result=unj(row['result_json']);payload=unj(row['payload_json']);artifact=None
        for candidate in many("SELECT * FROM artifacts WHERE project_id=? AND kind='explanation'",(row['project_id'],)):
            if unj(candidate['metadata_json']).get('generation_job_id')==row['id']:
                path=fixture.Path(candidate['path']);words='\n'.join(p.text for p in Document(path).paragraphs)
                artifact={'id':candidate['id'],'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                    'title':candidate['title'],'format':candidate['format'],'words':words,
                    'metadata':unj(candidate['metadata_json'])}
        jobs.append({'id':row['id'],'project_id':row['project_id'],'status':row['status'],'error':row['error'],
            'parallel':payload.get('parallel'),'plan':result.get('chapter_dependencies'),'artifact':artifact})
    return {'jobs':jobs,'events':events,'calls':len(fixture.calls),'mastery':len(many('SELECT * FROM mastery')),
            'learning_events':len(many('SELECT * FROM learning_events'))}


mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)
if __name__=='__main__':fixture.asyncio.run(fixture.main())
