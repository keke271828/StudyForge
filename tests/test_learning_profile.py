import asyncio

import pytest
from fastapi.testclient import TestClient

from studyforge import learning_memory as memory, learning_profile as profile, server
from studyforge.ai import generate_explanation
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid, update_mastery


def chat_insight(topic='柯西不等式', observation='构造动机需要进一步解释。'):
    project = create_project('数学学习')
    conversation, message = uid(), uid()
    text = '我已经理解柯西不等式的计算，但还不明白辅助函数的构造动机。'
    execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)',
            (conversation, project['id'], 'deepseek', None, now(), '[]', 'test-model', None))
    execute('INSERT INTO messages VALUES (?,?,?,?,?)', (message, conversation, 'user', text, now()))
    memory.discussion_completed(conversation, message)
    event = one('SELECT * FROM learning_events ORDER BY id DESC LIMIT 1')
    memory._save_insight(event['id'], topic, 'gap', 'reasoning', observation, '辅助函数的构造动机', '暂定')
    return one('SELECT * FROM learning_insights ORDER BY id DESC LIMIT 1'), project, conversation


def score_record(key, score, kind='做题', topic='柯西不等式', difficulty=None):
    if kind == '自评':
        update_mastery(topic, self_rating=score, difficulty_rating=difficulty)
    elif kind == '费曼讲解':
        update_mastery(topic, feynman=score)
    elif score is not None:
        update_mastery(topic, quiz=score)
    memory.assessment_record(key, topic, kind, score, '学生实际提交的答案片段', '原评分反馈', difficulty_rating=difficulty)
    return one('SELECT * FROM learning_insights ORDER BY id DESC LIMIT 1')


def test_correction_keeps_original_evidence_marks_self_report_and_retrieves_cross_project():
    insight, _, _ = chat_insight()
    changed = profile.change_insight(insight['id'], 0, correction='我现在已理解构造，请集中讲解适用边界。')
    create_project('另一个学习项目')
    context = memory.profile_context('柯西不等式')
    assert '我现在已理解构造' in context and '构造动机需要进一步解释。' not in context
    assert '用户纠正（未验证）' in context and '不验证用户纠正' in context
    assert changed['version'] == 1 and changed['quote'] == insight['quote']
    assert one('SELECT * FROM learning_insights')['observation'] == insight['observation']
    assert many('SELECT * FROM mastery') == []
    evidence = profile.insight_evidence(insight['id'])
    assert evidence['insight']['original_observation'] == insight['observation']
    assert '还不明白辅助函数' in evidence['evidence_text']
    restored = profile.change_insight(insight['id'], 1, correction=None)
    assert restored['confidence'] == '暂定' and restored['observation'] == insight['observation']


def test_removal_stops_retrieval_and_same_event_callbacks_with_changed_topic():
    insight, _, _ = chat_insight()
    memory._save_insight(insight['event_id'], '教学偏好', 'preference', '', '喜欢例子。', '喜欢例子', '暂定')
    profile.change_insight(insight['id'], 0, deleted=True)
    memory._save_insight(insight['event_id'], '重新命名后的柯西判断', 'gap', 'reasoning', '旧判断复活', '构造动机', '暂定')
    assert '构造动机需要进一步解释。' not in memory.profile_context('柯西不等式')
    assert '喜欢例子' in memory.profile_context('柯西不等式')  # Another judgment is not removed implicitly.
    assert len(many('SELECT * FROM learning_insights')) == 2
    assert memory.memory_snapshot()['pending'] == 0
    assert not asyncio.run(memory.MemoryWorker(lambda _: pytest.fail('同证据应停止后台调用')).run_once(ignore_idle=True))
    assert profile.list_insights(status='removed')['insights'][0]['id'] == insight['id']
    profile.change_insight(insight['id'], 1, deleted=False)
    assert '构造动机需要进一步解释。' in memory.profile_context('柯西不等式')


def test_inflight_background_cannot_reintroduce_removed_evidence():
    insight, _, _ = chat_insight()
    class Inflight:
        async def complete(self, *args, **kwargs):
            profile.change_insight(insight['id'], 0, deleted=True)
            return j({'insights': [{'event_id': insight['event_id'], 'topic': '新的标题', 'kind': 'gap',
                'dimension': 'concepts', 'observation': '不应复活', 'quote': '辅助函数的构造动机', 'anchors': ['辅助函数']}]})
        async def close(self): pass
    assert asyncio.run(memory.MemoryWorker(lambda _: Inflight()).run_once(ignore_idle=True))
    assert memory.memory_snapshot()['total_insights'] == 0
    assert len(many('SELECT * FROM learning_insights')) == 1


def test_conflicts_not_silently_overwritten_and_removed_cannot_be_corrected():
    insight, _, _ = chat_insight()
    profile.change_insight(insight['id'], 0, correction='新判断')
    with pytest.raises(profile.ProfileConflict): profile.change_insight(insight['id'], 0, correction='覆盖新判断')
    profile.change_insight(insight['id'], 1, deleted=True)
    with pytest.raises(profile.ProfileConflict): profile.change_insight(insight['id'], 2, correction='复活')
    assert profile.insight_evidence(insight['id'])['insight']['correction'] == '新判断'


@pytest.mark.parametrize('correction', [' ', 'x' * 1001])
def test_invalid_corrections_are_atomic(correction):
    insight, _, _ = chat_insight()
    with pytest.raises(ValueError): profile.change_insight(insight['id'], 0, correction=correction)
    assert many('SELECT * FROM learning_insight_controls') == []
    assert many('SELECT * FROM learning_event_profile_blocks') == []


def test_search_pagination_and_categories_include_old_evidence_not_just_latest_100():
    insight, _, _ = chat_insight()
    for index in range(135):
        memory._save_insight(insight['event_id'], f'无关资料{index}', 'exposure', '', '已导入', '资料片段', '接触记录')
    score_record('self', 90, '自评', topic='哲学')
    score_record('quiz', 80)
    assert profile.list_insights(search='柯西不等式')['filtered_count'] == 2
    assert profile.list_insights(category='self_report')['filtered_count'] == 1
    assert profile.list_insights(category='assessment')['filtered_count'] == 1
    assert profile.list_insights(category='chat')['filtered_count'] == 1
    first = profile.list_insights(limit=30)
    second = profile.list_insights(limit=30, offset=30)
    assert first['filtered_count'] == 138 and len(second['insights']) == 30
    assert not ({x['id'] for x in first['insights']} & {x['id'] for x in second['insights']})
    assert profile.list_insights(search="%' OR 1=1 --")['insights'] == []


def test_scores_recomputed_after_removal_self_report_never_raises_score():
    score_record('low', 50)
    high = score_record('high', 100)
    self_report = score_record('self', 100, '自评', difficulty=80)
    assert profile.effective_profile()[0]['score'] == 65
    original_mastery = one('SELECT * FROM mastery')
    profile.change_insight(high['id'], 0, deleted=True)
    row = profile.effective_profile()[0]
    assert row['score'] == 50 and row['assessment_count'] == 1 and row['self_rating'] == 100
    assert one('SELECT * FROM mastery') == original_mastery
    profile.change_insight(self_report['id'], 0, deleted=True)
    assert profile.effective_profile()[0]['difficulty_rating'] is None
    assert profile.effective_profile()[0]['self_rating'] is None
    profile.change_insight(high['id'], 1, deleted=False)
    assert profile.effective_profile()[0]['score'] == 65


def test_removed_all_scores_do_not_leak_via_legacy_aggregate_or_duplicate_callback():
    score = score_record('quiz', 99)
    profile.change_insight(score['id'], 0, deleted=True)
    memory.assessment_record('quiz', '柯西不等式', '做题', 99, '旧作答', '')
    assert one('SELECT * FROM mastery')['score'] == 99
    assert profile.effective_profile() == []
    assert server.profile_difficulty('柯西不等式', profile.effective_profile()) == 2
    context = memory.profile_context('柯西不等式')
    assert '历史对话' in context and '不作为当前画像' in context and '99' not in context
    fresh = score_record('new-quiz', 40)
    assert profile.effective_profile()[0]['score'] == 40 and fresh['event_id'] != score['event_id']


def test_self_report_only_static_review_and_legacy_scores_have_explicit_limits():
    score_record('self', 100, '自评', '哲学', difficulty=20)
    row = profile.effective_profile()[0]
    assert row['score'] is None and row['score_basis'] == 'self_report_only'
    assert server.profile_difficulty('哲学', [row]) == 2
    assert one('SELECT * FROM mastery')['score'] == 0  # Never used as an objective zero.
    score_record('static', None, '编程作业', '算法')
    static = next(x for x in profile.effective_profile() if x['topic'] == '算法')
    assert static['score'] is None and static['assessment_count'] == 0 and static['score_basis'] == 'unscored'
    update_mastery('旧物理知识', quiz=80, self_rating=100)
    legacy = next(x for x in profile.effective_profile() if x['topic'] == '旧物理知识')
    assert legacy['score'] == 80 and legacy['score_basis'] == 'legacy_summary' and legacy['assessment_count'] is None
    revision = profile.profile_revision()
    profile.change_legacy_profile('旧物理知识', True)
    assert all(x['topic'] != '旧物理知识' for x in profile.effective_profile())
    assert profile.profile_revision() != revision
    profile.change_legacy_profile('旧物理知识', False)
    assert next(x for x in profile.effective_profile() if x['topic'] == '旧物理知识')['score'] == 80


def test_evidence_api_whitelists_student_text_not_hidden_solutions_or_mentor_tools():
    event = memory.record_event('private', '做题', {'topic': '论证', 'score': 80, 'student_text': '学生论证',
        'solutions': 'hidden reference', 'mentor_context': 'hidden assistant', 'rubric': 'hidden rubric', 'tools': 'hidden tools'}, analyzed=True)
    memory._save_insight(event, '论证', 'assessment', 'reasoning', '原作答反馈', '学生论证', '评估记录')
    insight = one('SELECT * FROM learning_insights')
    client = TestClient(server.app)
    response = client.get(f"/api/profile/insights/{insight['id']}/evidence")
    assert response.status_code == 200 and response.json()['recorded_score'] == 80
    assert 'hidden' not in response.text and 'payload_json' not in response.text


def test_evidence_shows_original_full_user_message_with_visible_display_limit():
    insight, _, conversation = chat_insight()
    execute("UPDATE messages SET content=? WHERE conversation_id=? AND role='user'", ('长消息' * 10000, conversation))
    evidence = profile.insight_evidence(insight['id'])
    assert evidence['truncated'] and len(evidence['evidence_text']) == 24000


def test_api_validation_edit_remove_restore_and_ratings():
    insight, _, _ = chat_insight()
    client = TestClient(server.app); path = f"/api/profile/insights/{insight['id']}"
    assert client.patch(path, json={'version': 0, 'correction': '纠正后的判断'}).status_code == 200
    assert client.patch(path, json={'version': 0, 'correction': '旧页面覆盖'}).status_code == 409
    assert client.delete(path+'?version=1').status_code == 200
    assert client.get('/api/profile/memory').json()['total_insights'] == 0
    assert client.post(path+'/restore', json={'version': 2}).status_code == 200
    assert client.patch(path, json={'version': True, 'correction': '错误'}).status_code == 422
    assert client.patch(path, json={'version': 3, 'correction': ' '}).status_code == 400
    assert client.get('/api/profile/insights/999/evidence').status_code == 404
    assert client.get('/api/profile/memory?category=other').status_code == 422
    assert client.get('/api/profile/memory?limit=101').status_code == 422
    assert client.post('/api/profile/rating', json={'topic': '哲学', 'rating': 100, 'difficulty_rating': 20}).json()['score'] is None
    assert client.post('/api/profile/rating', json={'topic': ' ', 'rating': 90}).status_code == 400


def test_chat_and_document_receive_correction_not_old_judgment(monkeypatch):
    insight, project, conversation = chat_insight()
    profile.change_insight(insight['id'], 0, correction='现在需讲适用边界，不要假定不会计算。')
    captured = []
    class Tutor:
        def __init__(self, model=None, effort=None):
            self.model = model or 'test-model'
            self.effort = effort
        async def agent_stream(self, messages):
            captured.append(j(messages)); yield 'final', '解释适用边界。'
        async def complete(self, system, user, **kwargs):
            captured.append(system + '\n' + user); return '## 系统性总结\n解释适用边界。'
    monkeypatch.setattr(server, 'DeepSeekClient', Tutor)
    async def send():
        response = await server.chat_stream(server.ChatIn(project_id=project['id'], source_ids=[], conversation_id=conversation,
                                                          provider='deepseek', text='请讲柯西不等式。'))
        return b''.join([packet async for packet in response.body_iterator])
    assert b'error' not in asyncio.run(send())
    unrelated = {'topic': '量子物理', 'score': 10}
    asyncio.run(generate_explanation(Tutor(), '柯西不等式原资料', 3, [unrelated], requirements='请解释适用边界'))
    for payload in captured:
        assert '现在需讲适用边界' in payload and '构造动机需要进一步解释。' not in payload
    assert '量子物理' not in captured[-1] and '经校准' in captured[-1]


def test_feynman_and_quiz_are_separate_and_removing_judgment_does_not_change_grade_records():
    quiz = score_record('quiz', 79)
    score_record('feynman', 85, '费曼讲解')
    row = profile.effective_profile()[0]
    assert row['score'] == 80.8 and row['quiz_score'] == 79 and row['feynman_score'] == 85
    profile.change_insight(quiz['id'], 0, correction='这次是借助提示完成，需要独立复核。')
    assert profile.insight_evidence(quiz['id'])['recorded_score'] == 79
    assert profile.effective_profile()[0]['quiz_score'] == 79
    assert '借助提示' in memory.profile_context('柯西不等式')


def test_paused_score_snapshot_refreshes_after_profile_control_but_keeps_unmodified_snapshot():
    project = create_project('暂停时的画像')
    job = create_job(project['id'], 'generate', {})
    insight = score_record('quiz', 90)
    old = profile.generation_profile(job)
    assert old[0]['score'] == 90
    score_record('new', 40)  # Normal new activity does not silently change a started task's snapshot.
    assert profile.generation_profile(job) == old
    profile.change_insight(insight['id'], 0, deleted=True)
    new = profile.generation_profile(job)
    assert new[0]['score'] == 40 and new[0]['assessment_count'] == 1
    assert one("SELECT response FROM generation_steps WHERE job_id=? AND step_key='mastery_snapshot'", (job,))['response'] == j(new)


def test_legacy_and_mcp_use_effective_scores_after_exclusion():
    from studyforge.mcp_server import get_learning_profile
    update_mastery('旧概念', quiz=88, self_rating=100)
    client = TestClient(server.app)
    assert client.put('/api/profile/legacy', json={'topic': '旧概念', 'removed': True}).status_code == 200
    assert get_learning_profile() == []
    assert client.get('/api/profile/legacy').json()[0]['topic'] == '旧概念'
    assert '旧概念' in memory.profile_context('旧概念') and '88' not in memory.profile_context('旧概念')
    assert client.put('/api/profile/legacy', json={'topic': '旧概念', 'removed': False}).status_code == 200
    assert get_learning_profile()[0]['score'] == 88
