"""Live, isolated philosophy lesson QA using the configured quality model."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from uuid import uuid4

root = Path(__file__).resolve().parent.parent / 'build' / ('teaching-live-' + uuid4().hex)
os.environ['STUDYFORGE_DATA_DIR'] = str(root)

from docx import Document
from studyforge import model_catalog
from studyforge.codex_bridge import bridge
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid, update_mastery
from studyforge.config import files_dir, artifacts_dir
from studyforge.server import GenerateIn, _generate_job

ORIGINAL = (
    '本文是一份用于讲解质量验收的自拟社会科学资料。\n'
    '福柯的规训权力分析关注日常制度如何塑造行为。规训并不只体现为一次明确的命令，'
    '还可能通过时间安排、持续观察、规范化评判和检查，让人不断调整自己的行为。\n'
    '学校安排课程表并记录学习表现，说明制度能够把个体放进可比较的分类之中。'
    '这里的关键问题是行为如何逐渐符合某种标准，而不是把一切制度都说成同一种权力。\n'
    '这样的分析提醒我们考察规范形成的过程与实际作用。理解规训需要区分外部强迫、'
    '日常习惯和对标准的主动认同；这些因素可能共同存在，但不能只凭行为相似就认定原因相同。'
)


async def main():
    project = create_project('多学科讲解质量验收')
    source = files_dir() / '社会科学验收.txt'
    source.write_text(ORIGINAL, encoding='utf-8')
    source_id = uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,error,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
            (source_id, project['id'], source.name, '.txt', str(source), '[]', 'ready', None, now()))
    # A physics profile must not redirect the subject of this philosophy lesson.
    update_mastery('牛顿力学', quiz=95)
    selected = model_catalog.recommended_generation((await model_catalog.get_models())['models'])
    value = GenerateIn(project_id=project['id'], source_ids=[source_id], format='docx', summary_level=2,
                       exercises=False, review_mode='express', model=selected['model'], reasoning_effort=selected['effort'])
    job_id = create_job(project['id'], 'generate', value.model_dump())
    started = time.perf_counter()
    try:
        await _generate_job(job_id, value)
    finally:
        await bridge.close()
    job = one('SELECT * FROM jobs WHERE id=?', (job_id,))
    if job['status'] != 'completed': raise RuntimeError(job['error'])
    artifacts = many('SELECT * FROM artifacts')
    if len(artifacts) != 1 or artifacts[0]['format'] != 'docx':
        raise RuntimeError(f'Unexpected files: {[a["format"] for a in artifacts]}')
    document = Document(artifacts[0]['path'])
    paragraphs = [p for p in document.paragraphs if p.text.strip()]
    quotes = [p.text for p in paragraphs if p.style.name == 'Source Quote']
    if not quotes: raise RuntimeError('没有区分原文引用')
    original = re.sub(r'\s+', '', ORIGINAL)
    for quote in quotes:
        value = re.sub(r'\[[^\]\n]+[｜|][^\]\n]+\]', '', quote)
        value = re.sub(r'^(?:原文引用|原文)[：:]\s*', '', value)
        for part in re.split(r'\[…\]|\[\.\.\.\]|…|\.{3}', value):
            normalized = re.sub(r'\s+', '', part).strip('“”「」"')
            if len(normalized) > 3 and normalized not in original:
                raise RuntimeError(f'引用与原文不一致：{part}')
    text = '\n'.join(p.text for p in paragraphs)
    if not all(word in text for word in ('福柯', '系统性总结')): raise RuntimeError('Missing terminology or summary')
    if not any(word in text for word in ('延伸', '补充背景', '相关概念')): raise RuntimeError('Missing relevant extension')
    if re.search(r'F\s*=\s*ma|物理图景|磁通量|课后练习|配套习题', text): raise RuntimeError('Inappropriate physics or assignments')
    if any(path.suffix != '.docx' for path in artifacts_dir().iterdir()): raise RuntimeError('Unexpected auxiliary files')
    if not any('系统性总结' in p.text for p in paragraphs[-8:]): raise RuntimeError('Summary is not at the end')
    if sum(p.text.strip() == '系统性总结' for p in paragraphs) != 1:
        raise RuntimeError('Duplicate systematic summaries')
    print(json.dumps({'ok': True, 'model': selected['model'], 'seconds': round(time.perf_counter()-started, 1),
                      'path': artifacts[0]['path'], 'quote_count': len(quotes), 'characters': len(text),
                      'artifact_count': len(artifacts)}, ensure_ascii=False))


if __name__ == '__main__': asyncio.run(main())
