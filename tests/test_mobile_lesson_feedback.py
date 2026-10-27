import asyncio
import threading
import time

from studyforge import conversations, lesson_feedback, server
from studyforge.ai import save_settings
from studyforge.config import files_dir
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid
from studyforge.exporters import export_document
from studyforge.mobile_context import remote_device
from studyforge.source_scope import ParseIn, derived_source
from test_mobile_access import mobile_client, pair


def phone_lesson(monkeypatch):
    import fitz
    save_settings({'chat_provider': 'deepseek', 'background_learning_enabled': False,
                   'agent_tools_enabled': False, 'agent_permission_mode': 'full_access'})
    project = create_project('手机理解反馈')
    chat = conversations.create(project['id'], 'deepseek', 'current-tutor')
    another = conversations.create(project['id'], 'deepseek')
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',
            (uid(), another['id'], 'user', 'OTHER_CHAT_PRIVATE_HISTORY', now()))
    parent = uid()
    book = files_dir() / 'scope-book.pdf'
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((50, 65), 'UNSELECTED_BOOK_PARAGRAPH')
        page = document.new_page()
        page.insert_text((50, 65), 'TARGET_FEEDBACK_PARAGRAPH: state each variable and its conditions.')
        page.insert_text((50, 100), 'REST_OF_SELECTED_PAGE_PRIVATE')
        document.save(book)
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (parent, project['id'], '选段书.pdf', '.pdf', str(book), 'stored', now()))
    selected = derived_source(one('SELECT * FROM sources WHERE id=?', (parent,)),
        ParseIn(mode='text', page_spec='2', locator='文件第2页原文选段',
                selected_text='TARGET_FEEDBACK_PARAGRAPH: state each variable and its conditions.'))['source_id']
    original_preferences = {'source_ids': [parent], 'learning_mode': 'overview',
                            'explanation_style': 'academic', 'output_language': 'en'}
    conversations.update(chat['id'], project['id'], original_preferences)
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',
            (uid(), chat['id'], 'user', '请先说明量和条件，不要出题，不要硬套比喻。', now()))
    message = uid()
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',
            (message, chat['id'], 'assistant', '已生成讲解文档：量与符号不同，先说明量的意义和条件。', now()))
    job = create_job(project['id'], 'generate', {'source_ids': [selected], 'conversation_id': chat['id'],
        'learning_mode': 'research', 'explanation_style': 'clear', 'output_language': 'bilingual'})
    execute("UPDATE jobs SET status='completed' WHERE id=?", (job,))
    document = export_document('# 量与条件\n\n先说明变量的意义及成立条件。', 'docx', '量与条件', 'phone-feedback.docx')
    artifact = server.add_artifact(project['id'], [selected], 'explanation', 'docx', '量与条件', document,
                                  {'generation_job_id': job, 'conversation_id': chat['id']})
    execute('INSERT INTO generation_dialogue_outputs VALUES (?,?,?)', (job, chat['id'], message))
    questionnaire = lesson_feedback.ensure_questionnaire(job)

    class Tutor:
        def __init__(self):
            self.model = 'current-tutor'
            self.effort = None
            self.requests = []
            self.release = threading.Event()
            self.fail = False
            self.identities = []

        async def agent_stream(self, messages):
            self.requests.append(messages)
            self.identities.append(remote_device.get())
            assert self.agent_runtime.mobile_device_id == remote_device.get()
            while not self.release.is_set():
                await asyncio.sleep(.02)
            if self.fail:
                self.fail = False
                raise RuntimeError('模拟补讲服务暂时不可用')
            yield 'final', 'PHONE_SUPPLEMENT：先说明量的含义，再解释为什么需要这个条件。还有哪一步不清楚？'

        async def close(self):
            pass

    tutor = Tutor()
    def current_tutor(**kwargs):
        assert kwargs.get('model') == 'current-tutor'
        return tutor
    monkeypatch.setattr(server, 'DeepSeekClient', current_tutor)
    return project, chat, another, questionnaire, artifact, tutor, original_preferences, parent


def feedback_payload(project, chat, request_id=None):
    return {'project_id': project['id'], 'conversation_id': chat['id'], 'request_id': request_id or uid()}


def wait_run(client, ident, status):
    for _ in range(180):
        row = client.get('/api/mobile/chat/' + ident).json()
        if row['status'] == status:
            return row
        time.sleep(.025)
    raise AssertionError(row)


def test_phone_feedback_survives_post_and_preserves_scope_preferences_and_private_history(monkeypatch):
    project, chat, _, q, _, tutor, original, parent = phone_lesson(monkeypatch)
    manager, client = mobile_client()
    with client:
        device = pair(manager, client)
        assert client.get('/lesson-feedback.js').status_code == 200
        url = '/api/lesson-feedback/' + q['id']
        dialogue = client.get(url + '/dialogue').json()
        assert dialogue['model'] == 'current-tutor' and dialogue['learning_mode'] == 'research'
        answer = {'difficulties': ['terminology', 'motivation'], 'other_text': '不懂量的含义和为什么要加条件。'}
        assert client.post(url + '/submit', json=answer).status_code == 200
        assert client.post(url + '/submit', json=answer).status_code == 200
        assert not tutor.requests, '保存问卷不得调用模型'
        route = '/api/mobile/lesson-feedback/' + q['id'] + '/followup'
        payload = feedback_payload(project, chat)
        started = client.post(route, json=payload)
        assert started.status_code == 200, started.text
        ident = started.json()['run_id']
        assert client.post(route, json=payload).json()['run_id'] == ident
        active = client.get('/api/mobile/chats').json()['runs'][0]
        assert active['state']['questionnaire_id'] == q['id']
        assert active['state']['kind'] == 'lesson_feedback'
        # The POST has finished; the model is deliberately held on the PC.
        assert client.get('/api/mobile/chat/' + ident).json()['status'] in ('queued', 'running')
        tutor.release.set()
        result = wait_run(client, ident, 'completed')
        assert result['content'].startswith('PHONE_SUPPLEMENT')
        assert tutor.identities == [device] and len(tutor.requests) == 1
        context = j(tutor.requests[0])
        assert 'TARGET_FEEDBACK_PARAGRAPH' in context and '本次是讲解后补讲' in context
        for private in ('UNSELECTED_BOOK_PARAGRAPH', 'REST_OF_SELECTED_PAGE_PRIVATE', 'OTHER_CHAT_PRIVATE_HISTORY'):
            assert private not in context
        assert '研究' in context and '中英' in context and '通俗' in context
        current = conversations.detail(chat['id'], project['id'])
        for name, value in original.items():
            assert current[name] == value, '补讲不能悄悄改写当前对话的选材或教学设置'
        assert one('SELECT status FROM sources WHERE id=?', (parent,))['status'] == 'stored'
        assert one('SELECT reply_status FROM lesson_questionnaires')['reply_status'] == 'completed'
        assert client.post(route, json=payload).json()['reused']
        assert client.post(route, json=feedback_payload(project, chat)).status_code == 409
        assert many('SELECT * FROM mastery') == [] and len(many('SELECT * FROM learning_events')) == 1
        assert len(many("SELECT * FROM messages WHERE conversation_id=? AND role='user'", (chat['id'],))) == 2


def test_phone_failed_followup_retries_without_duplicate_feedback_or_student_message(monkeypatch):
    project, chat, _, q, _, tutor, *_ = phone_lesson(monkeypatch)
    manager, client = mobile_client()
    with client:
        pair(manager, client)
        url = '/api/lesson-feedback/' + q['id']
        answer = {'difficulties': ['motivation'], 'other_text': '为什么需要附加条件？'}
        assert client.post(url + '/submit', json=answer).status_code == 200
        tutor.fail = True
        tutor.release.set()
        route = '/api/mobile/lesson-feedback/' + q['id'] + '/followup'
        first = client.post(route, json=feedback_payload(project, chat)).json()
        failed = wait_run(client, first['run_id'], 'failed')
        assert '暂时不可用' in failed['error']
        assert one('SELECT reply_status FROM lesson_questionnaires')['reply_status'] == 'failed'
        second = client.post(route, json=feedback_payload(project, chat)).json()
        wait_run(client, second['run_id'], 'completed')
        assert len(tutor.requests) == 2 and len(many('SELECT * FROM learning_events')) == 1
        assert len(many("SELECT * FROM messages WHERE conversation_id=? AND role='user'", (chat['id'],))) == 2


def test_phone_feedback_requires_original_project_chat_and_waits_for_busy_chat(monkeypatch):
    project, chat, another, q, _, tutor, *_ = phone_lesson(monkeypatch)
    manager, client = mobile_client()
    with client:
        pair(manager, client)
        route = '/api/mobile/lesson-feedback/' + q['id'] + '/followup'
        assert client.post(route, json=feedback_payload(project, chat)).status_code == 400
        assert client.post('/api/lesson-feedback/' + q['id'] + '/submit', json={'difficulties': ['terminology']}).status_code == 200
        assert client.post(route, json=feedback_payload(project, another)).status_code == 400
        other = create_project('其他项目')
        assert client.post(route, json=feedback_payload(other, chat)).status_code == 400
        normal = client.post('/api/mobile/chat', json={'request_id': uid(), 'request': {
            'project_id': project['id'], 'conversation_id': chat['id'], 'provider': 'deepseek',
            'model': 'current-tutor', 'text': '暂时不引用资料，只讨论概念。', 'include_materials': False}}).json()
        assert client.post(route, json=feedback_payload(project, chat)).status_code == 409
        assert one('SELECT reply_status FROM lesson_questionnaires')['reply_status'] == 'pending'
        stopped = client.post('/api/mobile/chat/' + normal['run_id'] + '/stop')
        assert stopped.status_code == 200
        wait_run(client, normal['run_id'], 'cancelled')
        tutor.release.set()
        started = client.post(route, json=feedback_payload(project, chat))
        assert started.status_code == 200, started.text
        wait_run(client, started.json()['run_id'], 'completed')


def test_phone_can_skip_questionnaire_without_ai_or_profile_change(monkeypatch):
    project, chat, _, q, _, tutor, *_ = phone_lesson(monkeypatch)
    manager, client = mobile_client()
    with client:
        pair(manager, client)
        url = '/api/lesson-feedback/' + q['id']
        assert client.post(url + '/submit', json={}).status_code == 400
        assert client.post(url + '/submit', json={'skip': True}).json()['status'] == 'skipped'
        assert client.post('/api/mobile/lesson-feedback/' + q['id'] + '/followup', json=feedback_payload(project, chat)).status_code == 400
        assert not tutor.requests and many('SELECT * FROM learning_events') == []
