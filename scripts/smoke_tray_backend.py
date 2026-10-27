"""Isolated native-tray acceptance backend. Never contacts a model provider."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import uvicorn
from fastapi import Header

from studyforge import ai, runtime, server, conversations
from studyforge.config import data_dir, files_dir
from studyforge.db import create_project, execute, j, many, now, one, uid, unj


if os.environ.get('STUDYFORGE_SMOKE_TRAY') != '1' or not os.environ.get('STUDYFORGE_SMOKE_REPORT'):
    raise RuntimeError('托盘自检后端只能在隔离验收模式运行')

runtime.manage_desktop_lifetime()
phase = int(os.environ['STUDYFORGE_TRAY_PHASE'])
ai.get_secret = server.get_secret = lambda name: None
ai.save_settings({'chat_provider': 'deepseek', 'deepseek_model': 'tray-test-model',
                  'background_learning_enabled': False, 'auto_select_imports': False})
case_file = data_dir() / 'tray-case.json'
if phase == 1:
    project = create_project('托盘隔离验收')
    chat = conversations.create(project['id'], 'deepseek', 'tray-test-model')
    conversations.activate(chat['id'])
    source = uid(); path = files_dir() / '托盘测试资料.txt'
    path.write_text('相关不能推出因果。因果推断需要额外假设和证据。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (source, project['id'], path.name, '.txt', str(path), 'ready', now()))
    case = {'project_id': project['id'], 'source_id': source, 'conversation_id': chat['id']}
    case_file.write_text(j(case), encoding='utf-8')
else:
    case = json.loads(case_file.read_text(encoding='utf-8'))

calls = []
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(180)'],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         **runtime.background_process_options())
(data_dir() / f'tray-process-{phase}.json').write_text(j({'backend_pid': os.getpid(), 'child_pid': child.pid}), encoding='utf-8')


class Client:
    def __init__(self, model, agent_runtime):
        self.model = model; self.effort = None; self.job = getattr(agent_runtime, 'job_id', None)

    async def complete(self, system, user, **kwargs):
        kind = 'exercise' if system == '托盘测试出题' else 'explanation'
        calls.append({'job_id': self.job, 'kind': kind, 'model': self.model})
        if kind == 'exercise' and phase == 1:
            await asyncio.Event().wait()  # A deliberately unfinished request at explicit exit.
        await asyncio.sleep(.6)
        return ('# 因果推断入门\n\n相关不能推出因果。[来源：托盘测试资料.txt｜第 1 段]\n\n'
                '因果推断需要额外假设和证据。\n\n## 系统性总结\n相关性是线索，因果判断还需要条件和依据。')

    async def close(self):
        pass


server.client_for = lambda provider, model=None, agent_runtime=None, **kwargs: Client(model, agent_runtime)


async def understand(*args, **kwargs):
    return []  # Automatic UI reading is isolated too; it must not call a real model.


async def generate_set(client, project_id, source_ids, *args, **kwargs):
    await client.complete('托盘测试出题', '说明为什么相关不能直接推出因果。')
    set_id = uid()
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
            (set_id, project_id, j(source_ids), '托盘恢复测试题', '[]', '[]', 2, 'assigned', now()))
    return set_id, []


server.understand_material = understand
server.generate_set = generate_set
server.student_document = lambda *args, **kwargs: '# 配套习题（无答案）\n说明为什么相关不能直接推出因果。'

# Test routes must precede the catch-all static-file route.
static_route = server.app.routes.pop()


@server.app.get('/qa/tray/info')
def info(x_studyforge_desktop_token: str | None = Header(default=None)):
    server.require_desktop_owner(x_studyforge_desktop_token)
    return dict(case, phase=phase, calls=calls, child_pid=child.pid, backend_pid=os.getpid(),
                child_containment=bool(runtime._job_handle),
                artifacts=[{'id': row['id'], 'kind': row['kind'], 'metadata': unj(row['metadata_json'], {})}
                           for row in many('SELECT * FROM artifacts')])


@server.app.post('/qa/tray/start/{name}')
async def start(name: str, x_studyforge_desktop_token: str | None = Header(default=None)):
    server.require_desktop_owner(x_studyforge_desktop_token)
    value = server.GenerateIn(project_id=case['project_id'], source_ids=[case['source_id']], provider='deepseek',
        model='tray-test-model', format='docx', summary_level=2, learning_mode='overview', exercises=name == 'resume',
        instructions='先解释因果推断的概念和适用条件；保持原来的讲解要求。')
    result = await server.generate(value)
    case[name + '_job'] = result['job_id']; case_file.write_text(j(case), encoding='utf-8')
    return result


@server.app.get('/qa/tray/steps/{job_id}')
def steps(job_id: str, x_studyforge_desktop_token: str | None = Header(default=None)):
    server.require_desktop_owner(x_studyforge_desktop_token)
    return {'count': one('SELECT COUNT(*) AS n FROM generation_steps WHERE job_id=?', (job_id,))['n']}


server.app.routes.append(static_route)
if __name__ == '__main__':
    uvicorn.run(server.app, host='127.0.0.1', port=int(os.environ['STUDYFORGE_PORT']), log_level='warning')
