import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from studyforge import lesson_feedback, server
from studyforge.ai import save_settings
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid, update_mastery
from studyforge.learning_memory import profile_context


def completed_lesson(tmp_path, monkeypatch):
    save_settings({'chat_provider': 'deepseek', 'deepseek_model': 'lesson-model', 'background_learning_enabled': False})
    project = create_project('哲学'); source = uid(); conversation = uid()
    original = tmp_path / '规训权力.txt'; original.write_text('福柯研究规训权力。规训包括观察、记录、规范化判断。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (source, project['id'], original.name, '.txt', str(original), 'ready', now()))
    execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)',
            (conversation, project['id'], 'deepseek', None, now(), j([source]), 'lesson-model', None))
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',
            (uid(), conversation, 'user', '我只想读懂原文，用概念对照解释，不要出题，也不要强行套物理。', now()))
    requests = []; original_client = httpx.AsyncClient
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, text='data: ' + j({'choices': [{'delta': {'content':
            '# 规训权力\n福柯研究规训权力及其机制。[来源：规训权力.txt｜第 1 段]\n\n## 系统性总结\n观察和记录参与规训。'}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n')
    monkeypatch.setattr('studyforge.ai.get_secret', lambda key: 'test-key')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *args, **kwargs: original_client(transport=httpx.MockTransport(respond)))
    value = server.GenerateIn(project_id=project['id'], source_ids=[source], provider='deepseek',
                              conversation_id=conversation, model='lesson-model', exercises=False)
    job = create_job(project['id'], 'generate', value.model_dump())
    asyncio.run(server._generate_job(job, value))
    assert one('SELECT status FROM jobs WHERE id=?', (job,))['status'] == 'completed'
    return project, job, conversation, requests, respond, original_client


def test_completed_lecture_offers_six_optional_choices_and_other_with_no_extra_ai(tmp_path, monkeypatch):
    project, job, conversation, requests, *_ = completed_lesson(tmp_path, monkeypatch)
    api = TestClient(server.app)
    questionnaire = api.get('/api/lesson-feedback/by-job/' + job).json()
    assert len(questionnaire['options']) == 7 and questionnaire['ready']
    assert questionnaire['options'][-1]['id']=='content_accuracy' and not questionnaire['content_check']
    assert questionnaire['conversation_id'] == conversation and len(requests) == 1
    assert questionnaire['options'][2]['label'] == '看懂计算，但不懂构造动机'
    assert api.get('/api/lesson-feedback/by-job/' + job).json()['id'] == questionnaire['id']
    assert len(many('SELECT * FROM lesson_questionnaires')) == 1
    assert many('SELECT * FROM exercise_sets') == []
    assert api.get(f"/api/projects/{project['id']}/lesson-feedback").json()[0]['id'] == questionnaire['id']
    dialogue = api.get(f"/api/lesson-feedback/{questionnaire['id']}/dialogue").json()
    assert dialogue['model'] == 'lesson-model' and any('已生成讲解文档' in row['content'] for row in dialogue['messages'])


def test_feedback_is_evidence_only_and_same_tutor_receives_source_context(tmp_path, monkeypatch):
    project, job, conversation, requests, *_ = completed_lesson(tmp_path, monkeypatch)
    update_mastery('规训权力', quiz=90); before = many('SELECT * FROM mastery')
    api = TestClient(server.app); questionnaire = api.get('/api/lesson-feedback/by-job/' + job).json(); qid = questionnaire['id']
    choices = [item['id'] for item in questionnaire['options'] if item['id']!='content_accuracy']
    submitted = api.post(f'/api/lesson-feedback/{qid}/submit', json={'difficulties': choices, 'other_text': '规范化判断和观察有何不同？'})
    assert submitted.status_code == 200 and len(requests) == 1
    assert len(many('SELECT * FROM learning_insights')) == 7 and many('SELECT * FROM mastery') == before
    assert all(row['confidence'] == '自评（未验证）' for row in many('SELECT * FROM learning_insights'))
    memory = profile_context('请解释规训权力.txt及其哲学背景。')
    assert '看懂计算' in memory and '自评' in memory
    result = api.post(f'/api/lesson-feedback/{qid}/followup')
    assert result.status_code == 200 and '"error"' not in result.text
    assert len(requests) == 2 and requests[-1]['model'] == 'lesson-model'
    content = j(requests[-1]['messages'])
    assert '规范化判断和观察有何不同' in content and '已生成讲解文档' in content
    assert '用概念对照解释' in content and '不要强行套物理' in content
    assert '本次是讲解后补讲' in content and '不能擅自布置新作业' in content
    assert one('SELECT reply_status FROM lesson_questionnaires')['reply_status'] == 'completed'
    assert one('SELECT COUNT(*) AS n FROM learning_events')['n'] == 1, '问卷证据不得再次烧 token 进行背景分析'
    assert many('SELECT * FROM exercise_sets') == [] and many('SELECT * FROM mastery') == before
    assert api.post(f'/api/lesson-feedback/{qid}/followup').status_code == 409


def test_skip_makes_no_ai_call_or_memory_judgment(tmp_path, monkeypatch):
    _, job, _, requests, *_ = completed_lesson(tmp_path, monkeypatch)
    api = TestClient(server.app); qid = api.get('/api/lesson-feedback/by-job/' + job).json()['id']
    assert api.post(f'/api/lesson-feedback/{qid}/submit', json={'skip': True}).json()['status'] == 'skipped'
    assert api.post(f'/api/lesson-feedback/{qid}/submit', json={'skip': True}).status_code == 200
    assert api.post(f'/api/lesson-feedback/{qid}/followup').status_code == 400
    assert many('SELECT * FROM learning_events') == [] and many('SELECT * FROM mastery') == [] and len(requests) == 1


def test_unrelated_free_feedback_kept_in_questionnaire_but_not_learning_profile(tmp_path,monkeypatch):
    _,job,_,_,*_=completed_lesson(tmp_path,monkeypatch)
    api=TestClient(server.app);qid=api.get('/api/lesson-feedback/by-job/'+job).json()['id']
    response=api.post(f'/api/lesson-feedback/{qid}/submit',json={'other_text':'为什么删除按钮没有反应？'})
    assert response.status_code==200
    assert one('SELECT other_text FROM lesson_questionnaires')['other_text']=='为什么删除按钮没有反应？'
    assert many('SELECT * FROM learning_events')==[] and many('SELECT * FROM learning_insights')==[]


def test_mixed_free_feedback_profile_only_receives_knowledge_part(tmp_path,monkeypatch):
    _,job,_,_,*_=completed_lesson(tmp_path,monkeypatch)
    api=TestClient(server.app);qid=api.get('/api/lesson-feedback/by-job/'+job).json()['id']
    text='为什么删除按钮没有反应？\n请解释规范化这个概念的含义。'
    assert api.post(f'/api/lesson-feedback/{qid}/submit',json={'difficulties':['motivation'],'other_text':text}).status_code==200
    records=j(many('SELECT * FROM learning_events')+many('SELECT * FROM learning_insights'))
    assert '规范化' in records and '删除按钮' not in records


@pytest.mark.parametrize('payload', [{'difficulties': ['unknown']}, {'difficulties': ['motivation', 'motivation']}, {},
                                     {'other_text': 'x' * 3001}])
def test_invalid_or_empty_feedback_is_not_recorded(tmp_path, monkeypatch, payload):
    _, job, _, requests, *_ = completed_lesson(tmp_path, monkeypatch)
    api = TestClient(server.app); qid = api.get('/api/lesson-feedback/by-job/' + job).json()['id']
    assert api.post(f'/api/lesson-feedback/{qid}/submit', json=payload).status_code in (400, 422)
    assert many('SELECT * FROM learning_events') == [] and len(requests) == 1


def test_failed_followup_preserves_feedback_and_retry_deduplicates_messages(tmp_path, monkeypatch):
    _, job, conversation, requests, respond, original_client = completed_lesson(tmp_path, monkeypatch)
    api = TestClient(server.app); qid = api.get('/api/lesson-feedback/by-job/' + job).json()['id']
    answers = {'difficulties': ['motivation'], 'other_text': '请详细解释构造动机。'}
    assert api.post(f'/api/lesson-feedback/{qid}/submit', json=answers).status_code == 200
    assert api.post(f'/api/lesson-feedback/{qid}/submit', json=answers).status_code == 200
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *args, **kwargs: original_client(transport=httpx.MockTransport(
        lambda request: httpx.Response(503, json={'error': {'message': 'temporarily unavailable'}}))))
    first = api.post(f'/api/lesson-feedback/{qid}/followup')
    assert '"error"' in first.text and one('SELECT reply_status FROM lesson_questionnaires')['reply_status'] == 'failed'
    assert one('SELECT other_text FROM lesson_questionnaires')['other_text'] == answers['other_text']
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *args, **kwargs: original_client(transport=httpx.MockTransport(respond)))
    retry = api.post(f'/api/lesson-feedback/{qid}/followup')
    assert '"error"' not in retry.text and one('SELECT reply_status FROM lesson_questionnaires')['reply_status'] == 'completed'
    assert len(many("SELECT * FROM messages WHERE conversation_id=? AND role='user'", (conversation,))) == 2
    assert len(many('SELECT * FROM learning_events')) == 1


def test_backend_restart_recovers_interrupted_followup_and_profile_cross_project(tmp_path, monkeypatch):
    _, job, _, _, *_ = completed_lesson(tmp_path, monkeypatch)
    api = TestClient(server.app); qid = api.get('/api/lesson-feedback/by-job/' + job).json()['id']
    api.post(f'/api/lesson-feedback/{qid}/submit', json={'other_text': '解释规训权力的前置概念。'})
    execute("UPDATE lesson_questionnaires SET reply_status='running'")
    with TestClient(server.app) as restarted:
        assert restarted.get('/api/profile/memory').json()['insights'][0]['questionnaire_id'] == qid
        assert one('SELECT reply_status FROM lesson_questionnaires')['reply_status'] == 'failed'
    other = create_project('跨项目')
    assert other['id'] and '前置概念' in profile_context('规训权力.txt')


def test_delivered_lecture_can_get_followup_while_its_worksheet_job_runs(tmp_path, monkeypatch):
    _, job, _, requests, *_ = completed_lesson(tmp_path, monkeypatch)
    api = TestClient(server.app); qid = api.get('/api/lesson-feedback/by-job/' + job).json()['id']
    execute("UPDATE jobs SET status='running' WHERE id=?", (job,))
    assert api.get('/api/lesson-feedback/by-job/' + job).json()['ready']
    api.post(f'/api/lesson-feedback/{qid}/submit', json={'difficulties': ['terminology']})
    response=api.post(f'/api/lesson-feedback/{qid}/followup')
    assert response.status_code == 200 and '"error"' not in response.text
    assert one('SELECT status,reply_status FROM lesson_questionnaires') == {'status': 'submitted', 'reply_status': 'completed'}
    assert len(requests) == 2


def test_old_lecture_can_get_questionnaire_without_regeneration(tmp_path, monkeypatch):
    _, job, _, requests, *_ = completed_lesson(tmp_path, monkeypatch)
    execute('DELETE FROM lesson_questionnaires')
    q = lesson_feedback.ensure_questionnaire(job)
    assert q['job_id'] == job and len(requests) == 1


def test_codex_supplement_keeps_original_thread_model_effort_and_student_request(tmp_path, monkeypatch):
    project = create_project('数学'); conversation = uid(); source = uid(); message = uid()
    original = tmp_path / '构造.txt'; original.write_text('证明时通过构造辅助对象消去未知量。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (source, project['id'], original.name, '.txt', str(original), 'ready', now()))
    execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)',
            (conversation, project['id'], 'codex', 'same-tutor-thread', now(), j([source]), 'selected-tutor', 'high'))
    execute('INSERT INTO messages VALUES (?,?,?,?,?)', (uid(), conversation, 'user', '请先讲为什么想到辅助对象，再讲计算。', now()))
    execute('INSERT INTO messages VALUES (?,?,?,?,?)', (message, conversation, 'assistant', '已生成讲解文档：用辅助对象消去未知量。', now()))
    job = create_job(project['id'], 'generate', {'source_ids': [source]})
    execute("UPDATE jobs SET status='completed' WHERE id=?", (job,))
    artifact = tmp_path / '讲解.docx'; artifact.write_bytes(b'test')
    server.add_artifact(project['id'], [source], 'explanation', 'docx', '辅助对象构造', artifact, {'generation_job_id': job})
    execute('INSERT INTO generation_dialogue_outputs VALUES (?,?,?)', (job, conversation, message))
    qid = lesson_feedback.ensure_questionnaire(job)['id']; calls = []
    async def validate(model, effort): assert (model, effort) == ('selected-tutor', 'high')
    async def stream(prompt, remote_thread_id=None, model=None, effort=None, **kwargs):
        assert '请先讲为什么想到辅助对象' in kwargs['fallback_history']
        calls.append((prompt, remote_thread_id, model, effort, kwargs['agent_runtime'].conversation_id))
        yield 'thread', 'same-tutor-thread'; yield 'final', '构造的目标是消去未知量，这提示我们寻找共同约束。还有哪一步不清楚？'
    monkeypatch.setattr(server.model_catalog, 'validate_effort', validate)
    monkeypatch.setattr('studyforge.codex_bridge.CodexBridge.stream_turn',lambda self,*args,**kwargs:stream(*args,**kwargs))
    api = TestClient(server.app)
    api.post(f'/api/lesson-feedback/{qid}/submit', json={'difficulties': ['motivation']})
    result = api.post(f'/api/lesson-feedback/{qid}/followup')
    assert '"error"' not in result.text and len(calls) == 1
    assert calls[0][1:] == ('same-tutor-thread', 'selected-tutor', 'high', conversation)
    assert '构造动机' in calls[0][0] and '本次是讲解后补讲' in calls[0][0]
