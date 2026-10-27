"""A follow-up can read delivered work, without opening another chat or private diagnosis."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from studyforge import ai, conversations, homework, server
from studyforge.agent_tools import AgentRuntime, tool_specs
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid, unj


TOOL = 'sf_read_homework_feedback'


def case(tmp_path, *, status='completed', project=None, chat=None, solutions=True, feedback=True):
    ai.save_settings({'agent_tools_enabled': False, 'background_learning_enabled': False})
    project = project or create_project('按题继续学习')
    chat = chat or conversations.create(project['id'], 'deepseek', 'fixture-model')
    questions = [{'index': 0, 'topic': '高斯定律', 'question': '面内净电荷为零，电场一定为零吗？'},
                 {'index': 1, 'topic': '加法', 'question': '计算2+3并说明步骤。'}]
    reference = [{'index': 0, 'solution': 'REFERENCE_GAUSS：净通量为零不等于场为零。', 'rubric': '区分场和通量'},
                 {'index': 1, 'solution': 'REFERENCE_ADD：2+3=5。', 'rubric': '加法正确'}]
    set_id, attempt = uid(), uid()
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
        (set_id, project['id'], '[]', '通量与计算', j(questions), j(reference), 2, 'graded', now()))
    worksheet = one('SELECT * FROM exercise_sets WHERE id=?', (set_id,))
    grade = {'score': 80, 'scores': [70, 90], 'feedback': ['混淆净通量和场。', '加法计算有误。']}
    analysis = {'items': [{'index': 0, 'kind': 'terminology', 'confidence': 'self_report',
        'cause': '学生自报把净通量当成场强。', 'evidence': [{'source': 'questionnaire', 'quote': '我把净通量当作场强'}],
        'explanation': 'FEEDBACK_GAUSS：均匀非零电场穿过盒子，进入与穿出的通量抵消，但每处电场仍不为零。',
        'check': '区分局部的场与整个面的积分。'},
        {'index': 1, 'kind': 'implementation', 'confidence': 'supported', 'cause': '加法步骤错误。',
         'evidence': [{'source': 'answer', 'quote': '2+3=4'}],
         'explanation': 'FEEDBACK_ADD：从2依次加三个1，得到3、4、5。', 'check': '用5−3=2核对。'}]}
    job = create_job(project['id'], 'homework_grade', {'conversation_id': chat['id']})
    execute('UPDATE jobs SET status=? WHERE id=?', ('completed' if status == 'completed' else 'paused', job))
    ids = {}
    for kind, enabled in [('solutions', solutions), ('grading', feedback)]:
        if enabled:
            path = tmp_path / (attempt+'-'+kind+'.docx'); path.write_bytes(b'fixture-only')
            ids[kind] = server.add_artifact(project['id'], [], kind, 'docx', '通量与计算', path,
                {'homework_attempt_id': attempt, 'exercise_set_id': set_id, 'conversation_id': chat['id']})['id']
    execute('INSERT INTO homework_attempts(id,exercise_set_id,project_id,conversation_id,job_id,source_version,'
        'answers_json,options_json,status,grade_json,analysis_json,solution_artifact_id,feedback_artifact_id,created_at,updated_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (attempt, set_id, project['id'], chat['id'], job,
        homework.version(worksheet), j(['内电荷为零所以处处场为零。', '2+3=4']), '{}', status,
        j(grade), j(analysis), ids.get('solutions'), ids.get('grading'), now(), now()))
    return project, chat, attempt, worksheet, ids


def read(project, chat, **args):
    return asyncio.run(AgentRuntime(project['id'], conversation_id=chat['id']).execute(TOOL, args))


def test_learning_tool_is_advertised_to_both_provider_adapters():
    assert TOOL in [item['function']['name'] for item in tool_specs()]
    assert TOOL in [item['name'] for item in tool_specs(codex=True)]


def test_read_one_question_preserves_evidence_without_other_question(tmp_path):
    project, chat, attempt, worksheet, _ = case(tmp_path)
    result = read(project, chat, attempt_id=attempt, question_number=2)
    assert 'error' not in result, result
    assert '2+3=4' in result['text'] and 'FEEDBACK_ADD' in result['text'] and 'REFERENCE_ADD' in result['text']
    assert 'FEEDBACK_GAUSS' not in result['text'] and 'REFERENCE_GAUSS' not in result['text']
    assert result['question_number'] == 2 and result['next_offset'] is None
    assert not many('SELECT * FROM learning_events') and not many('SELECT * FROM mastery')
    events = j(many('SELECT * FROM agent_tool_events'))
    assert '2+3=4' not in events and 'FEEDBACK_ADD' not in events


def test_index_has_status_and_identity_but_no_solutions_or_work(tmp_path):
    project, chat, attempt, *_ = case(tmp_path)
    result = read(project, chat)
    assert result['items'][0]['attempt_id'] == attempt
    assert result['items'][0]['question_count'] == 2 and result['items'][0]['feedback_available']
    assert 'REFERENCE_' not in j(result) and 'FEEDBACK_' not in j(result) and '2+3=4' not in j(result)


@pytest.mark.parametrize('foreign_project', [False, True])
def test_other_dialogue_is_inaccessible_even_with_known_id(tmp_path, foreign_project):
    project, chat, attempt, *_ = case(tmp_path)
    other_project = create_project('其他项目') if foreign_project else project
    other_chat = conversations.create(other_project['id'], 'deepseek')
    assert read(other_project, other_chat)['items'] == []
    denied = read(other_project, other_chat, attempt_id=attempt, question_number=1)
    assert 'error' in denied and 'REFERENCE_' not in j(denied)


def test_waiting_for_causes_does_not_release_unpublished_analysis(tmp_path):
    project, chat, attempt, *_ = case(tmp_path, status='awaiting_causes', feedback=False)
    result = read(project, chat, attempt_id=attempt, question_number=1)
    assert 'REFERENCE_GAUSS' in result['text'] and '内电荷为零所以' in result['text']
    assert 'FEEDBACK_GAUSS' not in j(result) and '学生自报' not in result['text']
    assert not result['feedback_available'] and result['status'] == 'awaiting_causes'


def test_unsubmitted_or_no_delivered_document_never_reveals_answers(tmp_path):
    project, chat, attempt, *_ = case(tmp_path, solutions=False, feedback=False)
    result = read(project, chat, attempt_id=attempt, question_number=1)
    assert 'REFERENCE_' not in j(result) and 'FEEDBACK_' not in j(result)
    execute('UPDATE homework_attempts SET answers_json=? WHERE id=?', (j(['', '2+3=4']), attempt))
    assert 'error' in read(project, chat, attempt_id=attempt, question_number=1)


def test_long_question_can_be_read_completely_in_order(tmp_path):
    project, chat, attempt, *_ = case(tmp_path)
    long = '逐步解释。'*5000
    execute("UPDATE homework_attempts SET analysis_json=json_set(analysis_json,'$.items[1].explanation',?) WHERE id=?", (long, attempt))
    cursor, chunks = 0, []
    while True:
        result = read(project, chat, attempt_id=attempt, question_number=2, offset=cursor, limit=1000)
        assert 'error' not in result and len(result['text']) <= 1000
        chunks.append(result['text'])
        if result['next_offset'] is None: break
        assert result['next_offset'] > cursor
        cursor = result['next_offset']
    text = ''.join(chunks)
    assert long in text and len(text) == result['total_characters']
    assert 'REFERENCE_GAUSS' not in text


def test_cached_protocol_invalidates_when_feedback_is_removed(tmp_path):
    project, chat, attempt, _, ids = case(tmp_path)
    runtime = AgentRuntime(project['id'], conversation_id=chat['id'])
    before = runtime.state_key()
    execute('DELETE FROM artifacts WHERE id=?', (ids['grading'],))
    assert AgentRuntime(project['id'], conversation_id=chat['id']).state_key() != before
    result = read(project, chat, attempt_id=attempt, question_number=1)
    assert 'FEEDBACK_GAUSS' not in j(result) and not result['feedback_available']


def test_older_attempt_pagination_and_invalidation_without_loading_bodies(tmp_path, monkeypatch):
    project, chat, attempt, _, ids = case(tmp_path)
    for _ in range(7): case(tmp_path, project=project, chat=chat)
    first = read(project, chat)
    assert first['total'] == 8 and first['next_offset'] == 6
    assert attempt not in j(first['items'])
    last = read(project, chat, offset=first['next_offset'])
    assert len(last['items']) == 2 and last['next_offset'] is None
    assert attempt in j(last['items'])
    runtime = AgentRuntime(project['id'], conversation_id=chat['id'])
    before = runtime.state_key()
    execute('DELETE FROM artifacts WHERE id=?', (ids['grading'],))
    assert AgentRuntime(project['id'], conversation_id=chat['id']).state_key() != before
    from studyforge import homework_context
    actual = homework_context.many; queries = []
    def capture(sql, *args):
        queries.append(sql); return actual(sql, *args)
    monkeypatch.setattr(homework_context, 'many', capture)
    runtime = AgentRuntime(project['id'], conversation_id=chat['id'])
    runtime.context(); runtime.state_key()
    assert queries
    assert all(not any(blob in sql for blob in ('answers_json', 'analysis_json', 'options_json', 'grade_json')) for sql in queries)


@pytest.mark.parametrize('number', [None, 0, 3, -1])
def test_question_number_must_be_explicit_and_in_range(tmp_path, number):
    project, chat, attempt, *_ = case(tmp_path)
    assert 'error' in read(project, chat, attempt_id=attempt, question_number=number)


def test_grade_doubt_is_not_relabelled_as_a_confirmed_error(tmp_path):
    project, chat, attempt, *_ = case(tmp_path, status='awaiting_grade_review')
    execute('UPDATE homework_attempts SET grade_json=?,analysis_json=? WHERE id=?',
        (j({'score': None, 'scores': [None, None], 'feedback': ['待核对', '待核对'],
            'grading_verification_required': True, 'uncertainties': ['评分依据尚待确认']}), j({'items': []}), attempt))
    result = read(project, chat, attempt_id=attempt, question_number=1)
    assert result['feedback_available'] and '评分待核实' in result['text'] and '暂不定分' in result['text']
    assert 'FEEDBACK_' not in result['text'] and '不能将评分疑点当成学生错误' in result['text']


def test_multiple_attempts_are_only_listed_and_not_silently_chosen(tmp_path):
    project, chat, first, *_ = case(tmp_path)
    _, _, second, *_ = case(tmp_path, project=project, chat=chat)
    result = read(project, chat, question_number=2)
    assert {item['attempt_id'] for item in result['items']} == {first, second}
    assert 'text' not in result and '先确认' in result['note']


def test_missing_or_misbound_delivery_is_not_read_as_a_report(tmp_path):
    project, chat, attempt, _, ids = case(tmp_path)
    execute('UPDATE artifacts SET metadata_json=? WHERE id=?',
        (j({'homework_attempt_id': 'foreign', 'exercise_set_id': 'foreign', 'conversation_id': chat['id']}), ids['grading']))
    result = read(project, chat, attempt_id=attempt, question_number=2)
    assert not result['feedback_available'] and 'FEEDBACK_ADD' not in result['text']
    from pathlib import Path
    Path(one('SELECT path FROM artifacts WHERE id=?', (ids['solutions'],))['path']).unlink()
    result = read(project, chat, attempt_id=attempt, question_number=2)
    assert not result['solutions_available'] and 'REFERENCE_ADD' not in result['text']


def test_private_grader_and_deleted_chat_cannot_use_feedback_tool(tmp_path):
    project, chat, attempt, *_ = case(tmp_path)
    private = AgentRuntime(project['id'], conversation_id=chat['id'], private_context=True)
    assert 'error' in asyncio.run(private.execute(TOOL, {'attempt_id': attempt, 'question_number': 1}))
    runtime = AgentRuntime(project['id'], conversation_id=chat['id'])
    execute('INSERT INTO deleted_conversations VALUES (?,?)', (chat['id'], now()))
    assert 'error' in asyncio.run(runtime.execute(TOOL, {}))


def test_changed_worksheet_does_not_mix_old_work_and_new_solutions(tmp_path):
    project, chat, attempt, worksheet, *_ = case(tmp_path)
    execute('UPDATE exercise_sets SET solutions_json=? WHERE id=?', (j([{'index': 0, 'solution': 'CHANGED_REFERENCE'}]), worksheet['id']))
    result = read(project, chat, attempt_id=attempt, question_number=1)
    assert 'error' not in result and 'CHANGED_REFERENCE' not in j(result)
    assert result['current_version_matches'] is False and 'REFERENCE_GAUSS' in result['text']


def test_native_stream_actually_reads_and_returns_to_the_same_followup(tmp_path, monkeypatch):
    project, chat, attempt, *_ = case(tmp_path)
    calls = []; original = httpx.AsyncClient
    def respond(request):
        body = json.loads(request.content); calls.append(body)
        if len(calls) == 1:
            assert TOOL in [tool['function']['name'] for tool in body['tools']]
            assert attempt in body['messages'][0]['content']
            delta = {'tool_calls': [{'index': 0, 'id': 'feedback-call', 'type': 'function', 'function':
                {'name': TOOL, 'arguments': j({'attempt_id': attempt, 'question_number': 2})}}]}
            reason = 'tool_calls'
        else:
            tool = body['messages'][-1]
            assert tool['role'] == 'tool' and tool['tool_call_id'] == 'feedback-call'
            assert 'FEEDBACK_ADD' in tool['content'] and '2+3=4' in tool['content']
            assert 'FEEDBACK_GAUSS' not in tool['content']
            delta = {'content': '你第2题写的是2+3=4；从2依次加三个1得到3、4、5。用5−3=2检查。'}; reason = 'stop'
        return httpx.Response(200, text='data: '+j({'choices': [{'delta': delta, 'finish_reason': reason}]})+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(ai, 'get_secret', lambda key: 'fixture-only')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(transport=httpx.MockTransport(respond)))
    response = TestClient(server.app).post('/api/chat/stream', json={'provider': 'deepseek', 'project_id': project['id'],
        'conversation_id': chat['id'], 'model': 'fixture-model', 'text': '第2题为什么算错？只补这一题。'})
    assert response.status_code == 200 and '"error"' not in response.text, response.text
    assert len(calls) == 2 and '2+3=4' in response.text
    assert not many('SELECT * FROM exercise_sets WHERE id NOT IN (SELECT exercise_set_id FROM homework_attempts)')


def test_codex_protocol_executes_reader_and_returns_only_metadata_to_ui(tmp_path, monkeypatch):
    from studyforge.codex_bridge import CodexBridge
    project, chat, attempt, *_ = case(tmp_path)
    bridge = CodexBridge(); sent = []
    async def send(packet): sent.append(packet)
    monkeypatch.setattr(bridge, '_send', send)
    runtime = AgentRuntime(project['id'], conversation_id=chat['id'])
    asyncio.run(bridge._handle_tool({'id': 'call-1', 'params': {'threadId': 'fixture', 'tool': TOOL,
        'arguments': {'attempt_id': attempt, 'question_number': 2}}}, runtime))
    assert sent[0]['result']['success']
    returned = json.loads(sent[0]['result']['contentItems'][0]['text'])
    assert 'FEEDBACK_ADD' in returned['text'] and 'FEEDBACK_GAUSS' not in returned['text']
    ui = []
    while not bridge.events.empty(): ui.append(bridge.events.get_nowait())
    assert 'FEEDBACK_ADD' not in j(ui) and ui[-1]['params']['status'] == 'completed'


def test_codex_turn_advertises_reader_when_external_tools_are_off(tmp_path, monkeypatch):
    from studyforge.codex_bridge import CodexBridge
    project, chat, attempt, *_ = case(tmp_path)
    bridge = CodexBridge(); calls = []
    async def start(): pass
    async def request(method, params):
        calls.append((method, params))
        if method == 'thread/start': return {'thread': {'id': 'ephemeral-fixture', 'ephemeral': True}}
        if method == 'turn/start':
            await bridge.events.put({'method': 'turn/completed', 'params': {'threadId': params['threadId'], 'turn': {'status': 'completed'}}})
        return {}
    monkeypatch.setattr(bridge, 'start', start); monkeypatch.setattr(bridge, 'request', request)
    async def run():
        return [event async for event in bridge.stream_turn('继续问第2题', agent_runtime=AgentRuntime(project['id'], conversation_id=chat['id']))]
    asyncio.run(run())
    advertised = next(params for method, params in calls if method == 'thread/start')['dynamicTools']
    assert {tool['name'] for tool in advertised} == {TOOL, 'sf_read_learning_profile'}
    prompt = next(params for method, params in calls if method == 'turn/start')['input'][0]['text']
    assert attempt in prompt and 'FEEDBACK_ADD' not in prompt and '2+3=4' not in prompt


def test_report_change_during_reply_does_not_relabel_an_old_internal_transcript(tmp_path, monkeypatch):
    project, chat, attempt, _, ids = case(tmp_path)
    calls = []; original = httpx.AsyncClient
    def respond(request):
        body = json.loads(request.content); calls.append(body)
        if len(calls) == 1:
            assert ids['grading'] not in j(body), 'Index must not load full artifacts or feedback'
            execute('DELETE FROM artifacts WHERE id=?', (ids['grading'],))
        else:
            assert 'PRIVATE_STALE_FEEDBACK' not in j(body)
        packet = {'choices': [{'delta': {'reasoning_content': 'PRIVATE_STALE_FEEDBACK', 'content': '已回应当前问题。'}, 'finish_reason': 'stop'}]}
        return httpx.Response(200, text='data: '+j(packet)+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(ai, 'get_secret', lambda key: 'fixture-only')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(transport=httpx.MockTransport(respond)))
    api = TestClient(server.app)
    for text in ('解释第2题', '再补充这一点'):
        response = api.post('/api/chat/stream', json={'provider': 'deepseek', 'project_id': project['id'],
            'conversation_id': chat['id'], 'model': 'fixture-model', 'text': text})
        assert '"error"' not in response.text
    assert len(calls) == 2
