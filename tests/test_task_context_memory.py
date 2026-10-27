"""Release controller-only copies while preserving real task inputs and retries."""
import asyncio
from contextlib import contextmanager
import copy
import json
import sqlite3
import weakref

import httpx
import pytest
from docx import Document

from studyforge import ai, conversations, db, job_control, server, task_retry
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid, update_job
from studyforge.generation_control import active_generations, control_for
from studyforge.mobile_context import remote_device
from studyforge.scheduling import execution_context


class OriginalBuffer:
    def __init__(self, size=2_000_000):
        self.text = bytearray(size)


async def until(predicate):
    for _ in range(300):
        if predicate(): return
        await asyncio.sleep(.005)
    raise AssertionError('Expected task boundary was not reached')


def test_registered_task_projects_only_ownership_and_preserves_full_saved_intent():
    project = create_project('Metadata projection')
    payload = dict(conversation_id='own-chat', _mobile_device_id='own-device',
                   dialogue_snapshot={'messages': [{'role': 'user', 'content': 'PRIVATE_FULL_HISTORY' * 10000}]},
                   library_snapshot={'scope': ['scope-a', 'scope-b']})
    ident = create_job(project['id'], 'generate', payload)
    original = one('SELECT payload_json FROM jobs WHERE id=?', (ident,))['payload_json']
    assert job_control.execution_metadata(ident) == dict(project_id=project['id'], kind='generate',
        conversation_id='own-chat', mobile_device_id='own-device')
    seen = []
    async def work():
        seen.append((dict(execution_context.get()), remote_device.get()))
        update_job(ident, 'completed', 100)
        return {'completed': ['kept-output']}
    async def run():
        value = await job_control.start_job(ident, work)
        assert value == {'completed': ['kept-output']}
        assert not execution_context.get() and remote_device.get() is None
    asyncio.run(run())
    assert seen[0][0]['conversation_id'] == 'own-chat' and seen[0][0]['project_id'] == project['id']
    assert seen[0][1] == 'own-device'
    assert one('SELECT payload_json FROM jobs WHERE id=?', (ident,))['payload_json'] == original


def test_parallel_projects_keep_ownership_and_device_context_independent():
    projects = [create_project('Project A'), create_project('Project B')]
    ids = [create_job(project['id'], 'generate', dict(conversation_id=f'chat-{i}', _mobile_device_id=f'device-{i}'))
           for i, project in enumerate(projects)]
    seen = []
    async def work(index):
        await asyncio.sleep(.01)
        seen.append((index, dict(execution_context.get()), remote_device.get()))
        update_job(ids[index], 'completed', 100)
    async def run():
        await asyncio.gather(*(job_control.start_job(ident, lambda i=i: work(i)) for i, ident in enumerate(ids)))
        assert not execution_context.get() and remote_device.get() is None
    asyncio.run(run())
    for index, context, device in seen:
        assert context['project_id'] == projects[index]['id'] and context['conversation_id'] == f'chat-{index}'
        assert device == f'device-{index}'


def test_retry_backoff_reads_status_without_loading_payload_or_result(monkeypatch):
    project = create_project('Backoff status')
    ident = create_job(project['id'], 'generate', {'dialogue_snapshot': 'PRIVATE_SNAPSHOT' * 10000})
    task_retry.schedule('project', ident, httpx.ConnectError('fixture disconnect'))
    native = db.connect
    @contextmanager
    def protected():
        with native() as connection:
            connection.set_authorizer(lambda action, table, column, *_:
                sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and table == 'jobs' and
                column in ('payload_json', 'result_json') else sqlite3.SQLITE_OK)
            yield connection
    monkeypatch.setattr(db, 'connect', protected)
    async def run():
        task = asyncio.create_task(task_retry.wait_project(ident))
        await asyncio.sleep(.03)
        assert not task.done()
        task.cancel(); await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled()
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['plain', 'cause', 'node-group', 'exception-group'])
def test_saved_retry_decision_releases_failed_original_before_backoff_finishes(monkeypatch, failure):
    ai.save_settings({'task_auto_retry': True, 'task_retry_limit': 5})
    monkeypatch.setattr(task_retry, 'retry_delay', lambda *a: .5)
    project = create_project('Release failed original')
    ident = create_job(project['id'], 'generate', {'instructions': 'ORIGINAL_FROZEN_INSTRUCTION'})
    references, calls = [], []
    async def work():
        calls.append(one('SELECT payload_json FROM jobs WHERE id=?', (ident,))['payload_json'])
        if len(calls) == 1:
            original = OriginalBuffer(); references.append(weakref.ref(original))
            try:
                raise httpx.ConnectError('fixture connection reset')
            except Exception as cause:
                if failure == 'cause': raise RuntimeError('wrapped fixture error') from cause
                if failure == 'node-group': raise task_retry.NodeFailures('some node failed', [cause])
                if failure == 'exception-group': raise ExceptionGroup('independent failure group', [cause])
                raise
        update_job(ident, 'completed', 100, {'artifacts': ['already-saved-output']})
    async def run():
        task = job_control.start_job(ident, work)
        await until(lambda: (task_retry.public('project', ident) or {}).get('state') == 'waiting')
        assert references and references[0]() is None, 'Failed model frame must not retain its original buffer during backoff'
        assert not task.done()
        saved = task_retry.public('project', ident)
        assert saved['retry_count'] == 1 and saved['last_error'] and saved['reason']
        await asyncio.wait_for(task, 2)
        assert len(calls) == 2 and calls[0] == calls[1]
        assert task_retry.public('project', ident)['state'] == 'completed'
    asyncio.run(run())


def test_discarded_frames_do_not_change_http_reason_retry_after_or_side_effect_flag():
    observed = []
    def failed():
        original = OriginalBuffer(); observed.append(weakref.ref(original))
        request = httpx.Request('POST', 'https://fixture.invalid')
        response = httpx.Response(503, headers={'retry-after': '17'}, request=request)
        raise httpx.HTTPStatusError('service interrupted', request=request, response=response)
    try: failed()
    except Exception as error:
        before = task_retry.classify(error); delay = task_retry.retry_delay(1, error)
        attempt = task_retry.Attempt('project', 'fixture', error=error, unsafe_replay=True, failure_handled=True)
        task_retry.release_attempt_error(attempt)
        assert observed[0]() is None and attempt.error is None and error.__traceback__ is None
        assert task_retry.classify(error) == before and task_retry.retry_delay(1, error) == delay == 17
        assert attempt.unsafe_replay and attempt.failure_handled


def test_permanent_failure_is_preserved_and_buffer_released_without_retry():
    project = create_project('Permanent failure')
    ident = create_job(project['id'], 'generate', {})
    references = []
    async def work():
        original = OriginalBuffer(); references.append(weakref.ref(original))
        raise PermissionError('fixture file requires approval')
    async def run(): await job_control.start_job(ident, work)
    asyncio.run(run())
    assert references[0]() is None
    row = one('SELECT status,error FROM jobs WHERE id=?', (ident,))
    assert row['status'] == 'failed' and 'PermissionError' in row['error']
    assert task_retry.public('project', ident)['state'] == 'blocked'


def test_generation_uses_full_frozen_history_original_and_saved_teaching_settings(tmp_path, monkeypatch):
    ai.save_settings({'chat_provider': 'deepseek', 'background_learning_enabled': False, 'agent_tools_enabled': False})
    monkeypatch.setattr(ai, 'get_secret', lambda _: 'fixture-account')
    project = create_project('Frozen complete input')
    chat = conversations.create(project['id'], 'deepseek', 'saved-model')
    source = uid(); path = tmp_path / 'original.txt'
    text = '开头前提需要成立。\n' + '完整原文中的推导步骤。' * 1800 + '\n尾部条件不能省略。'
    path.write_text(text, encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (source, project['id'], path.name, '.txt', str(path), 'ready', now()))
    messages = [{'role': 'user', 'content': 'FROZEN_HISTORY_START\n' + '我的具体理解和疑问。' * 1000 + '\nFROZEN_HISTORY_END'},
                {'role': 'assistant', 'content': 'FROZEN_TEACHING_CONTEXT'}]
    snapshot = {'mentor': dict(id=chat['id'], project_id=project['id'], provider='deepseek', model='saved-model', reasoning_effort='high'),
                'messages': copy.deepcopy(messages)}
    value = server.GenerateIn(project_id=project['id'], conversation_id=chat['id'], source_ids=[source], provider='deepseek',
        model='saved-model', reasoning_effort='high', explanation_style='clear', learning_mode='deep', format='docx', review_mode='express')
    payload = value.model_dump() | dict(dialogue_snapshot=snapshot, explanation_style='balanced', learning_mode='overview', output_language='en')
    ident = create_job(project['id'], 'generate', payload)
    frozen = one('SELECT payload_json FROM jobs WHERE id=?', (ident,))['payload_json']
    execute('INSERT INTO messages VALUES (?,?,?,?,?)', (uid(), chat['id'], 'user', 'LATER_LIVE_CHAT_MUST_NOT_REPLACE_SNAPSHOT', now()))
    posted = []
    async def respond(request):
        body = json.loads(request.content); posted.append(body)
        answer = '# Preconditions and conclusions\n\nThe original conditions must hold. [original.txt｜行 1-3]\n\n## Systematic summary\nCheck each condition before using the conclusion.'
        return httpx.Response(200, text='data: '+j({'choices': [{'delta': {'content': answer}, 'finish_reason': 'stop'}]})+'\n\ndata: [DONE]\n\n')
    native = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: native(*a, **(kw | {'transport': httpx.MockTransport(respond)})))
    async def run(): await job_control.start_job(ident, server._generate_job(ident, value))
    asyncio.run(run())
    row = one('SELECT status,error FROM jobs WHERE id=?', (ident,))
    assert row['status'] == 'completed', row['error']
    # Find the writer by actual original content, independent of prompt labels.
    writer = next(body for body in posted if '完整原文中的推导步骤。' in j(body))
    request_text = j(writer)
    assert writer['model'] == 'saved-model' and writer['reasoning_effort'] == 'high'
    public = [{'role': message['role'], 'content': message['content']} for message in writer['messages']]
    assert all(message in public for message in messages)
    assert '开头前提需要成立' in request_text and '尾部条件不能省略' in request_text
    assert request_text.count('完整原文中的推导步骤。') == 1800
    assert 'LATER_LIVE_CHAT_MUST_NOT_REPLACE_SNAPSHOT' not in request_text
    artifact = many('SELECT path,metadata_json FROM artifacts')[0]
    metadata = json.loads(artifact['metadata_json'])
    assert metadata['learning_mode'] == 'overview' and metadata['explanation_style'] == 'balanced' and metadata['output_language'] == 'en'
    assert metadata['dialogue_message_count'] == 2 and metadata['conversation_id'] == chat['id']
    assert any('Systematic summary' in paragraph.text for paragraph in Document(artifact['path']).paragraphs)
    assert one('SELECT payload_json FROM jobs WHERE id=?', (ident,))['payload_json'] == frozen


def test_waiting_read_dependency_updates_only_reading_id_and_preserves_concurrent_payload_changes(tmp_path, monkeypatch):
    from test_task_scheduling import chat_material
    pid, cid, sid = chat_material(tmp_path)
    reading = create_job(pid, 'read', {'dialogue_snapshot': 'private reading history' * 10000})
    value = server.GenerateIn(project_id=pid, conversation_id=cid, source_ids=[sid], provider='deepseek', reading_job_id=reading)
    ident = create_job(pid, 'generate', value.model_dump() | {'extra_future_field': 'original'})
    class NoInference(Exception): pass
    async def stop_after_dependency(_): raise NoInference('intent saved before original reading')
    monkeypatch.setattr(server, 'generation_input_records', stop_after_dependency)
    async def run():
        task = asyncio.create_task(server._generate_job(ident, value))
        await until(lambda: 'reading_dependency' in one('SELECT result_json FROM jobs WHERE id=?', (ident,))['result_json'])
        execute("UPDATE jobs SET payload_json=json_set(payload_json,'$.extra_future_field','updated while waiting') WHERE id=?", (ident,))
        update_job(reading, 'completed', 100, {'reading_id': 'sealed-reading-id'})
        await asyncio.wait_for(task, 2)
    asyncio.run(run())
    stored = json.loads(one('SELECT payload_json FROM jobs WHERE id=?', (ident,))['payload_json'])
    assert stored['reading_id'] == 'sealed-reading-id' and stored['extra_future_field'] == 'updated while waiting'
    assert stored['conversation_id'] == cid and stored['source_ids'] == [sid]


def test_retry_import_still_restores_source_status_and_cancel_updates_only_its_source(tmp_path):
    project = create_project('Import status projection')
    source = uid(); path = tmp_path / 'file.txt'; path.write_text('original', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (source, project['id'], path.name, '.txt', str(path), 'error', now()))
    ident = create_job(project['id'], 'import', {'source_id': source, 'dialogue_snapshot': 'PRIVATE_UNNEEDED' * 10000})
    assert task_retry.schedule('project', ident, httpx.ConnectError('fixture disconnect'))
    assert one('SELECT status FROM sources WHERE id=?', (source,))['status'] == 'pending'
    asyncio.run(job_control.cancel_job(ident))
    assert one('SELECT status,error FROM sources WHERE id=?', (source,))['status'] == 'error'
    assert one('SELECT status FROM jobs WHERE id=?', (ident,))['status'] == 'cancelled'
