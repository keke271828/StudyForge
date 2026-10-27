"""Re-export saved audited content with the current renderer and note layout."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'build/teaching-speed-video-refined-20261010-1'
os.environ['STUDYFORGE_DATA_DIR'] = str(ROOT / 'build/teaching-speed-video-20261010-1/data')

from studyforge.db import many, one
from studyforge.exporters import export_docx
from studyforge.lesson_quality import citation_checks, mark_source_warnings
from studyforge.materials import read_original_sources
from studyforge.review import review_explanation
from studyforge.teaching import finish_explanation


async def main():
    review = json.loads((TARGET / 'acceptance-content-review.json').read_text(encoding='utf-8'))
    report = json.loads((TARGET / 'result.json').read_text(encoding='utf-8'))
    ids = json.loads(one('SELECT payload_json FROM jobs WHERE id=?', (report['job_id'],))['payload_json'])['source_ids']
    records = read_original_sources(many('SELECT * FROM sources WHERE id IN (' + ','.join('?' for _ in ids) + ')', ids))
    document = (TARGET / 'verified-lecture.md').read_text(encoding='utf-8')
    original_notes = mark_source_warnings('', review['source_checks']).strip()
    if document.count(original_notes) != 1: raise ValueError('未唯一定位引用核对附注')
    document = document.replace(original_notes, '', 1)

    class SavedAudit:
        async def complete(self, *args, **kwargs):
            # Replay an already obtained public audit response. No network or
            # model invocation occurs while formatting these same corrections.
            return json.dumps(review['reviews'][0], ensure_ascii=False)

    document, replayed = await review_explanation(SavedAudit(), '重放已保存核查', document,
        mode='fast', learning_mode='deep', explanation_style='clear')
    before = '所以 n 列最多有 n+1 条竖线。'
    after = '所以 n 列共有 n+1 个列边界位置（包括两侧外边界）；这是位置的数量，不是竖线条数的绝对上限。'
    if document.count(before) != 1: raise ValueError('未唯一定位列边界数量的表述')
    document = document.replace(before, after, 1)
    document = await finish_explanation(SavedAudit(), document, explanation_style='clear')
    checks = citation_checks(document, records)
    document = mark_source_warnings(document, checks)
    output = TARGET / 'LaTeX表格课程_验收复核版.docx'
    export_docx(document, 'LaTeX 表格课程：讲解与操作实例（验收复核版）', output)
    (TARGET / 'acceptance-lecture.md').write_text(document, encoding='utf-8')
    result = {'docx': str(output), 'original_sample_preserved': True,
              'model_prose_changed': True, 'additional_model_requests': 0,
              'replayed_audit': replayed, 'source_checks': checks,
              'manual_corrections': [{'before': before, 'after': after,
                  'reason': '区分边界位置数和可以重复画线的条数。'}],
              'note': '重放已取得的快速核查并采用新版排版；另有一处明确记录的人工验收修正。不是未经修改的自动输出。'}
    (TARGET / 'manual-qa.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'docx': str(output), 'warnings': checks['warning_count']}, ensure_ascii=False))


if __name__ == '__main__': asyncio.run(main())
