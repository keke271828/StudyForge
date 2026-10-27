import copy
import hashlib

from PIL import Image
import pytest

from studyforge import parsers
from studyforge.frame_ocr import ExactFrameOCR
from studyforge.media import run_ffmpeg


def pages(tmp_path):
    values=[]
    for i in range(8):
        image=Image.new('RGB',(80,50),'white')
        if i>=4:image.putpixel((40,25),(0,0,0))
        path=tmp_path/f'{i:05}.png';image.save(path);values.append(path)
    return values


def test_exact_repeat_and_one_pixel_change(tmp_path):
    values=pages(tmp_path);calls=[]
    def recognize(path):calls.append(path);return hashlib.sha256(path.read_bytes()).hexdigest()
    reader=ExactFrameOCR(recognize)
    result=[reader.read(path) for path in values]
    assert result[:4]==[result[0]]*4 and result[4:]==[result[4]]*4 and result[0]!=result[4]
    assert reader.requests==len(calls)==2 and reader.reused==6
    assert not hasattr(reader,'images')


def test_failed_ocr_is_retried_instead_of_reused(tmp_path):
    values=pages(tmp_path);calls=[]
    def recognize(path):calls.append(path);return '[OCR 未完成：临时错误]' if len(calls)==1 else '原文字'
    reader=ExactFrameOCR(recognize)
    assert reader.read(values[0]).startswith('[OCR 未完成')
    assert reader.read(values[1])==reader.read(values[2])=='原文字'
    assert reader.requests==2 and reader.reused==1


def test_empty_success_can_be_reused_and_large_text_is_not_retained(tmp_path):
    values=pages(tmp_path);empty=ExactFrameOCR(lambda path:'')
    assert empty.read(values[0])==empty.read(values[1])=='' and empty.reused==1
    large=ExactFrameOCR(lambda path:'x'*32001)
    assert len(large.read(values[0]))==len(large.read(values[1]))==32001
    assert large.previous_text is None and large.requests==2


def test_file_changed_during_ocr_is_not_saved_for_reuse(tmp_path):
    values=pages(tmp_path);calls=[]
    def change(path):calls.append(path);Image.new('RGB',(80,50),'black').save(path);return '旧画面的文字'
    reader=ExactFrameOCR(change);assert reader.read(values[0])=='旧画面的文字'
    assert reader.previous_hash is reader.previous_text is None
    assert reader.read(values[0])=='旧画面的文字' and len(calls)==2


def test_separate_videos_do_not_share_an_ocr_instance(tmp_path):
    values=pages(tmp_path);a=ExactFrameOCR(lambda path:'A');b=ExactFrameOCR(lambda path:'B')
    assert a.read(values[0])=='A' and b.read(values[0])=='B'
    assert a.requests==b.requests==1


@pytest.mark.parametrize('strategy',['dense','smart'])
def test_old_and_new_video_content_and_timestamps_match(tmp_path,monkeypatch,strategy):
    video=tmp_path/'clip.mp4'
    run_ffmpeg('-f','lavfi','-i','color=white:s=80x50:r=1:d=1','-c:v','libx264','-pix_fmt','yuv420p',str(video))
    values=pages(tmp_path);times={path.name:i*10 for i,path in enumerate(values)}
    (tmp_path/'timestamps.json').write_text(__import__('json').dumps(times),encoding='utf-8')
    calls=[[],[]];index=0
    monkeypatch.setattr(parsers,'video_frames',lambda *a,**kw:values)
    def recognize(path):calls[index].append(path);return '完整板书 '+hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(parsers,'_ocr',recognize)
    from studyforge import frame_ocr
    class EveryFrame:
        def __init__(self,recognize):self.recognize=recognize;self.requests=0;self.reused=0
        def read(self,path):self.requests+=1;return self.recognize(path)
    monkeypatch.setattr(frame_ocr,'ExactFrameOCR',EveryFrame)
    before=parsers.parse_video(video,frame_strategy=strategy)
    monkeypatch.setattr(frame_ocr,'ExactFrameOCR',ExactFrameOCR);index=1
    current=parsers.parse_video(video,frame_strategy=strategy)
    sampling=current[0]['meta']['video_sampling']
    assert sampling['ocr_requests']==len(calls[1])
    assert sampling['ocr_frames']==len(calls[0])
    assert len(calls[1])<=len(calls[0])
    # Added measurements are the sole difference; no frame/position/text loss.
    current=copy.deepcopy(current)
    for key in ('ocr_requests','ocr_reused_frames'):
        current[0]['meta']['video_sampling'].pop(key);before[0]['meta']['video_sampling'].pop(key)
    assert current==before
    if strategy=='dense':assert len(calls[0])==8 and len(calls[1])==2
