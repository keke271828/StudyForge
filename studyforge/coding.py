from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from .runtime import background_process_options

from .ai import DeepSeekClient, parse_json_response, complete_json
from .teaching import ASSESSMENT_RULES, FORMATIVE_FEEDBACK_RULES
from .assessment import presentation_policy
from .db import connect, execute, j, now, one, uid, unj, update_mastery
from .coding_runtime import IMAGES, TEST_RULES, run_tests, test_count
from .scheduling import run_local

LANGUAGES = {"python": "Python", "javascript": "JavaScript", "typescript": "TypeScript",
             "cpp": "C++", "matlab": "MATLAB", "wolfram": "Wolfram Language"}

MAX_ASSIGNMENT_REVISIONS = 2
REVIEW_SCHEMA = (
    '{"passed":boolean,"blocking_issues":[{"problem":"具体问题","evidence":"题意或代码中的依据",'
    '"suggested_fix":"修订建议"}],"notes":["非阻断建议或边界说明"]}'
)
REVIEW_RULES = (
    '使用中文。只把会影响合法输入的正确输出、可解性、确定性、测试或评分的实质错误列入 blocking_issues，必须给出依据。'
    '性能优化、可读性建议、满足要求的行为说明、题目合法输入范围之外的类型或超限输入处理，属于 notes。'
    '不要求题目额外支持未约定的非法输入，也不要求唯一实现方式。'
    '如果字符边界或大小写规则未定义且确实导致合法输入有不同结果，属于需要修订的歧义；'
    '规则已明确时，不用假设另一种规则来否决题目。状态不变量与操作规则矛盾属于实质错误。'
    '不得把线性复杂度、正确的不重叠匹配或可选的防御式编程当成错误。'
    'passed 仅在 blocking_issues 为空时为 true，notes 可以非空。'
)


class AssignmentReviewError(RuntimeError):
    def __init__(self, message: str, reports: list[dict]):
        super().__init__(message)
        self.reports = reports


def _structured_review(result: dict, require_passed: bool = True) -> dict | None:
    """Unlabelled legacy issues need a model decision, never a keyword whitelist."""
    if 'blocking_issues' not in result and 'issues' not in result:
        return None
    blockers = result.get('blocking_issues', [])
    notes = result.get('notes', [])
    if not isinstance(blockers, list) or not isinstance(notes, list):
        return None
    if not all(isinstance(issue, dict) and isinstance(issue.get('problem'), str)
               and issue['problem'].strip() and isinstance(issue.get('evidence'), str)
               and issue['evidence'].strip() for issue in blockers):
        return None
    blockers = list(blockers)
    notes = list(notes)
    legacy = result.get('issues', [])
    if not isinstance(legacy, list):
        return None
    for issue in legacy:
        if not isinstance(issue, dict):
            return None
        if issue.get('severity') == 'blocking' and issue.get('problem') and issue.get('evidence'):
            blockers.append(issue)
        elif issue.get('severity') == 'advisory' and issue.get('problem'):
            notes.append(issue['problem'])
        else:
            return None
    passed = result.get('passed')
    if passed is not None and not isinstance(passed, bool):
        return None
    if require_passed and not isinstance(passed, bool):
        return None
    if passed is False and not blockers:
        return None
    return dict(result, passed=not blockers, blocking_issues=blockers, notes=notes)


async def _audit_assignment(client, system: str, context: str, *, independent: bool = False) -> dict:
    result = parse_json_response(await client.complete(system + REVIEW_RULES, context, json_mode=True))
    normalized = _structured_review(result, require_passed=not independent)
    if normalized is None:
        classified = parse_json_response(await client.complete(
            '复核这份审查结果，把实质错误与非阻断建议分开。不要仅因原 issues 非空就否决，也不要仅因旧 passed=true 就放行。'
            + REVIEW_RULES + '只返回 JSON：' + REVIEW_SCHEMA,
            f'审查所依据的材料：\n{context}\n\n原审查结果：\n{json.dumps(result, ensure_ascii=False)}', json_mode=True))
        normalized = _structured_review(classified)
        if normalized is None:
            raise ValueError('审查结果未区分实质错误与建议，无法确认可发布性')
        normalized = dict(result, **normalized)
    if independent and (not isinstance(result.get('approach'), str) or not result['approach'].strip()):
        raise ValueError('独立解题结果缺少算法说明')
    normalized.pop('issues', None)
    return normalized


def _draft_issues(item: dict, language: str) -> list[dict]:
    required = ('title', 'problem', 'starter_code', 'reference_code', 'topic')
    if language in IMAGES:
        required += ('test_code',)
    issues = []
    for field in required:
        if not isinstance(item.get(field), str) or not item[field].strip():
            issues.append({'problem': f'作业缺少有效的 {field}', 'evidence': f'{field} 为空或不是文本',
                           'suggested_fix': f'补全 {field}'})
    if language == 'python':
        import ast
        for field in ('starter_code', 'test_code', 'reference_code'):
            if not isinstance(item.get(field), str) or not item[field].strip():
                continue
            try:
                tree = ast.parse(item[field])
            except SyntaxError as exc:
                issues.append({'problem': f'{field} 有语法错误', 'evidence': f'第 {exc.lineno} 行：{exc.msg}',
                               'suggested_fix': '修正为合法的 Python 代码'})
                continue
            if field == 'test_code':
                tests = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
                if len(tests) < 3:
                    issues.append({'problem': '单元测试不足 3 项', 'evidence': f'仅找到 {len(tests)} 个 test_ 方法',
                                   'suggested_fix': '补充正常输入和题目明确要求的边界测试'})
    if language in ('javascript', 'typescript', 'cpp') and isinstance(item.get('test_code'), str):
        count = test_count(item['test_code'], language)
        if count < 3:
            issues.append({'problem': '单元测试不足 3 项', 'evidence': f'仅找到 {count} 个独立测试调用',
                           'suggested_fix': '使用约定测试接口补充正常输入和已规定的边界测试'})
    return issues


def public_assignment_reviews(reports: list[dict]) -> list[dict]:
    """Keep independent algorithms, reference code and private tests out of student artifacts."""
    result = []
    for report in reports:
        value = report.get('result', report)
        summary = {'stage': report['stage'], 'attempt': report.get('attempt', 1),
                   'passed': value.get('passed'), 'blocking_count': len(value.get('blocking_issues', [])),
                   'note_count': len(value.get('notes', []))}
        if report.get('stage') == '自动修订':
            summary['note'] = '已修订题意、参考实现及测试，并从独立解题重新核查'
        runtime = report.get('reference_tests')
        if runtime:
            summary['runtime'] = {key: runtime[key] for key in ('ran', 'passed', 'tests', 'reason') if key in runtime}
        result.append(summary)
    return result


async def create_assignment(client: DeepSeekClient, project_id: str, source_ids: list[str], digest: str,
                            difficulty: int = 1, language: str = "python") -> tuple[str, list[dict]]:
    if language not in LANGUAGES:
        raise ValueError("不支持的编程语言")
    runtime_rules = TEST_RULES.get(language, 'test_code 设为空字符串；给出可人工核对的输入输出样例。')
    runtime_rules += '不得使用网络、文件系统或第三方包。所有输入输出样例必须与题意、测试、参考实现一致。'
    generation_prompt = (
        f"你是 {LANGUAGES[language]} 编程教师。根据资料设计一题可迁移的编程作业，包含明确的输入输出、限制、起始代码。"
        '明确合法输入的类型和范围；未要求的非法输入不纳入评分。涉及字符时明确 ASCII/Unicode、大小写与词边界规则。'
        '涉及任务状态时明确允许的状态数量及每次操作前后的不变量；错误处理和样例必须与规则一致。'
        '题目与说明默认中文，保留代码标识符。起始代码只给接口、说明与待实现部分，不泄露参考算法。'
        "检查参考实现与题意一致。只返回 JSON："
        '{"title":"...","problem":"...","starter_code":"...","test_code":"...","reference_code":"...","topic":"..."}。'
        + runtime_rules + ASSESSMENT_RULES)
    from .learning_memory import profile_context
    from . import workflows
    learner=workflows.snapshot('coding_profile',lambda:profile_context(digest),getattr(client,'control',None))
    item = parse_json_response(await client.complete(generation_prompt, f'难度 {difficulty}/5。资料：\n{digest}' + learner, json_mode=True))
    reports = []
    for attempt in range(1, MAX_ASSIGNMENT_REVISIONS + 2):
        blockers = _draft_issues(item, language)
        if blockers:
            reports.append({'stage': '结构与语法核查', 'attempt': attempt, 'passed': False, 'blocking_issues': blockers})
        else:
            try:
                independent = await _audit_assignment(
                    client, '你是独立解题员，只看到编程题意。独立给出算法和边界条件，不参考现成答案。只返回 JSON：'
                    '{"approach":"...","edge_cases":["..."],"passed":boolean,'
                    '"blocking_issues":[{"problem":"...","evidence":"...","suggested_fix":"..."}],"notes":["..."]}。',
                    item['problem'], independent=True)
                reports.append({'stage': '独立解题', 'attempt': attempt, 'result': independent})
                blockers = independent['blocking_issues']
                if not blockers:
                    for stage, focus in (('参考解与测试审查', '逐条核对参考代码、样例、边界条件及测试与题意的一致性；测试不覆盖未约定的非法输入'),
                                         ('成品审查', '核对输入输出、难度、起始代码、评分标准与题意；学生题意和起始代码不泄露参考算法')):
                        report = await _audit_assignment(
                            client, '你是独立编程作业审查员。只返回 JSON：' + REVIEW_SCHEMA,
                            f'审查阶段：{stage}。重点：{focus}。\n独立解法：{independent}\n作业：{json.dumps(item, ensure_ascii=False)}')
                        report.update(stage=stage, attempt=attempt)
                        reports.append(report)
                        blockers = report['blocking_issues']
                        if blockers:
                            break
            except ValueError as exc:
                reports.append({'stage': '审查结果核查', 'attempt': attempt, 'passed': False, 'notes': [str(exc)]})
                raise AssignmentReviewError('未获得可靠的编程作业审查结果，请重试；审查记录已保存', reports) from exc
        if not blockers and language in IMAGES:
            from . import workflows
            workflows.stage('隔离运行参考实现与私有测试',75)
            reference_check = await workflows.local_step('reference_tests',[language,item['reference_code'],item['test_code']],
                lambda:run_local('container',_run_assignment_tests,language,item['reference_code'],item['test_code'],label='参考实现容器判题'))
            reports[-1]['reference_tests'] = reference_check
            if reference_check.get('ran') and not reference_check.get('passed'):
                blockers = [{'problem': '参考实现未通过隔离测试', 'evidence': reference_check.get('output', '测试未通过'),
                             'suggested_fix': '对照题意修正参考实现或错误的测试，禁止删除必需测试来掩盖错误'}]
                reports.append({'stage': '参考实现运行核查', 'attempt': attempt, 'passed': False, 'blocking_issues': blockers})
        if not blockers:
            break
        if attempt > MAX_ASSIGNMENT_REVISIONS:
            problems = '；'.join(issue['problem'][:180] for issue in blockers[:3])
            raise AssignmentReviewError(f'自动修订 {MAX_ASSIGNMENT_REVISIONS} 次后仍有影响正确判题的问题，未发布：{problems}', reports)
        item = parse_json_response(await client.complete(
            generation_prompt + '这是自动修订任务。修正报告中的实质错误，保留知识点、语言和难度。'
            '同步更新题意、样例、起始代码、参考代码和测试，使它们使用同一套明确规则。不要为了通过审查删除必要行为或测试。返回完整作业 JSON。',
            f'难度：{difficulty}/5\n原资料：\n{digest}\n待修订作业：{json.dumps(item, ensure_ascii=False)}'
            f'\n实质问题：{json.dumps(blockers, ensure_ascii=False)}', json_mode=True))
        reports.append({'stage': '自动修订', 'attempt': attempt, 'passed': None})
    assignment_id = uid()
    public = [{"index": 0, "question": item["problem"], "topic": item["topic"],
               "starter_code": item["starter_code"], "language": language}]
    private = [{"index": 0, "solution": item["reference_code"],
                "rubric": "单元测试 80%，代码审查 20%" if language in IMAGES else "静态代码审查；运行验证后再定最终成绩",
                "test_code": item.get("test_code", ""), 'generation_reviews': reports}]
    execute("INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)",
            (assignment_id, project_id, j(source_ids), f"编程作业：{item['title']}", j(public), j(private),
             difficulty, "assigned", now()))
    return assignment_id, reports


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                                capture_output=True, text=True, timeout=8, **background_process_options())
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _run_python_tests(code: str, tests: str) -> dict:
    return run_tests('python', code, tests, _docker_available)


def _run_assignment_tests(language: str, code: str, tests: str) -> dict:
    if language == 'python': return _run_python_tests(code, tests)
    return run_tests(language, code, tests, _docker_available)


async def grade_code(client: DeepSeekClient, assignment_id: str, code: str, *,homework_attempt_id=None) -> dict:
    from .practice import submission_guard
    with submission_guard(assignment_id):
        return await _grade_code(client,assignment_id,code,homework_attempt_id=homework_attempt_id)


async def _grade_code(client: DeepSeekClient, assignment_id: str, code: str, *,homework_attempt_id=None) -> dict:
    from .review_versions import require_unchanged,fingerprint
    row = one("SELECT * FROM exercise_sets WHERE id=?", (assignment_id,))
    if not row:
        raise ValueError("编程作业不存在")
    if row["status"] != "assigned":
        raise ValueError("这份编程作业已经完成批改")
    question = unj(row["questions_json"], [])[0]
    solution = unj(row["solutions_json"], [])[0]
    language = question.get("language", "python")
    syntax_error = None
    if language == "python":
        import ast
        try:
            ast.parse(code)
        except SyntaxError as exc:
            syntax_error = f"第 {exc.lineno} 行语法错误：{exc.msg}"
        from . import workflows
        workflows.stage('隔离运行学生代码',30)
        test_result = await workflows.local_step('student_tests',[language,code,solution.get('test_code','')],
            lambda:run_local('container',_run_assignment_tests,language,code,solution.get('test_code',''),label='学生代码容器判题')) if not syntax_error else {
            "ran": False, "score": 0, "reason": syntax_error}
    else:
        from . import workflows
        workflows.stage('隔离运行学生代码',30)
        test_result = await workflows.local_step('student_tests',[language,code,solution.get('test_code','')],
            lambda:run_local('container',_run_assignment_tests,language,code,solution.get('test_code',''),label='学生代码容器判题'))
    require_unchanged(row)  # Container execution may wait while the worksheet changes.
    workflows.stage('代码审查与评分',65)
    def validate_review(result):
        from .practice import finite_scores
        finite_scores([result.get('score')],1)
        if not isinstance(result.get('feedback'),str) or not result['feedback'].strip() or not isinstance(result.get('issues'),list) or any(not isinstance(x,str) for x in result['issues']):
            raise ValueError('代码批改需要具体反馈和问题数组')
    review = await complete_json(client,
        "你是编程教师。审查正确性、清晰度、边界条件与代码质量。"
        "接受满足题意的不同算法和实现，不要求逐字复现参考代码；测试通过仅覆盖已运行用例，不能声称全部输入已验证。"
        "错误反馈引用实际代码步骤、解释错误如何产生及局部修正办法；不能把未运行的测试说成已运行。"
        + ASSESSMENT_RULES + FORMATIVE_FEEDBACK_RULES + presentation_policy(assignment_id) + '只返回JSON：'
        '{"score":0-100,"feedback":"...","issues":["实际代码或已执行测试支持的问题"]}。',
        f"语言：{LANGUAGES[language]}\n作业：{question['question']}\n参考实现：\n{solution['solution']}\n"
        f"学生代码：\n{code}\n测试结果：{test_result}", validate=validate_review)
    from .practice import finite_scores
    value = review.get('score')
    if type(value) in (int, float) and not 0 <= value <= 100:
        raise RuntimeError('编程审查分数不在 0 到 100 之间，未保存成绩')
    static_score = finite_scores([review.get('score')], 1)[0]
    provisional = not test_result.get("ran")
    final_score = round(.8 * test_result["score"] + .2 * static_score, 1) if not provisional else None
    result = {"score": final_score, "provisional": provisional, "test": test_result,
              "static_score": static_score, "review": review,
              "requires_feynman": final_score is not None and final_score < 80,
              "assignment_version_sha256":fingerprint([row[key] for key in ('questions_json','solutions_json','difficulty')])}
    submission_id = uid()
    result['submission_id']=submission_id
    if homework_attempt_id:result['homework_attempt_id']=homework_attempt_id
    with connect() as database:
        database.execute('BEGIN IMMEDIATE')
        require_unchanged(row,database)
        next_status = 'assigned' if final_score is None else ('feynman_required' if final_score < 80 else 'passed')
        updated = database.execute("UPDATE exercise_sets SET status=? WHERE id=? AND status='assigned'", (next_status, assignment_id))
        if updated.rowcount != 1: raise ValueError('这份编程作业已经完成批改，请刷新查看成绩')
        database.execute("INSERT INTO submissions VALUES (?,?,?,?,?,?,?)",
                         (submission_id, assignment_id, j({"code": code}), j(result), final_score if final_score is not None else -1, "{}", now()))
        from .homework_checkpoint import save
        save(database,homework_attempt_id,row,[code],result)
        from .learning_memory import assessment_record
        assessment_record('coding:' + submission_id, question['topic'], '编程作业', final_score, code,
                          str(review.get('feedback', '')), row['project_id'], dimension='coding',database=database)
        if final_score is not None:
            update_mastery(question["topic"], quiz=final_score,database=database)
    return result
