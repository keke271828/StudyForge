import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from studyforge import server
from studyforge.db import create_project, execute, j, many, now, one, uid


def assignment(status='feynman_required', language='javascript'):
    project = create_project('费曼进阶审计')
    parent = uid()
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
            (parent, project['id'], '[]', '字符串边界',
             j([{'index':0, 'question':'限定 ASCII 边界，定义 countKey', 'topic':'字符串边界', 'language':language}]),
             j([{'index':0, 'solution':'原私有参考算法', 'rubric':'边界判断', 'test_code':'私有测试'}]), 2, status, now()))
    return parent


class Grader:
    def __init__(self): self.closed = 0; self.calls = []
    async def complete(self, system, user, **kwargs):
        self.calls.append(user)
        return json.dumps({'score':80, 'passed':True, 'feedback':'通过', 'gaps':[]})
    async def close(self): self.closed += 1


def install_next(monkeypatch, *, failing=False):
    calls = []
    async def create(client, project_id, sources, digest, difficulty, language):
        calls.append((difficulty,language,digest))
        if failing: raise RuntimeError('模拟网络中断')
        new_id = uid()
        execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
                (new_id, project_id, j(sources), '下一份编程作业',
                 j([{'index':0,'question':'新情境的 ASCII 匹配','topic':'字符串边界','language':language,'starter_code':'// TODO only'}]),
                 j([{'index':0,'solution':'新私有参考算法','rubric':'测试80%','test_code':'私有测试'}]), difficulty, 'assigned', now()))
        return new_id, []
    async def forbidden(*args, **kwargs): pytest.fail('Programming progression became ordinary exercises')
    monkeypatch.setattr(server, 'create_assignment', create)
    monkeypatch.setattr(server, 'generate_set', forbidden)
    return calls


def use_grader(monkeypatch):
    grader = Grader()
    async def client(*args, **kwargs): return grader
    monkeypatch.setattr(server, 'assessment_client', client)
    return grader


def test_feynman_keeps_language_difficulty_and_review_context(monkeypatch):
    grader = use_grader(monkeypatch)
    calls = install_next(monkeypatch)
    parent = assignment()
    response = TestClient(server.app).post(f'/api/exercises/{parent}/feynman', json={'explanation':'先明确 ASCII 字母数字与下划线边界，其他字符是分隔符；不能把 Unicode 字符类直接当成 ASCII 规则。'*3})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['passed'] and result['next_set']['difficulty'] == 3
    assert result['next_set']['questions'][0]['language'] == 'javascript'
    assert 'solutions' not in result['next_set'] and '新私有参考算法' not in response.text
    assert '限定 ASCII 边界' in grader.calls[0] and '原私有参考算法' in grader.calls[0]
    assert grader.closed == 1 and len(calls) == 1


def test_failed_progression_preserves_feynman_pass_and_can_retry(monkeypatch):
    use_grader(monkeypatch)
    install_next(monkeypatch, failing=True)
    parent = assignment()
    api = TestClient(server.app)
    failed = api.post(f'/api/exercises/{parent}/feynman', json={'explanation':'边界按 ASCII 字母、数字与下划线识别，首先判断两侧字符是否合法，不匹配超出规则的字符。'*3})
    assert failed.status_code == 400
    assert one('SELECT status FROM exercise_sets WHERE id=?',(parent,))['status'] == 'retry_ready'
    calls = install_next(monkeypatch)
    repeated = api.post(f'/api/exercises/{parent}/advance', json={})
    assert repeated.status_code == 200, repeated.text
    again = api.post(f'/api/exercises/{parent}/advance', json={})
    assert again.status_code == 200 and again.json()['next_set']['id'] == repeated.json()['next_set']['id']
    assert len(calls) == 1 and len(many('SELECT * FROM artifacts')) == 1


def test_progression_rejects_skipping_feynman(monkeypatch):
    use_grader(monkeypatch)
    calls = install_next(monkeypatch)
    response = TestClient(server.app).post(f'/api/exercises/{assignment()}/advance', json={})
    assert response.status_code == 400 and not calls
