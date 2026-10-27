"""Render a generated Markdown lesson without calling a model again."""
import os
import sys
from pathlib import Path

from studyforge.exporters import export_document

root = Path(sys.argv[1]).resolve()
os.environ['STUDYFORGE_DATA_DIR'] = str(root / 'render-data')
source = root / 'oscillator-quality.md'
text = source.read_text(encoding='utf-8-sig')
for fmt in ('docx', 'pdf'):
    path = export_document(text, fmt, '理想弹簧振子：讲解质量验收', f'oscillator-quality.{fmt}')
    print(path)
