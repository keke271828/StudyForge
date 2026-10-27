"""Render Word's QA PDFs into pages and layout contact sheets under build."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('pdf')
args = parser.parse_args()
pdf = Path(args.pdf).resolve()
if not pdf.is_relative_to(root / 'build') or pdf.suffix != '.pdf':
    raise ValueError('只验收工作区 build 下的 PDF')
target = pdf.parent / 'pages'
target.mkdir(exist_ok=True)
document = fitz.open(pdf)
page_paths, beyond = [], []
for index, page in enumerate(document):
    path = target / f'page-{index+1:02d}.png'
    page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False).save(path)
    page_paths.append(path)
    for block in page.get_text('blocks'):
        x0, y0, x1, y1 = block[:4]
        if x0 < -1 or y0 < -1 or x1 > page.rect.width+1 or y1 > page.rect.height+1:
            beyond.append({'page': index+1, 'rectangle': list(block[:4])})
for first in range(0, len(page_paths), 12):
    subset = page_paths[first:first+12]
    sheet = Image.new('RGB', (1500, 4*710), '#D5D9DE')
    draw = ImageDraw.Draw(sheet)
    for offset, path in enumerate(subset):
        with Image.open(path) as image:
            image.thumbnail((470, 660))
            x, y = 15+(offset%3)*500, 30+(offset//3)*710
            sheet.paste(image, (x,y))
            draw.text((x,y-20), f'Page {first+offset+1}', fill='#111111')
    sheet.save(pdf.parent / f'layout-{first//12+1}.png')
summary = {'pdf': str(pdf), 'pages': len(document), 'text_outside_page': beyond,
           'rendered_pages': [str(path) for path in page_paths]}
(pdf.parent / 'pdf-structure.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'pages': summary['pages'], 'text_outside_page': beyond}, ensure_ascii=False))
