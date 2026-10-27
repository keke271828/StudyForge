"""Small audit request plans. No change to the selected model or effort."""

AUDIT_SYSTEM=(
    '你是习题审查员。只返回 JSON 对象：'
    '{"passed":boolean,"issues":[{"index":0,"category":"statement|solution|rubric|answer_leak|source","problem":"..."}],"corrected_questions":[...]}。'
    '只列会造成歧义、错误求解或不公平评分的实质问题；可选优化、措辞偏好、题意已限定之外的输入不构成失败。'
    '无实质问题时passed=true且issues=[]。需要修订时提供完整corrected_questions，字段question,solution,rubric,topic,source_url；'
    '修订仍需再次求解和复核，本轮不自行宣布修订通过。'
    '若提供了独立解题疑点，另返回 independent_issue_decisions 数组，逐项包含 concern_id、blocking（布尔值）、reason（依据题目条件或实际推导，说明确认还是驳回）。'
    '不能照单全收求解阶段的评论：解题步骤、可选优化、正确推导的说明和已排除的边界情况应驳回，实质缺陷或无法核实的问题才阻止发布。')


def stages(strategy='dual'):
    if strategy=='dual':
        return [('解析核查','将独立解法与参考解逐题比对，检查关键条件、计算、单位、边界和评分点。'),
                ('成品核查','检查题意是否确定、可独立求解和评分；学生版只提取question/topic/source_url，不能在这些字段泄漏答案。')]
    if strategy=='combined':
        return [('综合核查','一次完成以下核对：题意和条件是否确定、能否独立求解；将独立解法与参考解逐题比对，'
            '检查关键推导、计算、单位、边界与评分点；学生版只提取question/topic/source_url，检查这些字段有无泄漏答案。'
            '各项都按同一题意与本次范围判断，只列实质问题。')]
    raise ValueError('未知习题核查策略')


def request(stage,criterion,context_policy,digest,independent,concerns,questions):
    return (f'阶段：{stage}。{criterion}\n{context_policy}\n资料：\n{digest}\n独立解法：{independent}'
        f'\n独立解题疑点编号：{concerns}\n题目与解答：\n{questions}')
