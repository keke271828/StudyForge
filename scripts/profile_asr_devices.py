"""Real offline CPU/GPU comparison on 3 complete local course audio excerpts.

Run one device at a time in separate processes, with identical model and
transcription arguments. This is not a full-video/teaching quality benchmark.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import wave

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'build/asr-quality-performance-20261012'
os.environ['STUDYFORGE_DATA_DIR']=str(FOLDER/'isolated-data')
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(FOLDER/'unused-semantic-model')
sys.stdout.reconfigure(encoding='utf-8')


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def prepare():
    from studyforge.media import run_ffmpeg
    video=Path('C:/Users/Lenovo/AppData/Local/StudyForge/946d97854c1543f8aaced0337295b89e.mp4')
    if not video.is_file():raise RuntimeError('指定的实际课程原视频不存在，不能用合成语音替代对照')
    folder=FOLDER/'audio-samples';folder.mkdir(exist_ok=True)
    for start in (0,300,900):
        target=folder/f'course-{start:04}.wav'
        if not target.exists():run_ffmpeg('-ss',str(start),'-i',str(video),'-t','60','-vn','-ac','1','-ar','16000',str(target))
    return folder


def peak_ram():
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
            ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
             'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage')]
    counters=Counters();counters.cb=ctypes.sizeof(counters)
    kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=wintypes.HANDLE
    psapi=ctypes.WinDLL('psapi');psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb):raise ctypes.WinError()
    return counters.PeakWorkingSetSize


def main(device):
    folder=prepare()
    handles=[]
    if device=='cuda':
        runtime=FOLDER/'cuda-runtime'
        if not runtime.is_dir():runtime=ROOT/'resources/asr-cuda'
        dlls=sorted(runtime.rglob('*.dll'))
        for directory in sorted({str(path.parent) for path in dlls}):
            handles.append(os.add_dll_directory(directory))
        os.environ['PATH']=os.pathsep.join([*sorted({str(path.parent) for path in dlls}),os.environ.get('PATH','')])
    from faster_whisper import WhisperModel
    import ctranslate2
    model_path=Path.home()/'.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120'
    start=time.perf_counter()
    model=WhisperModel(str(model_path),device=device,compute_type='int8_float32' if device=='cuda' else 'int8',
                       cpu_threads=4,num_workers=1,local_files_only=True)
    load_ms=(time.perf_counter()-start)*1000
    options=dict(language=None,vad_filter=True,beam_size=5)
    samples=[]
    for path in sorted(folder.glob('*.wav')):
        with wave.open(str(path)) as audio:duration=audio.getnframes()/audio.getframerate()
        start=time.perf_counter();segments,info=model.transcribe(str(path),**options)
        parts=[dict(start=round(item.start,2),end=round(item.end,2),text=item.text.strip()) for item in segments]
        elapsed_ms=(time.perf_counter()-start)*1000
        samples.append(dict(file=path.name,audio_sha256=digest(path),audio_seconds=duration,elapsed_ms=elapsed_ms,
                            language=info.language,segments=parts))
        print(json.dumps(dict(device=device,file=path.name,elapsed_ms=elapsed_ms,segments=len(parts)),ensure_ascii=False),flush=True)
    result=dict(device=device,model='small',model_sha256=digest(model_path/'model.bin'),model_load_ms=load_ms,
        actual_compute_type=model.model.compute_type,options=options,cpu_threads=4,ctranslate2_version=ctranslate2.__version__,
        peak_process_ram_bytes=peak_ram(),samples=samples,external_model_requests=0)
    (FOLDER/f'asr-{device}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:result[key] for key in result if key!='samples'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('device',choices=['cpu','cuda']);args=parser.parse_args();main(args.device)
