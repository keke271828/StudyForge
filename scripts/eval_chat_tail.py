"""Replay native captured chat messages with redundant teaching tail omitted."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


async def main(name, source_folder='task-order-real-20261017-1'):
    out = ROOT / 'build' / name
    if out.exists() and any(out.iterdir()): raise SystemExit('Use a fresh folder.')
    out.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(out / 'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(out / 'isolated-model')
    from studyforge import ai
    from studyforge.db import j
    from studyforge.deepseek_protocol import Reply
    from studyforge.learning_modes import mode_task_reminder
    from studyforge.teaching_policy import TEACHING_TASK_REMINDER
    from studyforge.teaching_styles import style_task_reminder
    from studyforge.scheduling import model_slot
    from scripts.diagnose_deepseek_speed import traced_class
    ai.save_settings({'api_connection_mode': 'direct', 'agent_tools_enabled': False, 'background_learning_enabled': False,
                      'agent_network_enabled': False, 'library_reference_mode': 'off', 'model_concurrency': 2})
    packet = json.loads((ROOT / 'build' / source_folder / 'cases.json').read_text(encoding='utf-8'))
    cases = []
    for case in packet['cases']:
        if case['role'] != 'tutor': continue
        before = case['requests']['baseline']
        after = copy.deepcopy(before)
        tail = style_task_reminder(case['style']) + TEACHING_TASK_REMINDER + mode_task_reminder(case['mode'])
        assert before[-1]['content'] == case['question'] + tail
        after[-1]['content'] = case['question']
        assert before[:-1] == after[:-1]
        cases.append(case | {'requests': {'baseline': before, 'plain_question': after}, 'removed_characters': len(tail)})
    (out / 'cases.json').write_text(j({'cases': cases, 'model': 'deepseek-flash', 'effort': 'high',
        'difference': 'omit_redundant_tutor_tail_keep_full_system_and_sources', 'planned_real_requests': len(cases) * 2}), encoding='utf-8')
    cls = traced_class(); results = []
    for index, case in enumerate(cases):
        async def sample(arm):
            client = cls('deepseek-flash', effort='high'); began = time.perf_counter()
            row = {'case': case['id'], 'arm': arm, 'role': 'tutor', 'model': 'deepseek-flash', 'effort': 'high'}
            try:
                body = copy.deepcopy(case['request_options']); body['messages'] = copy.deepcopy(case['requests'][arm])
                reply = Reply(service_name='DeepSeek')
                async with asyncio.timeout(240):
                    async with model_slot('deepseek'):
                        async for part in client.stream_packets(body): reply.accept(part)
                    reply.validate(client.model)
                assert not reply.calls and reply.content.strip()
                filename = case['id'] + '-' + arm + '-final.md'
                (out / filename).write_text(reply.content, encoding='utf-8')
                row.update(status='completed', answer_file=filename, output_characters=len(reply.content),
                           answer_sha256=hashlib.sha256(reply.content.encode()).hexdigest())
            except Exception as exc:
                row.update(status='failed', error_type=type(exc).__name__)
            finally:
                await client.close()
            row.update(seconds=time.perf_counter() - began, model_requests=len(client.traces),
                       http_attempts=[t.public() for t in client.traces])
            results.append(row); (out / 'results.json').write_text(j(results), encoding='utf-8')
            print(json.dumps({k: row[k] for k in ('case', 'arm', 'status', 'seconds', 'model_requests')}), flush=True)
        arms = ('baseline', 'plain_question') if index == 0 else ('plain_question', 'baseline')
        await asyncio.gather(*(sample(arm) for arm in arms))


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv)>2 else 'task-order-real-20261017-1'))
