"""Real StudyForge video A/B runs. No mocked downloader, OCR or model responses.

Run prepare once, then A and B in separate processes to keep RAM/caches isolated.
Common download and full transcript timings are reported separately and reused.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

workspace = Path(__file__).resolve().parents[1]
source_root = Path(os.environ.get('STUDYFORGE_BENCH_SOURCE_ROOT', workspace)).resolve()
if source_root != workspace and not source_root.is_relative_to(workspace/'build'):
    raise ValueError('试验源码快照只能位于当前工作区 build 目录')
sys.path.insert(0, str(source_root))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def peak_ram_mb():
    if os.name != 'nt':
        return None
    class Counters(ctypes.Structure):
        _fields_ = [('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong)] + [
            (k,ctypes.c_size_t) for k in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage',
            'QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    value = Counters(); value.cb = ctypes.sizeof(value)
    handle = ctypes.windll.kernel32.GetCurrentProcess
    handle.restype = ctypes.c_void_p
    if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(handle()), ctypes.byref(value), value.cb):
        return round(value.PeakWorkingSetSize / 1024**2, 2)


def initialize(work, name, source_settings):
    data = work / name / 'data'
    data.mkdir(parents=True, exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(data)
    saved = json.loads(source_settings.read_text(encoding='utf-8')) if source_settings.is_file() else {}
    config = {key:saved[key] for key in ('whisper_model','voice_language') if key in saved}
    config.update(chat_provider='deepseek', deepseek_model='deepseek-flash',
                  deepseek_generation_model='deepseek-flash', deepseek_vision_model='deepseek-flash',
                  model_concurrency=2, review_mode='express', generation_parallel=False,
                  agent_tools_enabled=False, background_learning_enabled=False, video_import_mode='full')
    write_json(data / 'settings.json', config)
    return data


def prepare(args):
    from studyforge.media import download_public_video, video_metadata_path
    from studyforge.parsers import parse_audio, segment
    result = {'url':args.url, 'status':'preparing', 'full_video':True}
    state = args.work / 'prepared.json'
    started = time.perf_counter()
    write_json(state, result)
    try:
        if args.input:
            original = args.input.resolve()
            if not original.is_file(): raise ValueError('本地视频文件不存在')
            video = args.work / 'common' / original.name
            shutil.copyfile(original, video)
            metadata = args.metadata or video_metadata_path(original)
            if metadata.is_file():
                info = json.loads(metadata.read_text(encoding='utf-8'))
                from studyforge.video_links import canonical_video_url
                if (info.get('media_bytes') == video.stat().st_size and
                        canonical_video_url(info.get('url','')) == canonical_video_url(args.url)):
                    write_json(video_metadata_path(video), info)
            result['download_seconds'] = 0
            result['local_input'] = True
        else:
            video = download_public_video(args.url, on_progress=lambda name,p:print(f'{name} {p}%',flush=True))
            result['download_seconds'] = round(time.perf_counter()-started,3)
        import av
        with av.open(str(video)) as container:
            result['duration_seconds'] = container.duration / av.time_base if container.duration else None
            if not container.streams.video or not container.streams.audio:
                raise ValueError('用于完整对照的视频必须同时包含音轨和画面')
            result['video_width'] = container.streams.video[0].codec_context.width
            result['video_height'] = container.streams.video[0].codec_context.height
        result['video_path'] = str(video)
        result['video_bytes'] = video.stat().st_size
        with video.open('rb') as stream:
            result['video_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        metadata = video_metadata_path(video)
        info = json.loads(metadata.read_text(encoding='utf-8')) if metadata.exists() else {}
        result['title'] = info.get('title') or video.stem
        if info.get('duration') and abs(info['duration']-result['duration_seconds']) > 5:
            raise ValueError('本地音画时长与所选分集的元数据不符')
        result['status'] = 'transcribing'; write_json(state,result)
        transcription_started = time.perf_counter()
        captions = info.get('subtitles') or []
        if args.transcript_record:
            from studyforge.video_links import canonical_video_url
            capsule=json.loads(args.transcript_record.read_text(encoding='utf-8'))
            if (capsule.get('schema') != 'studyforge.video/1' or
                    capsule.get('metadata',{}).get('mode') != 'full' or
                    capsule.get('metadata',{}).get('original_media_sha256') != result['video_sha256'] or
                    canonical_video_url(capsule.get('source_url','')) != canonical_video_url(args.url)):
                raise ValueError('缓存逐字稿没有与本次原视频的全文、分集网址和 SHA256 匹配')
            transcript=[part for part in capsule['segments'] if part.get('kind')=='transcript']
            if not transcript:raise ValueError('视频记录不含逐字稿')
            for part in transcript:
                start_time,end_time=part['meta']['start'],part['meta']['end']
                if not (0<=start_time<end_time<=result['duration_seconds']+1):
                    raise ValueError('缓存逐字稿的时间范围与原视频不符')
            result.update(title=capsule.get('title') or result['title'],
                          transcript_method='verified_original_capsule',
                          transcript_original_record=str(args.transcript_record.resolve()),
                          first_transcription_seconds=None,
                          transcription_note='复用与原文件 SHA256 和分集网址匹配的完整逐字稿；首次转录耗时未知，不冒充冷启动耗时')
        elif captions:
            transcript = [segment(f"{p['start']:.1f}-{p['end']:.1f} 秒",p['text'],'transcript',
                                  start=p['start'],end=p['end'],method='video_subtitle') for p in captions]
            result['transcript_method'] = 'site_subtitles'
        else:
            print('完整音轨转录中；保留当前 Whisper 模型与 beam_size=5',flush=True)
            from studyforge import local_compute
            stop = threading.Event()
            def progress():
                while not stop.wait(30):
                    print(f"完整音轨转录 {time.perf_counter()-transcription_started:.0f}s · 峰值内存 {peak_ram_mb()} MB",flush=True)
            monitor=threading.Thread(target=progress,daemon=True); monitor.start()
            try: transcript = parse_audio(video)
            finally: stop.set();monitor.join()
            result['transcript_method'] = 'whisper'
            with local_compute._lock:
                result['whisper_model_used'] = local_compute._models.get('asr',(None,))[0]
        write_json(args.work / 'transcript.json', transcript)
        result['transcription_seconds'] = round(time.perf_counter()-transcription_started,3)
        result['transcript_segments'] = len(transcript)
        result['transcript_characters'] = sum(len(p['text']) for p in transcript)
        result['status'] = 'ready'
    except Exception as error:
        result.update(status='failed',error=f'{type(error).__name__}: {error}')
    result['elapsed_seconds'] = round(time.perf_counter()-started,3)
    result['peak_ram_mb'] = peak_ram_mb()
    write_json(state,result)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if result['status']=='ready' else 2


async def run_variant(args):
    from studyforge import parsers, server
    from studyforge.config import files_dir
    from studyforge.conversations import create as conversation_create
    from studyforge.db import create_project, create_job, execute, j, now, one, uid, unj
    from studyforge.job_control import active_jobs, start_job
    from studyforge.scheduling import execution_scope
    prepared = json.loads((args.work/'prepared.json').read_text(encoding='utf-8'))
    if prepared['status'] != 'ready': raise ValueError('原视频未取得，不能生成或比较讲解')
    original = Path(prepared['video_path'])
    transcript = json.loads((args.work/'transcript.json').read_text(encoding='utf-8'))
    actual_parser = parsers.parse_video
    parsers.PARSERS[original.suffix.lower()] = lambda path: actual_parser(
        path, frame_strategy='smart' if args.phase=='A' else 'dense', prepared_transcript=transcript)
    project = create_project(f"视频对照 {args.phase} {prepared['title'][:80]}")
    source = uid(); copied = files_dir() / (source+original.suffix.lower())
    try: os.link(original,copied)
    except OSError: shutil.copyfile(original,copied)
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at,origin_url) VALUES (?,?,?,?,?,?,?,?)',
            (source,project['id'],prepared['title'],copied.suffix,str(copied),'pending',now(),args.url))
    result={'variant':args.phase, 'status':'running', 'project_id':project['id'], 'source_id':source,
            'model':'deepseek-flash','review_mode':'express','format':'docx','exercises':False,
            'source_sha256':prepared['video_sha256'],'common_preparation':prepared}
    report = args.work / args.phase / 'report.json'
    start = time.perf_counter()
    try:
        job = create_job(project['id'],'import',{'source_id':source})
        async with execution_scope(job_id=job,project_id=project['id'],label='A/B 实际资料解析'):
            await server._import_job(job,source,copied,remote_url=args.url)
        imported = one('SELECT * FROM jobs WHERE id=?',(job,))
        if imported['status']!='completed': raise RuntimeError(imported['error'])
        result['parsing_seconds'] = round(time.perf_counter()-start,3)
        row = one('SELECT segments_json FROM sources WHERE id=?',(source,))
        parts = unj(row['segments_json'],[])
        result['sampling'] = next((p['meta']['video_sampling'] for p in parts if p.get('meta',{}).get('video_sampling')), {})
        result['frame_times'] = [p['meta'].get('time') for p in parts if p['kind']=='video_frame']
        if args.wait_for_variant:
            result.update(status='waiting',current_stage='本地解析完成，等待另一方案结束模型请求')
            write_json(report,result);wait_started=time.perf_counter()
            previous=args.work/args.wait_for_variant/'report.json'
            while True:
                if previous.exists() and json.loads(previous.read_text(encoding='utf-8')).get('status') in ('completed','failed'):
                    break
                await asyncio.sleep(5)
            result['comparison_wait_seconds']=round(time.perf_counter()-wait_started,3)
            start+=time.perf_counter()-wait_started
            result['status']='running'
        chat = conversation_create(project['id'],'deepseek','deepseek-flash',None)
        request = server.GenerateIn(project_id=project['id'],source_ids=[source],conversation_id=chat['id'],
            provider='deepseek',model='deepseek-flash',review_mode='express',format='docx',summary_level=3,
            explanation_style='clear',learning_mode='deep',parallel=False,exercises=False,
            instructions='完整讲解本集课程，保留重要定义、公式、适用条件、推导、方法动机和具体例子；以视频时间戳定位来源。画面无法确认处明确标注，不从上下文猜测。')
        generation_started = time.perf_counter()
        launched = await server.generate(request); job = launched['job_id']; result['generation_job_id']=job
        while one('SELECT status FROM jobs WHERE id=?',(job,))['status'] in ('queued','running','pausing'):
            current=one('SELECT * FROM jobs WHERE id=?',(job,))
            result['current_stage']=unj(current['result_json'],{}).get('stage')
            result['elapsed_seconds']=round(time.perf_counter()-start,3)
            result['peak_ram_mb']=peak_ram_mb(); write_json(report,result)
            print(args.phase,result['current_stage'],f"{result['elapsed_seconds']:.0f}s",flush=True)
            await asyncio.sleep(15)
        if job in active_jobs: await active_jobs[job]
        current=one('SELECT * FROM jobs WHERE id=?',(job,))
        if current['status']!='completed': raise RuntimeError(current['error'] or current['status'])
        result['generation_seconds']=round(time.perf_counter()-generation_started,3)
        result['artifacts']=[]
        for item in unj(current['result_json'],{}).get('artifacts',[]):
            artifact=one('SELECT * FROM artifacts WHERE id=?',(item['id'],))
            destination=args.work/'outputs'/f"{args.phase}方案 {server.artifact_download_name(artifact)}"
            destination.parent.mkdir(exist_ok=True); shutil.copyfile(artifact['path'],destination)
            result['artifacts'].append(str(destination))
        result['status']='completed'
    except Exception as error:
        result.update(status='failed',error=f'{type(error).__name__}: {error}')
    result['elapsed_seconds']=round(time.perf_counter()-start,3);result['peak_ram_mb']=peak_ram_mb()
    write_json(report,result);print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if result['status']=='completed' else 2


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--phase',choices=['prepare','A','B'],required=True)
    parser.add_argument('--url',required=True)
    parser.add_argument('--work-dir',type=Path,required=True)
    parser.add_argument('--input',type=Path)
    parser.add_argument('--metadata',type=Path)
    parser.add_argument('--transcript-record',type=Path)
    parser.add_argument('--wait-for-variant',choices=['A','B'])
    parser.add_argument('--settings',type=Path,default=Path(r'C:\Users\Lenovo\AppData\Local\StudyForge\settings.json'))
    args=parser.parse_args();args.work=args.work_dir.resolve()
    if args.wait_for_variant==args.phase:raise ValueError('不能等待自身方案')
    if not args.work.is_relative_to(Path(__file__).resolve().parents[1]/'build'):
        raise ValueError('对照目录须位于当前工作区 build 目录内')
    initialize(args.work,'common' if args.phase=='prepare' else args.phase,args.settings)
    return prepare(args) if args.phase=='prepare' else asyncio.run(run_variant(args))


if __name__=='__main__':raise SystemExit(main())
