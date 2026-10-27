"""Six bounded real summaries: unchanged system, spare-context body evidence."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
CASES={
    'math':{'title':'迭代的参数范围与任意初值',
        'body':'本例的目标是使任意实初值x₀都收敛到0，迭代为xₙ₊₁=(1-q)xₙ。仅当0<q<2时才有这一保证；q=0会保持原初值，q=2通常正负交替。初值恰好为0的特殊情形不能推出任意初值的结论。',
        'recaps':['在本节讨论的参数条件下，迭代趋于0。','判断迭代要看更新规则及初值的作用。']},
    'causal':{'title':'随机提醒与实际学习行为',
        'body':'本节使用一个假设实验示意，不是现实调查报告。随机分配的是记笔记提醒，而不是实际记笔记行为；提醒组平均高3分。由于未排除提醒改变学习投入等其他路径，也未保证所有人遵从，不能把提醒组差异直接称为多记笔记本身的因果效果。',
        'recaps':['随机安排提醒后，观察到两组成绩差异。','应按实际随机分配的对象解读比较设计。']},
    'chemistry':{'title':'总压强、分压与惰性气体',
        'body':'本节的压强变化默认指恒温压缩理想混合气体。平衡方向还取决于反应气体的计量数差，不能笼统说所有增压都向少气体侧移动。若恒温恒容加入理想惰性气体，总压强增加，各反应气体分压保持不变，平衡不移动；不能把它套成恒温压缩。',
        'recaps':['压力变化与气相反应的平衡方向有关。','需区分总压强、分压与改变压强的具体方式。']},
}


def chapters(case):
    return ['# 第一部分\n\n'+('已完成的背景介绍。'*3500)+'\n\n## 使用条件\n\n'+case['body']+'\n\n'+
        ('已完成的展开说明。'*3500)+'\n\n## 系统性总结\n'+case['recaps'][0],
        '# 第二部分\n\n'+('已经讲解过的具体示意。'*3500)+'\n\n## 系统性总结\n'+case['recaps'][1]]


async def main(name):
    out=ROOT/'build'/name
    if out.exists() and any(out.iterdir()):raise SystemExit('Use a fresh folder.')
    out.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(out/'data');os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(out/'isolated-model')
    from studyforge import ai
    from studyforge.teaching import summary_context,finish_explanation
    from studyforge.summary_evidence import augment
    from scripts.diagnose_deepseek_speed import traced_class
    from unittest.mock import patch
    ai.save_settings({'api_connection_mode':'direct','agent_tools_enabled':False,'agent_network_enabled':False,
        'background_learning_enabled':False,'model_concurrency':2})
    cls=traced_class();results=[]
    (out/'input-cases.json').write_text(json.dumps(CASES,ensure_ascii=False,indent=2),encoding='utf-8')
    for number,(name,case) in enumerate(CASES.items()):
        values=chapters(case)
        with patch('studyforge.summary_evidence.augment',lambda plan,*a,**k:plan):base=summary_context(values,budget=6000)
        candidate=augment(base,values,6000)
        assert case['body'] not in base['text'] and case['body'] in candidate['text']
        assert candidate['text'].startswith(base['text']) and len(candidate['text'])<=6000
        plans={'baseline':base,'with_body':candidate}
        (out/(name+'-plans.json')).write_text(json.dumps(plans,ensure_ascii=False,indent=2),encoding='utf-8')
        async def sample(arm):
            native=cls('deepseek-flash',effort='high');calls=[];start=time.perf_counter()
            class Adapter:
                async def complete(self,system,user,**kwargs):
                    assert not calls
                    calls.append({'system':system,'user':user});answer=''
                    async for kind,value in native.agent_stream([{'role':'system','content':system},{'role':'user','content':user}]):
                        if kind=='final':answer=value
                    calls[0]['response']=answer;return answer
            row={'case':name,'arm':arm,'model':'deepseek-flash','effort':'high','summary_only':True}
            try:
                async with asyncio.timeout(240):
                    await finish_explanation(Adapter(),'\n\n'.join(values),chapters=values,summary_plan=plans[arm],explanation_style='balanced')
                file=name+'-'+arm+'-final.md';(out/file).write_text(calls[0]['response'],encoding='utf-8')
                row.update(status='completed',answer_file=file)
            except BaseException as exc:row.update(status='failed',error_type=type(exc).__name__)
            finally:await native.close()
            row.update(seconds=time.perf_counter()-start,model_requests=len(native.traces),input_characters=len(plans[arm]['text']),
                http_attempts=[t.public() for t in native.traces],input_sha256=hashlib.sha256(plans[arm]['text'].encode()).hexdigest())
            (out/(name+'-'+arm+'-records.json')).write_text(json.dumps(calls,ensure_ascii=False,indent=2),encoding='utf-8')
            results.append(row);(out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:row[k] for k in ['case','arm','status','seconds','model_requests']},ensure_ascii=True),flush=True)
        order=['baseline','with_body'] if number%2==0 else ['with_body','baseline']
        await asyncio.gather(*(sample(arm) for arm in order))


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
