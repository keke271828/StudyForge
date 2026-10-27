"""Real tool dispatch, precise saved spans and later-version UI isolation."""
import asyncio
import hashlib

from scripts import smoke_library_ui as fixture
from studyforge import library,library_history
from studyforge.agent_tools import AgentRuntime,ReadLibrary
from studyforge.db import execute,j,many,now,one,uid

fixture.enable_semantic(False)
fixture.ai.save_settings({'agent_tools_enabled':True})
node=library.update_node(fixture.nodes[1]['id'],{'start_page':1,'end_page':2,'end_y':.5,'confirmed':True})
old=uid()
execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,created_at,updated_at) '
    'VALUES (?,?,?,?,?,?,?,?,?,?)',(old,node['id'],library.reading_signature(fixture.b,node,'deepseek','saved-tool-reader','high'),
        'deepseek','saved-tool-reader','high','completed','PRIVATE_NAVIGATION_NOTE '*100,now(),now()))
for page in (1,2):
    value=library.extract_page(fixture.b,node,page,ocr=False)
    execute('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',(old,page,value['locator'],value['original_text'],
        'AI_VIEW_ONLY: this saved observation is not an original quotation.',value['image_path'],value['image_sha256']))
library.set_preferences(fixture.c['id'],fixture.p['id'],'manual',[{'node_id':node['id'],'purpose':'reference'}])
runtime=AgentRuntime(fixture.p['id'],conversation_id=fixture.c['id'],provider='deepseek')
runtime.library_snapshot=library.reference_snapshot(fixture.c['id'],fixture.p['id'],'field')

# A later valid reading exists before the read, but the task keeps its snapshot.
newer=uid()
execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,created_at,updated_at) '
    'VALUES (?,?,?,?,?,?,?,?,?,?)',(newer,node['id'],library.reading_signature(fixture.b,node,'deepseek','later-tool-reader','high'),
        'deepseek','later-tool-reader','high','completed','NEWER_NOTE',now(),'2099-01-01T00:00:00+00:00'))
execute('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',(newer,1,'PDF 第 1 页','NEWER_VERSION_BODY','',None,None))


@fixture.server.app.get('/__tool_receipt_test__/state')
def state():
    return {'model_requests':len(fixture.calls),'events':len(many('SELECT * FROM learning_events')),
        'mastery':len(many('SELECT * FROM mastery')),'jobs':len(many('SELECT * FROM jobs')),
        'exercise_sets':len(many('SELECT * FROM exercise_sets'))}


mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)


async def main():
    cases=[]
    window=library.read_text_window(old,fixture.b['title'],node['title'],page=2)
    original=one('SELECT original_text FROM library_chunks WHERE reading_id=? AND page=?',(old,2))['original_text']
    assert original
    scenarios=[('partial',{'page':2,'offset':window['text'].index(original)+5,'limit':100}),
        ('visual',{'page':2,'offset':window['text'].index('AI_VIEW_ONLY'),'limit':100}),
        ('empty',{'page':1,'offset':999999,'limit':100}),('all',{'limit':12000})]
    for label,args in scenarios:
        result=await runtime.execute('sf_read_library_node',j({'node_id':node['id'],**args}))
        assert 'error' not in result,result
        saved=result['library_history'];receipt=saved['receipt']
        assert receipt['context_sha256']==hashlib.sha256(result['text'].encode()).hexdigest()
        assert receipt['sources'][0]['library_reading']['id']==old
        cases.append({'label':label,'lookup_id':saved['id'],'receipt':receipt,'returned_text':result['text']})
    legacy=library_history.record(fixture.c['id'],fixture.p['id'],'旧回查记录',{'evidence':[{'node_id':node['id'],'page':1}]})
    library.update_node(node['id'],{'title':'<img src=x onerror="window.toolInjected=true"> 后来改名','end_y':.6,'confirmed':True})
    fixture.case.update(tool_cases=cases,legacy_lookup_id=legacy['id'],old_reading_id=old,new_reading_id=newer,
        old_title=node['title'],new_title=library.node(node['id'])['title'])
    assert not many('SELECT * FROM learning_events') and not fixture.calls
    await fixture.main()


if __name__=='__main__':asyncio.run(main())
