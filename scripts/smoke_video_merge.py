"""Verify real yt-dlp audio/video merging using the application's FFmpeg."""
from pathlib import Path
from uuid import uuid4
import json
import os

root = Path(__file__).resolve().parent.parent / 'build' / ('video-merge-' + uuid4().hex)
root.mkdir(parents=True)
os.environ['STUDYFORGE_DATA_DIR'] = str(root)

import av
from yt_dlp import YoutubeDL
from yt_dlp.postprocessor.ffmpeg import FFmpegMergerPP
from studyforge.media import ffmpeg_exe, run_ffmpeg

video, audio, combined = root / 'video.mp4', root / 'audio.m4a', root / 'combined.mp4'
run_ffmpeg('-f', 'lavfi', '-i', 'color=c=white:s=320x180:d=1', '-an', '-c:v', 'mpeg4', str(video))
run_ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-vn', '-c:a', 'aac', str(audio))
with YoutubeDL({'ffmpeg_location': ffmpeg_exe(), 'quiet': True, 'no_warnings': True}) as downloader:
    merger = FFmpegMergerPP(downloader)
    if not merger.available:
        raise RuntimeError('The application FFmpeg cannot be found by yt-dlp')
    merger.run({'filepath': str(combined), 'ext': 'mp4', 'vcodec': 'mpeg4', 'acodec': 'aac',
                '__files_to_merge': [str(video), str(audio)], 'requested_formats': [
                    {'filepath': str(video), 'vcodec': 'mpeg4', 'acodec': 'none', 'protocol': 'http'},
                    {'filepath': str(audio), 'vcodec': 'none', 'acodec': 'aac', 'protocol': 'http'}]})
with av.open(str(combined)) as container:
    if len(container.streams.video) != 1 or len(container.streams.audio) != 1:
        raise RuntimeError('Merged video is missing audio or video')
print(json.dumps({'ok': True, 'ffmpeg': ffmpeg_exe(), 'video_streams': 1, 'audio_streams': 1}))
