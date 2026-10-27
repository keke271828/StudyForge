"""Frozen examples for a one-call teaching alignment experiment.

No application instructions are changed by importing this file. Statements in
the constructed controls are teaching examples, not empirical observations.
"""
from pathlib import Path


VERSION = '2026-10-15-example-to-question-evidence'
RULES = (
    '在同一JSON中增加 example_alignment：'
    '{"question":"本次真正需要解释的问题，短句",'
    '"checks":[{"quote":"讲解中连续原句或短段",'
    '"explains":"这个例子实际说明的对象或命题",'
    '"relation":"supports、analogy、contrast、off_target或uncertain",'
    '"reason":"例子怎样接回问题，或具体缺少哪一步",'
    '"issue_index":null}]}。只摘最关键的至多3个例子，没有例子则checks为空。'
    'quote逐字摘录20至800字符，不复制整篇；这是可核对的教学依据，不输出内部思考。'
    'supports为直接支持，analogy为有明确对应的类比，contrast为有效对照，off_target为被冒称能说明目标却换了问题，uncertain为无法确定。'
    '类比对象不同、反例不满足所反驳命题、讲解比较两种不同情形，本身都不是跑题；检查其对应和论证作用。'
    '只有换问题且没有建立必要联系时才列实质issues，并以issue_index关联该问题的原数组编号。'
    '若讲解承认某例只说明另一件事，却仍用它作为原结论的主要示范或在总结声称原问题已讲透，也需指出未补上的联系。'
    '不能把真正有用的补充或学生明确不要求展开的内容判成遗漏。'
)

PAIR_VERSION = '2026-10-15-example-claim-and-reason'
PAIR_RULES = (
    '在同一JSON增加 example_links 数组，至多3项：'
    '[{"claim_quote":"示例自己提出的问题或声称支持的具体结论，逐字摘录",'
    '"reason_quote":"它实际给出的关键理由，逐字摘录",'
    '"verdict":"connected、gap或uncertain",'
    '"reason":"理由如何支持该结论，或具体缺哪一步",'
    '"issue_index":null}]。没有相关例子则返回[]。每段引文8至800字符。'
    '先核对例子内部的具体问题与理由，不能把待解释对象改写成宽泛的全文主题。'
    '理由只说明另一件相关的事，却被当成已解释原问题，是gap，列入issues并以issue_index关联；'
    '后文承认两件事不同，也不能代替缺失的论证。'
    '有明确对应的类比、有效对照和反例可为connected，不因对象不同就判错。'
    'uncertain只表示依据不足，不作错误定性；保留已经成立的部分，不要求扩大原任务。'
    '这是简短的可核对教学依据，不输出内部思考。'
)


def cases(root: Path):
    from scripts.teaching_inference_candidate import CASES
    social = CASES['explanation']
    values = {
        'historical_social': {
            'title': '历史漏检：为什么迟到与为什么担心迟到',
            'source': social['material'], 'question': social['question'],
            'draft': (root/'build/teaching-inference-real-20261015-1/explanation-candidate.md').read_bytes().decode('utf-8'),
            'expectation': '应指出考勤例子换了待解释对象；后文承认差别不能补足同一事件多种原因的主要示范。其他真实缺陷可另列。',
            'kind': 'known_defect',
        },
        'code_target': {
            'title': '编程：去空格的例子没有说明忽略大小写',
            'source': '需求：same_name应忽略首尾空格及英文字母大小写后比较名字。\n```python\ndef same_name(a, b):\n    return a.strip() == b.strip()\n```\n测试same_name("Alice", "Alice")与same_name(" Alice ", "Alice")均返回True。尚未运行大小写不同的测试。',
            'question': '这段实现真的能忽略大小写吗？请用具体输入把这点讲明白；不需要讲测试理论、不出题。',
            'draft': '# 名字比较为什么能工作\n\n先看一个具体例子：输入第一个名字" Alice "，第二个名字"Alice"。'
                'strip会去掉前者两端空格，于是两边都成为"Alice"，相等比较得到True。'
                '原先有空格、后来没有空格，这种表面形式的差别没有影响比较结果。\n\n'
                '这就说明这个实现已经能够忽略大小写，两个已通过的测试也支持这一点。\n\n'
                '## 系统性总结\n\nstrip把输入标准化，例子展示了不同大小写也会被当作同一个名字。',
            'expectation': '必须指出例子处理空白而非字母大小写；仅有strip无法满足要求。静态推演Alice/alice应False，不得声称实际已执行。',
            'kind': 'known_defect',
        },
        'math_contrast': {
            'title': '合理对照：形式上的系数不是实际向量',
            'source': CASES['cauchy']['material'], 'question': CASES['cauchy']['question'],
            'draft': '# 一个点的非负为什么不够\n\n取t=1只知道A+2B+C不小于零。我们想得到的是B²不大于AC，这个结论比前一个条件更强。'
                '下面只比较两个代数条件，不声称这些系数能来自实际向量：取A=100、B=20、C=1。'
                '第一个条件给100+40+1=141，大于零；但B²=400大于AC=100。'
                '因此单点非负这条信息本身不推出柯西所需的条件。由于这组系数违反柯西，它们不可能来自真实向量。\n\n'
                '对于真正的平方和，每个实数t都使f(t)非负。A>0时配方为A(t+B/A)²+C−B²/A；'
                '取t=−B/A，第一项为零，留下C−B²/A不小于零，才得到B²不大于AC。'
                'A=0时每个a_i都为零，B也为零，结论直接成立。\n\n'
                '## 系统性总结\n\n可调参数让我们用到最低点；形式系数的对照只说明一个弱条件不够，真正向量的平方和恒非负提供了更强信息。',
            'expectation': '这个对照有效；不能因形式系数不来自真实向量而判例子无效。无实质问题则不改。',
            'kind': 'valid_control',
        },
        'flux_analogy': {
            'title': '合理类比：有符号总量为零不代表各项为零',
            'source': '高斯定律：闭合曲面上的净电通量等于内部净电荷除以ε0。内部没有电荷的均匀非零电场也满足净通量为零。',
            'question': '内部净电荷为零，为什么不能说明电场处处为零？希望给一个容易理解的类比，再接回高斯定律。不出题。',
            'draft': '# 零总量和零电场\n\n你把有正负的总量为零，当成每一个位置的量都为零了。'
                '先作一个算术类比：一次收入50元、一次支出50元，净变化是50−50=0，但两笔变动都不是零。'
                '这只类比正负贡献抵消，不把电场说成现金流，也不借它计算场强。\n\n'
                '高斯定律累加的是电场对闭合曲面的有向通量。以匀强电场沿正x方向穿过立方体为例，'
                '右面的通量为EA，左面为−EA，其余四面因电场与法向垂直而为0；相加为0，但电场仍然非零。'
                '这里A是一个面的面积，E是场强大小。这个构型在立方体内无电荷，满足给定条件。\n\n'
                '## 系统性总结\n\n内部净电荷为零限制净通量，不确定每一点的电场；类比说明有符号的贡献可以抵消，匀强场例子直接展示了它。',
            'expectation': '类比有明确对应和界限、实际电场例子完整正确，不应因现金与电场对象不同判跑题。',
            'kind': 'valid_control',
        },
    }
    for item in values.values():
        item['question'] += '\n本次仅核查现有讲解的实质正确性与解释是否接上问题，不因没有补充其他背景而判错。'
    return values
