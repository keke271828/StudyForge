"""An affine rewrite must not disappear because one convenient sample agrees."""
import asyncio
from fractions import Fraction
import json

import pytest

from studyforge import algebra_hints as hints
from studyforge.review import review_explanation
from studyforge.review_input import MARKER


COLLISION=r'$$a+b=b+a=2a+b-2$$'


@pytest.mark.parametrize('wrong',[
    '2a+b-2','a+2b-5','3a+2b-9','a+b+(a-2)/3','(a+b)/2+3.5','14-a-b',
])
def test_same_at_old_sample_still_produces_an_exact_distinguishing_instance(wrong):
    result=hints.candidates('$$a+b=b+a='+wrong+'$$')
    assert len(result)==1
    row=result[0];values={k:Fraction(v) for k,v in row['substitution'].items()}
    assert values==({'a':Fraction(2),'b':Fraction(6)} if wrong=='a+2b-5' else {'a':Fraction(3),'b':Fraction(5)})
    def evaluate(expression):
        return sum((number*(values[key] if key else 1) for key,number in hints.Parser(expression).parse().items()),Fraction())
    assert str(evaluate(row['left']))==row['left_value']
    assert str(evaluate(row['right']))==row['right_value']
    assert row['left_value']!=row['right_value']
    assert '额外条件' in row['scope']


def test_only_change_a_variable_that_actually_has_a_nonzero_difference():
    row=hints.candidates('$$a+b=b+a=a+2b-5$$')[0]
    assert row['substitution']=={'a':'2','b':'6'}
    assert row['left_value']=='8' and row['right_value']=='9'


def test_interval_and_rational_coefficients_are_exact_not_float_samples():
    rows=hints.candidates(r'$$\left(a,b\right)=\left(2a-2,b\right)$$')
    assert len(rows)==1 and rows[0]['component']==1 and rows[0]['components']==2
    assert rows[0]['left_value']=='3' and rows[0]['right_value']=='4'
    row=hints.candidates(r'$$a+b=b+a=a+b+\frac{a-2}{100000000000000000000}$$')[0]
    assert Fraction(row['right_value'])-Fraction(row['left_value'])==Fraction(1,10**20)


@pytest.mark.parametrize('body',[
    '$$a+b=b+a=a+b+(a-2)*0$$',
    '$$a+b=b+a$$',  # A scalar equation alone can be a condition, not a rewrite.
    '$$a=2a-2$$',
    '$$a+b=b+a=a+b+c$$',  # Preserve the existing same-variable restriction.
    r'$$\sin a=2a-2$$',
    '> $$a+b=b+a=2a+b-2$$',
    '```text\n'+COLLISION+'\n```',
])
def test_existing_unsupported_source_and_non_identity_boundaries_remain(body):
    assert hints.candidates(body)==[]


def test_non_colliding_existing_hint_keeps_identical_values_and_order():
    row=hints.candidates(r'$$\left(b-\frac{b-a}{2},b+\frac{b-a}{2}\right)=\left(\frac{a+b}{2},\frac{a+3b}{2}\right)$$')[0]
    assert row['substitution']=={'a':'2','b':'5'}
    assert row['component']==2 and (row['left_value'],row['right_value'])==('13/2','17/2')


def test_explicit_condition_is_not_overruled_by_the_substitution():
    draft='# 条件\n已知a=2。\n\n'+COLLISION+'\n\n## 系统性总结\n此处利用已知条件。'
    document,reports=hints.retain_hints(draft,[])
    assert '附加条件' in document and '学生答案错误' not in document
    assert reports[0]['passed'] is None
    assert document.endswith('此处利用已知条件。')


@pytest.mark.parametrize('fix',[False,True])
def test_existing_fast_request_receives_witness_and_retains_unresolved_warning(fix):
    calls=[]
    class Client:
        async def complete(self,system,user,**kwargs):
            data=json.loads(user.split(MARKER,1)[1]);calls.append(data)
            assert data['explanation_text']==COLLISION
            row=data['local_algebra_candidates'][0]
            assert row['substitution']=={'a':'3','b':'5'} and row['left_value']!=row['right_value']
            return json.dumps({'passed':not fix,'issues':([{'location':'计算','problem':'多出a-2，没有相应条件'}] if fix else []),
                'corrections':([{'issue_index':0,'before':'2a+b-2','after':'a+b'}] if fix else [])})
    output,reports=asyncio.run(review_explanation(Client(),'a,b是任意实数。',COLLISION,mode='fast'))
    assert len(calls)==1
    if fix:
        assert hints.candidates(output)==[] and reports[0]['locally_corrected_issues']==[0]
        assert '局部代数核对提示' not in output
    else:
        assert '局部代数核对提示' in output and reports[-1]['passed'] is None


@pytest.mark.parametrize('language',['zh','en','bilingual'])
def test_express_does_not_add_a_model_request_and_uses_existing_warning_language(language):
    class Client:
        async def complete(self,*args,**kwargs):pytest.fail('No new model request in express mode.')
    output,reports=asyncio.run(review_explanation(Client(),'任意a,b。',COLLISION,mode='express',output_language=language))
    assert '8 ≠ 9' in output and reports[-1]['stage']=='有限本机代数核对'
    assert ('Local algebra checks to confirm' in output)==(language!='zh')


def test_bounded_default_number_of_hints_and_deterministic_output():
    text='\n\n'.join(f'$$a+b=b+a={n}a+b-{2*(n-1)}$$' for n in range(2,30))
    result=hints.candidates(text)
    assert len(result)==6 and result==hints.candidates(text)


def test_a_family_of_distinct_affine_maps_that_all_agree_at_the_initial_sample():
    # Independently build 35 distinct lines through the same initial point.
    for a in range(-3,4):
        for b in range(-2,3):
            if (a,b)==(1,1):continue
            constant=7-2*a-5*b
            body=f'$$a+b=b+a=({a})a+({b})b+({constant})$$'
            if not a or not b:continue  # Preserve the same-variable boundary.
            rows=hints.candidates(body)
            assert len(rows)==1,body
            row=rows[0];x=Fraction(row['substitution']['a']);y=Fraction(row['substitution']['b'])
            assert x+y!=a*x+b*y+constant
            assert Fraction(row['left_value'])==x+y
            assert Fraction(row['right_value'])==a*x+b*y+constant


@pytest.mark.parametrize('mode,repair',[('express',False),('fast',False),('fast',True)])
def test_native_generation_exports_the_witness_or_the_actual_repair_without_extra_calls(tmp_path,monkeypatch,mode,repair):
    import httpx
    from docx import Document
    from lxml import etree
    from studyforge import ai,conversations,server
    from studyforge.db import create_job,create_project,execute,j,many,now,one,uid,unj
    ai.save_settings({'chat_provider':'deepseek','deepseek_model':'fixture-model','background_learning_enabled':False})
    project=create_project('代数偶合核对');chat=conversations.create(project['id'],'deepseek')
    path=tmp_path/'原资料.txt';path.write_text('a,b是任意实数。只使用加法交换律，不附加a=2的限制。',encoding='utf-8');sid=uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
        (sid,project['id'],path.name,'.txt',str(path),'ready',now()))
    draft='# 加法说明\n\n'+COLLISION+'\n\n## 系统性总结\n本段演示了加法的改写。'
    calls=[];original=httpx.AsyncClient
    def respond(request):
        body=json.loads(request.content);calls.append(body)
        if body.get('response_format',{}).get('type')=='json_object':
            data=json.loads(body['messages'][-1]['content'].split(MARKER,1)[1])
            assert data['explanation_text']==draft and data['local_algebra_candidates'][0]['substitution']=={'a':'3','b':'5'}
            answer=j({'passed':not repair,'issues':([{'location':'等式链','problem':'多出a-2'}] if repair else []),
                'corrections':([{'issue_index':0,'before':'2a+b-2','after':'a+b'}] if repair else [])})
        else:answer=draft
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(ai,'get_secret',lambda key:'controlled-only')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**k:original(transport=httpx.MockTransport(respond)))
    value=server.GenerateIn(project_id=project['id'],source_ids=[sid],conversation_id=chat['id'],provider='deepseek',
        model='fixture-model',format='docx',exercises=False,review_mode=mode)
    job=create_job(project['id'],'generate',value.model_dump());asyncio.run(server._generate_job(job,value))
    state=one('SELECT * FROM jobs WHERE id=?',(job,));assert state['status']=='completed',state['error']
    snapshot=one('SELECT * FROM document_snapshots WHERE job_id=?',(job,))
    artifact=one("SELECT * FROM artifacts WHERE project_id=? AND kind='explanation'",(project['id'],))
    word=Document(artifact['path']);text=''.join(etree.fromstring(word.part.blob).xpath('//*[local-name()="t"]/text()'))
    reports=unj(snapshot['metadata_json'])['reviews']
    assert len(calls)==(1 if mode=='express' else 2)
    if repair:
        assert '2a+b-2' not in snapshot['content'] and '局部代数核对提示' not in text
        assert reports[0]['locally_corrected_issues']==[0]
    else:
        assert '局部代数核对提示' in text and '8 ≠ 9' in text and reports[-1]['passed'] is None
    assert snapshot['content'].endswith('本段演示了加法的改写。')
    assert not many('SELECT * FROM mastery') and not many('SELECT * FROM exercise_sets')
