"""Native HTTP requests expose AI-heading/source-range confusion; no cloud AI."""
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'build/lesson-source-request-20261021' / sys.argv[1]
if (FOLDER / 'results.json').exists(): raise SystemExit('Preserve previous phase.')
FOLDER.mkdir(parents=True, exist_ok=True)
os.environ['STUDYFORGE_DATA_DIR'] = str(FOLDER / 'data')
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(FOLDER / 'isolated-model')

import fitz
import httpx
from fastapi.testclient import TestClient
from studyforge import ai, conversations, lesson_feedback, server
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid

ai.save_settings({'background_learning_enabled':False,'agent_tools_enabled':False,'agent_network_enabled':False,'library_reference_mode':'off'})
ai.get_secret = lambda key:'controlled-only-key'
native = httpx.AsyncClient
requests = []


def respond(request):
    payload = json.loads(request.content)
    requests.append(payload)
    answer = '这是用于检查资料输入范围的受控回复，不代表模型已经核实了证明。'
    return httpx.Response(200, text='data: ' + j({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]}) + '\n\ndata: [DONE]\n\n')


httpx.AsyncClient = lambda *args, **kwargs:native(transport=httpx.MockTransport(respond))
api = TestClient(server.app)
project = create_project('原文范围复现（隔离夹具）')
source = FOLDER / 'source.pdf'
with fitz.open() as document:
    for label in ('SOURCE_FIRST_PAGE_ASSUMPTIONS', 'SOURCE_SECOND_PAGE_CONCLUSION'):
        page = document.new_page()
        page.insert_text((50, 80), label + ': This original textbook page has enough text for extraction without OCR.')
    document.save(source)
CASES = [
    ('chapter', '# 第2章的讲解', 'ready', '请核对这段解释，不出题。'),
    ('page', '# 第2页的讲解', 'ready', '请核对这个解释，不出题。'),
    ('stored_page', '# 第2页的讲解', 'stored', '请核对这个解释，不出题。'),
    ('explicit_pages', '# 第1章的讲解', 'ready', '只核对原PDF第2页，解释结论的条件，不出题。'),
    ('explicit_excerpt', '# 第1章的讲解', 'ready', '只看这段选中文字，不读取其他段落；我稍后粘贴原文。'),
]
rows = []
for ident, heading, status, question in CASES:
    chat = conversations.create(project['id'], 'deepseek', 'fixture-model')
    sid = uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (sid,project['id'],'原资料_'+ident+'.pdf','.pdf',str(source),status,now()))
    job = create_job(project['id'],'generate',{'source_ids':[sid],'conversation_id':chat['id'],'review_mode':'express'})
    lesson = heading + '\n\n这里是需要核对的旧AI解释，不是原PDF页码指令。'
    path = FOLDER / (ident + '.md'); path.write_text(lesson,encoding='utf-8')
    artifact = server.add_artifact(project['id'],[sid],'explanation','md',heading[2:],path,{'generation_job_id':job,'conversation_id':chat['id']})
    message = uid()
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(message,chat['id'],'assistant','已生成讲解文档：\n\n'+lesson,now()))
    execute('INSERT INTO generation_dialogue_outputs VALUES (?,?,?)',(job,chat['id'],message))
    execute("UPDATE jobs SET status='completed' WHERE id=?",(job,))
    root = lesson_feedback.ensure_questionnaire(job)
    section = api.get('/api/lesson-feedback/'+root['id']+'/sections').json()['items'][0]
    submitted = api.post('/api/lesson-feedback/'+root['id']+'/submit',json={'difficulties':['content_accuracy'],
        'other_text':question,'focus_section_id':section['id']})
    assert submitted.status_code == 200, submitted.text
    start = len(requests)
    response = api.post('/api/lesson-feedback/'+root['id']+'/followup')
    assert response.status_code == 200 and '"error"' not in response.text, response.text
    assert len(requests) == start + 1
    body = requests[-1]
    system = body['messages'][0]['content']
    record = {'case':ident,'ai_heading':heading,'source_status':status,'student_question':question,
        'first_page_in_system':'SOURCE_FIRST_PAGE_ASSUMPTIONS' in system,
        'second_page_in_system':'SOURCE_SECOND_PAGE_CONCLUSION' in system,
        'waiting_for_scope':'本次尚未读取正文' in system,'native_model_requests':1,
        'public_question':body['messages'][-1]['content']}
    (FOLDER/(ident+'-request.json')).write_text(j(body),encoding='utf-8')
    rows.append(record)
assert not many('SELECT * FROM learning_events') and not many('SELECT * FROM learning_insights')
result = {'phase':sys.argv[1],'cases':rows,'controlled_requests':len(requests),'external_model_requests':0,
          'learning_events':0,'automatic_exercises':len(many('SELECT * FROM exercise_sets'))}
(FOLDER/'results.json').write_text(j(result),encoding='utf-8')
print(j(result))
