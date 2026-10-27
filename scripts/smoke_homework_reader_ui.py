"""Actual offline desktop and paired HTTPS gateway, with synthetic public work."""
import asyncio
import json
from pathlib import Path

from scripts import smoke_homework_followup_ui as source
from studyforge import homework
from studyforge.db import execute, j, one
from studyforge.exporters import export_document
from tests.test_homework_context import case

fixture = source.fixture
row = homework.get_attempt(source.attempt)
analysis = json.loads(row['analysis_json'])
analysis['items'][1]['explanation'] = ('从 $2$ 开始依次加三个 $1$，得到 $3,4,5$，所以 $2+3=5$。'
    '\n\n为什么可以反过来检查？加上 $3$ 与减去 $3$ 互相抵消，所以正确结果应当满足 $5-3=2$。'
    '你写的 $4$ 则满足 $4-3=1$，没有恢复原来的 $2$，可以据此定位这一步加法。')
# Exercise incremental display using explicitly synthetic, repeated material.
analysis['items'][0]['explanation'] += '\n\n' + ('这是长记录窗口的合成滚动样例，不是模型生成的教学质量样本。\n\n'*650)
execute('UPDATE homework_attempts SET analysis_json=? WHERE id=?', (j(analysis), source.attempt))
row = homework.get_attempt(source.attempt)
path = export_document(homework.report_document(row, source.worksheet, json.loads(row['grade_json']), analysis),
                       'docx', '按题回看合成验收', 'homework-reader.docx')
execute('UPDATE artifacts SET path=? WHERE id=?', (str(path), source.ids['grading']))
_, _, pending, _, _ = case(Path(source.folder), project=source.project, chat=source.chat,
                           status='awaiting_causes', feedback=False)
fixture.case.update(reader_pending_attempt=pending)

if __name__ == '__main__': asyncio.run(fixture.main())
