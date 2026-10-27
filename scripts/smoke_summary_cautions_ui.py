"""Desktop/paired HTTPS phone fixture for the shared summary evidence panel."""
import asyncio
import os
from pathlib import Path
import sys


folder = Path(__file__).resolve().parents[1] / 'build' / sys.argv[1]
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(folder / 'isolated-model')
from scripts import smoke_library_ui as fixture
from studyforge.db import execute, j, now, uid
from studyforge.exporters import export_document
from studyforge.teaching import summary_context

fixture.enable_semantic(False)
source, original = uid(), folder / '条件.txt'
original.write_text('尾部估计只适用于n>N。', encoding='utf-8')
execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
    (source, fixture.p['id'], original.name, '.txt', str(original), 'ready', now()))
chapters = ['# 第一部分\n'+'已写解释。'*6000+'\n## 系统性总结\n条件。\n## 待核实事项\n'+
    'LONG_CAUTION：需要核实的条件。'*100,
    '# 第二部分\n'+'已写解释。'*6000+'\n## 系统性总结\n联系。\n## 待核实事项\n- SHORT_CAUTION：不能省略尾部范围。']
plan = summary_context(chapters, budget=1200)
assert (plan['caution_sections_total'], plan['caution_sections_included'], plan['caution_sections_omitted']) == (2, 1, 1)
path = export_document('# 核查衔接验收\n原文范围仍需核对。\n\n## 系统性总结\n候选总结。', 'docx', '核查衔接验收', 'summary-cautions-ui.docx')
meta = {'conversation_id': fixture.c['id'], 'model': 'controlled-fixture',
    'lesson_quality': dict({f'summary_{key}': plan[key] for key in
        ('caution_sections_total', 'caution_sections_included', 'caution_sections_omitted', 'unresolved_sections_total')},
        chapter_count=2, parse_cache_hits=0, citation_count=0, matched_citations=0, quote_count=0, matched_quotes=0,
        warning_count=0, warnings=[], note='仅核对本次合成输入记录，不确认讲解正确。'),
    'source_reading': [{'source_id': source, 'name': original.name, 'characters': 16, 'segments': 1, 'method': 'text'}]}
artifact = fixture.server.add_artifact(fixture.p['id'], [source], 'explanation', 'docx', '核查衔接验收', path, meta)
fixture.case.update(artifact_id=artifact['id'], process_id=os.getpid())


if __name__ == '__main__': asyncio.run(fixture.main())
