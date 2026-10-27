"""Before/after warm image preparation, with exact output and cache IO counts.

Synthetic PNGs and deterministic model observations isolate the cache cost.
No external model is called, and this is not full video generation latency.
"""
import argparse
import asyncio
from contextlib import contextmanager
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import tracemalloc

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'build/vision-reuse-20261011'


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


class Vision:
    model='fixed-writer';vision_model='fixed-image-model';effort='high'
    def __init__(self):self.calls=0
    async def analyze_images(self,frames):
        self.calls+=1
        return {item['id']:('本图独立核对记录：'+item['ocr']+'；关键条件和符号保留。')*50 for item in frames}
    async def analyze_image(self,path,locator,text):
        self.calls+=1
        return ('本图独立核对记录：'+text+'；关键条件和符号保留。')*50


def source(folder,count):
    from PIL import Image,ImageDraw
    parts=[];folder.mkdir(parents=True,exist_ok=True)
    for index in range(count):
        path=folder/f'{index:05}.png'
        picture=Image.new('RGB',(1280,720),(index%255,40,60))
        ImageDraw.Draw(picture).text((60,60),f'Source board frame {index}: x = y + 1',fill='white');picture.save(path)
        parts.append(dict(kind='video_frame',locator=f'{index*10} 秒画面',text=f'原始完整OCR，画面{index:04d}',meta={'image_path':str(path)}))
    return dict(id='fixture-source',name='可复用课程画面',original_path='fixture-original-video.mp4',segments=parts)


async def measure(api,cache,value,mode):
    client=Vision();original=await api.source_digest(client,[value]);before_calls=client.calls
    counts={'read':0,'update':0,'insert':0,'delete':0,'connections':0}
    original_connect=cache.connect
    @contextmanager
    def traced():
        counts['connections']+=1
        with original_connect() as database:
            def record(sql):
                if 'source_vision_cache' not in sql:return
                word=sql.split(' ',1)[0]
                kind={'SELECT':'read','UPDATE':'update','INSERT':'insert','DELETE':'delete'}.get(word)
                if kind:counts[kind]+=1
            database.set_trace_callback(record);yield database
    def reset_memory():
        if mode=='disk':api._VISION_CACHE.clear()
    reset_memory();assert await api.source_digest(client,[value])==original
    cache.connect=traced
    samples=[]
    try:
        for _ in range(3):
            reset_memory();gc.collect();start=time.perf_counter()
            result=await api.source_digest(client,[value]);samples.append((time.perf_counter()-start)*1000)
            assert result==original
    finally:cache.connect=original_connect
    io=dict(counts)
    reset_memory();gc.collect();tracemalloc.start()
    try:
        result=await api.source_digest(client,[value]);peak=tracemalloc.get_traced_memory()[1]
    finally:tracemalloc.stop()
    assert result==original and client.calls==before_calls
    return dict(mean_ms=sum(samples)/len(samples),samples_ms=samples,python_peak_bytes=peak,
        io_totals_for_three_runs=io,output_sha256=hashlib.sha256(json.dumps(result,ensure_ascii=False).encode()).hexdigest(),
        characters=len(result[0]),new_model_requests=client.calls-before_calls,cold_fixture_model_requests=before_calls)


async def run(variant):
    from studyforge import ai,vision_cache
    from studyforge import materials
    # Load both APIs in each independent process for comparable import costs.
    old_ai=module('studyforge._vision_api_before',FOLDER/'ai.before.py')
    old_cache=module('studyforge._vision_disk_before',FOLDER/'vision_cache.before.py')
    old_materials=module('studyforge._vision_hash_before',FOLDER/'materials.before.py')
    if variant=='before':materials.file_sha256=old_materials.file_sha256
    api,cache=(old_ai,old_cache) if variant=='before' else (ai,vision_cache)
    sys.modules['studyforge.vision_cache']=cache
    report=dict(variant=variant,external_model_requests=0,
        scope='warm synthetic image cache preparation only; original OCR and observations retained')
    for name,count,mode in [('memory_32',32,'memory'),('disk_117',117,'disk')]:
        api.clear_source_digest_cache();value=source(FOLDER/(variant+'-'+name),count)
        report[name]=await measure(api,cache,value,mode)
    (FOLDER/f'reuse-{variant}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('variant',choices=['before','current','compare']);args=parser.parse_args()
    os.environ['STUDYFORGE_DATA_DIR']=str(FOLDER/('bench-data-'+args.variant))
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(FOLDER/'unused-model')
    if args.variant=='compare':
        before=json.loads((FOLDER/'reuse-before.json').read_text(encoding='utf-8'))
        current=json.loads((FOLDER/'reuse-current.json').read_text(encoding='utf-8'))
        for name in ('memory_32','disk_117'):
            assert before[name]['output_sha256']==current[name]['output_sha256'],name
        result=dict(passed=True,complete_original_and_observations_identical=True,before=before,current=current)
        (FOLDER/'reuse-comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('All original OCR, observations and source locations match exactly')
    else:asyncio.run(run(args.variant))
