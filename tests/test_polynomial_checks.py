import asyncio
import json
from fractions import Fraction

import httpx
import pytest

from studyforge import ai
from studyforge.agent_tools import AgentRuntime,tool_specs
from studyforge.db import create_project,j,many
from studyforge.math_checks import check
from studyforge.polynomial_checks import Polynomials


def identity(left,right):return check('polynomial_identity',[left,right],[],[])
def derivative(text,variable,expected=None):
    return check('polynomial_derivative',[text]+([] if expected is None else [expected]),[],[],variable)


@pytest.mark.parametrize('left,right',[
    ('(a-b)**2','a*a-2*a*b+b*b'),
    ('A*(A*t*t+2*B*t+C)-(A*t+B)**2','A*C-B*B'),
    ('(x*y)**3','x**3*y**3'),
    ('(x+y)**2/2','x*x/2+x*y+y*y/2'),
    ('0.1*x+0.2*x','0.3*x'),
    ('(x-x+2)*y','2*y'),
    ('x/(y-y+2)','x/2'),
])
def test_exact_polynomial_identities_include_construction_step_and_decimal_coefficients(left,right):
    value=identity(left,right)
    assert value['results']['identical'] is True and value['results']['difference']=='0'
    assert value['meaning']=='formal_polynomial_algebra_not_complete_theorem'


def test_nonidentity_is_not_a_verdict_on_every_value_or_a_students_assumptions():
    value=identity('x*x','x')
    assert value['results']['identical'] is False
    algebra=Polynomials();difference=algebra.parse(value['results']['difference'])
    def evaluate(x):return sum(c*Fraction(x)**dict(m).get('x',0) for m,c in difference.items())
    assert evaluate(0)==evaluate(1)==0 and evaluate(2)!=0
    assert any('附加条件' in text for text in value['limitations'])


@pytest.mark.parametrize('text,variable,expected',[
    ('A*t**2+2*B*t+C','t','2*A*t+2*B'),
    ('m*v**2/2+k*x**2/2','v','m*v'),
    ('(x+y)**3','x','3*(x+y)**2'),
    ('x**3+2*x','x','3*x*x+2'),
    ('2/3','x','0'),
    ('x**3','z','0'),
    ('0.1*x+0.2*x','x','0.3'),
])
def test_formal_partial_derivative_keeps_other_variables_fixed(text,variable,expected):
    result=derivative(text,variable,expected)['results']
    assert result['matches'] is True and result['difference']=='0'
    assert identity(result['derivative'],expected)['results']['identical']


def test_a_computed_derivative_can_reject_a_wrong_candidate_without_inventing_a_theorem():
    value=derivative('x*x','x','x')
    assert value['results']['matches'] is False
    assert identity(value['results']['derivative'],'2*x')['results']['identical']
    assert 'theorem' in value['meaning']


def test_time_dependence_is_not_silently_assumed_for_independent_symbols():
    value=derivative('m*v*v/2+k*x*x/2','t','0')
    assert value['results']['matches'] is True
    assert any('链式法则' in line and '不自动' in line for line in value['limitations'])


def test_expansion_matches_independent_integer_evaluation_at_many_points():
    expression='(x-2*y)**4/3 + (x+y)*(2*x-y) - (x*x+y*y)/7'
    algebra=Polynomials();expanded=algebra.parse(expression)
    for x in range(-3,4):
        for y in range(-3,4):
            actual=sum(coef*Fraction(x)**dict(monomial).get('x',0)*Fraction(y)**dict(monomial).get('y',0)
                       for monomial,coef in expanded.items())
            expected=Fraction((x-2*y)**4,3)+(x+y)*(2*x-y)-Fraction(x*x+y*y,7)
            assert actual==expected


@pytest.mark.parametrize('expression',[
    'x/x','1/x','sqrt(x)','x**0','x**-1','x**0.5','x**9','x**True','x**x','x^2','x==x',
    'True','1/0','x/(x-x)','a+b+c+d+e+f+g','this_name_is_way_too_long',
    '(x+y+z+w)**8','(x**8)**4','((1e100)**8)**2','x.__class__','[x][0]','{x:1}','"x"',
])
def test_unsupported_domains_or_large_expansions_fail_instead_of_approximating(expression):
    with pytest.raises(ValueError):identity(expression,'0')


def test_code_and_file_effects_cannot_be_executed(tmp_path):
    target=tmp_path/'not-created'
    expression=f'__import__("pathlib").Path({str(target)!r}).write_text("bad")'
    with pytest.raises(ValueError):identity(expression,'0')
    assert not target.exists()


def test_argument_roles_and_size_are_explicit():
    for args in [
        ('polynomial_identity',['x'],[],[],None),('polynomial_identity',['x','x'],[],[],'x'),
        ('polynomial_derivative',['x'],[],[],None),('polynomial_derivative',['x','1','1'],[],[],'x'),
        ('polynomial_derivative',['x'],[],[],'x;bad'),('polynomial_identity',['x','x'],['1'],[],None),
        ('vectors',[],['1'],['2'],'x'),('arithmetic',['1'],[],[],'x'),
        ('polynomial_identity',['x+'*1000+'1','0'],[],[],None),
    ]:
        with pytest.raises(ValueError):check(*args)


def test_private_polynomial_values_and_symbols_do_not_enter_public_events():
    ai.save_settings({'agent_tools_enabled':True,'agent_permission_mode':'read_only'})
    runtime=AgentRuntime(create_project('私有多项式核对')['id'],private_context=True)
    value=asyncio.run(runtime.execute('sf_check_math',{'operation':'polynomial_identity',
        'expressions':['SecretTrial**2','SecretTrial*SecretTrial']}))
    assert value['results']['identical']
    error=asyncio.run(runtime.execute('sf_check_math',{'operation':'polynomial_derivative',
        'expressions':['SecretTrial**2'],'variable':'SecretTrialTooLong'}))
    assert 'error' in error and 'SecretTrial' not in j(error)
    assert 'SecretTrial' not in j(many('SELECT * FROM agent_tool_events'))
    assert many('SELECT * FROM artifacts')==many('SELECT * FROM mastery')==[]
    ai.save_settings({'agent_tools_enabled':False})
    assert '工具已关闭' in asyncio.run(runtime.execute('sf_check_math',{'operation':'polynomial_identity','expressions':['x','x']}))['error']


def test_native_symbolic_tool_roundtrip_and_codex_schema(monkeypatch):
    monkeypatch.setattr(ai,'get_secret',lambda name:'fixture-only')
    ai.save_settings({'agent_tools_enabled':True,'agent_permission_mode':'read_only'})
    runtime=AgentRuntime(create_project('实际工具协议')['id'])
    client=ai.DeepSeekClient('deepseek-flash',agent_runtime=runtime,effort='high');requests=[]
    def respond(request):
        body=json.loads(request.content);requests.append(body)
        if len(requests)==1:
            delta={'tool_calls':[{'index':0,'id':'poly','type':'function','function':{'name':'sf_check_math',
                'arguments':j({'operation':'polynomial_derivative','expressions':['A*t**2+2*B*t+C','2*A*t+2*B'],'variable':'t'})}}]}
            finish='tool_calls'
        else:
            value=json.loads(body['messages'][-1]['content']);assert value['results']['matches'] is True
            delta={'content':'形式导数相符；这一步只核对代数，极小值还需A>0等条件。'};finish='stop'
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':delta,'finish_reason':finish}]})+'\n\ndata: [DONE]\n\n')
    client._http=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    async def run():
        try:return [event async for event in client.agent_stream([{'role':'system','content':'学习导师'},{'role':'user','content':'核对导数。'}])]
        finally:await client.close()
    events=asyncio.run(run())
    assert len(requests)==2 and events[-1][0]=='final' and 'A>0' in events[-1][1]
    spec=next(t for t in tool_specs(codex=True) if t['name']=='sf_check_math')
    assert 'polynomial_derivative' in spec['inputSchema']['properties']['operation']['enum']
