import asyncio
import json

import httpx
import pytest

from studyforge import ai
from studyforge.algebra_hints import candidates, retain_hints
from studyforge.db import j
from studyforge.review import review_explanation
from studyforge.teaching import finish_explanation


WRONG = r'''# 邻域与中点
\[
(b-\varepsilon,b+\varepsilon)
=
\left(b-\frac{b-a}{2},\ b+\frac{b-a}{2}\right)
=
\left(\frac{a+b}{2},\ \frac{a+3b}{2}\right).
\]
## 系统性总结
统一阈值后，两个开邻域互不相交。
'''


def test_actual_observed_interval_rewrite_has_exact_counterexample():
    hints=candidates(WRONG)
    assert len(hints)==1
    hint=hints[0]
    assert hint['substitution']=={'a':'2','b':'5'}
    assert hint['left_value']=='13/2' and hint['right_value']=='17/2'
    assert hint['component']==2 and hint['components']==2
    assert '额外条件' in hint['scope']


def test_correct_endpoints_and_rational_linear_identities_have_no_hint():
    fixed=WRONG.replace(r'\frac{a+3b}{2}',r'\frac{3b-a}{2}')
    assert candidates(fixed)==[]
    assert candidates('$$a+a=2a=\\frac{4a}{2}$$')==[]


def test_two_endpoint_rewrite_and_latex_spacing_are_checked_without_an_extra_chain():
    wrong = r'$$\left(b-\frac{b-a}{2},\ b+\frac{b-a}{2}\right)=\left(\frac{a+b}{2},\ \frac{a+3b}{2}\right).$$'
    hints = candidates(wrong)
    assert len(hints) == 1 and hints[0]['component'] == 2
    assert hints[0]['left_value'] == '13/2' and hints[0]['right_value'] == '17/2'
    assert candidates(wrong.replace(r'\frac{a+3b}{2}', r'\frac{3b-a}{2}')) == []


@pytest.mark.parametrize('body',[
    '$$x=2a$$',  # a definition/solution is not an unconditional identity
    r'$$\sin x=2x=x+x$$',
    r'$$\frac{x}{y}=1=2$$',  # unsupported division must not hide a known numeric mistake
    r'$$a^2=2a=a+a$$',
    r'$$\int_0^1x\,dx=\frac12=0.5$$',
])
def test_unsupported_or_non_identity_math_is_not_claimed_verified(body):
    result=candidates(body)
    if body==r'$$\frac{x}{y}=1=2$$':assert result[0]['left_value']=='1' and result[0]['right_value']=='2'
    else:assert result==[]


def test_conditional_identity_is_only_a_contextual_hint_never_a_wrong_answer_verdict():
    body='# 条件\n已知 a+b=0。\n$$a+b=b+a=2a+2b$$\n## 系统性总结\n在所述条件下成立。'
    document,reports=retain_hints(body,[])
    assert reports[0]['passed'] is None and '附加条件' in document
    assert '学生答案错误' not in document
    assert document.endswith('在所述条件下成立。')


def test_source_quotes_and_code_are_preserved_without_becoming_ai_rewrite_hints():
    quoted='> $$1+1=2=3$$\n\n```python\n1+1=2=3\n```\n\n普通解释。'
    assert candidates(quoted)==[]
    assert retain_hints(quoted,[])==(quoted,[])


def test_bounded_closed_grammar_never_executes_text(tmp_path):
    marker=tmp_path/'should-not-exist'
    poisoned=f'$$__import__("pathlib").Path("{marker}").write_text("bad")=1=2$$'
    hints=candidates(poisoned)
    assert not marker.exists()
    assert all(hint['left']=='1' and hint['right']=='2' for hint in hints)
    assert candidates('$$'+'{'*300+'a'+'}'*300+'=a=a$$')==[]
    assert len(candidates('\n\n'.join('$$1+1=2='+str(i)+'$$' for i in range(3,40))))<=6


@pytest.mark.parametrize('language,heading',[('zh','局部代数核对提示'),('en','Local algebra checks to confirm'),
                                            ('bilingual','Local algebra checks to confirm')])
def test_express_mode_gives_visible_hints_without_another_model_call(language,heading):
    class Client:
        async def complete(self,*a,**kw):pytest.fail('Express must not create another review request')
    document,reports=asyncio.run(review_explanation(Client(),'原资料',WRONG,mode='express',output_language=language))
    assert heading in document
    assert document.rstrip().endswith('统一阈值后，两个开邻域互不相交。')
    assert reports[-1]['stage']=='有限本机代数核对' and reports[-1]['passed'] is None


def native(monkeypatch,response):
    monkeypatch.setattr(ai,'get_secret',lambda key:'fixture-only')
    client=ai.DeepSeekClient('deepseek-flash',effort='high');calls=[]
    def respond(request):
        body=json.loads(request.content);calls.append(body)
        packet=response(body)
        return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':j(packet)},'finish_reason':'stop'}]})
    client._http=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(client,'fork',lambda:client)
    return client,calls


def test_fast_false_positive_keeps_warning_and_sends_hint_in_the_existing_native_request(monkeypatch):
    client,calls=native(monkeypatch,lambda body:{'passed':True,'issues':[]})
    async def run():
        try:return await review_explanation(client,'本题极限定义对任意正ε成立。',WRONG,mode='fast')
        finally:await client.close()
    document,reports=asyncio.run(run())
    assert len(calls)==1 and calls[0]['model']=='deepseek-flash'
    request=calls[0]['messages'][-1]['content']
    assert '本题极限定义对任意正ε成立' in request and '13/2' in request and '17/2' in request
    assert '局部代数核对提示' in document and r'\frac{a+3b}{2}' in document
    assert reports[0]['passed'] is True and reports[-1]['passed'] is None
    assert reports[0]['local_algebra_candidates'][0]['component']==2


def test_fast_local_repair_removes_the_candidate_without_extra_review(monkeypatch):
    def reply(body):
        return {'passed':False,'issues':[{'location':'邻域右端点','problem':'a的符号错误','evidence':'b+(b-a)/2=(3b-a)/2'}],
                'corrections':[{'issue_index':0,'before':r'\frac{a+3b}{2}','after':r'\frac{3b-a}{2}'}]}
    client,calls=native(monkeypatch,reply)
    async def run():
        try:return await review_explanation(client,'原资料',WRONG,mode='fast')
        finally:await client.close()
    document,reports=asyncio.run(run())
    assert len(calls)==1 and candidates(document)==[]
    assert '局部代数核对提示' not in document and reports[0]['locally_corrected_issues']==[0]


def test_summary_generation_is_also_checked_and_warning_is_not_duplicated():
    class Client:
        async def complete(self,*a,**kw):return '## 系统性总结\n$$1+1=2=3$$\n总结结束。'
    async def run():
        document=await finish_explanation(Client(),'# 讲解\n完整正文。')
        return await finish_explanation(Client(),document)
    document=asyncio.run(run())
    assert document.count('## 局部代数核对提示')==1 and document.endswith('总结结束。')
    assert '完整正文。' in document and '$$1+1=2=3$$' in document


def test_real_word_export_preserves_the_warning_and_closing_summary():
    from docx import Document
    from studyforge.exporters import export_document
    document,_=retain_hints(WRONG,[])
    path=export_document(document,'docx','邻域核对','algebra-hints.docx')
    paragraphs=[item.text for item in Document(path).paragraphs]
    assert any('13/2' in item and '17/2' in item for item in paragraphs)
    assert any('局部代数核对提示' in item for item in paragraphs)
    assert paragraphs[-1]=='统一阈值后，两个开邻域互不相交。'
