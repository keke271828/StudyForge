"""Reuse preserved answers to inspect real fast review; no learner data writes."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import time


ROOT = Path(__file__).resolve().parents[1]


def sha(value): return hashlib.sha256(value.encode('utf-8')).hexdigest()


async def main(args):
    out = ROOT / 'build' / args.folder
    if (out / 'results.json').exists(): raise SystemExit('Use a new output folder to preserve every run.')
    out.mkdir(parents=True, exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(out / 'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(out / 'isolated-model')
    from studyforge import ai
    from studyforge.review import review_explanation
    from scripts.compare_teaching_models import CASES

    ai.save_settings({'agent_tools_enabled': False, 'agent_network_enabled': False,
        'background_learning_enabled': False, 'api_connection_mode': 'direct', 'model_concurrency': 2})
    cases = [
        ('field-flawed', 'field', 'kimi-field-attempt2.md', 'Contains net-zero versus no-source and necessity errors.'),
        ('field-control', 'field', 'codex-sol6-field-attempt1.md', 'Manual inspection found no material error in this sample.'),
        ('proof-control', 'proof', 'codex-astra-proof-attempt1.md', 'Manual inspection found no material error in this sample.'),
    ]
    inputs, rows, gate = [], [], asyncio.Semaphore(2)
    for name, case, filename, expectation in cases:
        draft = (ROOT / 'build/model-teaching-20261014' / filename).read_text(encoding='utf-8')
        (out / (name + '-original.md')).write_text(draft, encoding='utf-8', newline='')
        inputs.append({'name': name, 'source': CASES[case]['source'],
            'requirements': CASES[case]['question'] + '\n只核对当前回答内容，不以未另加文档标题、系统性总结或来源格式为由判错。',
            'draft': draft, 'draft_sha256': sha(draft), 'original_file': filename, 'expectation': expectation})
    (out / 'inputs.json').write_text(json.dumps(inputs, ensure_ascii=False, indent=2), encoding='utf-8')

    class Recorded:
        def __init__(self, client, records): self.client, self.records = client, records
        @property
        def conversation(self): return self.client.conversation
        def fork(self): return Recorded(self.client.fork(), self.records)
        async def complete(self, system, user, **kwargs):
            record = {'system': system, 'user': user, 'json_mode': kwargs.get('json_mode', False)}
            self.records.append(record)
            result = await self.client.complete(system, user, **kwargs)
            record.update(response=result, response_sha256=sha(result))
            return result
        async def close(self): await self.client.close()

    async def sample(case):
        async with gate:
            records = []
            client = Recorded(ai.DeepSeekClient('deepseek-flash', effort='high'), records)
            start = time.perf_counter()
            row = {'case': case['name'], 'model': 'deepseek-flash', 'effort': 'high', 'tools': False}
            try:
                result, reports = await asyncio.wait_for(review_explanation(client, case['source'], case['draft'],
                    mode='fast', learning_mode='deep', explanation_style='balanced', summary_level=3,
                    requirements=case['requirements']), 300)
                file = case['name'] + '-reviewed.md'
                (out / file).write_text(result, encoding='utf-8', newline='')
                row.update(status='completed', answer_file=file, answer_sha256=sha(result), audit_reports=reports,
                    original_body_unchanged=result == case['draft'])
            except Exception as exc:
                row.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
            finally:
                await client.close()
                row.update(seconds=round(time.perf_counter()-start, 2), model_requests=len(records))
                (out / (case['name'] + '-requests.json')).write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
                rows.append(row)
                (out / 'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps({k: v for k, v in row.items() if k != 'audit_reports'}, ensure_ascii=True), flush=True)
    await asyncio.gather(*(sample(case) for case in inputs))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder')
    asyncio.run(main(parser.parse_args()))
