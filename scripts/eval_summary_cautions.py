"""Actual summary evidence ablation, isolated synthetic material, no tools."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
CASES = {
    'math': {'title': '尾部估计的适用范围',
        'recaps': ['一个尾部估计给出 x_n<0.01。', '后续论证用这个估计控制误差。'],
        'detail': '核查发现：此估计只对n>100成立，前100项不受它约束；不能在总结中改成所有正整数n均有x_n<0.01。',
        'expectation': 'Keep n>100 attached to the bound, and do not claim the concern was independently resolved.'},
    'causal': {'title': '随机提醒与实际行为的因果归属',
        'recaps': ['一次随机提醒实验中，收到记笔记提醒者的平均成绩更高。', '比较设计帮助研究学习行为与成绩的关系。'],
        'detail': '核查发现：随机分配的是提醒，不是实际记笔记行为；有人不遵从，提醒也可能改变学习投入，且没有排除其他路径的假设。不能断言差异已经证明记笔记本身的效果。',
        'expectation': 'Separate the assigned reminder effect from the behaviour effect; do not invent missing assumptions or results.'},
}


async def main(folder, names=()):
    out = ROOT / 'build' / folder
    if (out / 'requests.json').exists(): raise SystemExit('Use a new folder to preserve earlier runs.')
    out.mkdir(parents=True, exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(out / 'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(out / 'isolated-model')
    from studyforge import ai
    from studyforge.teaching import summary_context, finish_explanation
    ai.save_settings({'api_connection_mode': 'direct', 'agent_tools_enabled': False,
        'agent_network_enabled': False, 'background_learning_enabled': False, 'model_concurrency': 2})
    requests = {}
    for name, case in CASES.items():
        chapters = [f'# 第{i+1}部分\n'+'已经写完的相关解释。'*6000+'\n## 系统性总结\n'+recap
            for i, recap in enumerate(case['recaps'])]
        chapters[0] += '\n\n## 待核实事项\n- '+case['detail']
        prepared = summary_context(chapters)
        assert prepared['excerpted'] and case['detail'] in prepared['text']
        class Capture:
            async def complete(self, system, user):
                self.request = {'system': system, 'user': user}
                return '## 系统性总结\n占位。'
        capture = Capture()
        await finish_explanation(capture, '\n\n'.join(chapters), chapters=chapters, summary_plan=prepared,
            explanation_style='balanced')
        for arm in ('omitted_detail', 'with_detail'):
            request = dict(capture.request)
            if arm == 'omitted_detail':
                assert request['user'].count(case['detail']) == 1
                request['user'] = request['user'].replace(case['detail'], '[本对照臂不提供此条核查记录的具体正文]')
            requests[name+':'+arm] = {'case': name, 'arm': arm, 'request': request,
                'title': case['title'], 'expectation': case['expectation'],
                'request_sha256': hashlib.sha256(json.dumps(request, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                'scope': 'Both arms use the current summary prompt; only the actual caution detail is ablated. Not a historical-version replay.'}
    (out / 'requests.json').write_text(json.dumps(requests, ensure_ascii=False, indent=2), encoding='utf-8')
    if set(names)-requests.keys(): raise SystemExit('Unknown selected case.')
    rows, gate = [], asyncio.Semaphore(2)
    async def sample(name, entry):
        async with gate:
            client = ai.DeepSeekClient('deepseek-flash', effort='high')
            start = time.perf_counter()
            row = {k: entry[k] for k in ('case', 'arm', 'request_sha256')}
            row.update(model='deepseek-flash', effort='high', tools=False)
            try:
                answer = await asyncio.wait_for(client.complete(**entry['request']), 300)
                filename = name.replace(':', '-')+'.md'
                (out / filename).write_text(answer, encoding='utf-8', newline='')
                row.update(status='completed', answer_file=filename,
                    answer_sha256=hashlib.sha256(answer.encode()).hexdigest(), characters=len(answer))
            except Exception as exc: row.update(status='failed', error=type(exc).__name__+': '+str(exc))
            finally:
                await client.close()
                row['seconds'] = round(time.perf_counter()-start, 2)
                rows.append(row)
                (out / 'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(row, ensure_ascii=True), flush=True)
    await asyncio.gather(*(sample(name, entry) for name, entry in requests.items() if not names or name in names))


if __name__ == '__main__': asyncio.run(main(sys.argv[1], sys.argv[2:]))
