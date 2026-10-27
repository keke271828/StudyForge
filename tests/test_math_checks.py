"""Arithmetic truth, vector counterexample, bounded inputs and agent wiring."""
import asyncio
import json

import httpx
import pytest

from studyforge import ai
from studyforge.agent_tools import AgentRuntime,tool_specs
from studyforge.db import create_project,j,many
from studyforge.math_checks import check,rational


@pytest.mark.parametrize('expression,expected',[
    ('0.1+0.2','3/10'),('1/3+1/6','1/2'),('2**-3','1/8'),
    ('-(2+3)*4','-20'),('1e-50*1e50','1'),('(-2)**2','4'),('-2**2','-4')])
def test_exact_arithmetic_without_binary_decimal_drift(expression,expected):
    assert str(rational(expression))==expected


def test_positive_dot_does_not_mean_same_direction():
    result=check('vectors',[],['1','0'],['1','1'])['results']
    assert result['dot_product']=='1' and result['gram_determinant']=='1'
    assert not result['same_direction'] and not result['linearly_dependent'] and result['angle_class']=='acute'
    assert result['angle_degrees_approx']==pytest.approx(45)


@pytest.mark.parametrize('left,right,same,opposite,kind',[
    (['1/2','1'],['1','2'],True,False,'zero'),(['1','2'],['-2','-4'],False,True,'straight'),
    (['1','0'],['-1','1'],False,False,'obtuse'),
    (['1','0'],['0','1'],False,False,'right'),(['0','0'],['1','1'],None,None,'undefined_zero_vector')])
def test_vector_direction_and_zero_angle_domains(left,right,same,opposite,kind):
    value=check('vectors',[],left,right)['results']
    assert value['same_direction'] is same and value['opposite_direction'] is opposite and value['angle_class']==kind
    if kind=='undefined_zero_vector':assert value['angle_degrees_approx'] is None and value['linearly_dependent']
    else:
        assert value['angle_domain_degrees']==[0,180]
        if kind in ('zero','straight'):assert value['angle_degrees_approx']==pytest.approx(0 if same else 180)


def test_large_exact_components_do_not_need_float_conversion_for_direction():
    value=check('vectors',[],['1e100**4','0'],['-(1e100**4)','0'])['results']
    assert value['opposite_direction'] and value['angle_class']=='straight'
    assert value['cosine_approx']==-1 and value['angle_degrees_approx']==180


@pytest.mark.parametrize('left,right',[
    (['1e100','1'],['1','0']),(['-1e100','1'],['1','0']),(['1e-100','1'],['1','0'])])
def test_rounded_angle_never_overrules_exact_direction(left,right):
    value=check('vectors',[],left,right)['results']
    assert value['angle_approx_resolution_limited'] and value['angle_warning']
    assert value['angle_class'] in ('acute','obtuse') and not value['same_direction'] and not value['opposite_direction']


@pytest.mark.parametrize('expression',[
    'True','sqrt(2)','x+1','0x10','1/0','0**-1','0**0','2**33','2**0.5',
    '1e101','9**9**9','[1,2][0]','sum([1,2])','1+'*200+'1'])
def test_unsupported_or_excessive_input_is_not_silently_approximated(expression):
    with pytest.raises(ValueError):rational(expression)


def test_text_is_never_executed(tmp_path):
    target=tmp_path/'should-not-exist'
    with pytest.raises(ValueError):rational(f'__import__("pathlib").Path({str(target)!r}).write_text("bad")')
    assert not target.exists()


def test_batch_and_dimension_constraints():
    assert check('arithmetic',['1/2','3*4'],[],[])['results'][1]['exact']=='12'
    for args in [('arithmetic',[],[],[]),('arithmetic',['1']*17,[],[]),('vectors',[],['1'],['1','2']),
                 ('vectors',[],['1']*33,['1']*33),('vectors',['1'],['1'],['2'])]:
        with pytest.raises(ValueError):check(*args)


def test_read_only_math_works_but_private_values_never_enter_public_tool_events():
    ai.save_settings({'agent_tools_enabled':True,'agent_permission_mode':'read_only'})
    runtime=AgentRuntime(create_project('数值核验')['id']);runtime.private_context=True
    value=asyncio.run(runtime.execute('sf_check_math',{'expressions':['34567+1']}))
    assert value['results'][0]['exact']=='34568' and value['meaning']=='numeric_case_not_general_proof'
    events=j(many('SELECT * FROM agent_tool_events'))
    assert '34567' not in events and '34568' not in events
    error=asyncio.run(runtime.execute('sf_check_math',{'expressions':[34567]}))
    assert 'error' in error and '34567' not in j(error)
    assert many('SELECT * FROM artifacts')==[] and many('SELECT * FROM mastery')==[]
    ai.save_settings({'agent_tools_enabled':False})
    assert '工具已关闭' in asyncio.run(runtime.execute('sf_check_math',{'expressions':['1+1']}))['error']


def test_native_model_tool_roundtrip_carries_exact_case_result(monkeypatch):
    monkeypatch.setattr(ai,'get_secret',lambda name:'fixture-only')
    ai.save_settings({'agent_tools_enabled':True,'agent_permission_mode':'read_only'})
    runtime=AgentRuntime(create_project('原生核验')['id']);client=ai.DeepSeekClient('deepseek-flash',effort='high',agent_runtime=runtime)
    requests=[]
    def respond(request):
        body=json.loads(request.content);requests.append(body)
        assert any(t['function']['name']=='sf_check_math' for t in body['tools'])
        if len(requests)==1:
            delta={'tool_calls':[{'index':0,'id':'math-case','type':'function','function':{'name':'sf_check_math',
                'arguments':j({'operation':'vectors','left':['1','0'],'right':['1','1']})}}]};finish='tool_calls'
        else:
            result=json.loads(body['messages'][-1]['content']);assert result['results']['same_direction'] is False
            delta={'content':'点积是1，但夹角45度，因此不是同向。这个反例不等于一般定理的证明。'};finish='stop'
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':delta,'finish_reason':finish}]})+'\n\ndata: [DONE]\n\n')
    client._http=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    async def run():
        try:return [e async for e in client.agent_stream([{'role':'system','content':'导师'},{'role':'user','content':'核验正点积是否一定同向。'}])]
        finally:await client.close()
    events=asyncio.run(run())
    assert len(requests)==2 and events[-1][0]=='final' and '45' in events[-1][1]
    assert any(t['name']=='sf_check_math' for t in tool_specs(codex=True))
