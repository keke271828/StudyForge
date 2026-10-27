"""Actual native transports admit images before encoding, including lifecycle."""
import asyncio
import copy
import json
import threading
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from studyforge import ai, provider_clients, vision_batches
from studyforge.db import create_job, create_project, many, one
from studyforge.generation_control import GenerationControl, PausableClient
from studyforge.scheduling import execution_scope, model_slot, scheduler, wake_schedulers


@pytest.fixture(autouse=True)
def private_account(monkeypatch):
    monkeypatch.setattr(ai, 'get_secret', lambda _: 'fixture-account-only')
    monkeypatch.setattr(provider_clients, 'get_secret', lambda _: 'fixture-account-only')
    ai._VISION_CACHE.clear()
    yield
    ai._VISION_CACHE.clear()


def client(protocol='deepseek', runtime=None):
    if protocol == 'deepseek':
        return ai.DeepSeekClient('writer', vision_model='image-model', effort='high', agent_runtime=runtime)
    return (provider_clients.GeminiClient if protocol == 'gemini' else provider_clients.ServiceClient)(
        'svc_' + 'a' * 32, model='image-model', agent_runtime=runtime)


def service(monkeypatch, protocol):
    monkeypatch.setattr(provider_clients, 'get_service', lambda _: dict(
        name='Fixture API', protocol=protocol, base_url='https://fixture.invalid/v1',
        default_model='writer', requires_key=True, supports_vision=True, supports_json=True, supports_tools=False))


def frames(tmp_path, count=1):
    values = []
    for index in range(count):
        path = tmp_path / f'page-{index}.png'
        Image.new('RGB', (40, 50), (index * 10, 20, 30)).save(path)
        values.append(dict(id=str(index), path=path, locator=f'PDF 第 {index+1} 页', ocr=f'原始文字 {index}'))
    return values


def answer(request, protocol, text='本图观察'):
    if protocol == 'gemini':
        return httpx.Response(200, json=dict(candidates=[dict(content=dict(role='model', parts=[dict(text=text)]), finishReason='STOP')]))
    return httpx.Response(200, json=dict(choices=[dict(message=dict(role='assistant', content=text), finish_reason='stop')]))


def transport(monkeypatch, handler):
    native = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: native(*a, **(kw | {'transport': httpx.MockTransport(handler)})))


async def until(predicate):
    for _ in range(300):
        if predicate():
            return
        await asyncio.sleep(.005)
    raise AssertionError('Expected native request boundary was not reached')


@pytest.mark.parametrize('protocol', ['deepseek', 'openai', 'gemini'])
def test_busy_model_queue_keeps_only_paths_and_cancels_without_encoding(tmp_path, monkeypatch, protocol):
    service(monkeypatch, protocol)
    ai.save_settings({'model_concurrency': 1})
    native = vision_batches.image_messages
    encoded, posted = [], []
    def encode(items, **kwargs):
        encoded.append([item['id'] for item in items]); return native(items, **kwargs)
    monkeypatch.setattr(vision_batches, 'image_messages', encode)
    async def respond(request):
        posted.append(json.loads(request.content)); return answer(request, protocol)
    transport(monkeypatch, respond)
    items = frames(tmp_path, 5)
    async def run():
        instance = client(protocol)
        try:
            async with model_slot('unrelated-chat'):
                tasks = [asyncio.create_task(instance.analyze_image(item['path'], item['locator'], item['ocr'])) for item in items]
                await until(lambda: scheduler().snapshot()['model']['queued'] == 5)
                assert encoded == posted == []
                assert scheduler().snapshot()['image_prepare']['active'] == scheduler().snapshot()['image_prepare']['queued'] == 0
                tasks[0].cancel(); await asyncio.gather(tasks[0], return_exceptions=True)
                assert scheduler().snapshot()['model']['queued'] == 4
            assert await asyncio.gather(*tasks[1:]) == ['本图观察'] * 4
            assert len(encoded) == len(posted) == 4
            assert not scheduler().snapshot()['model']['active'] and not scheduler().snapshot()['model']['queued']
        finally:
            await instance.close()
    asyncio.run(run())


@pytest.mark.parametrize('protocol', ['deepseek', 'openai', 'gemini'])
def test_admitted_payload_matches_original_pixels_options_and_ocr(tmp_path, monkeypatch, protocol):
    service(monkeypatch, protocol)
    captured = []
    async def respond(request):
        captured.append(json.loads(request.content))
        return answer(request, protocol, '{"frames":[{"id":"0","observation":"原图的条件"},{"id":"1","observation":"原图的公式"}]}')
    transport(monkeypatch, respond)
    items = frames(tmp_path, 2)
    original = copy.deepcopy(items)
    instance = client(protocol)
    options = dict(model=instance.vision_model, stream=False, response_format={'type': 'json_object'},
                   messages=vision_batches.image_messages(items, structured=True))
    expected = instance.prepare_body(options)
    if protocol == 'gemini':
        expected = provider_clients.gemini_body(expected)
    async def run():
        try:
            descriptor = await vision_batches.image_request_body(instance, items, structured=True)
            assert isinstance(descriptor, vision_batches.DeferredImageBody)
            assert descriptor['messages'] == [] and 'data:image' not in json.dumps(descriptor)
            assert await instance.analyze_images(items) == {'0': '原图的条件', '1': '原图的公式'}
            assert descriptor['messages'] == []
        finally:
            await instance.close()
    asyncio.run(run())
    assert captured == [expected]
    assert items == original


def test_pause_during_real_encoder_stops_before_http_and_releases_model_for_other_project(tmp_path, monkeypatch):
    ai.save_settings({'model_concurrency': 1})
    project = create_project('Pause before outbound model request')
    job = create_job(project['id'], 'generate', {})
    control = GenerationControl(job)
    entered, release = threading.Event(), threading.Event()
    native = vision_batches.image_messages
    encodes, posted = [], []
    def encode(items, **kwargs):
        encodes.append(items[0]['locator'])
        if len(encodes) == 1:
            entered.set(); assert release.wait(3)
        return native(items, **kwargs)
    monkeypatch.setattr(vision_batches, 'image_messages', encode)
    async def respond(request):
        posted.append(json.loads(request.content)); return answer(request, 'deepseek')
    transport(monkeypatch, respond)
    item = frames(tmp_path)[0]
    async def run():
        instance = client(runtime=SimpleNamespace(project_id=project['id'], job_id=job, conversation_id=None))
        unrelated = client(runtime=SimpleNamespace(project_id='other-project', job_id=None, conversation_id=None))
        task = asyncio.create_task(PausableClient(instance, control).analyze_image(item['path'], item['locator'], item['ocr']))
        try:
            await until(entered.is_set)
            control.pause(); release.set()
            await until(lambda: one('SELECT status FROM jobs WHERE id=?', (job,))['status'] == 'paused')
            assert posted == [] and not scheduler().snapshot()['model']['active']
            assert await asyncio.wait_for(unrelated.analyze_image(item['path'], '无关项目原图', item['ocr']), 2) == '本图观察'
            assert not task.done() and len(posted) == 1
            control.resume(); assert await asyncio.wait_for(task, 2) == '本图观察'
            assert len(posted) == 2 and len(encodes) == 3
            assert len(many('SELECT * FROM generation_steps WHERE job_id=?', (job,))) == 1
        finally:
            release.set(); task.cancel(); await asyncio.gather(task, return_exceptions=True)
            await instance.close(); await unrelated.close(); control.finish()
    asyncio.run(run())


def test_cancel_active_encoder_releases_model_but_not_native_thread_slot(tmp_path, monkeypatch):
    ai.save_settings({'model_concurrency': 1})
    entered, release = threading.Event(), threading.Event()
    native = vision_batches.image_messages
    calls, posted = [], []
    def encode(items, **kwargs):
        calls.append(items[0]['id'])
        if len(calls) == 1:
            entered.set(); assert release.wait(3)
        return native(items, **kwargs)
    monkeypatch.setattr(vision_batches, 'image_messages', encode)
    async def respond(request):
        posted.append(request); return answer(request, 'deepseek')
    transport(monkeypatch, respond)
    items = frames(tmp_path, 2)
    async def run():
        instance = client()
        task = asyncio.create_task(instance.analyze_image(items[0]['path'], items[0]['locator']))
        second = None
        try:
            await until(entered.is_set)
            task.cancel(); await asyncio.gather(task, return_exceptions=True)
            assert scheduler().snapshot()['model']['active'] == 0
            assert scheduler().snapshot()['image_prepare']['active'] == 1 and posted == []
            second = asyncio.create_task(instance.analyze_image(items[1]['path'], items[1]['locator']))
            await until(lambda: scheduler().snapshot()['image_prepare']['queued'] == 1)
            assert len(calls) == 1 and posted == []
            release.set(); assert await asyncio.wait_for(second, 2) == '本图观察'
            assert len(calls) == 2 and len(posted) == 1
        finally:
            release.set()
            if second: second.cancel(); await asyncio.gather(second, return_exceptions=True)
            await instance.close()
    asyncio.run(run())


def test_encoder_failure_does_not_send_or_leak_model_slot(tmp_path, monkeypatch):
    native = vision_batches.image_messages
    calls = []
    def encode(items, **kwargs):
        calls.append(items[0]['id'])
        if len(calls) == 1: raise ValueError('本机图片损坏')
        return native(items, **kwargs)
    monkeypatch.setattr(vision_batches, 'image_messages', encode)
    posted = []
    async def respond(request):
        posted.append(request); return answer(request, 'deepseek')
    transport(monkeypatch, respond)
    item = frames(tmp_path)[0]
    async def run():
        instance = client()
        try:
            with pytest.raises(ValueError, match='损坏'):
                await instance.analyze_image(item['path'], item['locator'])
            assert not posted and scheduler().snapshot()['model']['active'] == scheduler().snapshot()['image_prepare']['active'] == 0
            assert await asyncio.wait_for(instance.analyze_image(item['path'], item['locator']), 2) == '本图观察'
        finally:
            await instance.close()
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['connection', 'empty-content'])
def test_retry_rebuilds_same_payload_and_retains_only_descriptor(tmp_path, monkeypatch, failure):
    posted, descriptors, prepared = [], [], []
    native = vision_batches.image_messages
    def encode(items, **kwargs):
        value = native(items, **kwargs); prepared.append(value); return value
    monkeypatch.setattr(vision_batches, 'image_messages', encode)
    native_post = ai.DeepSeekClient._post
    async def inspect(instance, body, *args, **kwargs):
        descriptors.append(body)
        assert body['messages'] == []
        result = await native_post(instance, body, *args, **kwargs)
        assert body['messages'] == []
        return result
    monkeypatch.setattr(ai.DeepSeekClient, '_post', inspect)
    async def respond(request):
        posted.append(json.loads(request.content))
        if len(posted) == 1:
            if failure == 'connection': raise httpx.ConnectError('fixture', request=request)
            return answer(request, 'deepseek', '')
        return answer(request, 'deepseek')
    transport(monkeypatch, respond)
    item = frames(tmp_path)[0]
    async def run():
        instance = client()
        try:
            assert await asyncio.wait_for(instance.analyze_image(item['path'], item['locator']), 3) == '本图观察'
            assert len(prepared) == 2 and posted[0] == posted[1]
            assert all(isinstance(value, vision_batches.DeferredImageBody) and value['messages'] == [] for value in descriptors)
            assert not scheduler().snapshot()['model']['active']
        finally:
            await instance.close()
    asyncio.run(run())


@pytest.mark.parametrize('parallel,limit,expected', [(True, 2, 2), (True, 3, 3), (False, 3, 1)])
def test_actual_image_requests_follow_existing_parallel_switch_and_limit(tmp_path, monkeypatch, parallel, limit, expected):
    ai.save_settings({'task_parallel_enabled': parallel, 'model_concurrency': limit})
    state = dict(active=0, peak=0)
    encoded = []
    native = vision_batches.image_messages
    def encode(items, **kwargs):
        encoded.append(items[0]['locator']); return native(items, **kwargs)
    monkeypatch.setattr(vision_batches, 'image_messages', encode)
    entered, release = asyncio.Event(), asyncio.Event()
    async def respond(request):
        state['active'] += 1; state['peak'] = max(state['peak'], state['active'])
        if state['active'] == expected: entered.set()
        try:
            await release.wait(); return answer(request, 'deepseek')
        finally:
            state['active'] -= 1
    transport(monkeypatch, respond)
    items = frames(tmp_path, 7)
    async def run():
        instance = client()
        tasks = [asyncio.create_task(instance.analyze_image(item['path'], item['locator'])) for item in items]
        try:
            await asyncio.wait_for(entered.wait(), 2)
            await until(lambda: scheduler().snapshot()['model']['queued'] == 7 - expected)
            assert len(encoded) == expected
            release.set(); assert await asyncio.gather(*tasks) == ['本图观察'] * 7
            assert state['peak'] == expected
        finally:
            release.set()
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True); await instance.close()
    asyncio.run(run())


def test_foreground_priority_and_resizing_apply_before_any_encoding(tmp_path, monkeypatch):
    ai.save_settings({'model_concurrency': 1})
    encoded, posted = [], []
    native = vision_batches.image_messages
    def encode(items, **kwargs):
        encoded.append(items[0]['locator']); return native(items, **kwargs)
    monkeypatch.setattr(vision_batches, 'image_messages', encode)
    release = asyncio.Event()
    async def respond(request):
        text = json.loads(request.content)['messages'][1]['content'][0]['text']
        posted.append(text)
        await release.wait(); return answer(request, 'deepseek')
    transport(monkeypatch, respond)
    item = frames(tmp_path)[0]
    async def run():
        instance = client()
        async def call(name, priority):
            async with execution_scope(priority=priority):
                return await instance.analyze_image(item['path'], name)
        try:
            async with model_slot('existing-chat'):
                back = asyncio.create_task(call('后台资料', 10))
                await until(lambda: scheduler().snapshot()['model']['queued'] == 1)
                front = asyncio.create_task(call('前台資料', 0))
                await until(lambda: scheduler().snapshot()['model']['queued'] == 2)
                assert encoded == []
                ai.save_settings({'model_concurrency': 2}); wake_schedulers()
                await until(lambda: len(posted) == 1)
                assert encoded == ['前台資料']
            release.set(); assert await asyncio.gather(front, back) == ['本图观察'] * 2
            assert encoded == ['前台資料', '后台资料']
        finally:
            release.set(); await instance.close()
    asyncio.run(run())


def test_library_reservation_uses_materialized_images_and_never_charges_queued_work(tmp_path, monkeypatch):
    from studyforge import library_policy
    from test_library_policy import job
    row, _, _ = job(tmp_path)
    ai.save_settings({'model_concurrency': 1})
    posted = []
    async def respond(request):
        posted.append(json.loads(request.content)); return answer(request, 'deepseek')
    transport(monkeypatch, respond)
    item = frames(tmp_path)[0]
    async def run():
        instance = client()
        async def read():
            async with execution_scope(library_reading=True, job_id=row['id']):
                return await instance.analyze_image(item['path'], item['locator'], item['ocr'])
        try:
            async with model_slot('existing-chat'):
                task = asyncio.create_task(read())
                await until(lambda: scheduler().snapshot()['model']['queued'] == 1)
                assert not many('SELECT * FROM library_model_usage') and not posted
            assert await task == '本图观察'
            usage = many('SELECT * FROM library_model_usage')
            assert len(usage) == 1 and usage[0]['reserved_tokens'] == library_policy.estimate(posted[0])
            assert usage[0]['reserved_tokens'] >= 4096 + 8192
        finally:
            await instance.close()
    asyncio.run(run())
