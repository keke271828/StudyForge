import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from studyforge import server
from studyforge.coding import AssignmentReviewError, create_assignment, grade_code, public_assignment_reviews
from studyforge.db import create_project, execute, j, now, one, uid
from studyforge.exercises import public_set


class Responses:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = []

    async def complete(self, system, user, json_mode=False):
        self.calls.append((system, user))
        return json.dumps(next(self.values), ensure_ascii=False)


@pytest.fixture
def force_assignment(monkeypatch):
    monkeypatch.setattr('studyforge.coding._run_python_tests', lambda code, tests:
                        {'ran': False, 'reason': 'Docker Desktop 未启动'})
    return {'title': '计算合力', 'problem': '定义 force(m,a)，合法输入均为有限实数，返回 m*a。',
            'starter_code': 'def force(m, a):\n    pass', 'reference_code': 'def force(m, a):\n    return m*a',
            'test_code': 'import unittest\nfrom solution import force\nclass TestForce(unittest.TestCase):\n'
                         '    def test_a(self): self.assertEqual(force(2, 3), 6)\n'
                         '    def test_b(self): self.assertEqual(force(0, 3), 0)\n'
                         '    def test_c(self): self.assertEqual(force(2, -3), -6)', 'topic': '牛顿第二定律'}


def approved(**extra):
    return {'passed': True, 'blocking_issues': [], 'notes': [], **extra}


JS_TESTS = ('const {test} = require("node:test"); const assert = require("node:assert/strict"); '
            'const {force} = require("./solution"); '
            'test("positive", () => assert.equal(force(2,3),6)); '
            'test("zero", () => assert.equal(force(0,3),0)); '
            'test("negative", () => assert.equal(force(2,-3),-6));')


def blocked(problem, evidence):
    return {'passed': False, 'blocking_issues': [{'problem': problem, 'evidence': evidence,
                                               'suggested_fix': '补全明确且一致的规则'}], 'notes': []}


def test_coding_assignment_reviews_and_provisional_grade(monkeypatch):
    monkeypatch.setattr("studyforge.coding._run_python_tests",
                        lambda code, tests: {"ran": False, "reason": "Docker Desktop 未启动"})
    project = create_project("编程")
    generated = {
        "title": "计算合力", "problem": "定义 force(m, a)，返回牛顿第二定律的合力。",
        "starter_code": "def force(m, a):\n    pass", "reference_code": "def force(m, a):\n    return m*a",
        "test_code": "import unittest\nfrom solution import force\nclass TestForce(unittest.TestCase):\n    def test_a(self): self.assertEqual(force(2, 3), 6)\n    def test_b(self): self.assertEqual(force(0, 3), 0)\n    def test_c(self): self.assertEqual(force(2, -3), -6)",
        "topic": "牛顿第二定律",
    }
    reviewer = Responses([generated, {"approach": "质量乘加速度", "edge_cases": ["零质量"], "issues": []},
                          {"passed": True, "issues": [], "evidence": "题意与测试一致"},
                          {"passed": True, "issues": [], "evidence": "起始代码不含答案"}])
    assignment_id, reports = asyncio.run(create_assignment(reviewer, project["id"], [], "F=ma"))
    assert len(reports) == 3
    assert one("SELECT status FROM exercise_sets WHERE id=?", (assignment_id,))["status"] == "assigned"
    grader = Responses([{"score": 90, "feedback": "实现正确", "issues": []}])
    result = asyncio.run(grade_code(grader, assignment_id, "def force(m, a):\n    return m*a"))
    assert result["provisional"] and result["score"] is None
    assert result["static_score"] == 90


def test_javascript_assignment_uses_static_review(monkeypatch):
    monkeypatch.setattr('studyforge.coding._docker_available', lambda: False)
    project = create_project("编程多语言")
    generated = {"title": "受力计算", "problem": "定义 force(m,a) 并返回合力", "starter_code": "function force(m,a) {}",
                 "reference_code": "function force(m,a) { return m*a; } module.exports = {force};", "test_code": JS_TESTS, "topic": "牛顿定律"}
    reviewer = Responses([generated, {"approach": "相乘", "edge_cases": [], "issues": []},
                          {"passed": True, "issues": [], "evidence": "参考解正确"},
                          {"passed": True, "issues": [], "evidence": "题意完整"}])
    assignment_id, reports = asyncio.run(create_assignment(reviewer, project["id"], [], "F=ma", language="javascript"))
    assert len(reports) == 3
    grader = Responses([{"score": 88, "feedback": "实现正确", "issues": []}])
    result = asyncio.run(grade_code(grader, assignment_id, "function force(m,a) { return m*a; }"))
    assert result["provisional"] and result["score"] is None
    assert "Docker" in result["test"]["reason"]


def test_reported_advisories_do_not_prevent_assignment(force_assignment):
    project = create_project('建议不阻断')
    comments = ['Inputs not specified as str or n not an int are not handled.',
                'Performance is linear in text length times 5 keyword comparisons, which is acceptable.',
                'Regex tokenization does not count overlapping occurrences, which is correct.']
    reviewer = Responses([force_assignment, {'approach': '质量乘加速度', 'edge_cases': [], 'issues': comments},
                          approved(notes=comments), approved(notes=['可增加可读性说明']), approved()])
    assignment_id, reports = asyncio.run(create_assignment(reviewer, project['id'], [], 'F=ma'))
    assert public_set(assignment_id)['status'] == 'assigned'
    assert len(reviewer.calls) == 5  # One compatibility classification; no unnecessary revision.
    assert reports[0]['result']['notes'] == comments
    assert not any(report['stage'] == '自动修订' for report in reports)


def test_unicode_ambiguity_is_revised_and_reaudited(monkeypatch):
    monkeypatch.setattr('studyforge.coding._run_python_tests', lambda *args: {'ran': False})
    monkeypatch.setattr('studyforge.coding._docker_available', lambda: False)
    project = create_project('词边界')
    draft = {'title': '统计独立关键词', 'problem': '统计文本中的独立关键词，字母或数字相邻时不能计数。',
             'starter_code': 'function countKey(text) {}', 'reference_code': 'function countKey(text) { return 0; }',
             'test_code': 'const {test} = require("node:test"); test("one",()=>{}); test("two",()=>{}); test("three",()=>{});', 'topic': '字符串处理'}
    corrected = dict(draft, problem='输入为字符串；关键词为 ASCII key，不区分 ASCII 大小写。边界按 ASCII 字母、数字及下划线定义；非 ASCII 字符作为分隔。返回独立 key 的非重叠出现次数。',
                     reference_code="function countKey(text) { return (text.match(/(?<![A-Za-z0-9_])key(?![A-Za-z0-9_])/gi) || []).length; }")
    reviewer = Responses([draft,
                          {'approach': '扫描边界', 'edge_cases': ['非 ASCII 相邻字符'],
                           'issues': ["The definition of letter/digit may be interpreted as ASCII-only or Unicode."]},
                          blocked('字母数字的范围未明确，合法输入可能有两个结果', '字母或数字相邻时不能计数'),
                          corrected, approved(approach='按明确的 ASCII 规则扫描', edge_cases=['中文邻接']),
                          approved(), approved()])
    assignment_id, reports = asyncio.run(create_assignment(reviewer, project['id'], [], '字符串边界', language='javascript'))
    assert 'ASCII' in public_set(assignment_id)['questions'][0]['question']
    assert len([r for r in reports if r['stage'] == '自动修订']) == 1
    assert [r['attempt'] for r in reports if r['stage'] == '独立解题'] == [1, 2]
    assert 'test_code' in reviewer.calls[3][1] and 'reference_code' in reviewer.calls[3][1]


def test_in_progress_contradiction_is_repaired(monkeypatch):
    monkeypatch.setattr('studyforge.coding._run_python_tests', lambda *args: {'ran': False})
    project = create_project('状态转换')
    draft = {'title': '任务状态', 'problem': '任何时刻恰好一个 in_progress；complete 后没有 in_progress。',
             'starter_code': 'def transitions(actions):\n    pass',
             'reference_code': 'def transitions(actions):\n    active = 0\n    for action in actions:\n        active = 1 if action == "start" else 0\n    return active',
             'test_code': 'import unittest\nfrom solution import transitions\nclass TestTransitions(unittest.TestCase):\n'
                          '    def test_empty(self): self.assertEqual(transitions([]), 0)\n'
                          '    def test_start(self): self.assertEqual(transitions(["start"]), 1)\n'
                          '    def test_complete(self): self.assertEqual(transitions(["start", "complete"]), 0)',
             'topic': '状态机'}
    corrected = dict(draft, problem='输入 actions 是长度不超过 100 的合法操作列表，元素仅 start 或 complete。初始状态为 0 个 in_progress；任何时刻至多一个。start 保证此前为 0 并使状态变为 1；complete 保证此前为 1 并使状态变为 0。返回最终数量。不考查非法操作。')
    reviewer = Responses([draft, blocked('恰好一个与完成后为零相互矛盾', draft['problem']) | {'approach': '按 start/complete 转换状态'},
                          corrected, approved(approach='合法操作使 active 在 0、1 之间转换'),
                          approved(notes=['未知 action 不在合法输入范围内，无需自行添加处理']), approved()])
    assignment_id, reports = asyncio.run(create_assignment(reviewer, project['id'], [], '状态转换'))
    assert '至多一个' in public_set(assignment_id)['questions'][0]['question']
    assert reports[-1]['passed']


@pytest.mark.parametrize('failure_stage', ['参考解与测试审查', '成品审查'])
def test_late_blocker_is_repaired_then_all_stages_repeat(force_assignment, failure_stage):
    project = create_project(failure_stage)
    initial = [force_assignment, approved(approach='m 乘 a')]
    if failure_stage == '成品审查':
        initial.append(approved())
    initial.append(blocked('题意与成品存在实质不一致', '题意中的合法输入规定与代码不一致'))
    reviewer = Responses(initial + [force_assignment, approved(approach='m 乘 a'), approved(), approved()])
    assignment_id, reports = asyncio.run(create_assignment(reviewer, project['id'], [], 'F=ma'))
    assert public_set(assignment_id)
    assert {r['stage'] for r in reports if r.get('attempt') == 2} == {'独立解题', '参考解与测试审查', '成品审查'}


def test_real_blocker_is_not_bypassed_after_revision_limit(force_assignment):
    project = create_project('修订上限')
    rejection = blocked('合法输入的输出仍不确定', '题目同时规定两种不相容输出') | {'approach': '无法唯一确定算法'}
    reviewer = Responses([force_assignment, rejection, force_assignment, rejection, force_assignment, rejection])
    with pytest.raises(AssignmentReviewError, match='自动修订 2 次') as caught:
        asyncio.run(create_assignment(reviewer, project['id'], [], 'F=ma'))
    assert one('SELECT count(*) AS count FROM exercise_sets')['count'] == 0
    assert len([r for r in caught.value.reports if r['stage'] == '独立解题']) == 3


def test_invalid_reference_is_repaired_before_independent_review(force_assignment):
    project = create_project('语法修复')
    draft = dict(force_assignment, reference_code='def force(m,a)\n    return m*a')
    reviewer = Responses([draft, force_assignment, approved(approach='相乘'), approved(), approved()])
    assignment_id, reports = asyncio.run(create_assignment(reviewer, project['id'], [], 'F=ma'))
    assert public_set(assignment_id)
    assert reports[0]['stage'] == '结构与语法核查'


def test_failed_reference_tests_trigger_revision_and_rerun(force_assignment, monkeypatch):
    project = create_project('参考测试')
    runs = []
    def run(code, tests):
        runs.append(code)
        return {'ran': True, 'passed': len(runs) == 2, 'tests': 3, 'output': 'assertion failed' if len(runs) == 1 else 'OK'}
    monkeypatch.setattr('studyforge.coding._run_python_tests', run)
    wrong = dict(force_assignment, reference_code='def force(m,a):\n    return m+a')
    reviewer = Responses([wrong, approved(approach='相乘'), approved(), approved(),
                          force_assignment, approved(approach='相乘'), approved(), approved()])
    assignment_id, reports = asyncio.run(create_assignment(reviewer, project['id'], [], 'F=ma'))
    assert public_set(assignment_id)
    assert len(runs) == 2 and reports[-1]['reference_tests']['passed']


def test_student_review_artifact_does_not_reveal_algorithm(force_assignment):
    project = create_project('答案隐藏')
    reviewer = Responses([force_assignment, approved(approach='独立算法：return m*a'),
                          approved(evidence='参考代码 return m*a 正确'), approved()])
    assignment_id, reports = asyncio.run(create_assignment(reviewer, project['id'], [], 'F=ma'))
    visible = json.dumps(public_set(assignment_id, reveal=True), ensure_ascii=False)
    audit = json.dumps(public_assignment_reviews(reports), ensure_ascii=False)
    assert 'return m*a' not in visible + audit
    assert json.loads(one('SELECT * FROM exercise_sets WHERE id=?', (assignment_id,))['solutions_json'])[0]['generation_reviews']


def test_api_saves_unpublished_review_and_reads_original(force_assignment, tmp_path, monkeypatch):
    project = create_project('API 错误记录')
    original = tmp_path / 'original.txt'
    original.write_text('完整原资料：F=ma', encoding='utf-8')
    source_id = uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,error,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
            (source_id, project['id'], 'original.txt', '.txt', str(original), j([{'locator': 'preview', 'text': '旧概括'}]), 'ready', None, now()))
    rejection = blocked('规则矛盾', '两个合法输出') | {'approach': '无唯一解'}
    reviewer = Responses([force_assignment, rejection, force_assignment, rejection, force_assignment, rejection])
    def private_reviewer(provider, **options):
        assert options['agent_runtime'].private_context
        return reviewer
    monkeypatch.setattr(server, 'client_for', private_reviewer)
    response = TestClient(server.app).post('/api/coding/generate', json={'project_id': project['id'], 'source_ids': [source_id]})
    assert response.status_code == 400 and '自动修订 2 次' in response.json()['detail']
    assert '完整原资料' in reviewer.calls[0][1] and '旧概括' not in reviewer.calls[0][1]
    review = one('SELECT * FROM artifacts')
    assert review and '未发布' in review['title']
    review_path = Path(review['path'])
    assert len(json.loads(review_path.read_text(encoding='utf-8'))) == 5
    private_review = json.loads((review_path.parent / 'private-reviews' / review_path.name).read_text(encoding='utf-8'))
    assert private_review[-1]['result']['blocking_issues'][0]['problem'] == '规则矛盾'
