"""Cold concurrent native-image requests; simulated cloud latency, exact texts.

Run before/current in separate processes. This does not measure real DeepSeek
latency or whole application RAM. Original PNG/OCR/locators remain identical.
"""
import argparse
import asyncio
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import time
import tracemalloc

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'build/vision-concurrent-20261012'


async def run(variant):
    from PIL import Image,ImageDraw
    from studyforge import ai
    from studyforge.scheduling import model_slot
    spec=importlib.util.spec_from_file_location('studyforge._native_before',FOLDER/'ai.before.py')
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    api=old if variant=='before' else ai
    ai.get_secret=old.get_secret=lambda _: 'isolated-fixture-account'
    ai.save_settings({'model_concurrency':2,'task_parallel_enabled':True})
    folder=FOLDER/'cold-original-images';folder.mkdir(exist_ok=True)
    parts=[]
    for i in range(12):
        path=folder/f'{i:05}.png'
        image=Image.new('RGB',(1280,720),(40,80,i*10));ImageDraw.Draw(image).text((50,50),f'Board {i}: x = y + 1',fill='white');image.save(path)
        parts.append(dict(kind='video_frame',locator=f'{i*10} 秒',text=f'完整原始 OCR {i}',meta={'image_path':str(path)}))
    value=dict(id='cold-source',name='相同课程原图',original_path='fixture-course.mp4',segments=parts)
    async def measure(trace=False):
        api.clear_source_digest_cache();requests=[];encoded_images=0;stats=[[],[]]
        async def request(body,**kwargs):
            nonlocal encoded_images
            from studyforge.vision_batches import admitted_request_body
            async with admitted_request_body(body, 'fixture-native') as body:
                texts=[item['text'] for item in body['messages'][1]['content'] if item['type']=='text']
                encoded_images+=len(texts)
                requests.append(texts);await asyncio.sleep(.12)
            observations=[dict(id=re.search('图片ID：([^；]+)',text)[1],observation='本图独立观察 '+text.split('\n')[-1]) for text in texts]
            return json.dumps({'frames':observations},ensure_ascii=False) if 'frames' in body['messages'][0]['content'] else observations[0]['observation']
        clients=[api.DeepSeekClient('same-writer',vision_model='same-image-model',effort='high') for _ in range(2)]
        for client in clients:client._request_content=request
        gc.collect()
        if trace:tracemalloc.start()
        start=time.perf_counter()
        outputs=await asyncio.gather(*(api.source_digest(client,[value],on_cache=stats[i].append) for i,client in enumerate(clients)))
        elapsed=(time.perf_counter()-start)*1000
        peak=tracemalloc.get_traced_memory()[1] if trace else None
        if trace:tracemalloc.stop()
        assert outputs[0]==outputs[1]
        return dict(elapsed_ms=elapsed,python_peak_bytes=peak,requests=len(requests),encoded_images=encoded_images,
                    output_sha256=hashlib.sha256(json.dumps(outputs[0],ensure_ascii=False).encode()).hexdigest(),stats=stats)
    samples=[await measure() for _ in range(3)];allocation=await measure(True)
    assert len({row['output_sha256'] for row in [*samples,allocation]})==1
    result=dict(variant=variant,external_model_requests=0,simulated_model_latency_ms=120,model_concurrency=2,
                mean_ms=sum(row['elapsed_ms'] for row in samples)/3,samples=samples,allocation=allocation,
                scope='two cold concurrent 12-image native source reads; not real cloud latency or whole-app RAM')
    (FOLDER/f'cold-{variant}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:result[key] for key in ('variant','mean_ms','allocation')},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('variant',choices=['before','current','compare']);args=parser.parse_args()
    os.environ['STUDYFORGE_DATA_DIR']=str(FOLDER/('cold-data-'+args.variant))
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(FOLDER/'unused-model')
    if args.variant=='compare':
        before=json.loads((FOLDER/'cold-before.json').read_text(encoding='utf-8'))
        current=json.loads((FOLDER/'cold-current.json').read_text(encoding='utf-8'))
        assert before['allocation']['output_sha256']==current['allocation']['output_sha256']
        result=dict(passed=True,complete_texts_and_locations_identical=True,before=before,current=current)
        (FOLDER/'cold-comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Cold native request outputs match exactly')
    else:asyncio.run(run(args.variant))
