"""Recheck real outputs after fixing weaknesses found by human inspection.

Run after smoke_proof_teaching.py with its isolated build directory as argument.
Never operates on the user's data directory or starts Codex.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
target = Path(sys.argv[1]).resolve()
if target.parent != (root/'build').resolve() or not target.name.startswith('proof-teaching-'):
    raise ValueError('只能读取 smoke_proof_teaching 创建的隔离验收目录')
if not (target/'data'/'studyforge.sqlite3').is_file():
    raise ValueError('请先完成证明教学真实验收')
os.environ['STUDYFORGE_DATA_DIR'] = str(target/'data')

from docx import Document
from studyforge import server
from studyforge.codex_bridge import CodexBridge
from studyforge.db import create_job, j, many, one

model = os.environ.get('STUDYFORGE_SMOKE_MODEL', 'deepseek-flash')
codex_attempts = []


async def followup(name, prompt):
    selected = one('SELECT * FROM sources WHERE name=?', (name,))
    conversation = one('SELECT * FROM conversations WHERE project_id=? AND source_ids_json=?',
                       (selected['project_id'], j([selected['id']])))
    started = time.perf_counter()
    response = await server.chat_stream(server.ChatIn(project_id=selected['project_id'], source_ids=[selected['id']],
        conversation_id=conversation['id'], provider='deepseek', model=model, text=prompt))
    events = [json.loads(item) async for item in response.body_iterator]
    errors = [event['value'] for event in events if event['type']=='error']
    if errors:
        raise RuntimeError(str(errors))
    reply = next(event['value'] for event in reversed(events) if event['type']=='replace')
    return selected, conversation, reply, round(time.perf_counter()-started, 1)


async def main():
    print('收紧后复验：两段简短导师回答，接着在同一数学对话生成简要 DOCX。', flush=True)
    noether, math = await asyncio.gather(
        followup('诺特证明草稿.txt', '请把刚才自由粒子的守恒量与电荷守恒分别简明讲清，约700字。'),
        followup('柯西证明草稿.txt', '请换用配方法重新讲透原文件里的不等式，约900字。'))
    for label, result in [('noether', noether), ('schwarz', math)]:
        (target/f'{label}-refined.md').write_text(result[2], encoding='utf-8')
    selected, conversation, reply, seconds = math
    print('导师短回答已完成，检查实际简要文档。', flush=True)
    value = server.GenerateIn(project_id=selected['project_id'], source_ids=[selected['id']],
        conversation_id=conversation['id'], provider='deepseek', model=model, format='docx',
        summary_level=1, exercises=False, review_mode='express', generation_quality='custom',
        instructions='只覆盖上述配方法的核心推导、为什么这样构造和等号条件，约1000字。')
    job = create_job(selected['project_id'], 'generate', value.model_dump())
    started = time.perf_counter()
    await server._generate_job(job, value)
    row = one('SELECT * FROM jobs WHERE id=?', (job,))
    if row['status']!='completed':
        raise RuntimeError(row['error'])
    artifact = next(row for row in many('SELECT * FROM artifacts')
                    if json.loads(row['metadata_json']).get('generation_job_id')==job)
    lecture = one('SELECT m.content FROM generation_dialogue_outputs g JOIN messages m ON m.id=g.message_id WHERE g.job_id=?', (job,))['content']
    (target/'schwarz-refined-lecture.md').write_text(lecture, encoding='utf-8')
    doc = Document(artifact['path'])
    meta = json.loads(artifact['metadata_json'])
    report = {'model': model, 'noether_seconds': noether[3], 'math_seconds': seconds,
        'generation_seconds': round(time.perf_counter()-started,1), 'docx': artifact['path'],
        'same_dialogue': meta['conversation_id']==conversation['id'] and meta['dialogue_model']==model,
        'summary_level': meta['summary_level'], 'no_independent_review': len(meta['reviews'])==1 and meta['reviews'][0]['passed'] is None,
        'word_equations': len(doc.element.xpath('.//m:oMath')), 'codex_disabled': not codex_attempts,
        'noether_clickable_research_citation': bool(re.search(r'\]\(https://',noether[2])),
        'mathematical_correctness_requires_human_check': True}
    (target/'refinement-result.json').write_text(j(report),encoding='utf-8')
    print(j(report),flush=True)
    assert report['same_dialogue'] and report['summary_level']==1 and report['no_independent_review']
    assert report['word_equations']>0 and report['codex_disabled']


async def forbidden(*args, **kwargs):
    codex_attempts.append(True)
    raise AssertionError('DeepSeek 独立教学验收禁止调用 Codex')


if __name__ == '__main__':
    with patch.object(CodexBridge, 'start', forbidden), patch.object(server.model_catalog, 'get_models', forbidden), \
         patch.object(server.model_catalog, 'validate_effort', forbidden):
        asyncio.run(main())
