"""Record small mathematical acceptance corrections; preserve model output."""
from __future__ import annotations
import json
from pathlib import Path

from studyforge.exporters import export_docx

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'build/teaching-speed-proof-20261010-3'
document = (TARGET / 'model-lecture.md').read_text(encoding='utf-8')
prefix = '已生成讲解文档：'
if document.startswith(prefix): document = document[len(prefix):].lstrip()
changes = []


def correct(before, after, reason):
    global document
    if document.count(before) != 1: raise ValueError('验收修正无法唯一定位：' + reason)
    document = document.replace(before, after, 1)
    changes.append({'before': before, 'after': after, 'reason': reason})


correct('（取等号时两区间恰好在中点触碰，而中点是开区间端点、不属于任何一方，所以仍然不相交——这个端点细节后面还要用到。）',
        r'（取等号时，两区间的边界在 $c=a+\varepsilon_1=b-\varepsilon_2$ 处相接；$c$ 不属于任何一方，所以仍然不相交。只有 $\varepsilon_1=\varepsilon_2$ 时，这个边界点才是中点。这个端点细节后面还要用到。）',
        '两半径不相等时，相接边界不是中点。')
correct(r'**只要 $\varepsilon\le \tfrac{b-a}{2}$ 就一定能矛盾，超过就不一定**',
        r'**在上述两条误差估计中，只要 $0<\varepsilon\le \tfrac{b-a}{2}$ 就能推出矛盾；超过这个范围，仅靠这两条估计就不足以推出矛盾**',
        '保留正容差，并限定失败的是这组估计。')
correct(r'若强行取 $N=\max\{2,\cdot\}$、$n=3$，则 $x_3=\tfrac13<\tfrac12$ 成立，而 $|x_3-1|=\tfrac23>\tfrac12$ 失败，与"两条同时成立"冲突。',
        r'例如 $n=3$ 时，$x_3=\tfrac13<\tfrac12$，而 $|x_3-1|=\tfrac23>\tfrac12$。更关键的是，无论提出多大的整数门槛，都能选到一个超过它且不小于 $2$ 的下标，让第二条估计失败。因此不存在所需的 $N_2$，不能把一个不存在的门槛放进 $\max$。',
        '不以不存在的 N2 构造 max，明确反例的量词。')
correct(r'- **$\varepsilon$ 不能依赖于 $n$**：它是由 $a,b$ 确定的**常数**，必须在选 $N$ 之前定好。让人误以为"取 $\varepsilon$ 是作弊"的地方，正是把"$\forall\varepsilon$"误读成了"$\varepsilon$ 必须能应付所有情形"。实际上全称量词的意思是：每一个正数都可以拿来做一次使用。',
        r'- **本证明先固定容差，再选择对应门槛**：这里的 $\varepsilon=(b-a)/2$ 由固定的 $a,b$ 确定，再分别选择 $N_1,N_2$，最后让同一个足够大的 $n$ 同时满足两条估计。可以对不同的正数分别使用定义；但若随 $n$ 改选 $\varepsilon_n$，对应的 $N(\varepsilon_n)$ 也可能改变，不能直接断言这个 $n$ 已超过它。关键是量词顺序，不能把一次固定容差后的结论当成逐项变化容差后的统一结论。',
        '区分固定容差的这条证明与对多个容差分别使用定义。')
correct('3. **问矛盾从哪来**：两个逼近陈述本身不矛盾，只有让"误差预算"加起来小于间距时才矛盾。这一步是"缺什么"的诊断。',
        r'3. **问矛盾从哪来**：比较两条容差的和与间距。这里实际误差分别严格小于容差，所以容差之和不超过间距时便产生矛盾；不能漏掉允许取等号的情况。',
        '迁移线索沿用正文的非严格预算边界。')
correct('关键难点在于极限定义给的是两条**逼近性**陈述，而逼近性陈述单独看永远相容——只要两处容差足够大，同一个点可以同时落在 $a$ 和 $b$ 的邻域里。因此矛盾只能来自"容差之和覆盖不了两个候选极限之间的距离"这一几何事实',
        '关键难点在于极限定义给出的两条**逼近性**估计能否产生冲突，取决于如何选择容差。若两处容差之和大于两点间距，同一个点可以同时落在两个邻域里，单凭这两条估计不能产生矛盾。因此这里通过控制容差之和来制造冲突',
        '总结不重新引入永远相容或唯一机制的绝对化表述。')
correct(r'任何 $\varepsilon\le\tfrac{b-a}{2}$（甚至两条不相等的容差，只要和不超 $b-a$）都能导出矛盾。',
        r'任何 $0<\varepsilon\le\tfrac{b-a}{2}$（甚至两条不相等的正容差，只要和不超 $b-a$）都能导出矛盾。',
        '总结保留正性条件。')
correct(r'也要求 $\varepsilon$ 必须是与 $n$ 无关的常数。',
        r'这条证明先固定正容差，再选择对应的下标门槛。',
        '总结保留本次构造的范围。')

report = json.loads((TARGET / 'result.json').read_text(encoding='utf-8'))
review = report['outputs'][0]['metadata']['reviews'][0]
if set(review['locally_corrected_issues']) != set(range(len(review['issues']))):
    raise ValueError('未修正的审查疑点不能删去')
notes = '## 待核实事项\n' + '\n'.join(
    f"- {item['location']}: {item['problem']}（已局部修正，尚未再次独立复核。）"
    for item in review['issues'])
correct(notes, '', '额外数学验收确认两处自动局部修正；原始输出保留所有原始记录。')

path = TARGET / '极限唯一性_直观与专业并重_验收复核版.docx'
export_docx(document, '极限唯一性：直观与专业并重（验收复核版）', path)
(TARGET / 'acceptance-lecture.md').write_text(document, encoding='utf-8')
(TARGET / 'manual-qa.json').write_text(json.dumps({
    'docx': str(path), 'model_prose_changed': True, 'original_sample_preserved': True,
    'additional_model_requests': 0, 'corrections': changes,
    'note': '这是额外数学验收修订版，不伪称未经修改的自动生成结果，不改变原软件成果。'
}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'docx': str(path), 'localized_acceptance_edits': len(changes)}, ensure_ascii=False))
