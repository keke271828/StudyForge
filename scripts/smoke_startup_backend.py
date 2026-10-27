"""An isolated boot check, with model access disabled and a real mobile listener."""
import json
import os
import socket

if os.environ.get('STUDYFORGE_SMOKE_STARTUP') != '1' or not os.environ.get('STUDYFORGE_SMOKE_REPORT'):
    raise RuntimeError('Startup acceptance requires an isolated test directory')

from studyforge import ai, runtime, server, conversations, mobile_access
from studyforge.config import data_dir
from studyforge.db import create_project

runtime.manage_desktop_lifetime()
ai.get_secret = server.get_secret = lambda name: None
ai.save_settings({'chat_provider': 'deepseek', 'background_learning_enabled': False})
project = create_project('开机自动启动验收')
conversations.activate(conversations.create(project['id'], 'deepseek')['id'])
with socket.socket() as listener:
    listener.bind(('127.0.0.1', 0))
    mobile_port = listener.getsockname()[1]
directory = data_dir() / 'mobile'
directory.mkdir(parents=True, exist_ok=True)
(directory / 'connection.json').write_text(json.dumps({'auto_start': True, 'port': mobile_port}), encoding='utf-8')
mobile_access.lan_addresses = lambda: ['127.0.0.1']

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(server.app, host='127.0.0.1', port=int(os.environ['STUDYFORGE_PORT']))
