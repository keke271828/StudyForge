import asyncio
import json

import httpx
from PIL import Image

from studyforge import ai


def test_real_keepalive_for_text_and_stream_with_independent_fork(monkeypatch):
    """A real local HTTP socket verifies reuse and task isolation, without AI calls."""
    monkeypatch.setattr(ai, 'get_secret', lambda _: 'isolated-test-key')

    async def run():
        connections = 0
        requests = []
        handlers = set()

        async def respond(reader, writer):
            nonlocal connections
            connections += 1
            handlers.add(asyncio.current_task())
            try:
                while True:
                    try:
                        header = await reader.readuntil(b'\r\n\r\n')
                    except asyncio.IncompleteReadError:
                        return
                    headers = dict(line.split(':', 1) for line in header.decode().split('\r\n')[1:] if ':' in line)
                    body = json.loads(await reader.readexactly(int(headers['Content-Length'])))
                    requests.append((body, headers['Authorization'].strip()))
                    choice = {'choices': [{'finish_reason': 'stop', 'message': {'content': '完整正文'}}]}
                    payload = json.dumps(choice).encode()
                    kind = 'application/json'
                    if body.get('stream'):
                        payload = b'data: {"choices":[{"delta":{"content":"streamed"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
                        kind = 'text/event-stream'
                    writer.write((f'HTTP/1.1 200 OK\r\nContent-Type: {kind}\r\nContent-Length: {len(payload)}\r\nConnection: keep-alive\r\n\r\n').encode() + payload)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
                handlers.discard(asyncio.current_task())

        server = await asyncio.start_server(respond, '127.0.0.1', 0)
        monkeypatch.setattr(ai, 'DEEPSEEK_BASE', f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}')
        # Local test traffic must not go through a machine's proxy.
        monkeypatch.setenv('NO_PROXY', '127.0.0.1,localhost')
        parent = ai.DeepSeekClient('parent-model')
        child = parent.fork()
        try:
            for index in range(4):
                assert await parent.complete('规则', '原文 ' + str(index)) == '完整正文'
            packets = [packet async for packet in parent.stream_packets({'model': parent.model, 'messages': [], 'stream': True})]
            assert packets[0]['choices'][0]['delta']['content'] == 'streamed'
            assert connections == 1 and len(requests) == 5
            assert await child.complete('另一项规则', '独立原文') == '完整正文'
            await child.close()
            assert await parent.complete('规则', '后续原文') == '完整正文'
            assert connections == 2 and len(requests) == 7
            assert requests[-1][0]['messages'][-1]['content'] == '后续原文'
            assert all(auth == 'Bearer isolated-test-key' for _, auth in requests)
        finally:
            await parent.close()
            await parent.close()
            await child.close()
            server.close()
            await server.wait_closed()
            if handlers:
                await asyncio.wait_for(asyncio.gather(*tuple(handlers)), 2)

    asyncio.run(run())


def test_cancelled_stream_closes_response_before_task_client(monkeypatch):
    class Body(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\n\n'
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    body = Body()
    native = httpx.AsyncClient
    monkeypatch.setattr(ai, 'get_secret', lambda _: 'isolated-test-key')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: native(**kw, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=body, headers={'Content-Type': 'text/event-stream'}))))

    async def run():
        client = ai.DeepSeekClient('model')
        stream = client.stream_packets({'model': 'model', 'messages': [], 'stream': True})
        try:
            packet = await anext(stream)
            assert packet['choices'][0]['delta']['content'] == 'partial'
            await stream.aclose()
            assert body.closed
            connection = client.http_client()
            await client.close()
            assert connection.is_closed
        finally:
            await stream.aclose()
            await client.close()

    asyncio.run(run())


def test_image_progress_reports_failed_and_cached_frames_without_changing_original(tmp_path):
    parts = []
    for index in range(3):
        path = tmp_path / f'{index}.png'
        Image.new('RGB', (5, 5), (index, 0, 0)).save(path)
        parts.append({'kind': 'video_frame', 'locator': f'{index} 秒', 'text': '原始 OCR',
                      'meta': {'image_path': str(path)}})
    source = {'id': 'test-source', 'name': '教学视频', 'segments': parts,
              'read_manifest': {'limitations': []}}
    calls = []

    class Client:
        model = 'progress-model'

        async def analyze_image(self, path, locator, original):
            calls.append(path.name)
            if path.name == '1.png':
                raise RuntimeError('连接失败')
            return '已核实的画面内容'

    async def run():
        first = []
        digest, _ = await ai.source_digest(Client(), [source], on_image=lambda *value: first.append(value))
        assert [value[0] for value in first] == [0, 1, 2, 3]
        assert first[-1] == (3, 3, 1)
        assert '[画面分析待核实：RuntimeError]' in digest
        second = []
        await ai.source_digest(Client(), [source], on_image=lambda *value: second.append(value))
        assert second[-1] == (3, 3, 1) and len(calls) == 4

    asyncio.run(run())
    assert all(part['text'] == '原始 OCR' for part in parts)
    assert any('1 秒' in note for note in source['read_manifest']['limitations'])


def test_terminal_sse_does_not_wait_for_server_to_close_forever(monkeypatch):
    class OpenBody(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"complete"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    body = OpenBody()
    native = httpx.AsyncClient
    monkeypatch.setattr(ai, 'get_secret', lambda _: 'isolated-test-key')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: native(**kw, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=body, headers={'Content-Type': 'text/event-stream'}))))

    async def run():
        client = ai.DeepSeekClient('model')
        async def collect():
            return [packet async for packet in client.stream_packets({'model': 'model', 'messages': [], 'stream': True})]
        try:
            result = await asyncio.wait_for(collect(), 1)
            assert result[0]['choices'][0]['delta']['content'] == 'complete' and body.closed
        finally:
            await client.close()

    asyncio.run(run())
