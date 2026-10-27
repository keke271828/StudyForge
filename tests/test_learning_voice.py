"""External teaching is context; only the learner's own words support a profile."""
import asyncio

import pytest

from studyforge import learning_memory as memory, learning_profile as profile
from studyforge.db import execute,j,many,one
from studyforge.learning_signals import learning_excerpt
from tests.test_learning_memory import chat_event


EXTERNAL='我认为高斯定律说明没有净电荷时电场一定为零。'
OWN='我不理解高斯定律里的净通量与局部电场有什么区别。'


@pytest.mark.parametrize('text',[
    '> '+EXTERNAL,
    '教材原文：\n'+EXTERNAL,
    'AI回答：'+EXTERNAL,
    '```text\n'+EXTERNAL+'\n```',
    '~~~python\n# '+EXTERNAL+'\n~~~',
    '导师说：“'+EXTERNAL+'”',
])
def test_explicit_external_material_alone_is_not_learner_evidence(text):
    assert learning_excerpt(text)==''


@pytest.mark.parametrize('prefix',['> '+EXTERNAL,'原题：\n'+EXTERNAL,'```\n'+EXTERNAL+'\n```'])
def test_explicit_question_outside_the_quotation_is_preserved_exactly(prefix):
    assert learning_excerpt(prefix+'\n\n我的问题：'+OWN)=='我的问题：'+OWN


@pytest.mark.parametrize('text',[
    '我的理解：'+EXTERNAL,
    '我的理解：\n> '+EXTERNAL,
    '我的推导：\n```text\n'+EXTERNAL+'\n```',
])
def test_explicitly_self_attributed_reasoning_stays_eligible(text):
    assert EXTERNAL in learning_excerpt(text)


def test_inline_source_quote_preserves_the_surrounding_question_and_term_quotes():
    text='教材说：“'+EXTERNAL+'”但我不理解为什么。'
    value=learning_excerpt(text)
    assert EXTERNAL not in value and '我不理解为什么' in value
    assert '我不懂“高斯定律”是什么。'==learning_excerpt('我不懂“高斯定律”是什么。')


def test_unclosed_external_block_cannot_swallow_its_way_into_the_profile():
    assert not learning_excerpt('```\n'+EXTERNAL+'\n'+OWN)


def test_own_code_can_follow_a_blank_line_but_later_external_quote_stays_external():
    own='我认为代码里的加法循环应该从0开始。'
    text='下面是我的代码：\n\n```python\n# '+own+'\n```\n\n> '+EXTERNAL
    value=learning_excerpt(text)
    assert own in value and EXTERNAL not in value
    text='我的理解：'+own+'\n\n> '+EXTERNAL
    assert own in learning_excerpt(text) and EXTERNAL not in learning_excerpt(text)


def test_inline_textbook_label_does_not_hide_the_students_same_line_question():
    text='教材原文：“'+EXTERNAL+'”我的问题：'+OWN
    assert EXTERNAL not in learning_excerpt(text) and OWN in learning_excerpt(text)


def test_short_nested_fence_does_not_close_a_long_external_fence():
    assert not learning_excerpt('````text\n```\n'+EXTERNAL+'\n````')


def test_labeled_source_can_have_multiple_paragraphs_before_explicit_own_question():
    text='教材原文：\n'+EXTERNAL+'\n\n'+EXTERNAL+'\n\n我的问题：'+OWN
    assert learning_excerpt(text)=='我的问题：'+OWN


def insight(event,quote,topic='高斯定律'):
    return {'event_id':event,'kind':'gap','dimension':'concepts','quote':quote,'topic':topic,
        'observation':'本次知识疑问，理解程度待核对。','anchors':[topic]}


def test_second_gate_rejects_a_source_quote_even_when_the_event_has_real_learning():
    text='> '+EXTERNAL+'\n\n我的问题：'+OWN
    event={'id':1,'kind':'chat','payload':{'student_text':text,'mentor_context':''}}
    proposed={'insights':[insight(1,EXTERNAL),insight(1,OWN)]}
    rows=memory.validate_insights(proposed,[event])
    assert [row['quote'] for row in rows]==[OWN]


def test_native_discussion_keeps_only_the_users_question_and_does_not_score():
    event,_,chat,message=chat_event('> '+EXTERNAL+'\n\n我的问题：'+OWN)
    assert event and EXTERNAL not in event['payload_json'] and OWN in event['payload_json']
    before=many('SELECT * FROM mastery');memory.discussion_completed(chat,message)
    assert many('SELECT * FROM mastery')==before==[] and len(many('SELECT * FROM learning_events'))==1


def test_raw_original_message_protects_old_payloads_that_lost_quote_markers():
    event,_,chat,message=chat_event('> '+EXTERNAL+'\n\n我的问题：'+OWN)
    # Simulate the old extractor having discarded structural markers.
    payload={'message_id':message,'student_text':EXTERNAL+'\n'+OWN,'mentor_context':''}
    event['payload']=payload
    assert not memory.validate_insights({'insights':[insight(event['id'],EXTERNAL)]},[event])


def test_legacy_mixed_event_filters_only_the_external_insight_and_is_reversible():
    event,_,chat,message=chat_event('> '+EXTERNAL+'\n\n我的问题：'+OWN)
    memory._save_insight(event['id'],'旧错误记录','gap','concepts','误把引用当成学生观点。',EXTERNAL,'暂定')
    memory._save_insight(event['id'],'高斯定律','gap','concepts','真实疑问保留。',OWN,'暂定')
    execute('INSERT OR REPLACE INTO learning_event_filters VALUES (?,1,1)',(event['id'],))
    original=many('SELECT * FROM learning_insights');messages=many('SELECT * FROM messages')
    active=profile.list_insights()['insights']
    assert [x['topic'] for x in active]==['高斯定律']
    removed=profile.list_insights(status='removed')['insights'];assert len(removed)==1
    assert removed[0]['topic']=='旧错误记录' and removed[0]['quote']==EXTERNAL
    evidence=profile.insight_evidence(removed[0]['id'])
    assert evidence['insight']['external_evidence'] and '明确引用' in evidence['notice']
    assert many('SELECT * FROM learning_insights')==original and many('SELECT * FROM messages')==messages
    restored=profile.change_insight(removed[0]['id'],0,deleted=False)
    assert not restored['deleted'] and len(profile.list_insights()['insights'])==2
    assert many('SELECT * FROM mastery')==[]


def test_old_pure_quote_event_uses_original_message_without_deleting_history():
    event,_,chat,message=chat_event(OWN)
    execute('UPDATE messages SET content=? WHERE id=?',('> '+EXTERNAL,message))
    payload={'message_id':message,'student_text':EXTERNAL,'mentor_context':''}
    execute('UPDATE learning_events SET payload_json=? WHERE id=?',(j(payload),event['id']))
    execute('INSERT OR REPLACE INTO learning_event_filters VALUES (?,1,1)',(event['id'],))
    memory._save_insight(event['id'],'高斯定律','gap','concepts','错误引用判断',EXTERNAL,'暂定')
    assert profile.list_insights()['insights']==[]
    assert len(profile.list_insights(status='removed')['insights'])==1
    assert one('SELECT content FROM messages WHERE id=?',(message,))['content']=='> '+EXTERNAL
    assert one('SELECT policy_version FROM learning_event_filters')['policy_version']==2


def test_background_packet_and_commit_reject_external_claim_without_extra_model_calls():
    event,_,chat,message=chat_event('> '+EXTERNAL+'\n\n我的问题：'+OWN)
    payload={'message_id':message,'student_text':EXTERNAL+'\n'+OWN,'mentor_context':''}
    execute('UPDATE learning_events SET payload_json=? WHERE id=?',(j(payload),event['id']))
    calls=[]
    class Model:
        async def complete(self,system,user,**kwargs):
            calls.append(user)
            assert EXTERNAL not in user and OWN in user
            return j({'insights':[insight(event['id'],EXTERNAL),insight(event['id'],OWN)]})
        async def close(self):pass
    assert asyncio.run(memory.MemoryWorker(lambda _:Model()).run_once(ignore_idle=True))
    assert len(calls)==1
    assert [x['quote'] for x in many('SELECT * FROM learning_insights')]==[OWN]
    assert many('SELECT * FROM mastery')==[]


def test_explanation_and_exercise_design_receive_only_current_valid_profile(monkeypatch):
    from studyforge import exercises
    from studyforge.ai import generate_explanation
    event,_,chat,message=chat_event('> '+EXTERNAL+'\n\n我的问题：'+OWN)
    memory._save_insight(event['id'],'引用造成的误判','gap','concepts','COPIED_CLAIM_NO_TEACHING',EXTERNAL,'暂定',anchors=['高斯定律'])
    memory._save_insight(event['id'],'高斯定律','gap','concepts','OWN_QUESTION：需要分清整体与局部。',OWN,'暂定',anchors=['高斯定律'])
    calls=[]
    class Model:
        async def complete(self,system,user,**kwargs):
            calls.append((system,user))
            if '严谨的习题设计者' in system:
                return j({'questions':[{'question':'给定均匀场，解释整体净通量与局部场的区别。','solution':'参考解','rubric':'理由100分','topic':'高斯定律','source_url':''}]})
            if '独立解题员' in system:return j({'answers':[{'index':0,'solution':'独立解','issues':[]}]})
            if '习题审查员' in system:return j({'passed':True,'issues':[]})
            return '## 高斯定律\n整体净通量不直接决定局部场。\n\n## 系统性总结\n分清两个对象。'
    monkeypatch.setattr(exercises,'search_exercises',lambda _:asyncio.sleep(0,result=[]))
    async def scenario():
        client=Model()
        await generate_explanation(client,'高斯定律：整体有符号求和。',3,[],requirements='解释整体与局部。')
        project=one('SELECT project_id FROM conversations WHERE id=?',(chat,))['project_id']
        ident,_=await exercises.generate_set(client,project,[],'高斯定律：整体有符号求和。','概念检查')
        assert 'solutions' not in exercises.public_set(ident,reveal=True)
    asyncio.run(scenario())
    assert len(calls)==5
    for system,user in (calls[0],calls[1]):
        assert 'OWN_QUESTION' in user and 'COPIED_CLAIM_NO_TEACHING' not in system+user
    assert many('SELECT * FROM mastery')==[] and many('SELECT * FROM submissions')==[]
