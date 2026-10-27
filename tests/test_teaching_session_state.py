"""Exercise real chat/provider plumbing when teaching settings change."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from studyforge import ai, conversations, server
from studyforge.agent_tools import AgentRuntime
from studyforge.codex_bridge import CodexBridge
from studyforge.db import create_project, execute, j, many, now, one, uid
from studyforge.teaching_policy import chat_policy_signature


def prepared_chat(tmp_path, monkeypatch):
    ai.save_settings({'agent_tools_enabled': False, 'background_learning_enabled': False})
    monkeypatch.setattr(ai, 'get_secret', lambda key: 'fixture-only')
    project = create_project('教学切换验收')
    chat = conversations.create(project['id'], 'deepseek', 'deepseek-flash', 'high',
                                explanation_style='clear', output_language='zh')
    source, path = uid(), tmp_path / 'definition.txt'
    path.write_text('原文证据哨兵：参数选择需要满足定义与成立条件。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (source, project['id'], path.name, '.txt', str(path), 'ready', now()))
    conversations.update(chat['id'], project['id'], {'source_ids': [source]})
    requests, native = [], httpx.AsyncClient

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        number = len(requests)
        packet = {'choices': [{'delta': {'content': f'可见讲解{number}，条件须核对。',
                                         'reasoning_content': f'HIDDEN_PROTOCOL_{number}'},
                                'finish_reason': 'stop'}]}
        return httpx.Response(200, text='data: ' + j(packet) + '\n\ndata: [DONE]\n\n')

    monkeypatch.setattr(httpx, 'AsyncClient', lambda *args, **kwargs: native(transport=httpx.MockTransport(respond)))
    args = {'project_id': project['id'], 'conversation_id': chat['id'], 'provider': 'deepseek',
            'source_ids': [source], 'model': 'deepseek-flash', 'reasoning_effort': 'high',
            'learning_mode': 'deep', 'explanation_style': 'clear', 'output_language': 'zh'}
    return project, chat, args, requests


def post_chat(api, args, text):
    response = api.post('/api/chat/stream', json=args | {'text': text})
    assert response.status_code == 200 and '"error"' not in response.text, response.text
    assert 'HIDDEN_PROTOCOL_' not in response.text
    return response


@pytest.mark.parametrize('change,expected', [
    ({'learning_mode': 'overview'}, '当前学习模式：概览'),
    ({'explanation_style': 'academic'}, '当前讲解风格：学术专业'),
    ({'output_language': 'en'}, '当前讲解语言：英语'),
    ({'reasoning_effort': 'off'}, None),
])
def test_switch_rebuilds_hidden_protocol_and_keeps_public_history(tmp_path, monkeypatch, change, expected):
    project, chat, args, requests = prepared_chat(tmp_path, monkeypatch)
    api = TestClient(server.app)
    post_chat(api, args, '第一问：这个参数为什么可选？')
    first_hidden_user = requests[0]['messages'][-1]['content']
    first_scope = one('SELECT scope_key FROM agent_dialogue_scopes WHERE conversation_id=?', (chat['id'],))['scope_key']
    post_chat(api, args, '第二问：请沿用前面的记号。')
    assert any(row.get('reasoning_content') == 'HIDDEN_PROTOCOL_1' for row in requests[1]['messages'])
    assert any(row['content'] == first_hidden_user for row in requests[1]['messages'])
    assert one('SELECT scope_key FROM agent_dialogue_scopes WHERE conversation_id=?', (chat['id'],))['scope_key'] == first_scope

    post_chat(api, args | change, '第三问：按新的设置补充理由。')
    current = requests[-1]
    assert not any(row.get('reasoning_content') in ('HIDDEN_PROTOCOL_1', 'HIDDEN_PROTOCOL_2') for row in current['messages'])
    # Plain user messages now agree with public history; private reasoning,
    # rather than the unchanged student words, identifies the old protocol.
    public = [(row['role'], row['content']) for row in current['messages'][1:-1]]
    assert public == [('user', '第一问：这个参数为什么可选？'), ('assistant', '可见讲解1，条件须核对。'),
                      ('user', '第二问：请沿用前面的记号。'), ('assistant', '可见讲解2，条件须核对。')]
    if expected:
        assert expected in current['messages'][0]['content']
    else:
        assert current['thinking']['type'] == 'disabled'
    assert one('SELECT scope_key FROM agent_dialogue_scopes WHERE conversation_id=?', (chat['id'],))['scope_key'] != first_scope
    saved = conversations.detail(chat['id'], project['id'])
    assert saved['source_ids'] == args['source_ids'] and len(saved['messages']) == 6
    assert '原文证据哨兵' in current['messages'][0]['content']
    assert len(requests) == 3, 'Changing settings must not add review/model calls.'


def test_policy_revision_rebuilds_only_hidden_protocol(tmp_path, monkeypatch):
    project, chat, args, requests = prepared_chat(tmp_path, monkeypatch)
    api = TestClient(server.app)
    post_chat(api, args, '旧版问题：为什么需要这个条件？')
    old_scope = one('SELECT scope_key FROM agent_dialogue_scopes WHERE conversation_id=?', (chat['id'],))['scope_key']
    monkeypatch.setattr(server, 'CHAT_RULES', server.CHAT_RULES + ' POLICY_REVISION_SENTINEL')
    post_chat(api, args, '新版追问：请继续。')
    assert not any(row.get('reasoning_content') == 'HIDDEN_PROTOCOL_1' for row in requests[-1]['messages'])
    assert 'POLICY_REVISION_SENTINEL' in requests[-1]['messages'][0]['content']
    assert requests[-1]['messages'][1]['content'] == '旧版问题：为什么需要这个条件？'
    assert requests[-1]['messages'][2]['content'] == '可见讲解1，条件须核对。'
    assert one('SELECT scope_key FROM agent_dialogue_scopes WHERE conversation_id=?', (chat['id'],))['scope_key'] != old_scope
    assert len(requests) == 2 and len(conversations.detail(chat['id'], project['id'])['messages']) == 4


def test_old_tail_protocol_is_rebuilt_once_then_new_plain_turns_reuse_it(tmp_path, monkeypatch):
    from studyforge.teaching import TEACHING_TASK_REMINDER
    project, chat, args, requests = prepared_chat(tmp_path, monkeypatch)
    original_signature = server.chat_policy_signature
    def old_signature(*a, **kw):
        return original_signature(*a, **dict(kw, task_reminder=TEACHING_TASK_REMINDER))
    api = TestClient(server.app)
    with monkeypatch.context() as old:
        old.setattr(server, 'chat_policy_signature', old_signature)
        post_chat(api, args, '旧问题：我已懂计算，只问为什么构造。')
    saved = one('SELECT messages_json FROM agent_dialogue_state WHERE conversation_id=?', (chat['id'],))
    protocol = json.loads(saved['messages_json'])
    next(row for row in protocol if row['role'] == 'user')['content'] += TEACHING_TASK_REMINDER
    execute('UPDATE agent_dialogue_state SET messages_json=? WHERE conversation_id=?', (j(protocol), chat['id']))
    post_chat(api, args, '新问题：只接上这个理由。')
    current = requests[-1]['messages']
    assert current[-1]['content'] == '新问题：只接上这个理由。'
    assert current[1]['content'] == '旧问题：我已懂计算，只问为什么构造。'
    assert not any(r.get('reasoning_content') == 'HIDDEN_PROTOCOL_1' for r in current)
    assert TEACHING_TASK_REMINDER not in j(current)
    assert '原文证据哨兵' in current[0]['content'] and '当前学习模式：精学' in current[0]['content']
    post_chat(api, args, '再问：沿用原来的记号。')
    assert any(r.get('reasoning_content') == 'HIDDEN_PROTOCOL_2' for r in requests[-1]['messages'])
    assert len(requests) == 3 and len(conversations.detail(chat['id'], project['id'])['messages']) == 6


def test_turn_and_branch_keep_their_teaching_snapshot(tmp_path):
    project = create_project('正在执行的教学任务')
    chat = conversations.create(project['id'], 'deepseek', 'deepseek-flash', 'high')
    signature = chat_policy_signature('deep', 'clear', 'zh')
    runtime = AgentRuntime(project['id'], conversation_id=chat['id'], effort='high', teaching_signature=signature)
    before = runtime.state_key()
    conversations.update(chat['id'], project['id'], {'learning_mode': 'research', 'explanation_style': 'academic', 'output_language': 'en'})
    assert runtime.state_key() == before
    child = runtime.fork()
    assert child.teaching_signature == signature and child.effort == 'high'
    assert child.branch_key is not None and child.cache is not runtime.cache
    next_turn = AgentRuntime(project['id'], conversation_id=chat['id'], effort='high',
                             teaching_signature=chat_policy_signature('research', 'academic', 'en'))
    assert next_turn.state_key() != before and next_turn.workspace == runtime.workspace


def test_codex_reuses_matching_teaching_and_restores_public_history_on_change(monkeypatch):
    project = create_project('Codex 教学切换')
    chat = conversations.create(project['id'], 'codex', 'fixture-model', 'high')
    bridge, requests = CodexBridge(), []

    async def start():
        pass

    async def request(method, params):
        requests.append((method, params))
        if method == 'thread/start':
            return {'thread': {'id': 'thread-' + str(len(requests)), 'ephemeral': True}}
        if method == 'turn/start':
            await bridge.events.put({'method': 'turn/completed', 'params': {'threadId': params['threadId'], 'turn': {'status': 'completed'}}})
        return {}

    monkeypatch.setattr(bridge, 'start', start)
    monkeypatch.setattr(bridge, 'request', request)

    async def scenario():
        clear = AgentRuntime(project['id'], conversation_id=chat['id'], effort='high',
                             teaching_signature=chat_policy_signature('deep', 'clear', 'zh'))
        first = [event async for event in bridge.stream_turn('首次问题', agent_runtime=clear)]
        remote = next(value for kind, value in first if kind == 'thread')
        second = [event async for event in bridge.stream_turn('相同配置追问', remote, agent_runtime=clear)]
        assert next(value for kind, value in second if kind == 'thread') == remote
        changed = AgentRuntime(project['id'], conversation_id=chat['id'], effort='high',
                               teaching_signature=chat_policy_signature('deep', 'balanced', 'zh'))
        third = [event async for event in bridge.stream_turn('切换后追问', remote, agent_runtime=changed,
                  fallback_history=j([{'role': 'user', 'content': '公开问题哨兵'}, {'role': 'assistant', 'content': '公开回答哨兵'}]))]
        assert next(value for kind, value in third if kind == 'thread') != remote

    asyncio.run(scenario())
    starts = [params for method, params in requests if method == 'thread/start']
    turns = [params for method, params in requests if method == 'turn/start']
    assert len(starts) == 2 and len(turns) == 3
    assert starts[0]['cwd'] == starts[1]['cwd'] and all(params['ephemeral'] for params in starts)
    assert '公开问题哨兵' in turns[-1]['input'][0]['text'] and '公开回答哨兵' in turns[-1]['input'][0]['text']
    assert many('SELECT * FROM messages WHERE conversation_id=?', (chat['id'],)) == []
