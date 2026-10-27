"""Synthetic submitted work and an unpublished cause questionnaire; zero AI."""
import asyncio
import json
from scripts import smoke_homework_reader_ui as base
from studyforge import homework
from studyforge.db import execute,j,now,one,uid
from studyforge.review_versions import assessment_basis

fixture=base.fixture
attempt=base.source.attempt
worksheet=base.source.worksheet
row=homework.get_attempt(attempt)
grade=json.loads(row['grade_json'])
reason=(r'**暂定定位**：\(\oint_S\mathbf E\cdot d\mathbf S=0\)约束整个闭合面的净通量，不能直接把它改写成\(\mathbf E=0\)。'
    '\n\n- 先区分整体积分与局部场。\n- 这些解释仍应对照题意和你的实际作答。')
next_step=r'核对每一步用到的条件，再看\(\mathbf E=E_0\hat z\)的非零常量场例子。'
quote=r'我把 \(Q_{\mathrm{内}}=0\) 直接当成处处场为零。'
grade.update(assessment_version=assessment_basis(worksheet),diagnostics=[{'index':0,'label':'不懂术语','status':'暂定诊断',
    'reason':reason,'next_step':next_step,'quote':quote,'kind':'terminology'}])
answers=json.loads(row['answers_json']);answers[0]=quote
execute('UPDATE homework_attempts SET grade_json=?,answers_json=? WHERE id=?',(j(grade),j(answers),attempt))
execute('INSERT INTO submissions VALUES (?,?,?,?,?,?,?)',(uid(),worksheet['id'],j(answers),j(grade),80,'{}',now()))
pending=fixture.case['reader_pending_attempt'];pending_row=homework.get_attempt(pending)
analysis=json.loads(pending_row['analysis_json'])
prompt=(r'你写到\(Q_{\mathrm{内}}=0\)。你当时怎样从\(\oint_S\mathbf E\cdot d\mathbf S=0\)想到\(\mathbf E=0\)？'
    '\n\n请说明**当时实际的思路**，仍不确定也可以写出卡住的一步。')
analysis['items'][0].update(confidence='uncertain',clarification=prompt)
execute('UPDATE homework_attempts SET analysis_json=?,answers_json=? WHERE id=?',
    (j(analysis),j([quote,'2+3=4']),pending))
fixture.case.update(math_worksheet_id=worksheet['id'],math_pending_id=pending,math_prompt=prompt,
    math_reason=reason,math_next_step=next_step,math_quote=quote)

if __name__=='__main__':asyncio.run(fixture.main())
