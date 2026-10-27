import asyncio
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from studyforge import server
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid
from studyforge.config import data_dir


def material(tmp_path, text='开头：社会制度。\n末尾：理论有适用边界。'):
    project = create_project('社会科学')
    source_id = uid()
    path = tmp_path / 'original.txt'
    path.write_text(text, encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,error,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
            (source_id, project['id'], '原文.txt', '.txt', str(path), j([dict(locator='预览', text='不能用于生成的旧摘要')]), 'ready', None, now()))
    return project, source_id, path


def conversation(project_id, sources, text='请用概念对照表讲解，解释作者的历史背景。'):
    conversation_id = uid()
    execute('INSERT INTO conversations(id,project_id,provider,remote_thread_id,created_at,source_ids_json) VALUES (?,?,?,?,?,?)',
            (conversation_id, project_id, 'codex', None, now(), j(sources)))
    execute('INSERT INTO messages VALUES (?,?,?,?,?)', (uid(), conversation_id, 'user', text, now()))
    return conversation_id


def test_reading_covers_long_original_and_reuses_only_unchanged_sources(tmp_path, monkeypatch):
    project, source_id, path = material(tmp_path, '开头重要定义。\n' + '论证细节。' * 18000 + '\n末尾限制：不能推广到所有制度。')
    calls = []
    class Client:
        model = 'test'
        async def complete(self, system, user):
            calls.append(user)
            assert '不能用于生成的旧摘要' not in user
            return '## 阅读笔记\n明确概念与限制。'
    monkeypatch.setattr(server, 'client_for', lambda *args, **kwargs: Client())
    value = server.ReadIn(project_id=project['id'], source_ids=[source_id], model='test', generation_quality='custom')
    def read():
        job_id = create_job(project['id'], 'read', value.model_dump())
        asyncio.run(server._read_job(job_id, value))
        job = one('SELECT * FROM jobs WHERE id=?', (job_id,))
        assert job['status'] == 'completed', job['error']
        return json.loads(job['result_json'])
    first = read()
    assert len(calls) >= 2 and '开头重要定义' in calls[0] and '末尾限制' in calls[-1]
    count = len(calls)
    second = read()
    assert second['cached'] and second['reading_id'] == first['reading_id'] and len(calls) == count
    path.write_text('修改后的原文：新的限制条件。', encoding='utf-8')
    third = read()
    assert not third['cached'] and third['reading_id'] != first['reading_id'] and '修改后的原文' in calls[-1]


def test_generation_combines_reading_chat_and_current_instructions_with_full_source(tmp_path, monkeypatch):
    project, source_id, path = material(tmp_path)
    calls = []
    class Client:
        model = 'test'
        async def complete(self, system, user, **kwargs):
            calls.append((system, user))
            if '只整理交接' in system:
                messages = json.loads(user)['messages']
                return json.dumps({'learning_goal': '理解制度', 'instructions': [
                    {'instruction': row['content'], 'evidence': [{'message_id': row['id'], 'quote': row['content']}]} for row in messages if row['role'] == 'user'],
                    'understanding': [], 'teaching_strategy': [], 'unresolved_questions': []})
            if '通读理解资料' in system:
                return '阅读笔记：制度概念及其适用边界。'
            return '# 制度的概念对照\n正文。\n\n## 系统性总结\n概念和边界。'
    monkeypatch.setattr(server, 'client_for', lambda *args, **kwargs: Client())
    read = server.ReadIn(project_id=project['id'], source_ids=[source_id], model='test', generation_quality='custom')
    read_job = create_job(project['id'], 'read', read.model_dump())
    asyncio.run(server._read_job(read_job, read))
    reading_id = json.loads(one('SELECT result_json FROM jobs WHERE id=?', (read_job,))['result_json'])['reading_id']
    conversation_id = conversation(project['id'], [source_id])
    value = server.GenerateIn(project_id=project['id'], source_ids=[source_id], conversation_id=conversation_id,
                              reading_id=reading_id, instructions='改为按概念的历史演变组织，仍保留对照表。')
    job_id = create_job(project['id'], 'generate', value.model_dump())
    asyncio.run(server._generate_job(job_id, value))
    assert one('SELECT status FROM jobs WHERE id=?', (job_id,))['status'] == 'completed'
    system, user = calls[-1]
    assert all(text in user for text in ('概念对照表', '历史演变', '阅读笔记', '末尾：理论有适用边界'))
    assert '不能用于生成的旧摘要' not in user and '最新要求优先' in system
    assert len(many('SELECT * FROM artifacts')) == 1
    path.write_text('已修改', encoding='utf-8')
    stale_job = create_job(project['id'], 'generate', value.model_dump())
    count = len(calls)
    asyncio.run(server._generate_job(stale_job, value))
    stale = one('SELECT * FROM jobs WHERE id=?', (stale_job,))
    assert stale['status'] == 'failed' and '原资料已变更' in stale['error'] and len(calls) == count


def test_unrelated_conversation_cannot_change_current_explanation(tmp_path, monkeypatch):
    project, source_id, _ = material(tmp_path)
    other = create_project('其他项目')
    conversation_id = conversation(other['id'], ['another-source'])
    response = TestClient(server.app).post('/api/generate', json={
        'project_id': project['id'], 'source_ids': [source_id], 'conversation_id': conversation_id,
        'generation_quality': 'custom', 'provider': 'codex'})
    assert response.status_code == 400 and '不匹配' in response.json()['detail']


def test_chat_reads_full_original_and_uses_authoritative_final(tmp_path, monkeypatch):
    project, source_id, _ = material(tmp_path)
    prompts = []
    async def stream(prompt, *args, **kwargs):
        prompts.append(prompt)
        yield 'thread', 'test-thread'
        yield 'delta', '不完整的流式回答'
        yield 'final', '完整回答：$E=mc^2$。哪个步骤需要再解释？'
    monkeypatch.setattr('studyforge.codex_bridge.CodexBridge.stream_turn',lambda self,*args,**kwargs:stream(*args,**kwargs))
    response = TestClient(server.app).post('/api/chat/stream', json={
        'project_id': project['id'], 'source_ids': [source_id], 'text': '解释边界条件。'})
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert '末尾：理论有适用边界' in prompts[0] and '旧摘要' not in prompts[0]
    from studyforge.teaching import TEACHER_PERSONA,CHAT_RULES,TEACHING_TASK_REMINDER
    assert prompts[0].startswith(TEACHER_PERSONA+CHAT_RULES) and TEACHING_TASK_REMINDER not in prompts[0]
    assert prompts[0].endswith('用户：解释边界条件。')
    final = next(item['value'] for item in events if item['type'] == 'replace')
    assert one("SELECT content FROM messages WHERE role='assistant'")['content'] == final
    conversation_id = next(item['value'] for item in events if item['type'] == 'conversation')
    changed = TestClient(server.app).post('/api/chat/stream', json={
        'project_id': project['id'], 'source_ids': [], 'text': '新资料', 'conversation_id': conversation_id})
    assert changed.status_code == 200
    assert one('SELECT source_ids_json FROM conversations WHERE id=?', (conversation_id,))['source_ids_json'] == '[]'


def test_upgrade_keeps_old_project_and_conversation():
    path = data_dir() / 'studyforge.sqlite3'
    with sqlite3.connect(path) as database:
        database.executescript('CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT NOT NULL);'
          'CREATE TABLE conversations(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,provider TEXT NOT NULL,remote_thread_id TEXT,created_at TEXT NOT NULL);')
        database.execute('INSERT INTO projects VALUES (?,?,?)', ('old-project', '原有学习项目', now()))
        database.execute('INSERT INTO conversations VALUES (?,?,?,?,?)', ('old-conversation', 'old-project', 'codex', 'original-thread', now()))
    assert one('SELECT * FROM projects')['name'] == '原有学习项目'
    old = one('SELECT * FROM conversations')
    assert old['remote_thread_id'] == 'original-thread' and old['source_ids_json'] == '[]'
    assert many('SELECT * FROM reading_sessions') == []
    assert old['model'] is None and old['reasoning_effort'] is None
    assert many('SELECT * FROM mentor_handoffs') == []
