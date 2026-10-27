"""Measure actual OCR RAM and time with old per-thread and new shared engines."""
import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmark_video_ab import peak_ram_mb, write_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['legacy','shared'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output=args.output.resolve()
    if not args.output.is_relative_to(Path(__file__).resolve().parents[1]/'build'):
        raise ValueError('输出必须位于工作区 build 内')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    from PIL import Image,ImageDraw,ImageFont
    image=args.output.parent/'ocr-sample.png'
    canvas=Image.new('RGB',(960,360),'white')
    font=ImageFont.truetype(r'C:\Windows\Fonts\arial.ttf',28)
    draw=ImageDraw.Draw(canvas)
    for i,line in enumerate(['Physics and mathematics','12345 + 67890 = 80235','Energy E = 0.5 m v^2','Keep every source detail.']):
        draw.text((25,25+70*i),line,font=font,fill='black')
    canvas.save(image)
    import rapidocr
    from studyforge import parsers
    native=rapidocr.RapidOCR;count=0;guard=threading.Lock();local=threading.local()
    def create(*a,**kw):
        nonlocal count
        with guard:count+=1
        return native(*a,**kw)
    rapidocr.RapidOCR=create
    barrier=threading.Barrier(3)
    def run(_):
        barrier.wait()
        if args.mode=='shared':return parsers._ocr(image)
        if not hasattr(local,'engine'):local.engine=create()
        return '\n'.join(local.engine(str(image)).txts or [])
    started=time.perf_counter()
    with ThreadPoolExecutor(max_workers=3) as pool:values=list(pool.map(run,range(3)))
    result={'mode':args.mode,'workers':3,'engine_instances':count,
            'elapsed_seconds':round(time.perf_counter()-started,3),'peak_ram_mb':peak_ram_mb(),
            'all_results_equal':len(set(values))==1,'recognized_text':values[0],
            'recognition_passed':all('12345' in x and '67890' in x and '80235' in x for x in values)}
    write_json(args.output,result);print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if result['recognition_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
