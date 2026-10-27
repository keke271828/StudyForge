"""Actual quotation boundaries and a result-only answer through the homework UI."""
import asyncio
import json
from scripts import smoke_homework_reader_ui as base
from studyforge import homework,server
from studyforge.db import execute,j,many,now,one,uid,unj
from studyforge.exporters import export_document
from tests.test_homework import Teacher

fixture=base.fixture
row=homework.get_attempt(base.source.attempt)
quote='2+3=4\n\n### 学生自己的笔记标题\n这仍是我的作答，不是导师补讲。'
answers=unj(row['answers_json']);answers[1]=quote
analysis=unj(row['analysis_json']);analysis['items'][1]['evidence']=[{'source':'answer','quote':quote}]
execute('UPDATE homework_attempts SET answers_json=?,analysis_json=? WHERE id=?',(j(answers),j(analysis),row['id']))
row=homework.get_attempt(row['id'])
path=export_document(homework.report_document(row,base.source.worksheet,unj(row['grade_json']),analysis),'docx','多行作答引用验收','evidence-reader.docx')
execute('UPDATE artifacts SET path=? WHERE id=?',(str(path),base.source.ids['grading']))
set_id=uid();worksheet=base.source.worksheet
execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
    (set_id,base.source.project['id'],'[]','只给结论的错因询问验收',worksheet['questions_json'],worksheet['solutions_json'],2,'assigned',now()))
teacher=Teacher(unknown=False)

async def respond(request):
    if request.method=='GET':return fixture.httpx.Response(200,json={'data':[{'id':'deepseek-flash'}]})
    body=json.loads(request.content);fixture.calls.append(body)
    result=await teacher.complete(body['messages'][0]['content'],body['messages'][-1]['content'])
    return fixture.httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':result},'finish_reason':'stop'}]})

fixture.respond=respond
fixture.case.update(evidence_worksheet=set_id)

@server.app.get('/__evidence__/state')
def evidence():
    attempt=one('SELECT * FROM homework_attempts WHERE exercise_set_id=?',(set_id,))
    if not attempt:return {'accepted':False}
    items=unj(attempt['analysis_json'],{}).get('items',[])
    return {'accepted':True,'attempt':attempt['id'],'status':attempt['status'],
        'first_confidence':items[0]['confidence'] if items else None,'first_cause':items[0]['cause'] if items else None,
        'feedback_registered':bool(attempt['feedback_artifact_id']),
        'error_insights':len(many("SELECT id FROM learning_insights WHERE kind='gap'")),
        'model_requests':len(fixture.calls)}

mount=next(route for route in server.app.routes if getattr(route,'name',None)=='web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)

if __name__=='__main__':asyncio.run(fixture.main())
