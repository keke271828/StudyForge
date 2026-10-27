"""Isolated local bottlenecks; does not call cloud models or alter user data."""
import argparse
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'build/generation-local-performance-20261011'


def measured(operation):
    operation();gc.collect()
    start = time.perf_counter()
    for _ in range(3):value = operation()
    elapsed = (time.perf_counter() - start) / 3
    gc.collect();tracemalloc.start()
    try:
        value = operation();peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    return dict(mean_ms=elapsed*1000, repeats=3, python_peak_bytes=peak, result=value)


def run(variant):
    from studyforge import generation_control, json_digest
    from studyforge.db import create_job, create_project, j, one
    spec = importlib.util.spec_from_file_location('studyforge._control_before', FOLDER / 'generation_control.before.py')
    old = importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    parts = [{'locator': f'第 {i} 页', 'text': f'完整原文{i:04d}，推导和条件。\n' * 5000, 'meta': {}} for i in range(60)]
    signature = ['writer', ['selected-model', 'high', parts]]
    original = [parts, []]
    def baseline_content():return hashlib.sha256(json.dumps(original, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    def current_content():return json_digest.sha256(original, sort_keys=True, default=str)
    def baseline_signature():return hashlib.sha256(j(signature).encode()).hexdigest()
    def current_signature():return json_digest.sha256(signature)
    project = create_project('local benchmark')
    ident = create_job(project['id'], 'generate', {'dialogue_snapshot': {'messages': ['长对话原文🙂\n' * 350000]}})
    control = (old if variant == 'before' else generation_control).GenerationControl(ident)
    def progress():
        for index in range(30):control.stage('读取完整资料', index, {'done': index})
        row = one('SELECT progress,result_json FROM jobs WHERE id=?', (ident,))
        return row
    report = dict(variant=variant, external_model_requests=0, scope='local hashes and 30 progress updates; not full application RAM or generation latency')
    report['original_content_hash'] = measured(baseline_content if variant == 'before' else current_content)
    report['saved_step_key'] = measured(baseline_signature if variant == 'before' else current_signature)
    report['progress_30_updates'] = measured(progress)
    (FOLDER / f'local-{variant}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('variant', choices=['before', 'current', 'compare']);args = parser.parse_args()
    os.environ['STUDYFORGE_DATA_DIR'] = str(FOLDER / ('bench-data-' + args.variant))
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(FOLDER / 'unused-model')
    if args.variant == 'compare':
        before = json.loads((FOLDER / 'local-before.json').read_text(encoding='utf-8'))
        current = json.loads((FOLDER / 'local-current.json').read_text(encoding='utf-8'))
        for name in ('original_content_hash', 'saved_step_key', 'progress_30_updates'):
            assert before[name]['result'] == current[name]['result'], name
        report = dict(passed=True, old_keys_and_results_identical=True, before=before, current=current)
        (FOLDER / 'local-comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Exact original content keys, legacy step keys and progress results match')
    else:
        run(args.variant)
