"""Real desktop and paired HTTPS phone follow-ups with an offline model transport."""
import asyncio
import json
import os
from pathlib import Path
import sys

folder = Path(__file__).resolve().parents[1] / 'build' / sys.argv[1]
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(folder/'isolated-model')
from scripts import smoke_library_ui as fixture
from tests.test_homework_context import case
from studyforge import homework
from studyforge.db import execute, j, many, one
from studyforge.exporters import export_document

fixture.enable_semantic(False)
project, chat, attempt, worksheet, ids = case(folder, project=fixture.p, chat=fixture.c)
row = homework.get_attempt(attempt)
path = export_document(homework.report_document(row, worksheet, json.loads(row['grade_json']), json.loads(row['analysis_json'])),
                       'docx', '按题继续学习', 'homework-followup-ui.docx')
execute('UPDATE artifacts SET path=? WHERE id=?', (str(path), ids['grading']))
homework.notify(row, '批改与错题讲解已完成。\n\n[下载反馈](/api/artifacts/'+ids['grading']+'/download)')


async def respond(request):
    if request.method == 'GET': return fixture.httpx.Response(200, json={'data': [{'id': 'deepseek-flash'}]})
    body = json.loads(request.content); fixture.calls.append(body)
    messages = body['messages']
    if messages[-1]['role'] == 'tool':
        tool = json.loads(messages[-1]['content'])
        assert 'FEEDBACK_ADD' in tool['text'] and 'FEEDBACK_GAUSS' not in tool['text']
        delta = {'content': '你原来写的是 $2+3=4$。从2连续加三个1，依次得到3、4、5，所以 $2+3=5$。'
                 '\n\n用逆运算检查：$5-3=2$，恢复了原来的2；$4-3=1$，没有恢复。这个核对只检查该步加法，不代表其他题也正确。'}
        reason = 'stop'
    elif attempt in messages[0]['content']:
        delta = {'tool_calls': [{'index': 0, 'id': 'feedback-'+str(len(fixture.calls)), 'type': 'function',
            'function': {'name': 'sf_read_homework_feedback', 'arguments': j({'attempt_id': attempt, 'question_number': 2})}}]}
        reason = 'tool_calls'
    else:
        delta = {'content': '本对话没有已关联的作业记录，请在原对话中继续问那道题。'}; reason = 'stop'
    return fixture.httpx.Response(200, text='data: '+j({'choices': [{'delta': delta, 'finish_reason': reason}]})+'\n\ndata: [DONE]\n\n')


fixture.respond = respond
fixture.case.update(homework_attempt_id=attempt, artifact_id=ids['grading'], process_id=os.getpid())

if __name__ == '__main__': asyncio.run(fixture.main())
