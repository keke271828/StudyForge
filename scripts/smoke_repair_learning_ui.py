"""Isolated native desktop and paired phone repair workflow, mock model only."""
import asyncio
import json
import os
from pathlib import Path
import sys

folder=Path(__file__).resolve().parents[1]/'build'/sys.argv[1]
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
from scripts import smoke_library_ui as fixture
from scripts.repair_learning_fixture import seed
from studyforge.db import j

fixture.enable_semantic(False)
case=seed(folder,fixture.p['id'],fixture.c['id']);fixture.case.update(case,process_id=os.getpid())

async def response(request):
    if request.method=='GET':return await fixture.respond(request)
    body=json.loads(request.content);fixture.calls.append(body);system=body['messages'][0]['content']
    if '严谨的习题设计者' in system:
        spec,_=json.JSONDecoder().raw_decode(body['messages'][-1]['content'].split('修复目标数据：',1)[1])
        answer={'questions':[{'question':'REPAIR_NEW：一个闭合盒子放在均匀电场中，比较两个相对面的带符号贡献，说明净和与局部电场的区别，并写出理由。',
            'topic':target['topic'],'solution':'REPAIR_PRIVATE_SOLUTION：独立完整解析。',
            'rubric':'定义、条件与解释分别给分。','source_url':'',
            'repair_target_index':target['index'],'repair_focus':'REPAIR_PRIVATE_FOCUS：区分闭合面整体净和与局部的场。'} for target in spec['targets']]}
    elif '独立解题员' in system:answer={'answers':[{'index':0,'solution':'独立核对通过。','issues':[]}]}
    else:answer={'passed':True,'issues':[]}
    if body.get('stream'):
        return fixture.httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':j(answer)},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    return fixture.httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':j(answer)},'finish_reason':'stop'}]})

fixture.httpx.AsyncClient=lambda *a,**kw:fixture.original(transport=fixture.httpx.MockTransport(response))
if __name__=='__main__':asyncio.run(fixture.main())
