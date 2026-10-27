import asyncio
import copy
import json

import pytest
from PIL import Image

from studyforge import ai
from studyforge.generation_control import PausableClient, control_for
from studyforge.db import create_job, create_project
from studyforge.vision_batches import BATCH_SIZE, observations


def frames(tmp_path, count=9):
    parts = []
    for index in range(count):
        path = tmp_path / f'frame-{index}.png'
        Image.new('RGB', (16, 16), (index, 0, 0)).save(path)
        parts.append({'locator': f'{index} 秒', 'text': f'原文-{index}',
                      'meta': {'image_path': str(path)}, 'kind': 'video_frame'})
    return {'id': 'video', 'name': '逐图证据', 'segments': parts}


def test_batched_reading_preserves_every_original_and_location_and_cache(tmp_path):
    batches, singles, progress = [], [], []
    class Client:
        model = 'vision-fixture'
        effort = 'high'
        async def analyze_images(self, batch):
            batches.append(batch)
            return {frame['id']: '核对 ' + frame['ocr'] for frame in batch}
        async def analyze_image(self, path, locator, text):
            singles.append(text)
            return '核对 ' + text
    source = frames(tmp_path)
    original = copy.deepcopy(source)
    async def run():
        client = Client()
        first, _ = await ai.source_digest(client, [source], on_image=lambda *args: progress.append(args))
        assert len(batches) == 2 and len(singles) == 1
        assert all(len(batch) <= BATCH_SIZE for batch in batches)
        for index in range(9):
            assert f'[来源 逐图证据｜{index} 秒]' in first
            assert f'原文-{index}\n[画面分析] 核对 原文-{index}' in first
        assert [item[0] for item in progress] == list(range(10))
        assert all(item[2] == 0 for item in progress)
        ai._VISION_CACHE.clear()
        second, _ = await ai.source_digest(client, [source])
        assert first == second and len(batches) == 2 and len(singles) == 1
        Image.new('RGB', (16, 16), 'blue').save(source['segments'][0]['meta']['image_path'])
        await ai.source_digest(client, [source])
        assert len(singles) == 2 and len(batches) == 2
        client.effort = 'low'
        await ai.source_digest(client, [source])
        assert len(batches) == 4 and len(singles) == 3
    asyncio.run(run())
    assert source == original


@pytest.mark.parametrize('invalid', [False, True])
def test_partial_or_invalid_batch_retries_only_unresolved_images(tmp_path, invalid):
    singles = []
    class Client:
        async def analyze_images(self, batch):
            if invalid: return {'foreign-image-id': '不能错配到原图'}
            return {'0': '第一张有图', '2': '第三张有图', '3': '第四张有图'}
        async def analyze_image(self, path, locator, text):
            singles.append(text)
            if text == '原文-1': raise RuntimeError('本张不可读取')
            return '单图补读 ' + text
    result, _ = asyncio.run(ai.source_digest(Client(), [frames(tmp_path, 4)]))
    assert singles == ([f'原文-{i}' for i in range(4)] if invalid else ['原文-1'])
    assert result.count('[画面分析待核实：RuntimeError]') == 1
    assert '不能错配到原图' not in result
    assert all(f'原文-{i}' in result for i in range(4))


def test_duplicate_image_ids_cannot_override_evidence():
    with pytest.raises(ValueError, match='重复'):
        observations({'frames': [{'id': '0', 'observation': ''}, {'id': '0', 'observation': '替换'}]}, ['0'])
    assert observations({'frames': [{'id': '1', 'observation': '图一'}]}, ['0', '1']) == {'1': '图一'}


def test_batch_respects_pause_and_reuses_completed_checkpoint(tmp_path):
    source = frames(tmp_path, 2)
    batch = [{'id': str(i), 'path': item['meta']['image_path'], 'locator': item['locator'], 'ocr': item['text']}
             for i, item in enumerate(source['segments'])]
    calls = []
    class Client:
        async def analyze_images(self, value):
            calls.append(value)
            return {'0': '图零', '1': '图一'}
    project = create_project('暂停多图验收')
    job = create_job(project['id'], 'generate', {})
    control = control_for(job)
    async def run():
        wrapped = PausableClient(Client(), control)
        control.pause()
        task = asyncio.create_task(wrapped.analyze_images(batch))
        await asyncio.sleep(.02)
        assert calls == [] and not task.done()
        control.resume()
        assert await task == {'0': '图零', '1': '图一'}
        assert await wrapped.analyze_images(batch) == {'0': '图零', '1': '图一'}
        assert len(calls) == 1
    try: asyncio.run(run())
    finally: control.finish()


@pytest.mark.parametrize('effort,expected', [('none', None), ('low', 'low'), ('medium', 'high'), ('xhigh', 'high'), ('max', 'max')])
def test_native_deepseek_sends_selected_effort_to_text_and_image_calls(tmp_path, monkeypatch, effort, expected):
    monkeypatch.setattr(ai, 'get_secret', lambda _: 'fixture-key')
    ai.save_settings({'deepseek_vision_model': 'selected-vision'})
    client = ai.DeepSeekClient('selected-writer', effort=effort)
    bodies = []
    async def request(body, **kwargs):
        from studyforge.vision_batches import resolve_request_body
        body = await resolve_request_body(body)
        bodies.append(body)
        return json.dumps({'frames': [{'id': str(i), 'observation': '本图核对'} for i in range(2)]})
    monkeypatch.setattr(client, '_request_content', request)
    source = frames(tmp_path, 2)
    batch = [{'id': str(i), 'path': item['meta']['image_path'], 'locator': item['locator'], 'ocr': item['text']}
             for i, item in enumerate(source['segments'])]
    async def run():
        await client.complete('正文要求', '原文')
        await client.analyze_image(batch[0]['path'], '单图', '原文')
        await client.analyze_images(batch)
    asyncio.run(run())
    assert bodies[0]['model'] == 'selected-writer'
    assert bodies[1]['model'] == bodies[2]['model'] == 'selected-vision'
    for body in bodies:
        assert body['thinking']['type'] == ('disabled' if expected is None else 'enabled')
        assert body.get('reasoning_effort') == expected
    assert sum(item['type'] == 'image_url' for item in bodies[2]['messages'][1]['content']) == 2
    explicit = {'thinking': {'type': 'disabled'}, 'messages': []}
    assert client.prepare_body(explicit) == explicit


def test_third_party_batch_uses_its_own_vision_model_and_protocol(tmp_path, monkeypatch):
    from studyforge import provider_clients
    monkeypatch.setattr(provider_clients, 'get_service', lambda _: {
        'name': '自定义视觉服务', 'default_model': 'own-model', 'requires_key': False,
        'supports_vision': True, 'supports_json': False, 'supports_tools': False})
    monkeypatch.setattr(provider_clients, 'get_secret', lambda _: '')
    client = provider_clients.ServiceClient('svc_' + 'a' * 32, model='own-selected-model')
    bodies = []
    async def request(body, **kwargs):
        from studyforge.vision_batches import resolve_request_body
        body = await resolve_request_body(body)
        bodies.append(body)
        return '{"frames":[{"id":"0","observation":"本图核对"}]}'
    monkeypatch.setattr(client, '_request_content', request)
    image = frames(tmp_path, 1)['segments'][0]
    asyncio.run(client.analyze_images([{'id': '0', 'path': image['meta']['image_path'], 'locator': '原图', 'ocr': ''}]))
    assert bodies[0]['model'] == 'own-selected-model'
    assert 'response_format' not in bodies[0] and 'thinking' not in bodies[0]


def test_native_effort_survives_chat_settings_and_document_snapshot(tmp_path, monkeypatch):
    from studyforge import server
    from studyforge.db import execute, j, now, one, uid
    monkeypatch.setattr(ai, 'get_secret', lambda _: 'fixture-key')
    ai.save_settings({'chat_provider': 'deepseek', 'chat_effort_deepseek': 'low'})
    requests = []
    async def packets(self, body):
        requests.append(body)
        yield {'choices': [{'delta': {'content': '# 高斯定律\n电通量与包围的净电荷有关。\n\n## 系统性总结\n区分总电场和包围电荷。'},
                             'finish_reason': 'stop'}]}
    async def forbidden(*args, **kwargs): raise AssertionError('Native DeepSeek 不得请求 Codex')
    monkeypatch.setattr(ai.DeepSeekClient, 'stream_packets', packets)
    monkeypatch.setattr(server.model_catalog, 'validate_effort', forbidden)
    project = create_project('原生推理档位')
    path = tmp_path / 'gauss.txt'
    path.write_text('高斯定律：闭合曲面的电通量取决于其包围的净电荷。', encoding='utf-8')
    source = uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (source, project['id'], path.name, '.txt', str(path), '[]', 'ready', now()))
    async def run():
        response = await server.chat_stream(server.ChatIn(project_id=project['id'], source_ids=[source],
            provider='deepseek', model='deepseek-flash', reasoning_effort='low', text='解释这份资料'))
        events = [json.loads(event) async for event in response.body_iterator]
        assert not any(event['type'] == 'error' for event in events)
        conversation = next(event['value'] for event in events if event['type'] == 'conversation')
        assert one('SELECT reasoning_effort FROM conversations WHERE id=?', (conversation,))['reasoning_effort'] == 'low'
        value = server.GenerateIn(project_id=project['id'], source_ids=[source], conversation_id=conversation,
            provider='deepseek', model='deepseek-flash', reasoning_effort='low', review_mode='express')
        await server.choose_generation_model(value)
        job = create_job(project['id'], 'generate', value.model_dump())
        await server._generate_job(job, value)
        assert one('SELECT status,error FROM jobs WHERE id=?', (job,))['status'] == 'completed'
        assert server.mentor_snapshot(server.GenerateIn(project_id=project['id'], source_ids=[source],
            provider='deepseek', reasoning_effort='high'))['mentor']['reasoning_effort'] == 'high'
    asyncio.run(run())
    assert len(requests) == 2
    assert all(body['thinking'] == {'type': 'enabled'} and body['reasoning_effort'] == 'low' for body in requests)
    assert ai.settings()['chat_effort_deepseek'] == 'low'
