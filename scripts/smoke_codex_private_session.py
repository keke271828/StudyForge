"""Check real Codex continuity, hidden history and cold recovery from app records."""
import asyncio
import json
import os
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = Path(tempfile.mkdtemp(prefix='codex-private-', dir=root / 'build'))
os.environ['STUDYFORGE_DATA_DIR'] = str(target / 'data')

from studyforge import server
from studyforge.ai import save_settings
from studyforge.agent_tools import AgentRuntime
from studyforge.db import create_project, j, one, uid


async def chat(value):
    response = await server.chat_stream(value)
    events = [json.loads(item) async for item in response.body_iterator]
    errors = [item['value'] for item in events if item['type'] == 'error']
    if errors: raise RuntimeError(str(errors))
    return events


async def main():
    model = server.get_settings().get('codex_local_default') or None
    save_settings({'chat_provider': 'codex'})
    project = create_project('独立 Agent 会话验收'); token = '学习测试-' + uid()[:8]
    print('真实 Codex：建立不保存到外部历史的学习会话并创建工作区文件。', flush=True)
    first = await chat(server.ChatIn(project_id=project['id'], provider='codex', model=model,
        text=f'本次测试口令是“{token}”。请调用 sf_write_text 在工作目录创建 isolation.txt，完整写入该口令；之后用一句话确认，不联网。'))
    conversation = next(item['value'] for item in first if item['type'] == 'conversation')
    remote = one('SELECT remote_thread_id FROM conversations WHERE id=?', (conversation,))['remote_thread_id']
    workspace = AgentRuntime(project['id'], provider='codex').workspace
    assert (workspace / 'isolation.txt').read_text(encoding='utf-8') == token
    metadata = (await server.bridge.request('thread/read', {'threadId': remote, 'includeTurns': False}))['thread']
    assert metadata['ephemeral'] is True and metadata.get('path') is None
    assert Path(metadata['cwd']).resolve() == workspace.resolve()
    listed = await server.bridge.request('thread/list', {'cwd': str(workspace), 'limit': 100})
    assert remote not in [row['id'] for row in listed.get('data', [])], listed
    second = await chat(server.ChatIn(project_id=project['id'], provider='codex', model=model, conversation_id=conversation,
        text='刚才的测试口令是什么？只返回原口令，不使用任何工具。'))
    assert token in next(item['value'] for item in second if item['type'] == 'replace')
    assert one('SELECT remote_thread_id FROM conversations WHERE id=?', (conversation,))['remote_thread_id'] == remote
    print('重启软件自身的 Agent 服务，检查本地聊天恢复；不关闭用户 Codex。', flush=True)
    await server.bridge.close()
    third = await chat(server.ChatIn(project_id=project['id'], provider='codex', model=model, conversation_id=conversation,
        text='继续这段学习对话：再次只返回原测试口令，不使用任何工具。'))
    assert token in next(item['value'] for item in third if item['type'] == 'replace')
    restarted = one('SELECT remote_thread_id FROM conversations WHERE id=?', (conversation,))['remote_thread_id']
    assert restarted != remote
    listed = await server.bridge.request('thread/list', {'cwd': str(workspace), 'limit': 100})
    assert not any(row['id'] in (remote, restarted) for row in listed.get('data', []))
    result = {'provider': 'codex', 'model': model, 'ephemeral': True, 'external_history_absent': True,
              'workspace': str(workspace), 'same_live_thread': True, 'recovered_after_agent_restart': True}
    (target / 'result.json').write_text(j(result), encoding='utf-8'); print(j(result), flush=True)


async def run():
    try: await main()
    finally: await server.bridge.close()


asyncio.run(run())
