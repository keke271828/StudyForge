"""Isolated HTTP/TLS fixture for original URL/image reading; no external AI."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
case_root = Path(os.environ['STUDYFORGE_MOBILE_CASE']).parent
os.environ['STUDYFORGE_DATA_DIR'] = str(case_root / 'data')
case_root.mkdir(parents=True, exist_ok=True)

from PIL import Image, ImageDraw, ImageFont
from studyforge import parsers, server, urls
from studyforge.config import temp_dir
from smoke_mobile import main

image = Image.new('RGB', (620, 160), 'white')
ImageDraw.Draw(image).text((25, 40), 'WHOLE IMAGE 12345', font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 36), fill='black')
image.save(case_root / 'scope-image.png')
original_parse = server.parse_file
failures = set()


def download(url, source_id, **kwargs):
    if url.endswith('/needs-login'):
        raise urls.BrowserImportRequired('网站需要登录或验证，请使用浏览器导入')
    path = temp_dir() / f'url-{source_id}.html'
    marker = 'RETRY_SOURCE_BODY' if url.endswith('/first-fails') else 'COMPLETE_SOURCE_BODY'
    path.write_text(f'<!doctype html><meta charset="utf-8"><article><h1>URL_LESSON</h1><p>{marker}：这是完整的网页正文，不是手动粘贴的选段。</p></article>', encoding='utf-8')
    return path


def parse(path):
    if path.suffix == '.html' and 'RETRY_SOURCE_BODY' in path.read_text(encoding='utf-8') and path.stem not in failures:
        failures.add(path.stem)
        raise RuntimeError('用于验收的首次解析失败，重试应重新下载原网址')
    return original_parse(path)


server.download_public_resource = download
server.parse_file = parse
server.validate_public_url = lambda url: url
main()
