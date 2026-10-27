"""Four real fast audits on synthetic sources, without storing hidden reasoning."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


async def main(name):
    out = ROOT/'build'/name
    if out.exists(): raise SystemExit('Use a new evidence folder.')
    out.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(out/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(out/'isolated-model')
    from studyforge import ai, review
    from studyforge.teaching_policy import DATA_SCOPE_RULES
    from scripts.diagnose_deepseek_speed import traced_class
    ai.save_settings({'api_connection_mode':'direct', 'agent_tools_enabled':False,
        'agent_network_enabled':False, 'background_learning_enabled':False,
        'model_concurrency':2, 'library_reference_mode':'off'})
    source = ('[材料.txt｜行 1-1]\n给定反应A+B→C的速率模型v=k[A][B]，浓度单位mol/L，'
        '速率单位mol/(L·s)。k=0.2 L/(mol·s)，[A]=0.5 mol/L，[B]=0.3 mol/L。'
        '反应式不能单独推出该速率律。')
    requirement = '只说明这组给定数值的含义，完成代入和单位推算，区分原文与补充假设。不要扩写其他章节，不出题。'
    main_text = ('由给定模型得v=0.2×0.5×0.3=0.03 mol/(L·s)。'
        'k的单位由速率单位除以两个浓度单位得到L/(mol·s)。总反应式本身不能推出这一速率模型。')
    cases = [
        {'id':'unsupported_initial', 'expect':'identify_unsupported_initial_without_discarding_valid_calculation',
         'document':'# 给定条件\n\n这组初始浓度是[A]=0.5 mol/L、[B]=0.3 mol/L。\n\n'+main_text+
            '\n\n## 总结\n给定的0.5和0.3是反应刚开始的浓度，所以0.03是初始速率。'},
        {'id':'explicit_hypothesis', 'expect':'allow_explicit_hypothetical_example',
         'document':'# 给定条件\n\n资料只给出这些浓度，未说明是否为初始时刻。\n\n'+main_text+
            '\n\n补充假设：若恰在反应开始时测到上述浓度，那么在这个假设下0.03是该初始时刻的速率。'
            '这只是展示如何用模型的假设例子，不是原文已给定的条件。'
            '\n\n## 总结\n已知的是给定模型及给定浓度下的瞬时速率；初始状态未由资料确认。'},
    ]
    (out/'cases.json').write_text(json.dumps({'source':source, 'requirements':requirement, 'cases':cases,
        'model':'deepseek-flash', 'effort':'high', 'modes':['fast'], 'tools':False,
        'baseline_scope_rules':review.INFERENCE_SCOPE_RULES.removesuffix(DATA_SCOPE_RULES),
        'current_scope_rules':review.INFERENCE_SCOPE_RULES}, ensure_ascii=False, indent=2), encoding='utf-8')
    results = []
    base = traced_class()
    class Client(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.response_receipts = []

        async def _post(self, body, timeout=240, retry=True):
            # A detached completion uses non-streaming POST. The stream tracer
            # alone would report zero requests, despite a completed real call.
            started = time.perf_counter()
            receipt = {'request_sha256':hashlib.sha256(json.dumps(body, sort_keys=True,
                ensure_ascii=False).encode()).hexdigest()}
            self.response_receipts.append(receipt)
            try:
                packet = await super()._post(body, timeout, retry)
                receipt.update(status='completed', usage=packet.get('usage'), returned_model=packet.get('model'))
                return packet
            except Exception as exc:
                receipt.update(status='failed', error_type=type(exc).__name__)
                raise
            finally:
                receipt['seconds'] = time.perf_counter()-started
    for case in cases:
        async def run(arm):
            client = Client('deepseek-flash', effort='high')
            packets = []
            class Adapter:
                async def complete(self, system, user, **kwargs):
                    if arm == 'baseline': system = system.replace(DATA_SCOPE_RULES, '', 1)
                    packets.append({'system':system, 'user':user})
                    return await client.complete(system, user, **kwargs)
            row = {'case':case['id'], 'arm':arm, 'expected':case['expect']}
            start = time.perf_counter()
            try:
                async with asyncio.timeout(240):
                    document, reports = await review.review_explanation(Adapter(), source, case['document'],
                        mode='fast', explanation_style='balanced', requirements=requirement, summary_level=3)
                file = case['id']+'-'+arm+'-reviewed.md'
                (out/file).write_text(document, encoding='utf-8')
                row.update(status='completed', document_file=file, reports=reports,
                    document_sha256=hashlib.sha256(document.encode()).hexdigest())
            except Exception as exc:
                row.update(status='failed', error_type=type(exc).__name__)
            finally:
                await client.close()
            row.update(seconds=time.perf_counter()-start, completion_calls=len(packets),
                nonstream_post_invocations=len(client.response_receipts),
                response_receipts=client.response_receipts,
                transport_retry_count=None, transport_retry_note='Internal connection retries are not counted by this wrapper.')
            (out/(case['id']+'-'+arm+'-requests.json')).write_text(
                json.dumps(packets, ensure_ascii=False, indent=2), encoding='utf-8')
            results.append(row)
            (out/'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({k:row[k] for k in ('case','arm','status','seconds','completion_calls','nonstream_post_invocations')},ensure_ascii=True),flush=True)
        await asyncio.gather(run('baseline'), run('current'))


if __name__ == '__main__': asyncio.run(main(sys.argv[1]))
