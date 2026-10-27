import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from studyforge import local_compute, parsers
from studyforge.ai import source_digest, _VISION_CACHE
from studyforge.db import many
from studyforge.media import run_ffmpeg, video_frames, video_frame_timestamps
from studyforge.scheduling import model_slot
from studyforge.video_sampling import KeyframeSelector


@pytest.fixture(autouse=True)
def empty_models():
    with local_compute._lock:
        if local_compute._timer: local_compute._timer.cancel()
        local_compute._models.clear()
    yield
    with local_compute._lock:
        if local_compute._timer: local_compute._timer.cancel()
        local_compute._models.clear()


def test_ocr_is_shared_across_threads_and_inference_does_not_overlap(monkeypatch):
    import rapidocr
    state={'created':0,'active':0,'peak':0}
    class Engine:
        def __init__(self,params):
            state['created']+=1
            assert 1 <= params['EngineConfig.onnxruntime.intra_op_num_threads'] <= 4
        def __call__(self,path):
            state['active']+=1;state['peak']=max(state['peak'],state['active'])
            time.sleep(.015);state['active']-=1
            return SimpleNamespace(txts=[path])
    monkeypatch.setattr(rapidocr,'RapidOCR',Engine)
    with ThreadPoolExecutor(max_workers=5) as pool:
        values=list(pool.map(parsers._ocr,[f'page-{i}' for i in range(9)]))
    assert state=={'created':1,'active':0,'peak':1}
    assert values==[f'page-{i}' for i in range(9)]


def test_switching_asr_does_not_retain_old_models_and_idle_cache_releases(monkeypatch):
    created=[]
    with local_compute.inference_slot():
        first=local_compute.cached_model('asr','small',lambda:created.append('small') or object())
        assert local_compute.cached_model('asr','small',lambda:pytest.fail('Reload')) is first
        second=local_compute.cached_model('asr','medium',lambda:created.append('medium') or object())
        assert second is not first
    assert list(local_compute._models)==['asr'] and created==['small','medium']
    monkeypatch.setattr(local_compute,'_last_used',time.monotonic()-local_compute.IDLE_SECONDS-1)
    local_compute.clear_idle_models()
    assert not local_compute._models


def test_family_switch_releases_idle_engine_before_loading_next():
    import weakref
    class Engine: pass
    with local_compute.inference_slot():
        previous=weakref.ref(local_compute.cached_model('asr','small',Engine))
        def load_ocr():
            assert previous() is None, 'Idle ASR weights must be released before loading OCR'
            return Engine()
        local_compute.cached_model('ocr','rapidocr',load_ocr)
        assert list(local_compute._models)==['ocr']


def test_local_queue_does_not_serialize_cloud_requests():
    async def run():
        entered=threading.Event();release=threading.Event();order=[]
        def heavy(name):
            order.append(name)
            if name=='first':entered.set();release.wait(2)
            return name
        first=asyncio.create_task(local_compute.run_source_io(heavy,'first',paths=['book.pdf']))
        while not entered.is_set():await asyncio.sleep(.005)
        second=asyncio.create_task(local_compute.run_source_io(heavy,'second',paths=['image.png']))
        await asyncio.sleep(.01)
        assert order==['first']
        async with model_slot('test'):order.append('cloud')
        plain=await local_compute.run_source_io(lambda:'text',paths=['notes.md'])
        assert plain=='text' and order==['first','cloud']
        release.set();assert await first=='first' and await second=='second'
        assert order==['first','cloud','second']
    asyncio.run(run())
    spans=many('SELECT resource,status FROM execution_spans')
    assert [p['resource'] for p in spans].count('model')==1
    assert all(p['status']=='completed' for p in spans)


def test_archived_video_and_cached_pdf_are_readable_while_heavy_task_runs(tmp_path):
    import fitz
    from studyforge.materials import remember_parsed_original, read_original_sources_async, file_sha256
    from studyforge.scheduling import resource_slot
    path=tmp_path/'book.pdf'
    with fitz.open() as document:
        document.new_page().insert_text((40,50),'Original evidence')
        document.save(path)
    parts=[{'locator':'第 1 页','text':'Original evidence','kind':'text','meta':{}}]
    remember_parsed_original(path,file_sha256(path),parts)
    async def run():
        async with resource_slot('media'):
            result=await asyncio.wait_for(read_original_sources_async([
                {'id':'book','name':'book','original_path':str(path),'segments':parts,'status':'ready'}]),1)
            assert result[0]['segments'][0]['text']=='Original evidence'
    asyncio.run(run())
    assert not local_compute.requires_local_compute('archive.sfvideo')


def test_import_seeds_verified_original_without_reusing_preview(tmp_path):
    from studyforge import server, materials
    from studyforge.db import create_project, create_job, execute, j, now, uid
    path=tmp_path/'book.txt';path.write_text('完整的原文',encoding='utf-8')
    project=create_project('cached originals');source=uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (source,project['id'],'book.txt','.txt',str(path),'pending',now()))
    job=create_job(project['id'],'import',{'source_id':source})
    asyncio.run(server._import_job(job,source,path))
    execute('UPDATE sources SET segments_json=? WHERE id=?',(j([{'locator':'摘要','text':'不完整的预览'}]),source))
    records=asyncio.run(materials.read_original_sources_async(server.source_records([source],project['id'])))
    assert records[0]['read_manifest']['parse_cache_hit'] and records[0]['segments'][0]['text']=='完整的原文'


def test_smart_merge_preserves_small_board_changes_final_frame_and_time_revisit(tmp_path):
    paths=[]
    for i in range(4):
        image=Image.new('RGB',(1280,720),'white')
        if i>=2:ImageDraw.Draw(image).text((600,320),'x = 2 + 3',fill='black')
        path=tmp_path/f'{i}.png';image.save(path);paths.append(path)
    selector=KeyframeSelector()
    assert selector.retain(paths[0],0)
    assert not selector.retain(paths[1],10)
    assert selector.retain(paths[2],20)
    assert not selector.retain(paths[3],30)
    assert selector.retain(paths[3],80)
    assert selector.retain(paths[3],90,final=True)


def test_unknown_timestamps_remain_visible(tmp_path):
    path=tmp_path/'frame.png';Image.new('RGB',(50,50)).save(path)
    selector=KeyframeSelector()
    assert selector.retain(path,None) and selector.retain(path,10)


def test_scene_sampler_finds_short_slide_between_dense_frames(tmp_path):
    video=tmp_path/'slides.mp4'
    run_ffmpeg('-f','lavfi','-i','color=white:s=320x180:r=2:d=4',
               '-vf',"drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,1,2)'",
               '-c:v','libx264','-pix_fmt','yuv420p',str(video))
    dense=video_frames(video);assert len(dense)==1
    smart=video_frames(video,scene_threshold=.08)
    times=video_frame_timestamps(smart)
    assert len(smart)>=3 and any(1<=stamp<=2 for stamp in times.values())


def test_over_64_image_readings_survive_ram_eviction_without_repeated_model_calls(tmp_path):
    calls=[]
    class Client:
        model='fixture-model'
        async def analyze_image(self,path,locator,text):
            calls.append(locator);return 'Visible content '+path.name
    parts=[]
    for i in range(70):
        path=tmp_path/f'{i}.png';Image.new('RGB',(5,5),(i,0,0)).save(path)
        parts.append({'locator':f'{i} 秒','text':'OCR','kind':'video_frame','meta':{'image_path':str(path)}})
    source={'id':'source','name':'Course','original_path':'course.sfvideo','segments':parts}
    async def run():
        first,_=await source_digest(Client(),[source])
        assert len(calls)==70
        _VISION_CACHE.clear()
        second,_=await source_digest(Client(),[source])
        assert first==second and len(calls)==70
        changed=tmp_path/'0.png';Image.new('RGB',(5,5),'blue').save(changed)
        await source_digest(Client(),[source]);assert len(calls)==71
        client=Client();client.model='different-model'
        await source_digest(client,[source]);assert len(calls)==141
    asyncio.run(run())
    assert source['segments'][0]['text']=='OCR'
