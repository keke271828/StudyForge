"""Isolated local desktop fixture. No model inference or user data is touched."""
import asyncio
import os
import socket
from pathlib import Path

import httpx
import uvicorn
from PIL import Image, ImageDraw

from studyforge import ai, server, conversations
from studyforge.db import create_project, j, many, one


def main():
    case_path = Path(os.environ['STUDYFORGE_BACKGROUND_CASE'])
    root = case_path.parent
    phase = int(os.environ.get('STUDYFORGE_BACKGROUND_PHASE', '1'))
    if phase == 1:
        ai.save_settings({'chat_provider': 'deepseek', 'agent_tools_enabled': False, 'background_learning_enabled': False})
        project = create_project('背景与阅读验收')
        chat = conversations.create(project['id'], 'deepseek'); conversations.activate(chat['id'])
        image = Image.new('RGB', (2200, 1000))
        draw = ImageDraw.Draw(image)
        for x in range(2200):
            ratio = x / 2199
            draw.line((x, 0, x, 999), fill=(int(25+195*ratio), int(78+98*ratio), int(135-45*ratio)))
        for n in range(12):
            draw.ellipse((n*190-150, 360, n*190+350, 1300), fill=(50+n*8, 92+n*5, 92+n*7))
        image.save(root/'验收背景.png')
        image.transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(root/'第二张背景.png')
    else:
        project = one('SELECT * FROM projects ORDER BY created_at LIMIT 1')
    ai.get_secret = lambda name: None
    server.get_secret = ai.get_secret
    server.shutil.which = lambda name: None
    native = httpx.AsyncClient
    network = {'model_calls': 0, 'catalog_calls': 0}
    def mock(request):
        if request.method == 'POST':
            network['model_calls'] += 1
            return httpx.Response(500, json={'error': {'message': 'Background must not request model inference'}})
        network['catalog_calls'] += 1
        return httpx.Response(200, json={'data': []})
    class LocalOnly(native):
        def __init__(self, *args, **kwargs):
            kwargs['transport'] = httpx.MockTransport(mock)
            super().__init__(*args, **kwargs)
    httpx.AsyncClient = LocalOnly

    @server.app.get('/__background_test__/state')
    def inspect():
        return network | {key: len(many('SELECT * FROM '+key)) for key in ['sources', 'messages', 'jobs', 'learning_events']}
    mount = next(route for route in server.app.router.routes if getattr(route, 'name', None) == 'web')
    server.app.router.routes.remove(mount)
    server.app.router.routes.append(mount)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    case_path.write_text(j({'url': f'http://127.0.0.1:{port}', 'phase': phase, 'project_id': project['id']}), encoding='utf-8')
    uvicorn.run(server.app, host='127.0.0.1', port=port, log_level='warning')


if __name__ == '__main__':
    main()
