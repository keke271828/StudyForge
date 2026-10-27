"""Middle-body context, bounded exact excerpts and summary workflow invariants."""
from hashlib import sha256

import pytest

from studyforge.summary_evidence import augment,paragraphs
from studyforge.teaching import summary_context


def chapters():
    return ['# 第一步\n\n'+('背景说明。'*6000)+'\n\n## 条件\n\n仅当参数q在(0,2)内时，本例的稳定结论才有保证。\n\n'+
        ('中间论证。'*6000)+'\n\n## 系统性总结\n迭代可以帮助说明稳定性。',
        '# 第二步\n\n'+('背景说明。'*6000)+'\n\n## 对象\n\n随机分配的是提醒，不是实际学习行为，不能把提醒效果当成行为本身的效果。\n\n'+
        ('中间论证。'*6000)+'\n\n## 系统性总结\n比较设计说明干预与结果的关系。']


def test_middle_conditions_fit_without_evicting_recaps_cautions_or_whole_chapters():
    values=chapters();base=summary_context(values)
    # Base may already include excerpts after integration; reconstruct the unchanged prefix.
    base=dict(base,text=base['text'].split('\n\n【辅助：',1)[0])
    base.pop('body_evidence',None);old=dict(base)
    result=augment(base,values,48000)
    assert '仅当参数q在(0,2)' in result['text'] and '随机分配的是提醒' in result['text']
    assert result['text'].startswith(base['text']) and len(result['text'])<=48000
    assert result['body_evidence']['chapters']==[1,2] and result['body_evidence']['included']==2
    for entry in result['body_evidence']['fragments']:
        exact=values[entry['chapter']-1][entry['start']:entry['end']]
        assert sha256(exact.encode()).hexdigest()==entry['sha256'] and exact in result['text']
    assert base['text']!=result['text'] and values==chapters() and base==old


@pytest.mark.parametrize('budget',[400,800,2000,6000,48000])
def test_budget_never_expands_and_old_scope_notice_remains(budget):
    values=chapters();base=summary_context(values,budget)
    result=augment(base,values,budget)
    assert len(result['text'])<=budget and result['text'].startswith(base['text'])
    assert result['omitted_chapters']==base['omitted_chapters'] and result['excerpted']==base['excerpted']


def test_full_text_and_omitted_chapter_plans_never_get_other_material():
    full=summary_context(['# 条件\n\n只有x>0才讨论此式。'])
    assert augment(full,['UNSELECTED'],48000)['text']==full['text']
    omitted={'text':'旧结构与节选。','excerpted':True,'omitted_chapters':1}
    result=augment(omitted,['仅当秘密条件成立。'],48000)
    assert result['text']==omitted['text'] and result['body_evidence']['reason']=='chapter_omissions'


def test_quotes_fenced_code_and_unclosed_math_are_not_promoted_to_body_evidence():
    value='# 解释\n\n> 只有QUOTED才成立。\n\n````python\n只有CODE才成立。\n```\n还在代码里。\n````\n\n'
    value+='真正条件：仅当x>0。\n\n$$\n\n\\forall x>0\n\n$$\n\n\\[\n只有UNCLOSED'
    blocks=list(paragraphs(value));joined='\n'.join(b['text'] for b in blocks)
    assert 'QUOTED' not in joined and 'CODE' not in joined and 'UNCLOSED' not in joined
    assert '$$\n\n\\forall x>0\n\n$$' in joined and '真正条件' in joined


def test_existing_caution_and_recap_are_not_copied_as_new_body_evidence():
    chapter='# 条件\n\n仅当x>0才有本式。\n\n## 待核实事项\n\n不能确认此结论。\n\n## 系统性总结\n\n只有x>0。'
    from studyforge.lesson_cautions import records
    base={'text':'章节小结。','excerpted':True,'omitted_chapters':0}
    result=augment(base,[chapter],6000,cautions=records([chapter]))
    assert '仅当x>0' in result['text'] and '不能确认' not in result['text'] and '只有x>0。' not in result['text']


def test_large_paragraph_is_not_cut_and_duplicate_pass_is_idempotent():
    values=['# 条件\n\n只有'+('很长的说明。'*500)+'才成立。\n\n仅当x>0才讨论。']
    plan={'text':'章节小结。','excerpted':True,'omitted_chapters':0}
    once=augment(plan,values,6000);twice=augment(once,values,6000)
    assert '很长的说明' not in once['text'] and '仅当x>0' in once['text'] and twice==once


def test_integrated_summary_plan_preserves_middle_body_without_mutating_a_prepared_plan():
    values=chapters();plan=summary_context(values)
    assert plan['body_evidence']['included']==2 and '仅当参数q在(0,2)' in plan['text']
    snapshot=repr(plan)
    import asyncio
    from studyforge.teaching import finish_explanation
    class Client:
        calls=0
        async def complete(self,system,user):
            self.calls+=1;assert user==plan['text'] and '随机分配的是提醒' in user
            return '## 系统性总结\n参数与分配对象的条件要保留。'
    client=Client();document='\n\n'.join(values)
    result=asyncio.run(finish_explanation(client,document,chapters=values,summary_plan=plan))
    assert client.calls==1 and result.startswith(document) and repr(plan)==snapshot


def test_a_reused_plan_cannot_silently_expand_a_new_smaller_budget():
    plan=summary_context(chapters())
    with pytest.raises(ValueError):augment(plan,chapters(),400)
