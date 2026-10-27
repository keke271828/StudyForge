"""Real paired audit probe: same draft, task scope omitted versus provided.

Both arms use the current audit code. This is a scope-ablation probe, not a
historical-version benchmark or a randomized teaching-quality evaluation.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import time


CASES = {
    'math': {
        'source': '[来源：数列短文｜第1段] 收敛定义：对每个ε>0，存在正整数N，使所有n>N均满足|x_n-a|<ε。\n'
                  '[来源：数列短文｜第2段] 唯一性：假设x_n同时收敛到a和b，a<b。取ε=(b-a)/2>0。'
                  '按定义有门槛N1、N2。n>max(N1,N2)时，x_n<(a+b)/2且x_n>(a+b)/2，矛盾。\n'
                  '[来源：数列短文｜第3段] 有界性：取ε=1，则尾部有|x_n|<|a|+1；'
                  '把有限个前项的绝对值和|a|+1一起取最大即可界住全部项。',
        'requirements': '只解释第2段的两个构造：为什么ε取一半、为什么取max。'
                        '我已经懂收敛定义，不要重讲第1段或第3段有界性证明。简短讲清依据和直觉，不布置习题。',
        'draft': '# 唯一性证明的两个选择\n\n'
                 '假设有不同极限a<b，距离d=b-a>0。定义允许任取正ε，所以可选ε=d/2；'
                 '这不是从“ε必须严格小于d/2”推出来的。半径d/2的两个开邻域在中点相接，'
                 '却都不包含中点，因而不相交；更小的正半径也可以。\n\n'
                 '趋于a只保证超过N1后在左邻域，趋于b只保证超过N2后在右邻域。'
                 '取N=max(N1,N2)，则同一项只要n>N就满足两个条件，'
                 '于是x_n<(a+b)/2又x_n>(a+b)/2，矛盾。[来源：数列短文｜第2段]\n\n'
                 '## 系统性总结\n\n一半距离让两个开邻域分开，较大门槛让两条尾部结论同时有效。',
    },
    'philosophy': {
        'source': '[来源：论证短文｜第1节] 描述性主张说明实际怎样，规范性主张评价应该怎样。'
                  '由“很多人这样做”推出“这样做正当”，还需要评价原则。事实可帮助判断后果和适用条件。\n'
                  '[来源：论证短文｜第2节] 相关与因果不同。调查发现两个变量关联，尚不能排除共同原因或反向影响。'
                  '扩大样本可降低抽样误差，但不自动消除混杂。\n'
                  '[来源：论证短文｜第3节] 演绎有效只说前提为真时结论必真，不保证前提本身真。'
                  '归纳论证提供不同程度支持，结论可被新证据修正。',
        'requirements': '这次只理解第1节从“大家都做”到“应当”的缺口。'
                        '不要讲相关因果、演绎或归纳；用一个完整小例子讲明白，别套其他学科，不要出题。',
        'draft': '# 人数多为什么还不够\n\n'
                 '“很多人在排队时插队”是对行为频率的描述；“插队正当”则是在评价行为。'
                 '前一句没有给出评价标准，不能单独推出后一句。[来源：论证短文｜第1节]\n\n'
                 '以一个假设为例：即使某处八成人插队，若采用“应尊重先来后到”的原则，'
                 '插队仍可能不正当。若有人改用“多数人做就正当”，他必须为这条原则辩护，'
                 '不能靠再报一次八成人来证明原则本身。\n\n'
                 '事实仍然有用：插队是否影响秩序、是否有紧急情形，关系到原则怎样适用；'
                 '事实帮助评价，却不能替你选定评价原则。\n\n'
                 '## 系统性总结\n\n频率描述实际行为，规范结论还需要可辩护的评价原则及适用理由。',
    },
}


async def main(folder, names=()):
    out = Path(__file__).resolve().parents[1] / 'build' / folder
    if (out / 'report.json').exists(): raise SystemExit('请使用新的试验目录')
    out.mkdir(parents=True, exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(out / 'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(out / 'isolated-model')
    from studyforge import ai
    from studyforge.review import review_explanation
    ai.save_settings({'agent_tools_enabled': False, 'agent_network_enabled': False, 'background_learning_enabled': False})
    (out / 'inputs.json').write_text(json.dumps(CASES, ensure_ascii=False, indent=2), encoding='utf-8')
    rows, gate = [], asyncio.Semaphore(1 if names else 2)
    selected = [(name, case, scoped) for name, case in CASES.items() for scoped in (False, True)]
    if names:
        known = {name+(':'+('scoped' if scoped else 'omitted')) for name, _, scoped in selected}
        if set(names)-known: raise SystemExit('未知试验名称')
        selected = [(name,case,scoped) for name,case,scoped in selected
                    if name+(':'+('scoped' if scoped else 'omitted')) in names]

    async def sample(name, case, scoped):
        async with gate:
            client = ai.DeepSeekClient('deepseek-flash', effort='high')
            start = time.perf_counter()
            row = {'case': name, 'scope_provided': scoped, 'model': client.model, 'effort': 'high', 'tools': False}
            try:
                result, reports = await asyncio.wait_for(review_explanation(client, case['source'], case['draft'],
                    mode='fast', learning_mode='deep', explanation_style='balanced',
                    requirements=case['requirements'] if scoped else '', summary_level=1 if scoped else None), 300)
                filename = name + ('-scoped' if scoped else '-omitted')
                (out / (filename + '.md')).write_text(result, encoding='utf-8')
                row.update(status='completed', audit_reports=reports, answer_file=filename + '.md')
            except Exception as exc:
                row.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
            finally:
                await client.close()
                row['seconds'] = round(time.perf_counter() - start, 2)
                rows.append(row)
                (out / 'report.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(row, ensure_ascii=True), flush=True)
    await asyncio.gather(*(sample(name, case, scoped) for name, case, scoped in selected))


if __name__ == '__main__': asyncio.run(main(sys.argv[1],sys.argv[2:]))
