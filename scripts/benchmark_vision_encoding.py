"""Native Windows RSS and exact visual payload comparison, isolated per mode."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmark_video_ab import peak_ram_mb


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['prepare','baseline','optimized'],required=True)
    parser.add_argument('--folder',default='vision-preparation-20261010-1')
    args=parser.parse_args();folder=(ROOT/'build'/args.folder).resolve()
    if not folder.is_relative_to(ROOT/'build'):raise ValueError('Benchmark outside build')
    folder.mkdir(parents=True,exist_ok=True);path=folder/'rgb-page.png'
    from PIL import Image,ImageDraw
    if args.mode=='prepare':
        image=Image.new('RGB',(4000,6000),'white');draw=ImageDraw.Draw(image)
        for row in range(100,5900,50):
            draw.line((80,row,3920,row),fill=(row%256,(row//3)%256,(row//7)%256),width=2)
            draw.text((100,row+5),'Source: x + y = 3; conditions and derivation.',fill='black')
        image.save(path);return
    from studyforge.vision_batches import image_content
    def previous(path):
        with Image.open(path) as original:
            image=original.convert('RGB');image.thumbnail((1280,1280));buffer=io.BytesIO();image.save(buffer,'JPEG',quality=82)
        return base64.b64encode(buffer.getvalue()).decode('ascii')
    before=time.perf_counter();values=[]
    for _ in range(4):
        values.append(previous(path) if args.mode=='baseline' else image_content(path)['image_url']['url'].split(',',1)[1])
    result={'mode':args.mode,'input_pixels':[4000,6000],'images_prepared':4,
        'elapsed_seconds':time.perf_counter()-before,'process_peak_working_set_mb':peak_ram_mb(),
        'payload_sha256':[hashlib.sha256(value.encode('ascii')).hexdigest() for value in values],
        'payload_characters':len(values[0]),'scope':'Single isolated Python process, four sequential native RGB preparations; no model or OCR.'}
    (folder/(args.mode+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
