import asyncio
from fractions import Fraction
import json
from pathlib import Path

from docx import Document
import httpx
import pytest

from studyforge import ai, conversations, server
from studyforge.agent_tools import AgentRuntime, tool_specs
from studyforge.db import create_project, execute, j, many, now, one, uid
from studyforge.math_checks import check
from studyforge.polynomial_checks import Polynomials
from studyforge.rational_checks import RationalExpressions
from studyforge.review import review_explanation


def identity(left, right):
    return check('rational_identity', [left, right], [], [])


def evaluate(polynomial, **values):
    return sum(coef * _product(Fraction(values[name]) ** power for name, power in term)
               for term, coef in polynomial.items())


def _product(values):
    result = Fraction(1)
    for value in values:
        result *= value
    return result


def restrictions(result, side):
    return [Polynomials().parse(text) for text in result['results'][side]['nonzero_conditions']]


@pytest.mark.parametrize('left,right', [
    ('(x*x-1)/(x-1)', 'x+1'), ('x/x', '1'), ('0/x', '0'),
    ('(x/x)*0', '0'), ('1/(x/y)', 'y/x'), ('1/(1/x)', 'x'),
    ('x**-1', '1/x'), ('(x/y)**-2', 'y*y/(x*x)'),
    ('(x+1)/(2*x+2)', '1/2'), ('0.1*x/(0.2*x)', '1/2'),
    ('1/x+1/y', '(x+y)/(x*y)'), ('(x-y)/(x+y)', '(-x+y)/(-x-y)'),
])
def test_exact_common_domain_identity_does_not_remove_original_restrictions(left, right):
    value = identity(left, right)
    assert value['verified'] is True and value['results']['identical_on_common_domain'] is True
    assert value['results']['cross_product_difference'] == '0'
    assert value['meaning'] == 'rational_identity_on_common_domain_not_domain_equivalence'
    assert value['results']['common_domain_nonzero_conditions']


def test_cancelled_hole_is_kept_separately_from_unrestricted_right_side():
    result = identity('(x*x-1)/(x-1)', 'x+1')
    left = restrictions(result, 'left')
    assert len(left) == 1 and evaluate(left[0], x=1) == 0 and evaluate(left[0], x=2) != 0
    assert result['results']['right']['nonzero_conditions'] == []
    assert result['results']['domain_comparison'] == 'not_compared'
    assert any('不补定义断点' in line for line in result['limitations'])


@pytest.mark.parametrize('expression', ['x/x', '0/x', '(x/x)*0', '1/(1/x)'])
def test_zero_and_inverse_rewrites_retain_a_previously_required_nonzero_factor(expression):
    result = identity(expression, '1' if expression == 'x/x' else 'x' if expression == '1/(1/x)' else '0')
    conditions = restrictions(result, 'left')
    assert any(evaluate(p, x=0) == 0 for p in conditions)


def test_nested_division_keeps_domain_of_divisor_even_after_it_moves_to_numerator():
    result = identity('1/(x/y)', 'y/x')
    left, right = restrictions(result, 'left'), restrictions(result, 'right')
    assert len(left) == 2 and len(right) == 1
    assert any(evaluate(p, x=2, y=0) == 0 for p in left)
    assert all(evaluate(p, x=2, y=0) != 0 for p in right)


def test_unknown_domain_equality_is_not_reported_as_inequality():
    result = identity('(x*x+1)/(x*x+1)', '1')
    assert result['results']['identical_on_common_domain'] is True
    assert result['results']['domain_comparison'] == 'not_compared'
    assert any('不表示定义域不同' in line for line in result['limitations'])
    assert identity('1/(2*x)', '0.5/x')['results']['domain_comparison'] == 'same_explicit_restrictions'


def test_nonidentity_is_not_a_claim_of_inequality_at_every_point():
    value = identity('x/(x+1)', '1/2')
    assert value['results']['identical_on_common_domain'] is False
    difference = Polynomials().parse(value['results']['cross_product_difference'])
    assert evaluate(difference, x=1) == 0 and evaluate(difference, x=2) != 0
    assert any('附加条件' in text for text in value['limitations'])


def test_exact_nested_arithmetic_matches_independent_fraction_values():
    algebra = RationalExpressions()
    form = algebra.parse('(x/y + 1/(x-1))/(2*x-y)')
    for x in range(-3, 4):
        for y in range(-3, 4):
            if not y or x == 1 or 2*x == y:
                assert any(evaluate(p, x=x, y=y) == 0 for p in form.nonzero_conditions)
                continue
            assert all(evaluate(p, x=x, y=y) != 0 for p in form.nonzero_conditions)
            actual = evaluate(form.numerator, x=x, y=y) / evaluate(form.denominator, x=x, y=y)
            assert actual == (Fraction(x, y) + Fraction(1, x-1)) / (2*x-y)


@pytest.mark.parametrize('expression', [
    '1/0', '1/(x-x)', 'x**0', 'x**-9', 'x**9', 'x**0.5', 'x**(1+1)', 'x**True',
    'sqrt(x)', 'x^2', 'True', 'x.__class__', '[x][0]', '{x:1}', '"x"',
    'a+b+c+d+e+f+g', 'this_name_is_way_too_long', '(x+y+z+w)**8', '(x**8)**4',
    'x+'*1000+'1', '1/((x-x)/x)',
])
def test_unsupported_or_excessive_work_fails_without_domain_guessing(expression):
    with pytest.raises(ValueError):
        identity(expression, '0')


def test_no_code_execution_and_argument_roles_are_preserved(tmp_path):
    target = tmp_path / 'never-created'
    with pytest.raises(ValueError):
        identity(f'__import__("pathlib").Path({str(target)!r}).write_text("bad")', '0')
    assert not target.exists()
    for expressions, left, right, variable in [(['x'], [], [], None), (['x', 'x'], ['1'], [], None),
                                             (['x', 'x'], [], [], 'x')]:
        with pytest.raises(ValueError):
            check('rational_identity', expressions, left, right, variable)


def test_private_values_and_original_domain_restrictions_stay_out_of_public_events():
    ai.save_settings({'agent_tools_enabled': True, 'agent_permission_mode': 'read_only'})
    runtime = AgentRuntime(create_project('私有有理式')['id'], private_context=True)
    result = asyncio.run(runtime.execute('sf_check_math', {'operation': 'rational_identity',
        'expressions': ['SecretRoot/SecretRoot', '1']}))
    assert result['results']['identical_on_common_domain'] is True
    assert 'SecretRoot' in j(result['results']) and 'SecretRoot' not in j(many('SELECT * FROM agent_tool_events'))
    error = asyncio.run(runtime.execute('sf_check_math', {'operation': 'rational_identity',
        'expressions': ['SecretRootTooLongForInput/1', '0']}))
    assert 'error' in error and 'SecretRoot' not in j(error)
    assert many('SELECT * FROM mastery') == many('SELECT * FROM artifacts') == []
    ai.save_settings({'agent_tools_enabled': False})
    assert '工具已关闭' in asyncio.run(runtime.execute('sf_check_math', {'operation':'rational_identity', 'expressions':['1/x','1/x']}))['error']


def transport_reply(body, calls, answer):
    calls.append(body)
    if len(calls) == 1:
        assert any(t['function']['name'] == 'sf_check_math' for t in body['tools'])
        delta = {'tool_calls': [{'index': 0, 'id': 'rational-case', 'type': 'function',
            'function': {'name':'sf_check_math', 'arguments':j({'operation':'rational_identity',
                'expressions':['(x*x-1)/(x-1)','x+1']})}}]}
        finish = 'tool_calls'
    else:
        value = json.loads(body['messages'][-1]['content'])
        assert value['results']['identical_on_common_domain'] is True
        assert value['results']['left']['nonzero_conditions'] and not value['results']['right']['nonzero_conditions']
        delta, finish = {'content': answer}, 'stop'
    return httpx.Response(200, text='data: ' + j({'choices':[{'delta':delta,'finish_reason':finish}]})+'\n\ndata: [DONE]\n\n')


def test_actual_native_tool_roundtrip_and_codex_schema(monkeypatch):
    monkeypatch.setattr(ai, 'get_secret', lambda *a:'fixture-only')
    ai.save_settings({'agent_tools_enabled': True, 'agent_permission_mode': 'read_only'})
    runtime = AgentRuntime(create_project('有理式工具协议')['id'])
    client = ai.DeepSeekClient('deepseek-flash', agent_runtime=runtime, effort='high'); calls=[]
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: transport_reply(json.loads(r.content), calls,
        '约分只在 x 不等于1时成立；原函数在1处没有定义。')))
    async def run():
        try:
            return [row async for row in client.agent_stream([{'role':'system','content':'学习导师'}, {'role':'user','content':'核对约分的条件。'}])]
        finally:
            await client.close()
    events = asyncio.run(run())
    assert len(calls)==2 and events[-1][0]=='final' and '没有定义' in events[-1][1]
    spec=next(t for t in tool_specs(codex=True) if t['name']=='sf_check_math')
    assert 'rational_identity' in spec['inputSchema']['properties']['operation']['enum']


def test_private_native_fast_review_can_check_rational_conditions_without_publishing_them(monkeypatch):
    monkeypatch.setattr(ai,'get_secret',lambda *a:'fixture-only')
    ai.save_settings({'agent_tools_enabled':True,'agent_permission_mode':'read_only'})
    runtime=AgentRuntime(create_project('私有审查有理式')['id'],private_context=True)
    calls=[];native=httpx.AsyncClient
    def respond(request):
        body=json.loads(request.content);calls.append(body)
        if len(calls)==1:
            assert body['response_format']=={'type':'json_object'}
            delta={'tool_calls':[{'index':0,'id':'private-rational','type':'function','function':{
                'name':'sf_check_math','arguments':j({'operation':'rational_identity','expressions':['PrivateRoot/PrivateRoot','1']})}}]}
            finish='tool_calls'
        else:
            result=json.loads(body['messages'][-1]['content'])
            assert result['results']['identical_on_common_domain'] and 'PrivateRoot' in j(result['results']['left'])
            delta={'content':j({'passed':True,'issues':[]})};finish='stop'
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':delta,'finish_reason':finish}]})+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:native(transport=httpx.MockTransport(respond)))
    client=ai.DeepSeekClient('deepseek-flash',agent_runtime=runtime,effort='high')
    draft='在原分母非零时，给定商恒为1。'
    async def run():
        try:
            return await review_explanation(client,'给定原分母非零。',draft,mode='fast')
        finally:
            await client.close()
    final,reports=asyncio.run(run())
    assert final==draft and len(calls)==2 and len(reports)==1 and reports[0]['passed'] is True
    assert 'PrivateRoot' not in j(many('SELECT * FROM agent_tool_events'))
    assert many('SELECT * FROM mastery')==many('SELECT * FROM artifacts')==[]


def test_complete_docx_generation_can_use_rational_check_without_extra_fixed_review(tmp_path, monkeypatch):
    ai.save_settings({'agent_tools_enabled': True, 'agent_permission_mode':'read_only', 'background_learning_enabled':False})
    monkeypatch.setattr(ai, 'get_secret', lambda *a:'fixture-only')
    project = create_project('有理式完整交付'); chat=conversations.create(project['id'],'deepseek','deepseek-flash','high')
    path=tmp_path/'source.txt'; path.write_text('给定有理式 (x*x-1)/(x-1)，原分母要求x不等于1。',encoding='utf-8'); sid=uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
        (sid,project['id'],path.name,'.txt',str(path),'ready',now()))
    calls=[]; native=httpx.AsyncClient
    answer=('# 约分与定义域\n\n分子可分解为$(x-1)(x+1)$。约分后得到$x+1$，但不能在 x=1 处直接当作原函数值。'
            '[source.txt｜行1-1]\n\n## 系统性总结\n\n原式的限制 x 不等于1 仍须保留，另行补定义才得到延拓后的函数。')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:native(transport=httpx.MockTransport(lambda r:transport_reply(json.loads(r.content),calls,answer))))
    async def run():
        result=await server.generate(server.GenerateIn(project_id=project['id'],conversation_id=chat['id'],source_ids=[sid],
            provider='deepseek',model='deepseek-flash',reasoning_effort='high',review_mode='express',output_format='docx',
            instructions='请核对约分条件并讲清定义域，不出题。'))
        for _ in range(300):
            job=one('SELECT * FROM jobs WHERE id=?',(result['job_id'],))
            if job['status'] in ('completed','failed'):
                assert job['status']=='completed',job['error'];return
            await asyncio.sleep(.01)
        raise AssertionError('完整讲解任务未结束')
    asyncio.run(run())
    artifact=one("SELECT * FROM artifacts WHERE kind='explanation'")
    assert artifact and Path(artifact['path']).is_file() and len(calls)==2
    text='\n'.join(p.text for p in Document(artifact['path']).paragraphs)
    assert '不能在 x=1' in text and '系统性总结' in text
    assert many('SELECT * FROM exercise_sets') == many('SELECT * FROM mastery') == []
