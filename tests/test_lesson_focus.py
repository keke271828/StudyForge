import asyncio
import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from studyforge import ai, conversations, db, lesson_feedback, lesson_focus, server
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid


def lesson(tmp_path, provider='deepseek', document=None, project=None, chat=None):
    ai.save_settings({'background_learning_enabled': False, 'agent_tools_enabled': False})
    project = project or create_project('精准补讲')
    chat = chat or conversations.create(project['id'], provider, 'fixture-model')
    text = document or '# 极限与定义\n\n## 为什么取距离的一半\n\n极限定义允许任意正数；两个开邻域可不相交。\n\n## 合并门槛\n\n取两个门槛的最大值。\n\n## 系统性总结\n\n构造邻域并统一门槛。'
    job = create_job(project['id'], 'generate', {'source_ids': [], 'conversation_id': chat['id'],
        'learning_mode': 'deep', 'explanation_style': 'balanced', 'output_language': 'zh'})
    path = tmp_path / (job + '.docx'); path.write_bytes(b'legacy-placeholder')
    server.add_artifact(project['id'], [], 'explanation', 'docx', '极限与定义', path,
                        {'generation_job_id': job, 'conversation_id': chat['id']})
    message = uid()
    execute('INSERT INTO messages VALUES (?,?,?,?,?)', (message, chat['id'], 'assistant', '已生成讲解文档：\n\n' + text, now()))
    execute('INSERT INTO generation_dialogue_outputs VALUES (?,?,?)', (job, chat['id'], message))
    execute("UPDATE jobs SET status='completed' WHERE id=?", (job,))
    question = lesson_feedback.ensure_questionnaire(job)
    return project, chat, question, text, message


def selected(question, title='为什么取距离的一半'):
    row = lesson_feedback.get_questionnaire(question['id'])
    return next(item for item in lesson_focus.section_options(row)['items'] if item['title'] == title)


def test_real_headings_distinguish_repeats_and_parent_ranges(tmp_path):
    text = ('开篇条件。\n\n# 数列\n\n## 定义\n\n数列定义原话。\n\n```python\n# 代码标题不应成为章节\n```\n'
            '> ## 引用标题不应成为章节\n\n# 函数\n\n## 定义\n\n函数定义原话。')
    *_, question, _, _ = lesson(tmp_path, document=text)
    row = lesson_feedback.get_questionnaire(question['id'])
    options = lesson_focus.section_options(row)['items']
    assert [item['title'] for item in options] == ['开篇说明', '数列', '定义', '函数', '定义']
    definitions = [item for item in options if item['title'] == '定义']
    assert definitions[0]['id'] != definitions[1]['id']
    assert definitions[0]['path'] == ['数列', '定义'] and definitions[1]['path'] == ['函数', '定义']
    focus = lesson_focus.select_focus(row, options[1]['id'])
    assert '数列定义原话' in focus['excerpt'] and '函数定义原话' not in focus['excerpt']
    intro = lesson_focus.select_focus(row, options[0]['id'])
    assert intro['excerpt'].strip() == '开篇条件。'


def test_headingless_legacy_lesson_and_empty_message(tmp_path):
    _, _, question, text, message = lesson(tmp_path, document='一个没有标题的旧讲解。')
    row = lesson_feedback.get_questionnaire(question['id'])
    option = lesson_focus.section_options(row)['items'][0]
    assert option['title'] == '整份讲解'
    assert lesson_focus.select_focus(row, option['id'])['excerpt'] == text
    execute("UPDATE messages SET content='' WHERE id=?", (message,))
    assert lesson_focus.section_options(row) == {'items': [], 'omitted': 0}
    with pytest.raises(ValueError, match='原讲解记录不可用'):
        lesson_focus.select_focus(row, option['id'])


def test_bounded_options_and_exact_excerpt_receipt(tmp_path):
    text = '# 全文\n' + '\n'.join('## 标题' + str(index) + '\n内容。' for index in range(310))
    _, _, question, _, _ = lesson(tmp_path, document=text)
    row = lesson_feedback.get_questionnaire(question['id'])
    options = lesson_focus.section_options(row)
    assert len(options['items']) == 300 and options['omitted'] == 11
    assert all(len(item['preview']) <= 160 and 'excerpt' not in item for item in options['items'])
    # Much larger sections keep an explicitly partial, immutable excerpt.
    long = '# 长证明\n' + '解释各步条件，不省略原讲解。' * 1100
    _, _, question, _, _ = lesson(tmp_path, document=long)
    row = lesson_feedback.get_questionnaire(question['id'])
    focus = lesson_focus.select_focus(row, lesson_focus.section_options(row)['items'][0]['id'])
    assert focus['excerpt'] == long[:7000] and focus['excerpt_cut'] and focus['chars'] == len(long)
    assert focus['document_sha256'] == focus['section_sha256'] == hashlib.sha256(long.encode()).hexdigest()
    assert lesson_focus.delivered_document(row) == long
    assert '尚未在这里提供' in lesson_focus.focus_context(dict(row, focus_json=j(focus)))


def test_invalid_stale_or_other_lesson_selection_commits_nothing(tmp_path):
    project, chat, question, _, message = lesson(tmp_path)
    _, _, other, *_ = lesson(tmp_path, document='# 另一讲解\n## 为什么取距离的一半\n不同的内容。', project=project, chat=chat)
    api = TestClient(server.app)
    endpoint = '/api/lesson-feedback/' + question['id'] + '/submit'
    stale = selected(question)['id']
    for bad in ('not-a-section', selected(other)['id']):
        assert api.post(endpoint, json={'difficulties': ['motivation'], 'focus_section_id': bad}).status_code == 400
    execute('UPDATE messages SET content=content||? WHERE id=?', ('\n交付文字已经修改。', message))
    assert api.post(endpoint, json={'difficulties': ['motivation'], 'focus_section_id': stale}).status_code == 400
    assert one('SELECT status,focus_json FROM lesson_questionnaires WHERE id=?', (question['id'],)) == {'status': 'pending', 'focus_json': '{}'}
    assert not many('SELECT * FROM learning_events') and not many('SELECT * FROM learning_insights')


def test_focus_idempotency_literal_self_report_and_no_mastery_inference(tmp_path):
    _, _, question, _, message = lesson(tmp_path)
    focus_id = selected(question)['id']
    value = {'difficulties': ['motivation'], 'other_text': '我不明白为什么允许取等号。\n删除按钮没反应。', 'focus_section_id': focus_id}
    api = TestClient(server.app); endpoint = '/api/lesson-feedback/' + question['id'] + '/submit'
    assert api.post(endpoint, json=value).status_code == 200
    # Repeating a saved submission must not recompute against a changed document.
    execute('UPDATE messages SET content=content||? WHERE id=?', ('\n后续校订。', message))
    assert api.post(endpoint, json=value).status_code == 200
    assert api.post(endpoint, json=dict(value, focus_section_id=None)).status_code == 400
    stored = lesson_feedback.get_questionnaire(question['id'])
    focus = lesson_focus.saved_focus(stored)
    assert '后续校订' not in focus['excerpt']
    assert '具体位置' in lesson_feedback.feedback_text(stored)
    assert '不是原文件或学生的理解证据' in lesson_feedback.remediation_policy(stored)
    event = many('SELECT * FROM learning_events'); insights = many('SELECT * FROM learning_insights')
    assert len(event) == 1 and len(insights) == 2 and not many('SELECT * FROM mastery')
    assert '删除按钮' not in j(event + insights)
    assert all(item['kind'] == 'self_report' and item['confidence'] == '自评（未验证）' for item in insights)
    assert '极限定义允许任意正数' not in j(event + insights), 'AI excerpt is not the student\'s profile evidence'
    assert '为什么取距离的一半' in j(insights)
    public = api.get('/api/projects/' + question['project_id'] + '/lesson-feedback').json()[0]
    assert public['focus']['id'] == focus_id and 'excerpt' not in public['focus']


def test_only_focus_is_not_a_learner_difficulty_and_skip_never_records_it(tmp_path):
    _, _, question, *_ = lesson(tmp_path)
    api = TestClient(server.app); endpoint = '/api/lesson-feedback/' + question['id'] + '/submit'
    assert api.post(endpoint, json={'focus_section_id': selected(question)['id']}).status_code == 400
    assert api.post(endpoint, json={'skip': True, 'focus_section_id': 'invalid-id'}).status_code == 200
    assert not many('SELECT * FROM learning_events')


def test_generic_heading_does_not_apply_this_difficulty_to_unrelated_knowledge(tmp_path):
    from studyforge.learning_memory import profile_context
    _, _, question, *_ = lesson(tmp_path, document='# 高斯定律\n\n## 定义\n\n闭合面的净通量由内部总电荷确定。')
    lesson_feedback.submit_questionnaire(question['id'], ['terminology'], '',
        focus_section_id=selected(question, '定义')['id'])
    anchors = json.loads(one('SELECT anchors_json FROM learning_insights')['anchors_json'])
    assert '高斯定律' in anchors and '定义' not in anchors
    assert '学生自报' not in profile_context('请解释函数的定义及其几何意义。')
    assert '学生自报' in profile_context('请解释高斯定律的概念。')


def test_native_followup_uses_one_real_request_and_the_selected_old_excerpt(tmp_path, monkeypatch):
    project, chat, question, _, _ = lesson(tmp_path)
    lesson(tmp_path, document='# 新的讲解\n\n不应把新文档当成问卷的目标。', project=project, chat=chat)
    api = TestClient(server.app); endpoint = '/api/lesson-feedback/' + question['id']
    assert api.post(endpoint + '/submit', json={'difficulties': ['motivation'], 'focus_section_id': selected(question)['id']}).status_code == 200
    calls = []; real = httpx.AsyncClient
    def respond(request):
        calls.append(json.loads(request.content))
        packet = {'choices': [{'delta': {'content': '这个选择合法，因为定义对任意正半径成立；等号时端点仍被排除。'}, 'finish_reason': 'stop'}]}
        return httpx.Response(200, text='data: ' + j(packet) + '\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(ai, 'get_secret', lambda key: 'fixture-only')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: real(transport=httpx.MockTransport(respond)))
    before = conversations.detail(chat['id'], project['id'])
    response = api.post(endpoint + '/followup')
    assert response.status_code == 200 and '"error"' not in response.text
    assert len(calls) == 1 and calls[0]['model'] == 'fixture-model'
    system = calls[0]['messages'][0]['content']
    assert '学生本次选中的补讲位置' in system and '极限定义允许任意正数' in system
    assert '不应把新文档' not in system
    assert '不归咎于学生' in system and '不能当作客观低能力' in system
    after = conversations.detail(chat['id'], project['id'])
    for key in ('source_ids', 'learning_mode', 'explanation_style', 'output_language'):
        assert after[key] == before[key]
    assert not many('SELECT * FROM mastery') and not many('SELECT * FROM exercise_sets')


def test_codex_prompt_binds_original_questionnaire_instead_of_latest_lecture(tmp_path, monkeypatch):
    project, chat, question, original, _ = lesson(tmp_path, provider='codex')
    lesson(tmp_path, provider='codex', document='# LATEST_OTHER_DOCUMENT_MARKER\n\n讨论另一件事。', project=project, chat=chat)
    calls = []
    async def stream(self, prompt, *args, **kwargs):
        calls.append((prompt, kwargs['fallback_history']))
        yield 'thread', 'fixture-thread'; yield 'final', '只补取半径的动机。'
    monkeypatch.setattr('studyforge.codex_bridge.CodexBridge.stream_turn', stream)
    api = TestClient(server.app); endpoint = '/api/lesson-feedback/' + question['id']
    api.post(endpoint + '/submit', json={'difficulties': ['motivation'], 'focus_section_id': selected(question)['id']})
    assert '"error"' not in api.post(endpoint + '/followup').text
    assert len(calls) == 1 and original in calls[0][0]
    assert 'LATEST_OTHER_DOCUMENT_MARKER' not in calls[0][0]
    assert 'LATEST_OTHER_DOCUMENT_MARKER' in calls[0][1], 'Same-chat public history still remains available'


def test_sections_endpoint_contains_no_other_chat_history(tmp_path):
    _, _, question, _, _ = lesson(tmp_path)
    lesson(tmp_path, document='# FOREIGN_PROJECT_TEXT\n不属于该问卷。')
    api = TestClient(server.app)
    result = api.get('/api/lesson-feedback/' + question['id'] + '/sections')
    assert result.status_code == 200 and result.json()['items']
    assert 'FOREIGN_PROJECT_TEXT' not in result.text and 'messages' not in result.json()
    dialogue = api.get('/api/lesson-feedback/' + question['id'] + '/dialogue').json()
    assert dialogue['sections'] == result.json()


def test_deleted_chat_does_not_leave_a_questionnaire_running(tmp_path):
    _, chat, question, *_ = lesson(tmp_path)
    lesson_feedback.submit_questionnaire(question['id'], ['motivation'], '')
    execute('INSERT INTO deleted_conversations VALUES (?,?)', (chat['id'], now()))
    api = TestClient(server.app)
    assert api.get('/api/lesson-feedback/' + question['id'] + '/sections').status_code == 404
    assert api.post('/api/lesson-feedback/' + question['id'] + '/followup').status_code == 404
    assert lesson_feedback.get_questionnaire(question['id'])['reply_status'] == 'pending'


def test_legacy_schema_adds_focus_without_erasing_saved_feedback(tmp_path):
    _, _, question, *_ = lesson(tmp_path)
    lesson_feedback.submit_questionnaire(question['id'], ['motivation'], '我不明白构造动机。')
    with db.connect() as database:
        database.execute('ALTER TABLE lesson_questionnaires DROP COLUMN focus_json')
    db._initialized_databases.clear()
    recovered = lesson_feedback.get_questionnaire(question['id'])
    assert recovered['focus_json'] == '{}'
    assert recovered['status'] == 'submitted' and recovered['other_text'] == '我不明白构造动机。'
