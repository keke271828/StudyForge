"""One additional acceptance audit of a saved real-model proof sample.

The original fast-mode output is preserved. This explicitly recorded extra
check is QA of the sample, not a hidden extra request added to the product.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'build/teaching-speed-proof-20261010-2'
os.environ['STUDYFORGE_DATA_DIR'] = str(TARGET / 'data')

from studyforge.ai import DeepSeekClient, source_digest
from studyforge.db import many
from studyforge.exporters import export_docx
from studyforge.lesson_quality import citation_checks, mark_source_warnings
from studyforge.materials import read_original_sources
from studyforge.review import review_explanation
from studyforge.teaching import finish_explanation


async def main():
    original = json.loads((TARGET / 'result.json').read_text(encoding='utf-8'))
    review = original['outputs'][0]['metadata']['reviews'][0]
    if set(review['locally_corrected_issues']) != set(range(len(review['issues']))):
        raise ValueError('原始未解决的问题不得在复核前删除')
    old_notes = '## 待核实事项\n' + '\n'.join(
        f"- {item['location']}: {item['problem']}（已局部修正，尚未再次独立复核。）"
        for item in review['issues'])
    document = (TARGET / 'verified-lecture.md').read_text(encoding='utf-8')
    if document.count(old_notes) != 1:
        raise ValueError('无法唯一定位已修正问题的程序附注')
    document = document.replace(old_notes, '', 1)
    records = read_original_sources(many("SELECT * FROM sources WHERE kind='.txt'"))
    client = DeepSeekClient('deepseek-flash')
    started = time.perf_counter()
    try:
        digest, _ = await source_digest(client, records)
        document, reports = await review_explanation(client, digest, document, mode='fast',
            learning_mode='deep', explanation_style='balanced', output_language='zh')
        document = await finish_explanation(client, document, 'zh', learning_mode='deep',
                                            explanation_style='balanced')
    finally:
        await client.close()
    checks = citation_checks(document, records)
    document = mark_source_warnings(document, checks)
    path = TARGET / '极限唯一性_直观与专业并重_复核样例.docx'
    export_docx(document, path.stem, path)
    (TARGET / 'acceptance-lecture.md').write_text(document, encoding='utf-8')
    result = {'docx': str(path), 'additional_acceptance_audits': 1,
              'model_request_count_not_measured': True,
              'seconds': round(time.perf_counter() - started, 2), 'reports': reports,
              'source_checks': checks, 'original_sample_preserved': True,
              'note': '此为额外验收复核，不计入首次快速模式的速度或请求数。'}
    (TARGET / 'acceptance-review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
