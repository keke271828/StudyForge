import asyncio
from pathlib import Path
from types import SimpleNamespace
import wave

import pytest

from studyforge import media, parsers, task_timing
from studyforge.db import create_job, create_project, many
from studyforge.scheduling import execution_scope, run_local


def test_video_records_real_local_stages_without_changing_asr_policy(tmp_path, monkeypatch):
    video = tmp_path / 'lecture.mp4'
    media.run_ffmpeg('-f','lavfi','-i','testsrc2=size=320x180:rate=2:duration=12',
                    '-f','lavfi','-i','sine=frequency=1000:sample_rate=16000:duration=12',
                    '-c:v','libx264','-c:a','aac','-pix_fmt','yuv420p','-shortest',str(video))
    audios=[]
    class Engine:
        def transcribe(self, filename, **options):
            audios.append(Path(filename))
            with wave.open(filename) as audio:
                assert audio.getnchannels()==1 and audio.getframerate()==16000
                assert audio.getnframes()/16000>=12
            assert options=={'language':None,'vad_filter':True,'beam_size':5}
            return iter([SimpleNamespace(start=0,end=12,text='原始完整讲述。')]),None
    monkeypatch.setattr(media,'_whisper_model',lambda selected:Engine())
    # Distinct mocked board text avoids the existing identical-frame merge;
    # this test checks timing/inference policy, not OCR recognition quality.
    monkeypatch.setattr(parsers,'_ocr',lambda path:f'原始板书文字 {Path(path).stem}。')
    project=create_project('video timing');ident=create_job(project['id'],'import',{})
    async def run():
        async with execution_scope(job_id=ident,project_id=project['id']):
            return await run_local('media',parsers.parse_video,video,label='视频本机解析')
    parts=asyncio.run(run())
    assert parts[0]['text']=='原始完整讲述。'
    frames=[part for part in parts if part['kind']=='video_frame']
    assert len(frames)==2 and [part['meta']['time'] for part in frames]==[0,10]
    assert [part['text'] for part in frames]==['原始板书文字 00000。','原始板书文字 00001。']
    assert audios and all(not path.exists() for path in audios)
    rows=many('SELECT resource,status FROM execution_spans WHERE job_id=?',(ident,))
    assert {row['resource'] for row in rows}=={'media','audio_extract','speech','speech_wait','speech_load','speech_decode','frame_extract','video_ocr','asr_info'}
    assert all(row['status']=='completed' for row in rows)
    assert task_timing.detail(ident)['observed']


def test_failed_audio_extraction_removes_partial_wav(tmp_path, monkeypatch):
    video=tmp_path/'original.mp4';video.write_bytes(b'original')
    written=[]
    def fail(*args):
        path=Path(args[-1]);path.write_bytes(b'partial audio');written.append(path)
        raise RuntimeError('expected extraction error')
    monkeypatch.setattr(media,'run_ffmpeg',fail)
    with pytest.raises(RuntimeError,match='expected extraction error'):media.transcribe(video)
    assert written and all(not path.exists() for path in written)
    assert video.read_bytes()==b'original'
