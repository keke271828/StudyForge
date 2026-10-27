"""The final audit must evaluate the lesson the student actually requested."""
import asyncio
import copy
import hashlib
import json

import pytest

from studyforge.ai import LEVEL_GUIDANCE
from studyforge.learning import learning_requirements
from studyforge.review import review_explanation


REQUEST = '只解释第一节为什么要用统一门槛；我已懂定义，不要重讲全章，也不要出题。'
PART = '当前为第2/3部分，只讲统一门槛；其他部分不是本章遗漏。'


def packet(user):
    marker = '本次讲解交付约束（由本次生成任务提供，不属于原资料）：\n'
    return json.JSONDecoder().raw_decode(user.split(marker, 1)[1])[0]


@pytest.mark.parametrize('mode,defect,requests', [
    ('express', False, 0), ('express', True, 0),
    ('fast', False, 1), ('fast', True, 1),
    ('balanced', False, 1), ('balanced', True, 2),
    ('strict', False, 3), ('strict', True, 7),
])
def test_every_audit_and_revision_keeps_requested_scope_without_extra_rounds(mode, defect, requests):
    class Client:
        def __init__(self): self.calls = []
        async def complete(self, system, user, json_mode=False):
            self.calls.append((system, user, json_mode))
            if json_mode:
                bad = defect and 'INITIAL_DRAFT' in user
                return json.dumps({'passed': not bad, 'issues': [
                    {'location': '第一节', 'problem': '遗漏统一门槛的适用条件。'}] if bad else []})
            return '# 修订\n统一门槛保证全部后续项，不重讲其他章节。\n\n## 系统性总结\n条件须同时成立。'
    client = Client()
    _, reports = asyncio.run(review_explanation(client, '第一节：统一门槛。第二节：其他主题。',
        'INITIAL_DRAFT', mode=mode, requirements=REQUEST, summary_level=1, section=PART))
    assert len(client.calls) == requests
    for _, user, _ in client.calls:
        scope = packet(user)
        assert scope == {'student_requirements': REQUEST, 'detail_guidance': LEVEL_GUIDANCE[1], 'current_part': PART}
    receipts = [r['teaching_scope'] for r in reports if 'teaching_scope' in r]
    assert len(receipts) == (requests if mode != 'strict' else requests - int(defect))
    for receipt in receipts:
        assert receipt['requirements_sha256'] == hashlib.sha256(REQUEST.encode()).hexdigest()
        assert receipt['part_sha256'] == hashlib.sha256(PART.encode()).hexdigest()
        assert receipt['summary_level'] == 1 and not receipt['history_reused']
        assert 'student_requirements' not in receipt, '审查小记录不重复保存学生聊天正文'


@pytest.mark.parametrize('inherited', ['same', 'none', 'changed'])
def test_history_is_only_deduplicated_on_the_actual_reviewer(inherited):
    history = [{'role': 'user', 'content': 'EARLIER_STUDENT_REQUEST：只讲第一节。'},
               {'role': 'assistant', 'content': 'EARLIER_AI_CLAIM：也许应该重讲全书。'}]
    requirements = learning_requirements(history, REQUEST)
    calls = []
    class Reviewer:
        def __init__(self):
            self.conversation = {'messages': copy.deepcopy(history)} if inherited != 'none' else None
            if inherited == 'changed': self.conversation['messages'][0]['content'] = 'CHANGED_REQUEST'
        async def complete(self, system, user, **kwargs):
            calls.append((copy.deepcopy(self.conversation), system, user))
            return '{"passed":true,"issues":[]}'
        async def close(self): pass
    class Parent:
        conversation = {'messages': history}
        def fork(self): return Reviewer()
    _, reports = asyncio.run(review_explanation(Parent(), '完整原文', '讲解', mode='strict',
        requirements=requirements, summary_level=2))
    assert len(calls) == 3
    for conversation, system, user in calls:
        sent = packet(user)['student_requirements']
        assert REQUEST in sent
        if inherited == 'same':
            assert 'EARLIER_STUDENT_REQUEST' not in sent
            assert conversation['messages'] == history
        else:
            assert 'EARLIER_STUDENT_REQUEST' in sent and 'EARLIER_AI_CLAIM' in sent
        assert ('独立审查员' in system) == (inherited == 'none')
    assert all(r['teaching_scope']['history_reused'] == (inherited == 'same') for r in reports)


def test_rewriter_uses_its_own_inherited_history_after_detached_audit():
    history = [{'role': 'user', 'content': 'ONLY_HERE：解释第一节的思路，不要讲第二节。'}]
    requirements = learning_requirements(history, REQUEST)
    calls = []
    class Reviewer:
        conversation = None
        async def complete(self, system, user, **kwargs):
            calls.append(('audit', user))
            return '{"passed":false,"issues":[{"location":"第一节","problem":"缺少必要条件"}]}'
        async def close(self): pass
    class Parent:
        conversation = {'messages': history}
        def fork(self): return Reviewer()
        async def complete(self, system, user, **kwargs):
            calls.append(('revision', user))
            return '# 第一节\n必要条件。\n\n## 系统性总结\n条件。'
    _, reports = asyncio.run(review_explanation(Parent(), '完整原文', '初稿', mode='balanced',
        requirements=requirements, summary_level=1))
    assert [kind for kind, _ in calls] == ['audit', 'revision']
    assert 'ONLY_HERE' in packet(calls[0][1])['student_requirements']
    assert 'ONLY_HERE' not in packet(calls[1][1])['student_requirements']
    assert [r['teaching_scope']['history_reused'] for r in reports] == [False, True]
