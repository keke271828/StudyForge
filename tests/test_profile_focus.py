"""Current questions outrank a book's incidental profile matches."""
import asyncio
import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from studyforge import ai, conversations, learning_memory as memory, learning_profile as profile, message_focus, server
from studyforge.db import connect, create_project, execute, j, many, now, one, uid


def insight(topic, observation, project_id, conversation_id=None, *, anchors=None):
    event = memory.record_event('focus:' + uid(), 'chat',
        {'student_text': '我不明白这个知识点的概念。PRIVATE_RAW_STUDENT',
         'mentor_context': 'PRIVATE_OTHER_CHAT'}, project_id, conversation_id, analyzed=True)
    memory._save_insight(event, topic, 'gap', 'concepts', observation,
                         'PRIVATE_RAW_STUDENT', '自报困难（未测验）', anchors=anchors or [topic])
    return one('SELECT id FROM learning_insights WHERE event_id=?', (event,))['id']


def wide_profile(project_id, chat_id=None):
    target = insight('高斯定律', 'TARGET_GAUSS_GAP：学生自报分不清曲面积分的净通量和局部电场，尚未测验。', project_id, chat_id)
    topics = ['牛顿定律', '动量', '功', '功率', '动能', '势能', '角动量', '转动惯量', '热力学']
    for topic in topics:
        insight(topic, 'OTHER_GAP：需核对' + topic + '的理解。', project_id, chat_id)
    return target, topics


def capture_http(monkeypatch):
    ai.save_settings({'agent_tools_enabled': False, 'background_learning_enabled': False, 'library_reference_mode': 'off'})
    monkeypatch.setattr(ai, 'get_secret', lambda *a: 'fixture-only')
    native, posted = httpx.AsyncClient, []
    def respond(request):
        body = json.loads(request.content); posted.append(body)
        reply = '# 净通量和局部场\n\n面积分为零不等于被积场处处为零。\n\n## 系统性总结\n条件不同。'
        return httpx.Response(200, text='data: ' + j({'choices': [{'delta': {'content': reply}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: native(transport=httpx.MockTransport(respond)))
    return posted


@pytest.mark.parametrize('quoted', [True, False])
def test_actual_tutor_prioritizes_current_question_and_explicit_reference(tmp_path, monkeypatch, quoted):
    other = create_project('画像来源项目'); foreign_chat = conversations.create(other['id'], 'deepseek')
    target, topics = wide_profile(other['id'], foreign_chat['id'])
    p = create_project('当前项目'); chat = conversations.create(p['id'], 'deepseek')
    execute('INSERT INTO messages VALUES (?,?,?,?,?)', (uid(), foreign_chat['id'], 'user', 'FOREIGN_CHAT_RAW_SENTINEL', now()))
    ref, sources = None, []
    if quoted:
        old = '高斯定律约束净电通量，不能只凭净通量为零就断定局部电场为零。'
        mid = uid(); execute('INSERT INTO messages VALUES (?,?,?,?,?)', (mid, chat['id'], 'assistant', old, now()))
        ref = {'message_id': mid, 'content_sha256': hashlib.sha256(old.encode()).hexdigest(),
               'selection': {'start': 0, 'end': 4, 'text': '高斯定律'}}
        question = '我不明白这句，能用具体情形重新解释吗？'
    else:
        sid = uid(); path = tmp_path / 'wide.txt'
        path.write_text('本章目录包括：' + '、'.join(topics) + '、高斯定律。\n高斯定律约束闭合曲面的净电通量。', encoding='utf-8')
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
                (sid, p['id'], path.name, '.txt', str(path), 'ready', now()))
        sources = [sid]; question = '高斯定律中总电荷为零能否推出场处处为零？只讲这个卡点。'
    posted = capture_http(monkeypatch)
    before = {t: len(many('SELECT * FROM ' + t)) for t in ('learning_insights', 'mastery')}
    event_ids = {row['id'] for row in many('SELECT id FROM learning_events')}
    with TestClient(server.app) as api:
        result = api.post('/api/chat/stream', json={
            'project_id': p['id'], 'conversation_id': chat['id'], 'provider': 'deepseek', 'model': 'fixture',
            'source_ids': sources, 'text': question, 'reply_reference': ref})
    assert result.status_code == 200 and '"error"' not in result.text, result.text
    assert len(posted) == 1
    system = posted[0]['messages'][0]['content']
    assert 'TARGET_GAUSS_GAP' in system
    if 'OTHER_GAP' in system:
        assert system.index('TARGET_GAUSS_GAP') < system.index('OTHER_GAP')
    assert 'PRIVATE_RAW_STUDENT' not in j(posted) and 'PRIVATE_OTHER_CHAT' not in j(posted) and 'FOREIGN_CHAT_RAW_SENTINEL' not in j(posted)
    assert one('SELECT content FROM messages WHERE conversation_id=? AND role=?', (chat['id'], 'user'))['content'] == question
    assert {t: len(many('SELECT * FROM ' + t)) for t in before} == before
    # Ordinary learning questions can still enter the existing candidate queue.
    # Retrieval itself must not create extra evidence or treat AI text as answers.
    new_events = [row for row in many('SELECT * FROM learning_events') if row['id'] not in event_ids]
    assert len(new_events) <= 1
    assert all(json.loads(row['payload_json'])['student_text'] == question for row in new_events)


def test_document_prioritizes_latest_question_not_incidental_full_history(tmp_path, monkeypatch):
    from studyforge.agent_tools import AgentRuntime
    from studyforge.learning import learning_requirements
    p = create_project('文档画像聚焦'); target, topics = wide_profile(p['id'])
    chat = conversations.create(p['id'], 'deepseek')
    history = [
        {'role': 'user', 'content': '以前问过' + '、'.join(topics)},
        {'role': 'assistant', 'content': '此前内容也可能有误，不能据此认定能力。'},
        {'role': 'user', 'content': '现在请只讲高斯定律为何不能推出局部电场零。'},
    ]
    snapshot = dict(chat, messages=history, remote_thread_id=None)
    posted = capture_http(monkeypatch)
    runtime = AgentRuntime(p['id'], [], 'deepseek', 'fixture', conversation_id=chat['id'], job_id=uid(), publishing=False)
    client = ai.DeepSeekClient('fixture', runtime, snapshot, effort='high')
    digest = '原文首部。' + '、'.join(topics) + '。高斯定律约束净通量。原文尾部。'
    async def generate():
        try:
            return await ai.generate_explanation(client, digest, 3, [], requirements=learning_requirements(history, '沿最后的问题生成讲解，不出题。'))
        finally:
            await client.close()
    assert '系统性总结' in asyncio.run(generate())
    assert len(posted) == 1
    user = posted[0]['messages'][-1]['content']
    assert 'TARGET_GAUSS_GAP' in user and user.index('TARGET_GAUSS_GAP') < user.index('OTHER_GAP')
    assert '原文首部' in user and '原文尾部' in user
    assert all(sum(row['content'].count(h['content']) for row in posted[0]['messages']) == 1 for h in history)
    assert snapshot['messages'] == history and 'PRIVATE_RAW_STUDENT' not in j(posted)
    assert not many('SELECT * FROM mastery')


def test_focus_ranking_respects_removed_corrected_and_anchor_records():
    p = create_project('排序'); target, topics = wide_profile(p['id'])
    broad = '、'.join(topics) + '、高斯定律'
    assert '高斯定律' not in [row['topic'] for row in profile.mentor_profile(broad, limit=8)['topics']]
    focused = profile.mentor_profile(broad, focus='只问高斯定律', limit=2)
    assert focused['topics'][0]['topic'] == '高斯定律' and focused['next_offset'] == 2
    next_page = profile.mentor_profile(broad, focus='只问高斯定律', offset=2, limit=2)
    assert not set(r['topic'] for r in focused['topics']) & set(r['topic'] for r in next_page['topics'])
    # An explicit new question wins over its attached old quote.
    tiers = profile.mentor_profile(broad, focus=['现在问牛顿定律', '高斯定律'], limit=2)
    assert [row['topic'] for row in tiers['topics']] == ['牛顿定律', '高斯定律']
    profile.change_insight(target, 0, correction='已自报分清概念，现在只想看适用条件。')
    assert '已自报分清概念' in memory.profile_context(broad, focus='高斯定律')
    profile.change_insight(target, 1, deleted=True)
    assert 'TARGET_GAUSS_GAP' not in memory.profile_context(broad, focus='高斯定律')
    anchored = insight('对积分对象的理解', 'ANCHOR_GAP：需要区分通量的正负。', p['id'], anchors=['净电通量'])
    packet = profile.mentor_profile(broad, focus='净电通量为什么能抵消', limit=1)
    assert packet['topics'][0]['topic'] == '对积分对象的理解'
    assert 'PRIVATE_' not in j(packet)


def test_focus_context_keeps_profile_overview_and_does_not_rewrite_scores():
    p = create_project('分数'); _, topics = wide_profile(p['id'])
    memory.assessment_record('focus-score', '高斯定律', '做题', 79, 'PRIVATE_SCORE_ANSWER', '未核对条件。', p['id'])
    memory.assessment_record('focus-self', '高斯定律', '自评', 90, 'PRIVATE_SELF_REPORT', '主观熟悉。', p['id'])
    before = j(profile.effective_profile())
    result = memory.profile_context('我的学习画像是什么？', focus='只问高斯定律')
    assert '79' in result and '90' in result and 'OTHER_GAP' in result and 'PRIVATE_' not in result
    assert j(profile.effective_profile()) == before
    rows = [{'topic': '旧话题' + str(i), 'score': 90} for i in range(32)] + [{'topic': '高斯定律', 'score': 79}]
    reference = '、'.join(row['topic'] for row in rows)
    assert '高斯定律：' not in profile.assessment_context(rows, reference)
    assert profile.assessment_context(rows, reference, focus='只看高斯定律').startswith('高斯定律：评估参考分 79/100')


def test_query_focus_uses_latest_student_and_selected_quote_not_hash_or_ai_history():
    from studyforge.learning import profile_focus, learning_requirements, requirements_without_duplicate_history
    quote = '净电通量'
    ref = {'selection': {'text': quote}, 'excerpt': '高斯定律：' + quote + '。无关的热力学。', 'message_id': 'IGNORE_ID',
           'content_sha256': 'IGNORE_HASH', 'excerpt_start': 0, 'excerpt_end': 28}
    history = [{'role': 'user', 'content': '旧问题牛顿定律'}, {'role': 'assistant', 'content': '旧的长解释。'},
               {'role': 'user', 'content': '这句是什么意思？', 'reply_reference': ref},
               {'role': 'assistant', 'content': '这里不能断定学生不懂。'}]
    # Construct a valid software transcript for the extraction path.
    start = ref['excerpt'].index(quote); ref['selection'].update(start=start, end=start + len(quote))
    requirements = learning_requirements(history, '保留计算单位。')
    focus = profile_focus(history, requirements_without_duplicate_history(requirements, history))
    joined = '\n'.join(focus)
    assert '保留计算单位' in focus[0] and focus[1:] == ['这句是什么意思？', '净电通量']
    assert all(text not in joined for text in ('旧问题', '旧的长解释', 'IGNORE_ID', 'IGNORE_HASH', '热力学'))
    assert profile_focus([], '独立的讲解要求') == ['独立的讲解要求']
