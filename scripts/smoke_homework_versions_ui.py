"""Synthetic original-version records behind actual desktop and HTTPS phone UI."""
import asyncio
import json
from pathlib import Path
from scripts import smoke_homework_reader_ui as base
from studyforge import homework
from studyforge.db import execute,j,one,unj
from studyforge.exporters import export_document
from tests.test_homework_context import case

fixture=base.fixture
records={}
for name,status in [('completed','completed'),('pending','awaiting_causes'),('unavailable','completed')]:
    project,chat,attempt,worksheet,ids=case(Path(base.source.folder),project=base.source.project,
        chat=base.source.chat,status=status,feedback=status=='completed')
    row=homework.get_attempt(attempt)
    analysis=unj(row['analysis_json'])
    if status=='awaiting_causes':
        analysis['items'][1].update(confidence='uncertain',clarification='你当时怎样进行这一步加法？')
        execute('UPDATE homework_attempts SET analysis_json=? WHERE id=?',(j(analysis),attempt))
    for kind,ident in ids.items():
        content=(homework.report_document(row,worksheet,unj(row['grade_json']),analysis) if kind=='grading' else
            '# 原题与答案解析\n\n## 第1题\n'+unj(worksheet['questions_json'])[0]['question']+
            '\n\n'+unj(worksheet['solutions_json'])[0]['solution']+
            '\n\n## 第2题\n计算2+3并说明步骤。\n\nREFERENCE_ADD：$2+3=5$。')
        path=export_document(content,'docx','原版本作业验收',attempt+'-'+kind+'.docx')
        execute('UPDATE artifacts SET path=? WHERE id=?',(str(path),ident))
    # Keep the accepted snapshot untouched, but replace current questions with
    # a one-question worksheet which must never appear beside these answers.
    execute('UPDATE exercise_sets SET questions_json=?,solutions_json=?,difficulty=4 WHERE id=?',
        (j([{'index':0,'topic':'新版话题','question':'NEW_QUESTION_MUST_NOT_MIX'}]),
         j([{'index':0,'solution':'NEW_REFERENCE_MUST_NOT_LEAK','rubric':'新评分'}]),worksheet['id']))
    if name=='unavailable':execute('UPDATE homework_attempts SET source_version=? WHERE id=?',('damaged',attempt))
    records[name]={'attempt':attempt,'worksheet':worksheet['id']}
fixture.case.update(version_records=records)

if __name__=='__main__':asyncio.run(fixture.main())
