"""Real PNG/JPEG/base64/HTTP encoding under a controlled native model queue.

Use separate processes for before/current. Responses/latency are explicit
fixtures; neither whole-app RAM nor real model latency/teaching is measured.
"""
import argparse
import asyncio
import ctypes
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'build/vision-admission-20261012'
TASKS, IMAGES_PER_TASK, MODEL_LIMIT = 8, 4, 2


def working_set():
    if os.name != 'nt': return None, None
    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
    value = Counters(); value.cb = ctypes.sizeof(value)
    handle = ctypes.windll.kernel32.GetCurrentProcess; handle.restype = ctypes.c_void_p
    if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(handle()), ctypes.byref(value), value.cb):
        return value.WorkingSetSize, value.PeakWorkingSetSize
    return None, None


def prepare():
    import numpy as np
    from PIL import Image, ImageDraw
    folder = FOLDER / 'originals'; folder.mkdir(parents=True, exist_ok=True)
    for index in range(TASKS * IMAGES_PER_TASK):
        rng = np.random.default_rng(700 + index)
        image = Image.fromarray(rng.integers(0, 256, (1280, 1280, 3), dtype=np.uint8))
        draw = ImageDraw.Draw(image)
        draw.rectangle((80, 80, 1190, 230), fill='white')
        draw.text((100, 100), f'Unique original page {index}: x + y = 3; x > 0', fill='black')
        image.save(folder / f'{index:02}.png')
    print('Prepared 32 deterministic detailed PNG pages', flush=True)


async def run(variant, measure):
    import httpx
    from studyforge import ai, vision_batches
    from studyforge.scheduling import scheduler
    spec = importlib.util.spec_from_file_location('studyforge._admission_before', FOLDER / 'ai.before.py')
    before = importlib.util.module_from_spec(spec); spec.loader.exec_module(before)
    api = before if variant == 'before' else ai
    ai.get_secret = before.get_secret = lambda _: 'isolated-fixture-only'
    ai.save_settings({'task_parallel_enabled': True, 'model_concurrency': MODEL_LIMIT})
    frames = [dict(id=str(index % IMAGES_PER_TASK), path=FOLDER / f'originals/{index:02}.png',
                   locator=f'原文件 第 {index+1} 页', ocr=f'原文字与公式 {index}: x+y=3，x>0')
              for index in range(TASKS * IMAGES_PER_TASK)]
    counts = dict(encodings=0, sent=0, active=0, peak_active=0, payload_chars=0)
    native_encode = vision_batches.image_messages
    def encode(items, **kwargs):
        value = native_encode(items, **kwargs)
        counts['encodings'] += 1
        return value
    vision_batches.image_messages = encode
    release, entered = asyncio.Event(), asyncio.Event()
    inputs = {}
    async def respond(request):
        packet = json.loads(request.content)
        count = counts['sent']; counts['sent'] += 1
        counts['active'] += 1; counts['peak_active'] = max(counts['peak_active'], counts['active'])
        if counts['sent'] >= MODEL_LIMIT: entered.set()
        content = packet['messages'][1]['content']
        texts = [item['text'] for item in content if item['type'] == 'text']
        for part in content:
            if part['type'] == 'image_url': counts['payload_chars'] += len(part['image_url']['url'])
        key = texts[0].split('位置：', 1)[1].split('\n', 1)[0]
        inputs[key] = hashlib.sha256(json.dumps(packet, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        try:
            if measure == 'memory' and count < MODEL_LIMIT: await release.wait()
            await asyncio.sleep(.12)
            value = {'frames': [dict(id=re.search('图片ID：([^；]+)', text)[1],
                                    observation='本图独立观察：' + text.split('\n')[-1]) for text in texts]}
            return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', 'content': json.dumps(value, ensure_ascii=False)}, 'finish_reason': 'stop'}]})
        finally:
            counts['active'] -= 1
    native_http = httpx.AsyncClient
    httpx.AsyncClient = lambda *a, **kw: native_http(*a, **(kw | {'transport': httpx.MockTransport(respond)}))
    clients = [api.DeepSeekClient('same-writer', vision_model='same-vision', effort='high') for _ in range(TASKS)]
    gc.collect()
    initial_ws, _ = working_set()
    if measure == 'memory': tracemalloc.start()
    start = time.perf_counter()
    tasks = [asyncio.create_task(instance.analyze_images(frames[i*IMAGES_PER_TASK:(i+1)*IMAGES_PER_TASK]))
             for i, instance in enumerate(clients)]
    saturation = None
    try:
        if measure == 'memory':
            await asyncio.wait_for(entered.wait(), 20)
            # Same two-second controlled service hold in both variants; let
            # the previous implementation fill its queue with prepared bodies.
            await asyncio.sleep(2)
            current, peak = tracemalloc.get_traced_memory(); ws, peak_ws = working_set()
            saturation = dict(encoded_batches=counts['encodings'], sent_batches=counts['sent'],
                              scheduler=scheduler().snapshot(), python_live_bytes=current,
                              python_peak_bytes=peak, process_working_set_bytes=ws,
                              process_peak_working_set_bytes=peak_ws)
            assert saturation['sent_batches'] == MODEL_LIMIT
            assert saturation['encoded_batches'] == (TASKS if variant == 'before' else MODEL_LIMIT)
            release.set()
        outputs = await asyncio.wait_for(asyncio.gather(*tasks), 30)
        elapsed = (time.perf_counter() - start) * 1000
        allocation = tracemalloc.get_traced_memory() if measure == 'memory' else (None, None)
        ws, peak_ws = working_set()
        result = dict(variant=variant, measure=measure, task_count=TASKS, images_per_task=IMAGES_PER_TASK,
            model_concurrency=MODEL_LIMIT, simulated_response_delay_ms=120,
            initial_service_hold_seconds=2 if measure == 'memory' else 0, external_model_requests=0,
            elapsed_ms=elapsed, initial_working_set_bytes=initial_ws,
            process_working_set_bytes=ws, process_peak_working_set_bytes=peak_ws,
            python_peak_bytes=allocation[1], saturation=saturation, counts=counts,
            input_sha256=inputs, output_sha256=hashlib.sha256(json.dumps(outputs, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            scope='Eight distinct four-image native API tasks; real image/HTTP encoding, fixture responses; not whole-app RAM or cloud latency')
        (FOLDER / f'{variant}-{measure}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({key: result[key] for key in ('variant', 'measure', 'elapsed_ms', 'python_peak_bytes', 'process_peak_working_set_bytes', 'saturation', 'counts', 'output_sha256')}, ensure_ascii=False), flush=True)
    finally:
        release.set()
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(instance.close() for instance in clients))
        if tracemalloc.is_tracing(): tracemalloc.stop()


def compare():
    pairs = {}
    for measure in ('memory', 'time'):
        before = json.loads((FOLDER / f'before-{measure}.json').read_text(encoding='utf-8'))
        current = json.loads((FOLDER / f'current-{measure}.json').read_text(encoding='utf-8'))
        assert before['output_sha256'] == current['output_sha256'] and before['input_sha256'] == current['input_sha256']
        pairs[measure] = dict(before=before, current=current, actual_inputs_identical=True, complete_outputs_identical=True)
    (FOLDER / 'comparison.json').write_text(json.dumps(dict(passed=True, measurements=pairs), ensure_ascii=False, indent=2), encoding='utf-8')
    print('All original encoded request inputs and final observations match exactly', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('variant', choices=['prepare', 'before', 'current', 'compare'])
    parser.add_argument('--measure', choices=['memory', 'time'], default='memory'); args = parser.parse_args()
    FOLDER.mkdir(parents=True, exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(FOLDER / ('data-' + args.variant + '-' + args.measure))
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(FOLDER / 'unused-model')
    if args.variant == 'prepare': prepare()
    elif args.variant == 'compare': compare()
    else: asyncio.run(run(args.variant, args.measure))
