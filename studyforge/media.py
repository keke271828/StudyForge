from __future__ import annotations

import subprocess
import json
import math
import re
from contextlib import ExitStack
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4

from .config import temp_dir, derived_dir
from .runtime import background_process_options

_asr_device = ContextVar('speech_requested_device',default=None)


def ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(*args: str, log_level: str = 'error') -> str:
    from .local_compute import cpu_threads
    # Bound decoder/filter frame buffers and leave CPU for the UI. Audio
    # inference settings, sampling times, scale and PNG output stay unchanged.
    threads = str(cpu_threads())
    output_args = [*args[:-1], '-threads', threads, args[-1]] if args else []
    result = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", log_level, "-y",
                             '-threads', threads, '-filter_threads', threads, *output_args],
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=3600, check=False, **background_process_options())
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:] or "FFmpeg 处理失败")
    return result.stderr


def transcribe(path: Path, language: str | None = None) -> list[dict]:
    from .ai import settings
    from .task_timing import timed_call, phase
    audio = derived_dir(path, 'audio') / f'{uuid4().hex}.wav'
    config=settings();selected=config.get('whisper_model','small')
    token=_asr_device.set(config.get('whisper_device','auto'))
    try:
        timed_call('audio_extract', '提取完整音轨', run_ffmpeg,
                   "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", str(audio))
        from .local_compute import inference_slot
        with phase('speech','语音阶段整体（含排队、加载和完整识别）'), ExitStack() as stack:
            with phase('speech_wait','等待本机识别引擎空闲'):
                stack.enter_context(inference_slot())
            with phase('speech_load','载入或复用所选语音模型（含设备核验）'):
                try:model=_whisper_model(selected)
                except Exception as exc:
                    raise RuntimeError(f'所选语音模型 {selected} 无法加载；请检查模型下载和运行环境，原文件已保留') from exc
            info=dict(getattr(model,'_studyforge_asr',{}) or {})
            options = {"language": language, "vad_filter": language is None, "beam_size": 5}
            if language == "zh":
                options["initial_prompt"] = "以下是普通话学习讨论，可能涉及各学科的知识、专有名词与公式。"
            with phase('speech_decode','识别完整音轨（含同模型恢复）'):
                parts,failed=_decode_speech(model,audio,options)
                if failed:
                    from .asr_backend import mark_failure
                    reason=mark_failure(selected)
                    model=None
                    previous=_asr_device.set('cpu')
                    try:model=_whisper_model(selected)
                    finally:_asr_device.reset(previous)
                    info=dict(getattr(model,'_studyforge_asr',{}) or {})
                    info.update(preferred_device=config.get('whisper_device','auto'),fallback_reason=reason)
                    parts,failed=_decode_speech(model,audio,options)
                    if failed:raise RuntimeError('同模型 CPU 恢复未完成，请检查语音识别环境')
                from .task_timing import record_info
                record_info('asr_execution',info|dict(selected_model=selected,actual_model=selected,
                    language=language or 'auto',beam_size=5,audio_seconds=_audio_seconds(audio)))
                return parts
    finally:
        audio.unlink(missing_ok=True)
        _asr_device.reset(token)


def _decode_speech(model,audio,options):
    try:
        parts,_=model.transcribe(str(audio),**options)
        return [{"start": round(p.start,2),"end":round(p.end,2),"text":p.text.strip()} for p in parts],False
    except Exception:
        if (getattr(model,'_studyforge_asr',{}) or {}).get('actual_device')!='cuda':raise
        # Return only a signal, not an exception/traceback holding the GPU engine
        # or a partially collected transcript alive during CPU recovery.
        return None,True


def _audio_seconds(path):
    import wave
    with wave.open(str(path)) as audio:return round(audio.getnframes()/audio.getframerate(),3)


def _whisper_model(name: str):
    from .asr_backend import load_model
    return load_model(name,_asr_device.get() or 'auto')


def video_frames(path: Path, every_seconds: int = 10, max_frames: int = 2160,
                 *, scene_threshold: float | None = None) -> list[Path]:
    if every_seconds <= 0 or max_frames < 1: raise ValueError('画面采样间隔和数量必须为正数')
    folder = derived_dir(path, 'frames')
    for old in folder.glob("*.png"):
        old.unlink()
    # Select actual source frames and record their timestamps. The former extra
    # time-zero frame + fps sequence was incorrectly labelled by index*10.
    selection = f'isnan(prev_selected_t)+gte(t-prev_selected_t,{every_seconds})'
    if scene_threshold is not None:
        if not 0 < scene_threshold < 1: raise ValueError('场景变化阈值须在 0 和 1 之间')
        selection += f'+gt(scene,{scene_threshold})*gte(t-prev_selected_t,1)'
    filters = (f"setpts=PTS-STARTPTS,select='{selection}',"
               'scale=1280:-2,format=rgb24,showinfo')
    log = run_ffmpeg('-i', str(path), '-vf', filters, '-fps_mode', 'vfr', '-frames:v', str(max_frames),
                     '-start_number', '0', str(folder / '%05d.png'), log_level='info')
    times = {f'{int(number):05d}.png': float(stamp) for number, stamp in
             re.findall(r'\bn:\s*(\d+)\s+pts:\s*[-\d]+\s+pts_time:([-+\d.eE]+)', log)}
    (folder / 'timestamps.json').write_text(json.dumps(times), encoding='utf-8')
    return sorted(folder.glob('*.png'))


def video_frame_timestamps(frames: list[Path]) -> dict[str, float]:
    if not frames: return {}
    manifest = frames[0].parent / 'timestamps.json'
    if not manifest.is_file(): return {}
    return json.loads(manifest.read_text(encoding='utf-8'))


def _caption_segments(path: Path) -> list[dict]:
    """Only timed subtitle formats are accepted, never arbitrary page text."""
    from bs4 import BeautifulSoup
    from .parsers import decode_text
    value, _ = decode_text(path.read_bytes())
    if path.suffix == '.json' or path.suffix == '.json3':
        data = json.loads(value)
        if isinstance(data, dict) and isinstance(data.get('body'), list):
            parts = [dict(start=p.get('from'), end=p.get('to'), text=p.get('content', '')) for p in data['body'] if isinstance(p, dict)]
        elif isinstance(data, dict) and isinstance(data.get('events'), list):
            parts = [dict(start=p.get('tStartMs', 0) / 1000,
                          end=(p.get('tStartMs', 0) + p.get('dDurationMs', 0)) / 1000,
                          text=''.join(str(s.get('utf8', '')) for s in p.get('segs', []) if isinstance(s, dict)))
                     for p in data['events'] if isinstance(p, dict)]
        else:
            return []
    else:
        def seconds(stamp):
            components = stamp.replace(',', '.').split(':')
            return sum(float(part) * 60 ** i for i, part in enumerate(reversed(components)))
        parts = []
        for block in re.split(r'\r?\n\s*\r?\n', value):
            match = re.search(r'([\d:. ,]+)\s*-->\s*([\d:.,]+)[^\r\n]*\r?\n(.+)', block, re.S)
            if match:
                parts.append(dict(start=seconds(match[1].strip()), end=seconds(match[2]), text=match[3]))
    result = []
    for part in parts:
        try:
            start, end = float(part['start']), float(part['end'])
            text = BeautifulSoup(str(part['text']), 'html.parser').get_text(' ', strip=True)
            if math.isfinite(start) and math.isfinite(end) and 0 <= start < end and text:
                result.append(dict(start=round(start, 2), end=round(end, 2), text=text))
        except (ValueError, TypeError, KeyError):
            continue
    return sorted(result, key=lambda p: p['start'])


def video_metadata_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + '.video.json')


def download_public_video(url: str, *, referer: str | None = None, cookies: list[dict] | None = None,
                          on_progress=None) -> Path:
    from http.cookiejar import Cookie
    from urllib.parse import urlparse
    import yt_dlp
    from .urls import validate_public_url
    validate_public_url(url)
    if referer:
        validate_public_url(referer)
    destination = temp_dir() / 'downloads' / uuid4().hex
    destination.mkdir(parents=True, exist_ok=True)
    final_paths = []
    def progress(data):
        if on_progress:
            total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
            percentage = min(99, int(100 * data.get('downloaded_bytes', 0) / total)) if total else 0
            on_progress('下载视频音轨与画面', percentage)
    def processed(data):
        if data.get('status') == 'finished':
            final_paths.append(data.get('info_dict', {}).get('filepath'))
    def allowed(info, *, incomplete=False):
        if info.get('is_live'):
            raise ValueError('正在直播的视频不能完整读取，请在直播结束后导入回放或上传录制文件')
        if info.get('has_drm'):
            raise ValueError('此视频受保护，请上传你有权使用的本地视频文件')
        if (info.get('filesize') or 0) > 2 * 1024 ** 3:
            raise ValueError('视频超过 2 GB，请分段后从本地导入')
        return None
    class Logger:
        # Site responses can contain signed URLs. Keep them out of logs/jobs/AI.
        def debug(self, _): pass
        def warning(self, _): pass
        def error(self, _): pass
    opts = {
        "outtmpl": str(destination / "%(id)s.%(ext)s"),
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/bestvideo[height<=1080]/best",
        "ffmpeg_location": ffmpeg_exe(), "merge_output_format": "mp4",
        "noplaylist": True, "quiet": True, "no_warnings": True,
        'playlist_items': '1', 'getcomments': False, 'writeinfojson': False,
        'writesubtitles': True, 'writeautomaticsub': True,
        'subtitleslangs': ['zh.*', 'en.*'], 'subtitlesformat': 'json3/vtt/srt/json/best',
        'restrictfilenames': True, 'windowsfilenames': True,
        'http_headers': {'Referer': referer or url},
        'socket_timeout': 25, 'retries': 2, 'fragment_retries': 2,
        'concurrent_fragment_downloads': 4, 'logger': Logger(), 'match_filter': allowed,
        'progress_hooks': [progress], 'postprocessor_hooks': [processed],
        "max_filesize": 2 * 1024 * 1024 * 1024,
    }
    hosts = {(urlparse(u).hostname or '').lower() for u in (url, referer or url)}
    completed = False
    try:
        with yt_dlp.YoutubeDL(opts) as downloader:
            # Use only cookies for this video/site, in memory. Never save them in
            # projects, logs, metadata, or model prompts.
            for item in cookies or []:
                domain = str(item.get('domain', '')).lower()
                plain = domain.lstrip('.')
                if not plain or '.' not in plain or not any(h == plain or h.endswith('.' + plain) for h in hosts):
                    continue
                name, value = str(item.get('name', '')), str(item.get('value', ''))
                if not name or any(c in name + value for c in '\r\n\x00'):
                    continue
                expires = item.get('expirationDate')
                downloader.cookiejar.set_cookie(Cookie(0, name, value, None, False, domain,
                    domain.startswith('.'), domain.startswith('.'), item.get('path') or '/', True,
                    bool(item.get('secure', True)), int(expires) if expires else None, not expires,
                    None, None, {'HttpOnly': item.get('httpOnly', False)}, False))
            from .ai import settings
            if settings().get('video_import_mode') == 'subtitles_first':
                info = downloader.extract_info(url, download=False)
                record = _subtitle_record(downloader, info, destination, url, referer, on_progress)
                if record:
                    completed = True
                    return record
                if on_progress: on_progress('字幕不足，改为提取完整音画', 0)
            info = downloader.extract_info(url, download=True)
            if info and 'entries' in info:
                info = next((part for part in info['entries'] if part), None)
            if not info:
                raise RuntimeError('视频未返回可用内容')
            prepared = Path(downloader.prepare_filename(info))
            candidates = [*reversed(final_paths), info.get('filepath'), info.get('_filename'),
                          prepared.with_suffix('.mp4'), prepared.with_suffix('.mkv'), prepared]
            filename = next((Path(p) for p in candidates if p and Path(p).is_file()
                             and Path(p).suffix.lower() in ('.mp4', '.mkv', '.webm', '.mov', '.avi')
                             and Path(p).resolve().is_relative_to(destination.resolve())), None)
            if filename is None:
                raise RuntimeError('视频音画合并未完成或文件过大，请上传本地视频')
            if filename.stat().st_size > 2 * 1024 ** 3:
                raise ValueError('合并后的视频超过 2 GB，请分段后从本地导入')
            import av
            with av.open(str(filename)) as container:
                if not container.streams.video:
                    raise RuntimeError('下载结果没有视频画面，已停止导入')
                if info.get('acodec') not in (None, 'none') and not container.streams.audio:
                    raise RuntimeError('视频音轨未合并，已停止导入')
            captions = []
            for language, subtitle in sorted((info.get('requested_subtitles') or {}).items(),
                                             key=lambda item: (not item[0].startswith('zh'), item[0])):
                caption_file = subtitle.get('filepath')
                if not caption_file or not Path(caption_file).is_file():
                    continue
                try:
                    captions = _caption_segments(Path(caption_file))
                except (ValueError, OSError):
                    continue
                duration = info.get('duration') or 0
                if captions and (not duration or (duration * .6 <= captions[-1]['end'] <= duration + 5)):
                    break
                captions = []
            video_metadata_path(filename).write_text(json.dumps({
                'title': str(info.get('title') or '视频资料')[:500], 'url': url,
                'subtitles': captions, 'subtitle_language': language if captions else None,
                'duration': info.get('duration'), 'media_bytes': filename.stat().st_size,
            }, ensure_ascii=False), encoding='utf-8')
            if on_progress:
                on_progress('视频下载与音画合并完成', 100)
            completed = True
            return filename
    except yt_dlp.utils.DownloadError as exc:
        raise RuntimeError('视频站点未允许读取，可能需要登录、验证或该视频暂不可访问') from exc
    finally:
        if not completed:
            from .video_records import clean_download
            clean_download(destination / 'incomplete.mp4')


def _subtitle_record(downloader, info, destination, url, referer, on_progress):
    """Optional transcript-only import, with an explicit no-visual-analysis limit."""
    import httpx
    from .urls import validate_public_url
    from .video_records import write_record
    if not isinstance(info, dict) or info.get('is_live'): return None
    subtitles = info.get('requested_subtitles') or {}
    for language, subtitle in sorted(subtitles.items(), key=lambda item:(not item[0].startswith('zh'),item[0])):
        if not isinstance(subtitle, dict) or not subtitle.get('url'): continue
        extension = subtitle.get('ext', '')
        if extension not in {'json3','json','vtt','srt'}: continue
        try:
            current = subtitle['url']
            with httpx.Client(timeout=25,follow_redirects=False,cookies=downloader.cookiejar,
                             headers={'Referer':referer or url,'User-Agent':'Mozilla/5.0'}) as client:
                for _ in range(5):
                    validate_public_url(current)
                    with client.stream('GET',current) as response:
                        if response.status_code in (301,302,303,307,308):
                            from urllib.parse import urljoin
                            current=urljoin(current,response.headers.get('location',''));continue
                        response.raise_for_status();content=bytearray()
                        for chunk in response.iter_bytes():
                            content.extend(chunk)
                            if len(content)>10*1024*1024:raise ValueError('字幕文件过大')
                    break
                else:continue
            caption=destination / ('caption.'+extension);caption.write_bytes(content)
            parts=_caption_segments(caption)
            duration=float(info.get('duration') or 0)
            if not parts or not duration or parts[0]['start']>max(3,duration*.05) or parts[-1]['end']<duration*.9 or parts[-1]['end']>duration+5:continue
            from .parsers import segment
            segments=[segment(f"{p['start']:.1f}-{p['end']:.1f} 秒",p['text'],'transcript',start=p['start'],end=p['end'],method='video_subtitle') for p in parts]
            limitation='本次使用字幕优先模式：只读取带时间戳字幕，未分析视频画面、板书或图表；需要完整音画时请切换读取方式重新导入'
            segments.append(segment('读取范围',limitation,'notice'))
            record=write_record(destination/'transcript.sfvideo',segments,url=url,title=str(info.get('title') or '视频字幕'),
                metadata={'mode':'subtitles_only','duration':duration,'subtitle_language':language,'limitation':limitation})
            if on_progress:on_progress('视频字幕读取完成，未下载音画文件',100)
            return record
        except (ValueError,OSError,httpx.HTTPError):continue
    return None
