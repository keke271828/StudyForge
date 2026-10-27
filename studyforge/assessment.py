"""Evidence-based grading reconciliation; model agreement is not ground truth."""
from __future__ import annotations

from .ai import complete_json
from .practice import finite_scores
from .teaching import ASSESSMENT_RULES


def presentation_policy(set_id):
    """Use the submitted chat's pinned language/style without importing history."""
    from .db import one, unj
    from .ai import settings
    from .teaching_styles import style_policy, language_policy
    from .workflows import snapshot
    def select():
        row = one('SELECT options_json FROM homework_attempts WHERE exercise_set_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1', (set_id,))
        return (unj(row['options_json'],{}).get('teaching') if row else None) or settings()
    prefs = snapshot('grading_presentation:'+set_id,select)
    return style_policy(prefs.get('explanation_style','clear'))+language_policy(prefs.get('output_language','zh'))+('语言规则只作用于反馈文本，JSON键名保持不变；学习模式和历史画像不改变正确性标准或分数。')


def validate_grade(result, count):
    finite_scores(result.get('scores'), count)
    feedback = result.get('feedback')
    # A single submitted question has no attribution ambiguity: models often
    # return one feedback string per rubric point instead of one per question.
    # Keep every point and the original score. Never guess groups for N > 1.
    if count == 1 and isinstance(feedback,list) and len(feedback)>1 and all(isinstance(x,str) and x.strip() for x in feedback):
        result['feedback_normalization']={'kind':'single_question_points','point_count':len(feedback)}
        result['feedback']=feedback=['\n\n'.join(feedback)]
    if not isinstance(feedback, list) or len(feedback) != count or any(not isinstance(x, str) or not x.strip() for x in feedback):
        actual=len(feedback) if isinstance(feedback,list) else '非数组'
        raise ValueError(f'本次共{count}道题，feedback必须恰有{count}个非空字符串，每题全部评分点合并在同一个字符串中，按原题顺序；目前为{actual}条，不能把每个评分点各算一题')
    doubts = result.setdefault('uncertainties', [])
    if not isinstance(doubts, list) or any(not isinstance(x, str) or not x.strip() for x in doubts):
        raise ValueError('评分疑点必须是非空字符串数组，无疑点返回空数组')


async def isolated_grade(client, system, user, count):
    fork = getattr(client, 'fork', None)
    grader = fork() if callable(fork) else client
    try:
        return await complete_json(grader, system + ASSESSMENT_RULES, user,
                                   validate=lambda result: validate_grade(result, count))
    finally:
        if grader is not client:
            close = getattr(grader, 'close', None)
            if close: await close()


def requires_reconciliation(first, second):
    left, right = first['scores'], second['scores']
    # Every discrepancy affecting mastery/failure/full credit is consequential,
    # even when its absolute numerical difference is small.
    return (bool(first['uncertainties'] or second['uncertainties']) or
            any(abs(a-b) > 5 or (a >= 80) != (b >= 80) or (a == 100) != (b == 100) for a,b in zip(left,right)) or
            (sum(left)/len(left) >= 80) != (sum(right)/len(right) >= 80))


async def verified_grade(client, questions, solutions, answers, diagnosis_prompt=''):
    count = len(questions)
    data = f'题目：{questions}\n参考解与评分标准：{solutions}\n学生答案：{answers}'
    schema = ('只返回JSON：{"scores":[0-100],"feedback":["与本题评分点和作答步骤对应的依据"],'
              '"uncertainties":["影响公平评分的实质疑点"],"overall_feedback":"最需要改进的一处"}。'
              f'本次共{count}道题，scores和feedback都必须恰有{count}项，按原题顺序对应；'
              '每题所有评分点的反馈合并为一个字符串，可在字符串内分段，不按评分点拆成多个数组项。')
    first = await isolated_grade(client, '你是严格、公平的批改者。' + schema + diagnosis_prompt, data, count)
    second = await isolated_grade(client, '你是第二位独立批改者。重新核对题意、参考解与学生的实际解法，不预知第一份评分。'
                                  + schema + diagnosis_prompt, data, count)
    if requires_reconciliation(first, second):
        grade = await isolated_grade(client, '你是评分复核者。两份批改涉及疑点或重要评分分歧。'
            '重新求解并对照明示评分点逐项裁决，不能把两份分数取平均当成判断。'
            '解释选取最终分数的证据，已排除的疑点不再列出；仍未解决的实质问题保留在uncertainties。'
            + schema + diagnosis_prompt, data+f'\n第一份批改：{first}\n第二份批改：{second}', count)
        basis = '经分歧复核裁决；分数与反馈来自同一份裁决'
    else:
        # Keep one complete evidence/score pair rather than manufacture a score
        # whose explanation belongs to a different rubric application.
        grade = dict(first)
        basis = '第二份评分未发现影响通过或满分判定的分歧；沿用第一份有依据的评分，未取平均'
    grade.update(first_review=first, second_review=second, grading_basis=basis,
                 grading_verification_required=bool(grade['uncertainties']))
    return grade
