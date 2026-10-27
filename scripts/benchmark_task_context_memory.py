"""Controlled registered-task waits, using real SQLite/controllers and buffers.

Separate processes compare the saved runner/current. No cloud requests, native
models or user DB. This measures controller/retry retention, not whole app RAM.
"""
import argparse
import asyncio
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import tracemalloc
import weakref

from scripts.benchmark_vision_admission import working_set

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'build/task-context-memory-20261013'
TASKS = 6


class OriginalBuffer:
    def __init__(self):
        self.text = bytearray(8 * 1024 * 1024)


def initialize(mode):
    from studyforge import ai
    from studyforge.db import create_job, create_project
    ai.save_settings({'task_auto_retry': True, 'task_retry_limit': 5, 'background_learning_enabled': False})
    project = create_project('Controller memory fixture')
    ids = []
    for index in range(TASKS):
        payload = dict(conversation_id=f'own-chat-{index}', _mobile_device_id=f'own-device-{index}',
                       instructions=f'固定任务 {index}')
        if mode == 'running':
            payload['dialogue_snapshot'] = dict(mentor={'model': 'unchanged-model'}, messages=[
                {'role': 'user', 'content': ('完整的知识疑问和论证。' * 25000) + f' USER_END_{index}'},
                {'role': 'assistant', 'content': ('已经完成的讲解和推导。' * 25000) + f' ASSISTANT_END_{index}'}])
        ids.append(create_job(project['id'], 'generate', payload))
    return ids


async def run(variant, mode):
    import httpx
    from studyforge import job_control, task_retry
    from studyforge.db import one, update_job
    from studyforge.mobile_context import remote_device
    from studyforge.scheduling import execution_context
    spec = importlib.util.spec_from_file_location('studyforge._context_before', FOLDER / 'job_control.before.py')
    before = importlib.util.module_from_spec(spec); spec.loader.exec_module(before)
    api = before if variant == 'before' else job_control
    task_retry.retry_delay = lambda *a: 300
    ids = initialize(mode)
    snapshots = [hashlib.sha256(one('SELECT payload_json FROM jobs WHERE id=?', (ident,))['payload_json'].encode()).hexdigest() for ident in ids]
    release = asyncio.Event(); entered = []; originals = []; calls = [0] * TASKS
    async def work(index):
        calls[index] += 1
        if mode == 'retry':
            original = OriginalBuffer(); originals.append(weakref.ref(original))
            try:
                raise httpx.ConnectError('controlled native request interrupted')
            except Exception as cause:
                raise RuntimeError('Controlled wrapper failure') from cause
        context = execution_context.get()
        assert context['conversation_id'] == f'own-chat-{index}' and remote_device.get() == f'own-device-{index}'
        entered.append(index)
        await release.wait()
        update_job(ids[index], 'completed', 100)
    gc.collect(); initial_ws, _ = working_set(); tracemalloc.start(); start = time.perf_counter()
    tasks = [api.start_job(ident, lambda i=index: work(i)) for index, ident in enumerate(ids)]
    try:
        for _ in range(500):
            if mode == 'running' and len(entered) == TASKS: break
            if mode == 'retry' and all((task_retry.public('project', ident) or {}).get('state') == 'waiting' for ident in ids): break
            await asyncio.sleep(.01)
        else: raise RuntimeError('Fixture did not reach the requested wait boundary')
        await asyncio.sleep(.05)
        current, peak = tracemalloc.get_traced_memory(); ws, peak_ws = working_set()
        elapsed = (time.perf_counter() - start) * 1000
        result = dict(variant=variant, mode=mode, task_count=TASKS, external_model_requests=0,
                      initialization_to_wait_ms=elapsed, python_live_bytes=current, python_peak_bytes=peak,
                      initial_working_set_bytes=initial_ws, process_working_set_bytes=ws, process_peak_working_set_bytes=peak_ws,
                      live_original_buffers=sum(reference() is not None for reference in originals),
                      original_buffer_bytes=8 * 1024 * 1024 if mode == 'retry' else 0,
                      calls=calls, scope='Six registered task controllers waiting; no model inference or application UI')
        tracemalloc.stop()
        after = [hashlib.sha256(one('SELECT payload_json FROM jobs WHERE id=?', (ident,))['payload_json'].encode()).hexdigest() for ident in ids]
        assert after == snapshots
        result['full_saved_intents_unchanged'] = True
        if mode == 'retry':
            result['retry_states'] = [task_retry.public('project', ident) for ident in ids]
            assert all(row['retry_count'] == 1 and row['limit_count'] == 5 and row['last_error'] and row['reason'] for row in result['retry_states'])
            assert result['live_original_buffers'] == (TASKS if variant == 'before' else 0)
        else:
            release.set(); await asyncio.gather(*tasks)
            assert all(one('SELECT status FROM jobs WHERE id=?', (ident,))['status'] == 'completed' for ident in ids)
        (FOLDER / f'{mode}-{variant}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({key: result[key] for key in ('variant', 'mode', 'python_live_bytes', 'python_peak_bytes',
              'process_working_set_bytes', 'process_peak_working_set_bytes', 'live_original_buffers', 'initialization_to_wait_ms')}, ensure_ascii=False), flush=True)
    finally:
        release.set()
        if tracemalloc.is_tracing(): tracemalloc.stop()
        for ident in ids:
            if any(not task.done() for task in tasks): await api.cancel_job(ident)
        await asyncio.gather(*tasks, return_exceptions=True)


def compare():
    results = {}
    for mode in ('running', 'retry'):
        before = json.loads((FOLDER / f'{mode}-before.json').read_text(encoding='utf-8'))
        current = json.loads((FOLDER / f'{mode}-current.json').read_text(encoding='utf-8'))
        assert before['full_saved_intents_unchanged'] and current['full_saved_intents_unchanged']
        if mode == 'retry':
            def evidence(result):
                return [{key: row[key] for key in ('enabled','limit_count','retry_count','state','last_error','reason')} for row in result['retry_states']]
            assert evidence(before) == evidence(current)
        results[mode] = dict(before=before, current=current, durable_intent_and_retry_evidence_preserved=True)
    (FOLDER / 'comparison.json').write_text(json.dumps(dict(passed=True, measurements=results), ensure_ascii=False, indent=2), encoding='utf-8')
    print('Complete saved task intent and retry count/reason/error records preserved', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('variant', choices=['before', 'current', 'compare'])
    parser.add_argument('--mode', choices=['running','retry'], default='running'); args = parser.parse_args()
    FOLDER.mkdir(parents=True, exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(FOLDER / ('data-' + args.mode + '-' + args.variant))
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(FOLDER / 'unused-model')
    if args.variant == 'compare': compare()
    else: asyncio.run(run(args.variant, args.mode))
