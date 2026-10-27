"""Isolated desktop/HTTPS mobile acceptance, with observable model requests."""
import asyncio
import json

import httpx
from scripts import smoke_library_ui as fixture
from studyforge import library, providers
from studyforge.db import execute

fixture.enable_semantic(False)
for n in fixture.nodes[1:3]:
    library.update_node(n['id'],{'start_page':n['start_page'],'end_page':n['start_page'],'end_y':.5,'confirmed':True})
fixture.case.update(field_node_id=fixture.nodes[1]['id'],polynomial_node_id=fixture.nodes[2]['id'])
entered=asyncio.Event();release=asyncio.Event()
async def response(request):
    if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'deepseek-flash'},{'id':'library-reader'},{'id':'library-vision'}]})
    payload=json.loads(request.content);fixture.calls.append(payload)
    if payload.get('model')=='library-reader' and not release.is_set():
        entered.set();await release.wait()
    answer='MODEL_ACCEPTANCE_NOTE：所选原页的数域封闭性。来源 PDF 第 1 页。'
    return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':answer},'finish_reason':'stop'}]})
httpx.AsyncClient=lambda *a,**kw:fixture.original(transport=httpx.MockTransport(response))
providers.set_secret=lambda *a:None
service=providers.save_service({'name':'第三方测试服务','protocol':'openai','base_url':'https://example.com/v1',
    'default_model':'third-party-reader','models':['third-party-reader'],'requires_key':False,'supports_vision':False})
fixture.case['third_party_provider']=service['id']

@fixture.server.app.get('/__library_models_test__/state')
def state():return {'entered':entered.is_set(),'calls':fixture.calls}

@fixture.server.app.post('/__library_models_test__/release')
def allow():release.set();return {'ok':True}

# Diagnostic routes precede the production static mount.
mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)
if __name__=='__main__':asyncio.run(fixture.main())
