"""Exercise frozen resources without accessing user projects or paid AI services."""
from __future__ import annotations

import json
from pathlib import Path


def self_check() -> None:
    import importlib
    import tempfile
    import zipfile
    import keyring
    import fitz
    from PIL import Image, ImageDraw, ImageFont
    from docx import Document
    from pptx import Presentation
    from .config import data_dir
    from .exporters import export_document
    from .media import ffmpeg_exe, run_ffmpeg
    from .parsers import parse_file
    from .server import web_dir
    from .api_network import http_options

    environment_route = http_options('system')
    direct_route = http_options('direct')
    if environment_route.get('trust_env') is not True or direct_route.get('trust_env') is not False:
        raise RuntimeError('Packaged API route selection is unavailable')
    if direct_route.get('verify') is False:
        raise RuntimeError('Packaged API direct route disabled certificate verification')

    required_web = ('index.html', 'desktop_startup.js', 'desktop_startup.css',
                    'user_guide.js', 'user_guide.css', 'help/guide.html', 'help/guide.js', 'help/guide.css',
                    'source_scope.js', 'mobile/index.html', 'mobile/app.js', 'mobile/homework.js',
                    'mobile/lesson-feedback.js', 'lesson_passage.js', 'lesson_passage.css', 'mobile/sw.js', 'vendor/katex.js')
    for resource in required_web:
        if not (web_dir / resource).is_file():
            raise RuntimeError('Missing packaged web resource: ' + resource)
    imports = ('faster_whisper', 'ctranslate2', 'onnxruntime', 'av', 'tokenizers', 'yt_dlp',
               'mcp.server.fastmcp', 'pyttsx3.drivers.sapi5', 'keyring.backends.Windows')
    for name in imports:
        importlib.import_module(name)
    backend = keyring.get_keyring()
    if not type(backend).__module__.startswith('keyring.backends.Windows'):
        raise RuntimeError(f'Windows keyring is unavailable: {backend}')
    import pyttsx3
    voice = pyttsx3.init()
    voice.stop()
    from faster_whisper.vad import get_vad_model
    get_vad_model()
    content = '# 安装版物理自检\n\n## 牛顿第二定律\n质量为 $m$ 的物体满足 $F=ma$。\n\n$$\nE=\\frac{1}{2}mv^2\n$$\n'
    exports = {}
    for fmt in ('docx', 'pdf', 'pptx', 'mm', 'apkg', 'ipynb', 'zip', 'py', 'js', 'ts', 'cpp', 'm', 'wl'):
        code = {'py': 'print(2 + 2)', 'js': 'console.log(2 + 2);', 'ts': 'console.log(2 + 2);',
                'cpp': '#include <iostream>\nint main(){std::cout << 4;}',
                'm': 'm = 1; a = 2; F = m*a;', 'wl': 'm=1; a=2; force=m*a;'}
        text = f'```{fmt}\n{code[fmt]}\n```' if fmt in code else content + '\n```python\nprint(2 + 2)\n```\n'
        if fmt == 'apkg':
            text = json.dumps({'cards': [{'question': '质量为 m、加速度为 a 时，合力如何表示？',
                'answer': 'F = ma。', 'source': '安装版验收样例：牛顿第二定律'}]}, ensure_ascii=False)
        path = export_document(text, fmt, '安装版自检', f'packaging-check.{fmt}')
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f'{fmt} export is empty')
        if fmt in ('docx', 'pdf', 'pptx', 'mm', 'apkg', 'ipynb', 'py', 'js', 'ts', 'cpp', 'm', 'wl'):
            if not parse_file(path):
                raise RuntimeError(f'{fmt} cannot be parsed')
        if fmt == 'docx': Document(path)
        if fmt == 'pptx': Presentation(path)
        if fmt == 'pdf':
            with fitz.open(path) as document:
                if '牛顿' not in ''.join(page.get_text() for page in document):
                    raise RuntimeError('Chinese PDF text is missing')
        if fmt == 'zip':
            with zipfile.ZipFile(path) as archive:
                if archive.testzip(): raise RuntimeError('Invalid exported ZIP')
        exports[fmt] = path.stat().st_size

    with tempfile.TemporaryDirectory(dir=data_dir()) as directory:
        root = Path(directory)
        image = Image.new('RGB', (1000, 220), 'white')
        ImageDraw.Draw(image).text((35, 45), 'Newton force F = ma', fill='black',
                                  font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 54))
        image.save(root / 'ocr.png')
        extracted = ' '.join(part['text'] for part in parse_file(root / 'ocr.png'))
        if 'Newton' not in extracted:
            raise RuntimeError(f'OCR failed: {extracted}')
        run_ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.1', str(root / 'sound.wav'))
        if (root / 'sound.wav').stat().st_size < 100:
            raise RuntimeError('Bundled FFmpeg failed')
    print(json.dumps({'ok': True, 'web': str(web_dir), 'imports': imports, 'exports': exports,
                      'api_network': {'environment_mode': True, 'direct_mode': True, 'certificate_verification': True},
                      'keyring': type(backend).__name__, 'ocr': extracted, 'ffmpeg': ffmpeg_exe()}, ensure_ascii=False))
