"""Native desktop and paired HTTPS fixture for long-source tutor input."""
import hashlib
import json

from scripts import smoke_library_ui as fixture
from scripts.source_focus_cases import CASES
from studyforge import source_focus
from studyforge.db import execute,j,many,now,uid
from studyforge.learning import source_fingerprint
from studyforge.materials import read_original_sources

fixture.enable_semantic(False)
fixture.ai.save_settings({'library_reference_mode':'off'})
fixture.server.discussion_completed=lambda *a:None
material=CASES['algebra']
path=fixture.case_path.parent/'long-original.txt'
path.write_text(material['front']+material['tail'],encoding='utf-8')
sid,rid=uid(),uid()
execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
    (sid,fixture.p['id'],'代数原文.txt','.txt',str(path),'[]','ready',now()))
records=read_original_sources([dict(id=sid,project_id=fixture.p['id'],name='代数原文.txt',kind='.txt',original_path=str(path))])
execute('INSERT INTO reading_sessions VALUES (?,?,?,?,?,?,?,?,?,?)',(rid,fixture.p['id'],j([sid]),source_fingerprint(records),
    'deepseek','deepseek-flash',None,j([{'part':1,'text':'人工准备的测试笔记，只作导航。'}]),j([records[0]['read_manifest']]),now()))
fixture.conversations.update(fixture.c['id'],fixture.p['id'],{'source_ids':[sid],'reading_id':rid})
fixture.case.update(source_id=sid,reading_id=rid,question=material['question'],targets=material['targets'])
original_focus=source_focus.prepare
receipts=[]
def observed(*args,**kwargs):
    text,receipt=original_focus(*args,**kwargs)
    receipts.append(receipt)
    return text,receipt
source_focus.prepare=observed
answer=('## 非零和可逆的区别\n\n'
    '这是界面验收的受控回复，不作为真实模型质量证据。\n\n'
    '在交换含幺环中，$[u]$ 可逆要求存在 $v$ 使 $uv-1\\in I$。\n\n'
    '模6时，$[5][5]=[1]$，因为 $25-1=24$ 是6的倍数；'
    '$[2]$ 非零，但任何整数 $v$ 都不能使偶数 $2v$ 与1同余模6。\n\n'
    '非零只说明不是零陪集；可逆还要求能乘回单位元。')
async def respond(request):
    if request.method=='GET':return fixture.httpx.Response(200,json={'data':[{'id':'deepseek-flash'}]})
    payload=json.loads(request.content);fixture.calls.append(payload)
    assert all(target in payload['messages'][0]['content'] for target in material['targets'])
    await fixture.asyncio.sleep(.5)
    return fixture.httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
fixture.httpx.AsyncClient=lambda *a,**kw:fixture.original(transport=fixture.httpx.MockTransport(respond))


@fixture.server.app.get('/__source_focus_test__/state')
def state():
    return {'calls':fixture.calls,'receipts':receipts,
            'users':many("SELECT content FROM messages WHERE conversation_id=? AND role='user' ORDER BY rowid",(fixture.c['id'],)),
            'mastery':len(many('SELECT * FROM mastery')),'events':len(many('SELECT * FROM learning_events'))}


mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)
if __name__=='__main__':fixture.asyncio.run(fixture.main())
