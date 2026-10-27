"""Compare one document-organization sentence; saved inputs keep other rules.

This is a development experiment, not an imported production prompt. Public
final text and provider counters are recorded; hidden reasoning is not saved.
"""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OLD = ('默认先用一个短段交代主线，再分层展开真正的难点；主线用于定位，不替代关键步骤。'
       '学生要求全面详讲时可以扩大展开，其他情况把扩展放在主问题讲清之后。')
NEW = ('围绕本次要讲清的问题连续解释含义、理由与关键步骤，具体例子紧接所解释的难点。'
       '资料短且问题单一时，不把同一结论拆成多个角度反复证明；'
       '每段新增解释应推进原问题或回应学生要求，展开深度按当前模式与详略。'
       '学生要求全面详讲时充分展开；总结压缩主线，不再重演推导。')

CASES = [
    {'id': 'constant_product', 'title': '单一概念：因子变化不必导致乘积变化', 'style': 'balanced', 'mode': 'deep', 'level': 3,
     'source': '数学示意：t>0，u(t)=t，v(t)=1/t，P(t)=u(t)v(t)。这里只讨论函数关系，不代表真实化学装置。',
     'question': '请讲清u和v都变化为什么不能推出乘积必变。保留原题t>0，给出一个具体数值对照，整理成可独立读懂的讲解，最后总结，不出题。',
     'checks': ['t>0保留，P=1', '数例与解释相连', '不把恒等关系外推真实装置', '避免由同一主线反复展开导数、对数导数和梯度']},
    {'id': 'rate_units', 'title': '完整短材料：单位、算例与给定模型', 'style': 'balanced', 'mode': 'deep', 'level': 3,
     'source': '给定反应式A+B→C，并额外给定本例速率模型v=k[A][B]。浓度以mol/L计，v以mol/(L·s)计。k=0.2 L/(mol·s)，[A]=0.5 mol/L，[B]=0.3 mol/L。反应式本身不能推出此速率模型。',
     'question': '请完整讲解这段：各符号什么意思、k的单位怎样得到、给定数值怎样代入，以及为什么反应式本身推不出这个模型。讲清关键理由，最后总结，不出题。',
     'checks': ['各量、单位推导与0.03 mol/(L·s)保留', '反应式与给定速率模型区分', '不凭给定公式断言速率随时间必变', '补充条件不冒充原文']},
    {'id': 'limit_proof', 'title': '证明动机：为什么选半间距', 'style': 'balanced', 'mode': 'deep', 'level': 3,
     'source': '实数列收敛的定义：对每个ε>0，存在N，当n>N时有|x_n-a|<ε。证明极限唯一：反设x_n→a且x_n→b，a<b，取ε=(b-a)/2。足够大的同一项将同时小于和大于中点(a+b)/2，矛盾。',
     'question': '请把这段证明讲懂，重点说明为什么要制造两个不相交的邻域，怎样想到取一半，取等号为什么合法，以及怎样让两组条件对同一项成立。讲解可独立阅读，最后总结，不出题。',
     'checks': ['∀ε允许使用合法正值，a<b保证正', '开邻域在半间距时不相交，≤而非必须严格小于半间距', '统一N>=N1,N2并选择同一足够大n', '方便选择不写成唯一方法']},
    {'id': 'social_mechanism', 'title': '社会科学：解释能力不等于唯一原因', 'style': 'clear', 'mode': 'deep', 'level': 3,
     'source': '制度规则会影响人的行为。评估理论需区分“它能解释某事件”和“它是该事件的唯一解释”。本文没有排除习惯、资源与个人目标等因素。',
     'question': '用同一个具体日常事件，把能解释为什么不等于唯一原因讲透，再接回原文。例子是假设示意，不当成调查事实；讲解独立完整，最后总结，不出题。',
     'checks': ['多种因素指向同一事件', '可能机制不冒充已证原因', '保留制度规则的作用，不强套数理模型', '不扩展成宏大理论课程']},
    {'id': 'requested_extensions', 'title': '充分展开控制：学生明确要求三个角度', 'style': 'academic', 'mode': 'research', 'level': 5,
     'source': 't>0，u(t)=t，v(t)=1/t，P(t)=u(t)v(t)=1。实二元函数F(u,v)=uv。各函数在给定范围内可微。',
     'question': '请充分展开：依次从代数恒等、乘积求导、平面等值线三个角度讲清两个因子变化而乘积不变。每个角度给出必要步骤，说明偏导与沿路径变化的差别，并保留原题范围；不用现实装置类比，最后总结，不出题。',
     'checks': ['三个明确要求的角度都保留', '乘积导数1/t-1/t=0', 'F梯度(v,u)与路径速度(1,-1/t²)内积为0', '不把紧凑组织变成删除用户要求']},
]


async def main(name):
    out = ROOT / 'build' / name
    if out.exists() and any(out.iterdir()):
        raise SystemExit('Use a fresh folder.')
    out.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(out / 'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(out / 'isolated-model')
    from studyforge import ai
    from studyforge.db import j
    from scripts.diagnose_deepseek_speed import traced_class
    ai.save_settings({'api_connection_mode': 'direct', 'agent_tools_enabled': False, 'agent_network_enabled': False,
                      'background_learning_enabled': False, 'library_reference_mode': 'off', 'model_concurrency': 2})
    cases = []
    for case in CASES:
        captured = []
        class Capture:
            async def complete(self, system, user, **kwargs):
                captured.append([{'role': 'system', 'content': system}, {'role': 'user', 'content': user}])
                return '受控捕获，不是对照结果。'
        await ai.generate_explanation(Capture(), '[来源 样例.txt｜行1]\n' + case['source'], case['level'], [],
                                      style=case['style'], learning_mode=case['mode'], requirements=case['question'])
        assert len(captured) == 1 and captured[0][0]['content'].count(OLD) == 1
        baseline = captured[0]
        candidate = copy.deepcopy(baseline)
        candidate[0]['content'] = candidate[0]['content'].replace(OLD, NEW, 1)
        assert baseline[1:] == candidate[1:]
        cases.append(case | {'requests': {'baseline': baseline, 'candidate': candidate}})
    (out / 'inputs.json').write_text(j({'cases': cases, 'old': OLD, 'new': NEW}), encoding='utf-8')
    cls, results = traced_class(), []
    for number, case in enumerate(cases):
        async def sample(arm):
            client = cls('deepseek-flash', effort='high')
            row = {'case': case['id'], 'arm': arm, 'model': 'deepseek-flash', 'effort': 'high'}
            started = time.perf_counter()
            try:
                answer = ''
                async with asyncio.timeout(300):
                    async for kind, value in client.agent_stream(case['requests'][arm]):
                        if kind == 'final':
                            answer = value
                assert answer.strip()
                path = out / (case['id'] + '-' + arm + '-final.md')
                path.write_text(answer, encoding='utf-8')
                row.update(status='completed', answer_file=path.name, characters=len(answer),
                           answer_sha256=hashlib.sha256(answer.encode()).hexdigest())
            except Exception as exc:
                row.update(status='failed', error_type=type(exc).__name__)
            finally:
                await client.close()
            row.update(seconds=time.perf_counter() - started, model_requests=len(client.traces),
                       input_characters=sum(len(m['content']) for m in case['requests'][arm]),
                       http_attempts=[t.public() for t in client.traces])
            results.append(row)
            (out / 'results.json').write_text(j(results), encoding='utf-8')
            print(json.dumps({k: row[k] for k in ('case', 'arm', 'status', 'seconds', 'model_requests')}), flush=True)
        order = ('baseline', 'candidate') if number % 2 == 0 else ('candidate', 'baseline')
        await asyncio.gather(*(sample(arm) for arm in order))


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1]))
