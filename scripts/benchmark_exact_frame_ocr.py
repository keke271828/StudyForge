"""Real RapidOCR on exact repeated PNGs, then byte-identical result comparison.

The original course frame is supplied locally; it is never modified. This
isolates static-frame OCR, not speech, cloud teaching, or a full video course.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'build/vision-concurrent-20261012'
os.environ['STUDYFORGE_DATA_DIR']=str(FOLDER/'real-ocr-data')
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(FOLDER/'unused-model')


def main():
    from studyforge.parsers import _ocr
    from studyforge.frame_ocr import ExactFrameOCR
    from studyforge import local_compute
    # Reuse an actual previously extracted PNG rather than generating a fake
    # textbook. The source path is recorded only in this local test report.
    choices=sorted((ROOT/'build/generation-local-performance-20261011').rglob('*.png'))
    if not choices:raise RuntimeError('没有已提取的本地课程画面，不能报告真实 OCR 对照')
    source=choices[0];folder=FOLDER/'exact-real-course-frame';folder.mkdir(exist_ok=True)
    paths=[]
    for index in range(8):
        path=folder/f'{index:05}.png';shutil.copyfile(source,path);paths.append(path)
    first=_ocr(paths[0])
    if first.startswith('[OCR 未完成'):raise RuntimeError(first)
    # Same loaded CPU engine, same OCR arguments and threads in both passes.
    start=time.perf_counter();before=[_ocr(path) for path in paths];old_ms=(time.perf_counter()-start)*1000
    reader=ExactFrameOCR(_ocr);start=time.perf_counter();current=[reader.read(path) for path in paths];new_ms=(time.perf_counter()-start)*1000
    assert before==current and all(text==first for text in before)
    result=dict(passed=True,source_frame=str(source),original_frame_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                complete_ocr_text_identical=True,text_characters=len(first),frame_count=8,before_ocr_requests=8,
                current_ocr_requests=reader.requests,reused_frames=reader.reused,before_ms=old_ms,current_ms=new_ms,
                cpu_threads=local_compute.cpu_threads(),external_model_requests=0,
                scope='real RapidOCR on 8 byte-identical copies of one course frame; warm CPU model; not total video latency')
    (FOLDER/'exact-ocr-comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (FOLDER/'exact-ocr-text.txt').write_text(first,encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
