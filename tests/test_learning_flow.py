import asyncio
import json
from pathlib import Path

import pytest

from studyforge.ai import generate_explanation
from studyforge.db import create_project, execute, j, one, uid
from studyforge.exercises import grade_feynman, grade_submission, public_set
from studyforge.review import review_explanation


class StubClient:
    def __init__(self, scores=None):
        self.scores = scores or []
        self.prompts = []

    async def complete(self, system, user, json_mode=False):
        self.prompts.append((system, user))
        if self.scores:
            value = self.scores.pop(0)
            return json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value
        return "OK"


def make_set(score_marker: str) -> str:
    project = create_project(score_marker)
    set_id = uid()
    execute("INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)",
            (set_id, project["id"], "[]", score_marker,
             j([{"index": 0, "question": "解释 F=ma", "topic": "牛顿定律"}]),
             j([{"index": 0, "solution": "合力等于质量乘加速度", "rubric": "概念完整"}]),
             1, "assigned", "2026-01-01"))
    return set_id


@pytest.mark.parametrize("score,required", [(79, True), (80, False)])
def test_grading_threshold_and_solution_release(score, required):
    set_id = make_set(str(score))
    stub = StubClient([{"scores": [score], "feedback": ["依据"], "uncertainties": []},
                       {"scores": [score], "feedback": ["复核依据"], "uncertainties": []}])
    assert "solutions" not in public_set(set_id, reveal=True)
    grade = asyncio.run(grade_submission(stub, set_id, ["我的解答"]))
    assert grade["score"] == score
    assert grade["requires_feynman"] == required
    assert "solutions" in public_set(set_id, reveal=True)


def test_feynman_retry_boundary():
    set_id = make_set("费曼")
    execute("UPDATE exercise_sets SET status='feynman_required' WHERE id=?", (set_id,))
    explanation = "我会从惯性系、质量、合力与加速度的定义出发，逐步解释牛顿第二定律的条件和物理含义，并给出质量为两千克的具体例子。" * 2
    stub = StubClient([{"score": 79, "passed": True, "feedback": "重试", "gaps": []},
                       {"score": 80, "passed": False, "feedback": "通过", "gaps": []}])
    first = asyncio.run(grade_feynman(stub, set_id, explanation))
    assert not first["passed"]
    assert one("SELECT status FROM exercise_sets WHERE id=?", (set_id,))["status"] == "feynman_retry"
    second = asyncio.run(grade_feynman(stub, set_id, explanation))
    assert second["passed"]
    assert one("SELECT status FROM exercise_sets WHERE id=?", (set_id,))["status"] == "retry_ready"


def test_summary_levels_change_generation_prompt():
    stub = StubClient()
    asyncio.run(generate_explanation(stub, "source", 1, []))
    asyncio.run(generate_explanation(stub, "source", 5, []))
    assert "概括性最强" in stub.prompts[0][1]
    assert "细节最多" in stub.prompts[1][1]


def test_review_repair_does_not_keep_resolved_issue():
    stub = StubClient([
        {"passed": False, "issues": [{"location": "页1", "problem": "缺少条件", "evidence": "原文"}]},
        {"passed": True, "issues": []},
        {"passed": True, "issues": []},
        "修订后的完整讲解",
        {"passed": True, "issues": []},
        {"passed": True, "issues": []},
        {"passed": True, "issues": []},
    ])
    document, reports = asyncio.run(review_explanation(stub, "原资料", "初稿"))
    assert len(reports) == 6
    assert "待核实事项" not in document
    assert document == "修订后的完整讲解"
