"""Checked CUDA speech backend with same-model CPU recovery.

Native GPU capability is checked in a short-lived process before use. A bad
DLL/driver must not terminate the desktop backend. No driver installation or
global PATH change is performed; optional runtime paths belong to this app.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

DEFAULTS = {'whisper_device': 'auto'}
_handles = []
_dll_lock = threading.RLock()
_probe_lock = threading.RLock()
_probes = {}
_failures = {}
PROBE_SECONDS = 90
RECHECK_SECONDS = 300


def validate_settings(values):
    if 'whisper_device' in values and values['whisper_device'] not in ('auto','cpu','cuda'):
        raise ValueError('语音识别设备须为 auto、cpu 或 cuda')


def runtime_directories():
    from .config import data_dir
    custom = os.environ.get('STUDYFORGE_ASR_CUDA_DIR')
    roots = ([Path(custom)] if custom else []) + [data_dir()/'runtimes/asr-cuda',
             Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'resources/asr-cuda']
    paths = []
    for root in roots:
        for suffix in ('','bin','nvidia/cublas/bin','nvidia/cudnn/bin','nvidia/cuda_runtime/bin'):
            value=(root/suffix).resolve()
            if value.is_dir() and value not in paths: paths.append(value)
    return paths


def prepare_cuda():
    if sys.platform != 'win32': return False,'本机尚未配置 Windows CUDA 语音运行库'
    with _dll_lock:
        directories=runtime_directories()
        # Some cuDNN components use native LoadLibrary rather than Python's
        # DLL search flags. This affects this process only, never system/user
        # registry PATH; a probe child inherits the same known directories.
        existing=os.environ.get('PATH','').split(os.pathsep)
        added=[str(path) for path in directories if str(path) not in existing]
        if added:os.environ['PATH']=os.pathsep.join([*added,*existing])
        for directory in directories:
            if any(item[0] == directory for item in _handles): continue
            _handles.append((directory,os.add_dll_directory(str(directory))))
        try:
            for name in ('cublas64_12.dll','cublasLt64_12.dll','cudnn64_9.dll','cudnn_ops64_9.dll'):
                ctypes.WinDLL(name)
        except OSError:
            return False,'缺少可加载的 CUDA 12／cuDNN 9 运行库，使用同一模型的 CPU 识别'
    return True,''


def fingerprint(name):
    import ctranslate2
    stamps=[]
    for directory in runtime_directories():
        for path in directory.glob('*.dll'):
            stat=path.stat();stamps.append((str(path),stat.st_size,stat.st_mtime_ns))
    return (name,ctranslate2.__version__,tuple(sorted(stamps)))


def gpu_count():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count()
    except Exception: return 0


def probe(name):
    from .runtime import background_process_options
    command = ([sys.executable,'--asr-probe',name] if getattr(sys,'frozen',False)
               else [sys.executable,'-m','studyforge.asr_backend','--asr-probe',name])
    env=dict(os.environ)
    directories=runtime_directories()
    if directories: env['PATH']=os.pathsep.join([*(str(path) for path in directories),env.get('PATH','')])
    env['PYTHONIOENCODING']='utf-8'
    try:
        value=subprocess.run(command,cwd=str(Path(__file__).resolve().parents[1]),env=env,
              capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=PROBE_SECONDS,
              **background_process_options())
        # Silence sample only; neither source audio nor credentials enter child.
        packet=json.loads(value.stdout.strip().splitlines()[-1]) if value.stdout.strip() else {}
        return (True,'') if value.returncode==0 and packet.get('ready') is True else (
            False,'GPU 语音自检未通过，使用同一模型的 CPU 识别')
    except (subprocess.TimeoutExpired,OSError,ValueError):
        return False,'GPU 语音自检未完成，使用同一模型的 CPU 识别'


def choose_device(name, preferred):
    if preferred=='cpu': return 'cpu',''
    if not gpu_count(): return 'cpu','没有可用 NVIDIA CUDA 显卡，使用 CPU 识别'
    ready,reason=prepare_cuda()
    if not ready: return 'cpu',reason
    key=fingerprint(name);stamp=time.monotonic()
    with _probe_lock:
        failure=_failures.get(key)
        if failure and stamp-failure[0]<RECHECK_SECONDS: return 'cpu',failure[1]
        cached=_probes.get(key)
        if cached and (cached[0] or stamp-cached[2]<RECHECK_SECONDS):
            ready,reason=cached[:2]
        else:
            ready,reason=probe(name);_probes[key]=(ready,reason,time.monotonic())
            while len(_probes)>32:_probes.pop(next(iter(_probes)))
    return ('cuda','') if ready else ('cpu',reason)


def mark_failure(name):
    reason='GPU 识别执行失败；已用同一模型完整重试 CPU，未交付部分转录'
    with _probe_lock:
        _failures[fingerprint(name)]=(time.monotonic(),reason)
        while len(_failures)>32:_failures.pop(next(iter(_failures)))
    return reason


def load_model(name, preferred):
    from faster_whisper import WhisperModel
    from .local_compute import cached_model,cpu_threads
    def factory():
        device,reason=choose_device(name,preferred)
        compute='int8_float32' if device=='cuda' else 'int8'
        model=None
        try:
            model=local_first_model(WhisperModel,name,device=device,compute_type=compute,cpu_threads=cpu_threads(),num_workers=1)
        except Exception:
            if device!='cuda':raise
            reason=mark_failure(name);device='cpu'
        if model is None:
            model=local_first_model(WhisperModel,name,device='cpu',compute_type='int8',cpu_threads=cpu_threads(),num_workers=1)
        model._studyforge_asr=dict(selected_model=name,actual_model=name,preferred_device=preferred,
            actual_device=device,compute_type=getattr(getattr(model,'model',None),'compute_type',compute),fallback_reason=reason)
        return model
    # Changing requested device/model releases the previous engine first. A
    # successful CUDA engine remains cached until normal idle eviction.
    return cached_model('asr',(name,preferred),factory)


def local_first_model(factory,name,**kwargs):
    from huggingface_hub.errors import LocalEntryNotFoundError
    try:
        return factory(name,local_files_only=True,**kwargs)
    except (LocalEntryNotFoundError,FileNotFoundError):
        # A complete local snapshot needs no metadata request on every engine
        # reload. Only an actual cache miss may download the selected model.
        return factory(name,local_files_only=False,**kwargs)


def status():
    from .ai import settings
    selected=settings().get('whisper_model','small');preferred=settings().get('whisper_device','auto')
    count=gpu_count()
    return dict(selected_model=selected,preferred_device=preferred,cuda_devices=count,
        note='实际语音任务会核验运行库及 GPU 执行；不可用时保留所选模型，用 CPU 完整识别。')


def child_probe(name):
    try:
        ready,_=prepare_cuda()
        if not ready:raise RuntimeError('runtime unavailable')
        from faster_whisper import WhisperModel
        import numpy as np
        model=WhisperModel(name,device='cuda',compute_type='int8_float32',cpu_threads=1,num_workers=1,local_files_only=True)
        parts,_=model.transcribe(np.zeros(16000,dtype=np.float32),language='zh',vad_filter=False,beam_size=5)
        list(parts)
        print(json.dumps({'ready':True}),flush=True)
    except Exception:
        print(json.dumps({'ready':False}),flush=True)
        raise SystemExit(1)


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--asr-probe':child_probe(sys.argv[2])
    else:raise SystemExit(2)
