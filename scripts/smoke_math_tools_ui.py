"""Real desktop and paired HTTPS mobile tool UI; isolated, no model network."""
import asyncio
import json
import os
from pathlib import Path
import sys

folder=Path(__file__).resolve().parents[1]/'build'/sys.argv[1]
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
from scripts import smoke_library_ui as fixture
from studyforge.db import j,many

fixture.enable_semantic(False)
fixture.ai.save_settings({'agent_tools_enabled':True,'agent_network_enabled':False,'agent_permission_mode':'read_only'})
fixture.case['process_id']=os.getpid()
polynomial='--polynomial' in sys.argv[2:]
rational='--rational' in sys.argv[2:]
fixture.case['polynomial']=polynomial
fixture.case['rational']=rational


async def respond(request):
    if request.method=='GET':return await fixture.respond(request)
    body=json.loads(request.content);fixture.calls.append(body)
    assert 'sf_check_math' in j(body.get('tools',[]))
    if body['messages'][-1]['role']=='tool':
        results=[json.loads(m['content']) for m in body['messages'] if m['role']=='tool'][-2:]
        if rational:
            assert all(r['operation']=='rational_identity' and r['results']['identical_on_common_domain'] for r in results)
            assert all(r['results']['left']['nonzero_conditions'] and not r['results']['right']['nonzero_conditions'] for r in results)
            assert all(r['results']['domain_comparison']=='not_compared' for r in results)
        elif polynomial:
            equality=next(r for r in results if r['operation']=='polynomial_identity')['results']
            derivative=next(r for r in results if r['operation']=='polynomial_derivative')['results']
            assert equality['identical'] is False and equality['difference']=='(-4)*a*b'
            assert derivative['matches'] is False and derivative['derivative']=='(1)*k*x'
        else:
            vector=next(r for r in results if r['operation']=='vectors')['results']
            arithmetic=next(r for r in results if r['operation']=='arithmetic')['results']
            assert vector['same_direction'] is False and vector['angle_class']=='acute'
            assert [r['exact'] for r in arithmetic]==['3/10','1/2']
        await asyncio.sleep(.7)  # Keep real completed-tool progress visible before the saved reply replaces it.
        answer=(r'UI_MATH_DONE：本机核对 $(x^2-1)/(x-1)=x+1$ 只在原分母非零时成立；$x=1$ 仍不在原函数定义域。$t(1/t)=1$ 也保留 $t\ne0$，不能因约分给断点补定义；若原题给定 $t>0$，仍按原范围讨论。'
                if rational else r'UI_MATH_DONE：本机核对得到 $(a-b)^2=a^2-2ab+b^2$，原先的加号不构成恒等式。能量表达式对位置的形式偏导为 $kx$，不是 $2kx$。这些结果只核对代数，时间求导还需链式法则与运动方程。'
                if polynomial else 'UI_MATH_DONE：本机精确核验 0.1+0.2=3/10，1/3+1/6=1/2；两个向量的点积为1、夹角约45°，不同向。只核验给定实例，不等于一般证明。')
        delta={'content':answer};finish='stop'
    else:
        tools=([('hole',{'operation':'rational_identity','expressions':['(x*x-1)/(x-1)','x+1']}),
                ('product',{'operation':'rational_identity','expressions':['t*(1/t)','1']})]
               if rational else [('identity',{'operation':'polynomial_identity','expressions':['(a-b)**2','a*a+2*a*b+b*b']}),
                ('derivative',{'operation':'polynomial_derivative','expressions':['m*v*v/2+k*x*x/2','2*k*x'],'variable':'x'})]
               if polynomial else [('vectors',{'operation':'vectors','left':['1','0'],'right':['1','1']}),
                                   ('arithmetic',{'operation':'arithmetic','expressions':['0.1+0.2','1/3+1/6']})])
        delta={'tool_calls':[{'index':i,'id':'ui-math-'+kind,'type':'function','function':{'name':'sf_check_math','arguments':j(args)}} for i,(kind,args) in enumerate(tools)]};finish='tool_calls'
    return fixture.httpx.Response(200,text='data: '+j({'choices':[{'delta':delta,'finish_reason':finish}]})+'\n\ndata: [DONE]\n\n')


@fixture.server.app.get('/__math_test__/state')
def state():
    return {'calls':len(fixture.calls),'tools':many('SELECT tool,status,result_json FROM agent_tool_events'),
        'scores':many('SELECT * FROM mastery'),'exercises':many('SELECT id FROM exercise_sets')}


mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)
fixture.httpx.AsyncClient=lambda *a,**kw:fixture.original(transport=fixture.httpx.MockTransport(respond))
if __name__=='__main__':asyncio.run(fixture.main())
