"""Current and proposed checks inside the existing one-call fast review."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from scripts.teaching_inference_candidate import CASES

ROOT = Path(__file__).resolve().parents[1]
INFERENCE_CHECK = (
    '核查新增结论是否超出已知条件：通常、往往、倾向等缓和词不能代替方向、大小或因果归属的依据。'
    '例子必须仍解释同一个对象，不能把解释某行为的产生换成解释对该行为的反应，再冒称已说明原问题。'
    '明确写为假设的示意按其假设核对，不要求它有真实调查数据；一种可能机制不等于唯一原因，观察概率差也不自动等于因果作用。'
    '疑点只限制相应断言，其他有依据的结论应保留；条件不足与已经证伪须区分，不把可选扩展当成实质遗漏。'
)
MARKER = '按所选风格检查具体的术语解释'


async def main(name, selected=()):
    out = ROOT/'build'/name
    if (out/'results.json').exists(): raise SystemExit('Use a new folder to preserve previous runs.')
    out.mkdir(parents=True, exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(out/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(out/'isolated-model')
    from studyforge import ai
    from studyforge.review import review_explanation
    ai.save_settings({'api_connection_mode': 'direct', 'agent_tools_enabled': False,
        'agent_network_enabled': False, 'background_learning_enabled': False, 'model_concurrency': 2})
    drafts = {
        'causal': (ROOT/'build/homework-followup-real-20261014-1/causal-read_feedback.md').read_bytes().decode('utf-8'),
        'explanation': (ROOT/'build/teaching-inference-real-20261015-1/explanation-candidate.md').read_bytes().decode('utf-8'),
        'control': '# 分清一个因素和唯一原因\n\n原文认为制度规则会影响行为，但未排除习惯、资源和个人目标。\n\n'
            '下面是假设的示意，不是调查事实：小林今天准时到办公室。他既在意迟到扣奖，也有提前出门的习惯；地铁正常运行，使他能按时到。'
            '“为什么今天准时”可以同时从这些因素得到解释。规则改变迟到的代价，是其中一条机制；早起习惯和可用交通也可能参与。'
            '示意不能证明真实小林的心理，只说明一种机制能够解释某结果，并不自动排除其他机制。'
            '这里没有比较有规则和无规则的相似人群，不能据此确定规则效应的大小或方向。\n\n'
            '## 系统性总结\n\n保留制度可能影响行为的观点，区分一种可能解释与唯一原因；要认定实际作用还需证据，假设例子仅说明逻辑。'
    }
    drafts['math_control'] = '# 两个向量的和\n\n已知两个平面向量的长度为5和12，但没有给出夹角或随机取向的分布。\n\n'
    drafts['math_control'] += '由三角不等式及反三角不等式，合向量长度在7到17之间。作为具体取向示意，同向时长度为5+12=17，反向时长度为12−5=7。'
    drafts['math_control'] += '这两个取向都满足题设，分别达到范围的端点。范围来自向量的几何约束；没有给出概率分布，不能把17说成最可能的结果。\n\n## 系统性总结\n\n可以确定长度范围及两个端点取向；不能凭空确定最可能的长度。'
    if selected:
        if set(selected)-drafts.keys(): raise SystemExit('Unknown case.')
        drafts = {key:drafts[key] for key in selected}
    else: drafts.pop('math_control')
    inputs = {}
    for key, draft in drafts.items():
        case = CASES['explanation' if key=='control' else 'bound' if key=='math_control' else key]
        inputs[key] = {'draft': draft, 'source': case['material'], 'requirements': case['question']+
            '\n本次仅核查这份现成讲解的实质错误；不要因原回答未另加标题、引文格式或系统总结而判错。',
            'draft_sha256': hashlib.sha256(draft.encode()).hexdigest()}
    (out/'inputs.json').write_text(json.dumps(inputs, ensure_ascii=False, indent=2), encoding='utf-8')
    rows, gate = [], asyncio.Semaphore(2)
    class Recorder:
        def __init__(self, arm, records): self.arm, self.records = arm, records
        async def complete(self, system, user, **kw):
            assert INFERENCE_CHECK not in system, 'Experimental check already enabled; use saved request inputs for historical replays.'
            if self.arm=='expanded':
                assert system.count(MARKER)==1; system = system.replace(MARKER, INFERENCE_CHECK+MARKER)
            item = {'system': system, 'user': user, 'json_mode': kw.get('json_mode', False)}; self.records.append(item)
            result = await self.client.complete(system, user, **kw)
            item['response'] = result
            return result
    async def sample(key, arm):
        async with gate:
            records = []; wrapper = Recorder(arm, records); client = ai.DeepSeekClient('deepseek-flash', effort='high'); wrapper.client = client
            start = time.perf_counter(); row = {'case': key, 'arm': arm, 'model': 'deepseek-flash', 'effort': 'high'}
            try:
                body, reports = await asyncio.wait_for(review_explanation(wrapper, inputs[key]['source'], inputs[key]['draft'],
                    mode='fast', learning_mode='deep', explanation_style='balanced', requirements=inputs[key]['requirements'], summary_level=3), 300)
                file = key+'-'+arm+'.md'; (out/file).write_text(body, encoding='utf-8', newline='')
                row.update(status='completed', output_file=file, output_sha256=hashlib.sha256(body.encode()).hexdigest(),
                           reports=reports, unchanged=body==inputs[key]['draft'])
            except Exception as exc: row.update(status='failed', error=type(exc).__name__+': '+str(exc))
            finally:
                await client.close(); row.update(seconds=round(time.perf_counter()-start, 2), model_calls=len(records))
                (out/(key+'-'+arm+'-requests.json')).write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
                rows.append(row); (out/'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps({k:v for k,v in row.items() if k!='reports'}, ensure_ascii=True), flush=True)
    await asyncio.gather(*(sample(key, arm) for key in inputs for arm in ('current','expanded')))


if __name__=='__main__': asyncio.run(main(sys.argv[1], sys.argv[2:]))
