"""Real large SQLite/text preparation; no cloud/model or user database.

Run before/current in separate processes. Timing excludes fixture construction,
output hashing and tracemalloc; a separate pass measures temporary Python memory.
The heartbeat measures the service event loop, not total generation duration.
"""
import argparse
import ast
import asyncio
import gc
import hashlib
import json
import os
from pathlib import Path
import statistics
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'build/source-preparation-20261013'


def saved_function(path, names, namespace):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def fixture(mode):
    from studyforge import ai, db
    ai.save_settings({'background_learning_enabled': False, 'task_parallel_enabled': True})
    project = db.create_project('Source preparation benchmark')
    text = ('完整原文：每个假设、计算与边界条件均保留。\n' * 240000) + 'FINAL_CONDITION_只在末尾出现'
    # Many page records also exercise deep copying and file metadata discovery.
    parts = ([{'locator': f'PDF 文件页 {i + 1}', 'text': text[i:i + 2400], 'meta': {}}
              for i in range(0, len(text), 2400)] if mode == 'pages' else
             [{'locator': '单个完整正文', 'text': text, 'meta': {}}])
    ident = 'source-fixture-original'
    db.execute('DELETE FROM sources WHERE id=?', (ident,))
    db.execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
               (ident, project['id'], '完整资料.txt', '.txt', 'fixture-original.txt', db.j(parts), 'ready', db.now()))
    sources = [dict(id=ident, project_id=project['id'], name='完整资料.txt', original_path='fixture-original.txt', segments=parts)]
    return project['id'], ident, sources


def digest_signature(result):
    from studyforge.json_digest import sha256
    return dict(sha256=sha256(result), chunk_count=len(result[1]), digest_characters=len(result[0]),
                last_condition_present='FINAL_CONDITION_只在末尾出现' in result[0])


async def sample(operation):
    interval = .01
    running = True
    gaps = []
    async def heartbeat():
        previous = time.perf_counter()
        while running:
            await asyncio.sleep(interval)
            current = time.perf_counter()
            gaps.append((current - previous) * 1000)
            previous = current
    ticker = asyncio.create_task(heartbeat())
    await asyncio.sleep(.02)
    start = time.perf_counter()
    try:
        result = await operation()
        elapsed = (time.perf_counter() - start) * 1000
        await asyncio.sleep(.02)
    finally:
        running = False
        await ticker
    return result, dict(elapsed_ms=elapsed, heartbeat_max_gap_ms=max(gaps),
                        heartbeat_p95_gap_ms=sorted(gaps)[min(len(gaps)-1, int(len(gaps)*.95))],
                        heartbeat_samples=len(gaps))


async def run(variant, mode):
    from studyforge import ai, server
    project, ident, sources = fixture(mode)
    legacy_ai = saved_function(FOLDER / 'ai.before.py', {'source_chunks', 'source_digest'}, dict(ai.__dict__))
    legacy_server = saved_function(FOLDER / 'server.before.py', {'source_records'}, dict(server.__dict__))
    class Client:
        model = 'unchanged-fixture-model'
        effort = 'high'
    async def validate():
        if variant == 'before':
            legacy_server['source_records']([ident], project)
        else:
            await server.source_records_async([ident], project, metadata_only=True)
        return True
    async def digest():
        api = legacy_ai['source_digest'] if variant == 'before' else ai.source_digest
        return await api(Client(), sources, include_source_ids=True)
    results = {}
    for label, operation in [('validation', validate), ('digest', digest)]:
        measurements = []
        signature = None
        for _ in range(3):
            gc.collect()
            value, measurement = await sample(operation)
            measurements.append(measurement)
            if label == 'digest':
                actual = digest_signature(value)
                assert signature is None or signature == actual
                signature = actual
            del value
        gc.collect()
        tracemalloc.start()
        value = await operation()
        live, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        if label == 'digest': assert signature == digest_signature(value)
        del value
        results[label] = dict(measurements=measurements, median_elapsed_ms=statistics.median(x['elapsed_ms'] for x in measurements),
                              max_heartbeat_gap_ms=max(x['heartbeat_max_gap_ms'] for x in measurements),
                              python_live_bytes=live, python_peak_bytes=peak, output=signature)
    result = dict(variant=variant, layout=mode, original_characters=sum(len(part['text']) for part in sources[0]['segments']),
                  source_segments=len(sources[0]['segments']), model_requests=0, results=results,
                  scope='Isolated SQLite validation and full source preparation; no model inference, OCR or end-to-end generation')
    (FOLDER / f'{mode}-{variant}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)


def compare():
    output = {}
    for mode in ('block', 'pages'):
        before = json.loads((FOLDER / f'{mode}-before.json').read_text(encoding='utf-8'))
        current = json.loads((FOLDER / f'{mode}-current.json').read_text(encoding='utf-8'))
        assert before['results']['digest']['output'] == current['results']['digest']['output']
        output[mode] = dict(original_characters=current['original_characters'], source_segments=current['source_segments'],
                            unchanged_full_digest_and_chunks=True, before=before['results'], current=current['results'])
    (FOLDER / 'comparison.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({mode: {label: {'before_ms': data['before'][label]['median_elapsed_ms'],
                                   'current_ms': data['current'][label]['median_elapsed_ms'],
                                   'before_heartbeat_gap_ms': data['before'][label]['max_heartbeat_gap_ms'],
                                   'current_heartbeat_gap_ms': data['current'][label]['max_heartbeat_gap_ms']}
                           for label in ('validation', 'digest')} for mode, data in output.items()}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('variant', choices=['before', 'current', 'compare'])
    parser.add_argument('mode', nargs='?', choices=['block', 'pages'], default='block')
    args = parser.parse_args()
    if args.variant == 'compare': compare()
    else:
        folder = FOLDER / f'data-{args.mode}-{args.variant}'
        os.environ['STUDYFORGE_DATA_DIR'] = str(folder)
        os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(folder / 'isolated-model')
        asyncio.run(run(args.variant, args.mode))
