"""One explicit additional content audit, separate from the timed video job."""
from __future__ import annotations
import asyncio
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'build/teaching-speed-video-refined-20261010-1'
DATA = ROOT / 'build/teaching-speed-video-20261010-1/data'
os.environ['STUDYFORGE_DATA_DIR'] = str(DATA)

from studyforge.ai import DeepSeekClient, source_digest
from studyforge.db import many, one
from studyforge.exporters import export_docx
from studyforge.lesson_quality import citation_checks, mark_source_warnings, expand_single_source_labels
from studyforge.materials import read_original_sources
from studyforge.review import review_explanation
from studyforge.teaching import finish_explanation


async def main():
    old = json.loads((TARGET / 'citation-recheck.json').read_text(encoding='utf-8'))['new_checks']
    result = json.loads((TARGET / 'result.json').read_text(encoding='utf-8'))
    ids = json.loads(one('SELECT payload_json FROM jobs WHERE id=?', (result['job_id'],))['payload_json'])['source_ids']
    records = read_original_sources(many('SELECT * FROM sources WHERE id IN (' + ','.join('?' for _ in ids) + ')', ids))
    document = (TARGET / 'verified-lecture.md').read_text(encoding='utf-8')
    notes = mark_source_warnings('', old).strip()
    if document.count(notes) != 1:
        raise ValueError('无法唯一定位原机械核对附注')
    document = document.replace(notes, '', 1)
    client = DeepSeekClient('deepseek-flash')
    started = time.perf_counter()
    try:
        digest, _ = await source_digest(client, records)
        document, reports = await review_explanation(client, digest, document, mode='fast',
            learning_mode='deep', explanation_style='clear', output_language='zh')
        document = await finish_explanation(client, document, 'zh', learning_mode='deep', explanation_style='clear')
    finally:
        await client.close()
    document, expanded = expand_single_source_labels(document, records)
    checks = citation_checks(document, records)
    checks['source_labels_expanded'] = expanded
    document = mark_source_warnings(document, checks)
    output = TARGET / 'LaTeX表格课程_额外快速核查版.docx'
    export_docx(document, output.stem, output)
    (TARGET / 'audited-lecture.md').write_text(document, encoding='utf-8')
    report = {'path': str(output), 'additional_acceptance_audits': 1,
              'seconds': round(time.perf_counter()-started, 2), 'reviews': reports,
              'source_checks': checks, 'original_sample_preserved': True,
              'excluded_from_cold_speed_benchmark': True}
    (TARGET / 'acceptance-content-review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__': asyncio.run(main())
