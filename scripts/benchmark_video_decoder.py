"""Compare native decoding of a real 60 s clip, preserving sampled pixels/audio."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'build/generation-local-performance-20261011'


class Memory(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
               ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
               ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
               ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
               ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]


def run(command):
    peak = 0;sample_count = 0;logs = []
    start = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW)
    def consume():logs.extend(line.decode('utf-8', errors='replace') for line in iter(process.stderr.readline, b''))
    reader = threading.Thread(target=consume);reader.start()
    get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
    while process.poll() is None:
        memory = Memory();memory.cb = ctypes.sizeof(memory)
        if get_memory(wintypes.HANDLE(int(process._handle)), ctypes.byref(memory), memory.cb):
            peak = max(peak, memory.PeakWorkingSetSize);sample_count += 1
        time.sleep(.02)
    reader.join();elapsed = time.perf_counter() - start
    assert process.returncode == 0, ''.join(logs)[-1000:]
    return dict(seconds=elapsed, native_peak_working_set_bytes=peak, memory_samples=sample_count), ''.join(logs)


def measure(video, variant):
    from studyforge.media import ffmpeg_exe
    from studyforge.local_compute import cpu_threads
    folder = FOLDER / ('decoder-' + variant);folder.mkdir(parents=True, exist_ok=True)
    prefix = [ffmpeg_exe(), '-hide_banner', '-loglevel', 'info', '-y']
    if variant == 'current':prefix += ['-threads', str(cpu_threads()), '-filter_threads', str(cpu_threads())]
    output_options = ['-threads', str(cpu_threads())] if variant == 'current' else []
    filters = "setpts=PTS-STARTPTS,select='isnan(prev_selected_t)+gte(t-prev_selected_t,10)',scale=1280:-2,format=rgb24,showinfo"
    frames, log = run(prefix + ['-t', '60', '-i', str(video), '-vf', filters, '-fps_mode', 'vfr', '-frames:v', '6',
        '-start_number', '0', *output_options, str(folder / '%05d.png')])
    frames['timestamps'] = {f'{int(n):05d}.png': float(t) for n, t in
        re.findall(r'\bn:\s*(\d+)\s+pts:\s*[-\d]+\s+pts_time:([-+\d.eE]+)', log)}
    frames['frame_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob('*.png'))}
    audio, _ = run(prefix + ['-t', '60', '-i', str(video), '-vn', '-ac', '1', '-ar', '16000', *output_options, str(folder / 'audio.wav')])
    audio['sha256'] = hashlib.sha256((folder / 'audio.wav').read_bytes()).hexdigest()
    return dict(variant=variant, original_video_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
        frames=frames, audio=audio, external_model_requests=0, tested_seconds=60,
        scope='60 s actual video decode/extraction only; no ASR, OCR, AI understanding or document generation')


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('variant', choices=['before', 'current', 'compare'])
    parser.add_argument('--video', type=Path, default=Path('C:/Users/Lenovo/AppData/Local/StudyForge/946d97854c1543f8aaced0337295b89e.mp4'))
    args = parser.parse_args()
    os.environ['STUDYFORGE_DATA_DIR'] = str(FOLDER / 'decoder-data')
    if args.variant == 'compare':
        before = json.loads((FOLDER / 'decoder-before.json').read_text(encoding='utf-8'))
        current = json.loads((FOLDER / 'decoder-current.json').read_text(encoding='utf-8'))
        assert before['original_video_sha256'] == current['original_video_sha256']
        for key in ('timestamps', 'frame_sha256'):assert before['frames'][key] == current['frames'][key]
        assert before['audio']['sha256'] == current['audio']['sha256']
        report = dict(passed=True, pixels_timestamps_and_pcm_identical=True, before=before, current=current)
        (FOLDER / 'decoder-comparison.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))
    else:
        report = measure(args.video, args.variant)
        (FOLDER / ('decoder-' + args.variant + '.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))
