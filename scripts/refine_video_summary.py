"""One recorded whole-lesson summary call using the final teaching bodies."""
from __future__ import annotations
import asyncio
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'build/teaching-speed-video-refined-20261010-1'
os.environ['STUDYFORGE_DATA_DIR'] = str(ROOT / 'build/teaching-speed-video-20261010-1/data')

from studyforge.ai import DeepSeekClient
from studyforge.exporters import export_docx
from studyforge.teaching import finish_explanation, summary_section


async def main():
    original = (TARGET / 'acceptance-lecture.md').read_text(encoding='utf-8')
    span = summary_section(original)
    if not span or original[span[1]:].strip(): raise ValueError('未唯一定位末尾全文总结')
    body = original[:span[0]].rstrip()
    client = DeepSeekClient('deepseek-flash')
    class Recorder:
        async def complete(self, system, user):
            raw = await client.complete(system, user)
            (TARGET / 'summary-model-response.md').write_text(raw, encoding='utf-8')
            return raw
    started = time.perf_counter()
    try:
        document = await finish_explanation(Recorder(), body, chapters=[body], learning_mode='deep', explanation_style='clear')
    finally:
        await client.close()
    summary = document[summary_section(document)[0]:]
    concepts = {key: key in summary for key in ('table', 'tabular', 'booktabs', 'hspace', 'multicolumn', 'multirow')}
    output = TARGET / 'LaTeX表格课程_验收复核版.docx'
    if not all(concepts.values()):
        (TARGET / 'summary-candidate.md').write_text(summary, encoding='utf-8')
        raise ValueError('整体总结未提及三个主要部分的核心命令，保留旧样例供检查')
    export_docx(document, 'LaTeX 表格课程：讲解与操作实例（验收复核版）', output)
    (TARGET / 'acceptance-lecture.md').write_text(document, encoding='utf-8')
    report = {'additional_summary_task': 1, 'seconds': round(time.perf_counter()-started, 2),
              'whole_teaching_body_characters': len(body), 'core_concepts_present': concepts,
              'semantic_validation': '关键词仅为范围提示；语义核对待检查实际生成内容。',
              'excluded_from_cold_speed_benchmark': True}
    (TARGET / 'summary-acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__': asyncio.run(main())
