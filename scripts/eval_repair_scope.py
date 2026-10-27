"""Bounded paired reviewer trials. Synthetic cases; private answers stay private."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
BASE=('本次为逐题错因修复。核对每题是否实际检查repair_focus指向的知识与关键步骤，'
    '所需前置充分，保持原难度，不只换数字或抄原题。修订保留正确repair_target_index和topic，'
    '若改变题意则同步更新repair_focus。不能为了排齐而交换目标标签，repair_focus保持私有，不进入question。'
    '学生自报和原因未明不能写成已确认的能力缺陷。')


def cases():
    from studyforge.db import j
    old=ROOT/'build/repair-selection-live-20261022-1'
    source=json.loads((old/'private-request-4.json').read_text(encoding='utf-8'))
    design=json.loads((old/'private-response-1.json').read_text(encoding='utf-8'))['questions'][0]
    physics_source=('净电通量是闭合面的有向面积分，等于内部净电荷除以真空介电常数。净通量零不能推出各点电场为零。'
                    '均匀电场穿过盒子的两端，可有等量反向的通量。外部电荷可影响内部电场，但不贡献净通量。')
    data=[('physics',physics_source,'内部净电荷为零能否推出内部电场处处为零？说明理由。',
           '净通量是整体有符号求和；穿入穿出可抵消，不能当成各点的场。',
           [design,{'question':'空间存在沿x正方向的均匀非零电场E，长方体内无电荷且两端面垂直x轴。判断穿过整个表面的净通量与内部电场是否为零，说明整体求和与局部量的区别。',
             'solution':'两端面有向通量等量异号，侧面零，净通量零；场已给为非零，不矛盾。',
             'rubric':'净通量40分，局部场30分，区分理由30分。'}],
           {'issue_index':0,'focus':'点电荷情境的前置与定义域；不把主结论判错。'}),
          ('math','实数数列收敛：对任意ε>0存在N，对所有n>N有|x_n-a|<ε。唯一性可用反证法：若a<b，取ε=(b-a)/2，两个开邻域不相交；取较大门槛使两条件同时成立。',
           '唯一性证明为什么取两个候选极限距离的一半？',
           '任选正ε由全称量词允许，选择不相交邻域制造矛盾；开区间端点不包含中点。',
           [{'question':'实数数列有两个不同的候选极限a<b。取ε=(b-a)/2，但把极限条件改为|x_n-a|≤ε和|x_n-b|≤ε。证明这两个闭邻域没有交点，因此矛盾。',
             'solution':'两个闭邻域不相交，得到矛盾。','rubric':'证明无交点50分，矛盾50分。'},
            {'question':'实数数列被假设同时收敛于a<b。某证明取ε=(b-a)/3。说明此选择是否合法、两个开邻域是否重叠，以及怎样让两条最终估计同时适用。不要求新的定理。',
             'solution':'ε>0合法；半径和小于距离，不相交；取max(N1,N2)。','rubric':'合法性30分，分离40分，共同门槛30分。'}],
           {'issue_index':0,'focus':'闭邻域共享中点；1/3等其他充分选择应保留。'}),
          ('social','观察到记笔记与成绩相关不能单独推出因果；动机、基础等可能混杂。大样本减小随机误差，不排除系统偏差。统计显著不等于效应大。',
           '为什么两万人的观察调查仍不能证明记笔记改善成绩？',
           '区分关联与因果，指出可能混杂；不因样本大认定已经排除。',
           [{'question':'调查两万名学生，记笔记组平均成绩80分，不记笔记组70分，p<0.001。没有其他信息。求让同一个学生开始记笔记带来的确切因果提升分数。',
             'solution':'确切提高10分，因为差异显著。','rubric':'答10分100分。'},
            {'question':'同样的观察调查中两组均值相差10分、统计显著。一名学生说已证实每个人多记笔记都能提高10分。指出这句话超出了数据的哪一步，并说明一个可能的混杂因素怎样影响两者。无需计算因果效应。',
             'solution':'组间关联不等于个体因果效应；动机可同时影响记笔记和成绩。','rubric':'区分关联/因果50分，具体混杂解释50分。'}],
           {'issue_index':0,'focus':'观察数据不足以识别确切因果效应；有效辨析题不拦截。'})]
    result=[]
    for name,digest,original,teaching,questions,expected in data:
        for i,item in enumerate(questions):
            item.update(topic=name,source_url='',repair_target_index=i,
                        repair_focus='观察是否能围绕原卡点说明必要条件及关键理由。')
        targets=[{'index':i,'topic':name,'question':original,'kind':'argumentation','basis':'student_self_report',
                  'cause':'学生自报尚未分清条件与结论，未独立验证。','teaching_excerpt':teaching,
                  'teaching_excerpted':False,'checking_method':'先确认已知条件，再检查结论能否由条件推出。'} for i in range(2)]
        # The first physics item is exactly the previously retained real design.
        independent={'answers':[{'index':i,'solution':q['solution'],'issues':[]} for i,q in enumerate(questions)]}
        result.append(dict(name=name,digest=digest,questions=questions,independent=independent,
                           spec={'difficulty':2,'targets':targets},expected=expected))
    return source['messages'][0]['content'],result


async def main(name,refined=False):
    folder=(ROOT/'build'/name).resolve()
    if folder.parent!=(ROOT/'build').resolve() or folder.exists():raise SystemExit('Use a fresh direct build subfolder.')
    folder.mkdir();os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
    from studyforge import ai
    from studyforge.db import j
    from studyforge.repair_learning import review_context
    ai.save_settings({'agent_network_enabled':False,'agent_tools_enabled':False,'background_learning_enabled':False,'api_connection_mode':'direct'})
    calls=[]
    class Capture(ai.DeepSeekClient):
        async def _post(self,body,timeout=240,retry=True):
            if len(calls)>=8:raise RuntimeError('Bounded evaluation request cap.')
            entry={'number':len(calls)+1,'model':body.get('model')};calls.append(entry)
            started=time.perf_counter();number=len(calls)
            (folder/f'private-request-{number}.json').write_text(j(body),encoding='utf-8')
            try:
                packet=await super()._post(body,timeout,retry=False)
                raw=packet.get('choices',[{}])[0].get('message',{}).get('content','')
                (folder/f'private-response-{number}.json').write_text(raw,encoding='utf-8')
                entry.update(usage=packet.get('usage'),status='completed');return packet
            except Exception as exc:entry.update(status='failed',error=type(exc).__name__);raise
            finally:entry['seconds']=round(time.perf_counter()-started,3)
    client=Capture('deepseek-flash',effort='high');system,items=cases()
    if refined:
        items=items[:1]
        valid=items[0]['questions'][1]
        valid['solution']=('两端面外法线相反，通量为+EA和-EA，侧面法线与场垂直，故净通量零。'
            '题面已给电场非零，但仍须解释这为什么不与高斯定律矛盾：净电通量是闭合面上的有符号整体和，'
            '电场是各点的局部矢量，整体为零可由正负抵消造成，不推出局部为零。')
        valid['rubric']=('满分100分：两端面异号、侧面为零并得净通量零40分，仅判断零10分；'
            '联系已知正确识别内部场非零20分；解释有符号整体和可抵消、并不决定局部矢量40分，'
            '只复述两判断而无区别理由本项0分。接受等价论证，后续一致推理不重复扣同一错误。')
        items[0]['independent']['answers'][1]['solution']=valid['solution']
    report={'calls':calls,'trials':[],'refined_positive_control':refined}
    contexts={case['name']:review_context(case['spec']) for case in items}
    try:
        for number,case in enumerate(items):
            order=['baseline','candidate'] if number%2==0 else ['candidate','baseline']
            for variant in order:
                policy=BASE+(contexts[case['name']][0] if variant=='candidate' else '')
                user=(f'阶段：成品核查。检查题意是否确定、可独立求解和评分；学生版只提取question/topic/source_url，不能在这些字段泄漏答案。\n{policy}\n资料：\n{case["digest"]}'
                      f'\n独立解法：{case["independent"]}\n独立解题疑点编号：[]\n题目与解答：\n{case["questions"]}')
                # Fixed supplied solution, not a new independent-solving quality test.
                raw=await client.complete(system,user,json_mode=True)
                result=ai.parse_json_response(raw)
                if type(result.get('passed')) is not bool or not isinstance(result.get('issues'),list):raise ValueError('Invalid audit report.')
                item={'case':case['name'],'variant':variant,'call':len(calls),'passed':result['passed'],
                      'issue_indices':sorted({x['index'] for x in result['issues'] if type(x.get('index')) is int}),
                      'expected':case['expected'],'repair_scope':contexts[case['name']][1] if variant=='candidate' else None}
                report['trials'].append(item);print(j(item),flush=True)
        report['status']='completed'
    except Exception as exc:report.update(status='failed',error=type(exc).__name__+': '+str(exc))
    finally:
        await client.close();(folder/'report.json').write_text(j(report),encoding='utf-8')


if __name__=='__main__':asyncio.run(main(sys.argv[1],refined='--refined' in sys.argv[2:]))
