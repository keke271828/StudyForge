import asyncio
import json

from studyforge.ai import client_for, save_settings
from studyforge.review import review_explanation
from studyforge.server import GenerateIn


def test_express_is_default_and_skips_extra_model_call():
    class Client:
        async def complete(self, system, user, json_mode=False):
            raise AssertionError("极速模式不应发起额外模型审查")

    assert GenerateIn(project_id="p", source_ids=["s"]).review_mode == "express"
    document, reports = asyncio.run(review_explanation(Client(), "资料", "讲解", mode="express"))
    assert document == "讲解"
    assert reports[0]["passed"] is None
    assert "未执行独立模型审查" in reports[0]["note"]


def test_legacy_generation_override_does_not_split_teacher_model():
    save_settings({"codex_model": "gpt-6-sol", "codex_generation_model": "gpt-6-luna"})
    assert client_for("codex").model == "gpt-6-sol"
    assert client_for("codex", generation=True).model == "gpt-6-sol"
    assert client_for("codex", model="gpt-6.1-sol", generation=True).model == "gpt-6.1-sol"


def test_fast_review_uses_one_call_and_marks_issues():
    class Client:
        def __init__(self):
            self.calls = 0

        async def complete(self, system, user, json_mode=False):
            self.calls += 1
            return json.dumps({"passed": False, "issues": [
                {"location": "公式 2", "problem": "缺少适用条件", "evidence": "原文第 3 页"}
            ]})

    client = Client()
    document, reports = asyncio.run(review_explanation(client, "资料", "初稿", mode="fast"))
    assert client.calls == 1
    assert len(reports) == 1
    assert "待核实事项" in document
    assert "缺少适用条件" in document


def test_balanced_review_repairs_only_when_needed():
    class Client:
        def __init__(self):
            self.calls = 0

        async def complete(self, system, user, json_mode=False):
            self.calls += 1
            if json_mode:
                return json.dumps({"passed": False, "issues": [
                    {"location": "段落 1", "problem": "漏掉前提"}
                ]})
            return "已修订的讲解"

    client = Client()
    document, reports = asyncio.run(review_explanation(client, "资料", "初稿", mode="balanced"))
    assert client.calls == 2
    assert document.startswith("已修订的讲解")
    assert "漏掉前提" in document and "不能确认这些疑点均已排除" in document
    assert reports[-1]["note"].endswith("未再次独立复核")


def test_fast_review_corrects_a_precise_error_without_a_rewrite_call():
    class Client:
        calls = 0
        async def complete(self, system, user, json_mode=False):
            self.calls += 1
            return json.dumps({'passed': False, 'issues': [{'location': '类比', 'problem': '应为同一个对象'}],
                'corrections': [{'issue_index': 0, 'before': '一个人靠近甲，另一个人靠近乙。',
                                 'after': '同一个人同时靠近甲和乙。'}]})
    client = Client()
    draft = '# 极限\n一个人靠近甲，另一个人靠近乙。\n\n## 系统性总结\n两个邻域互不相交。'
    result, reports = asyncio.run(review_explanation(client, '同一个数列的同一项', draft, mode='fast'))
    assert client.calls == 1
    assert '同一个人同时靠近甲和乙。' in result and '另一个人' not in result
    assert reports[0]['locally_corrected_issues'] == [0]
    assert '已局部修正' in result and '尚未再次独立复核' in result
    assert '应为同一个对象' not in result and '待核实事项' not in result


def test_fast_review_keeps_unresolved_concerns_and_full_private_audit():
    class Client:
        async def complete(self, system, user, json_mode=False):
            return json.dumps({'passed': False, 'issues': [
                {'location': '计算', 'problem': '加法错误'},
                {'location': '假设', 'problem': '缺少定义，无法确认'}],
                'corrections': [{'issue_index': 0, 'before': '2+3=4。', 'after': '2+3=5。'}]})
    document, reports = asyncio.run(review_explanation(Client(), '资料', '2+3=4。', mode='fast'))
    assert '2+3=5。' in document and '缺少定义，无法确认' in document
    assert '加法错误' not in document and '尚未再次独立复核' in document
    assert len(reports[0]['issues']) == 2


def test_local_corrections_protect_quotes_and_reject_ambiguous_or_broken_edits():
    from studyforge.review import apply_local_corrections
    draft = '# 定理\n> 原文条件甲。\n\n重复。重复。\n\n## 系统性总结\n结论。'
    issues = [{'problem': '需核对'}]
    for before, after in [('原文条件甲。', '换一种条件。'), ('重复。', '修订。'),
                          ('## 系统性总结', '删去总结'), ('结论。', '```\n未闭合代码')]:
        candidate, used = apply_local_corrections(draft, [{'issue_index': 0, 'before': before, 'after': after}], issues)
        assert candidate == draft and used == []
