"""Four actual source-check replies; legacy extraction is test-process only."""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build' / sys.argv[1]
if (OUT / 'results.json').exists(): raise SystemExit('Preserve the previous experiment.')
OUT.mkdir(parents=True, exist_ok=True)
os.environ['STUDYFORGE_DATA_DIR'] = str(OUT / 'data')
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(OUT / 'isolated-model')

import fitz
from fastapi.testclient import TestClient
from studyforge import ai, conversations, lesson_feedback, server
from studyforge.db import create_job, create_project, execute, j, many, now, uid
from scripts.diagnose_deepseek_speed import traced_class

ai.save_settings({'api_connection_mode':'direct','background_learning_enabled':False,'agent_tools_enabled':False,
    'agent_network_enabled':False,'model_concurrency':2,'library_reference_mode':'off'})
if not ai.get_secret('DEEPSEEK_API_KEY'):
    (OUT / 'results.json').write_text(j({'status':'unavailable','reason':'configured_key_unavailable','requests':0}),encoding='utf-8')
    raise SystemExit('Configured DeepSeek key unavailable; no requests sent.')
BASE = traced_class()
clients = []


class Client(BASE):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        clients.append(self)

    def supports_tools(self): return False


server.DeepSeekClient = Client
original_request = lesson_feedback.source_request
legacy_chats = set()
lesson_feedback.source_request = lambda row:lesson_feedback.feedback_text(row) if row['conversation_id'] in legacy_chats else original_request(row)
CASES = [
    {'id':'injective','title':'平方函数的单射性与零边界',
     'pages':['The domain is [0, +infinity). All variables x and y below belong to this domain.',
              'Define f(x)=x^2. To prove injectivity, suppose f(x)=f(y); then (x-y)(x+y)=0. Hence x=y.'],
     'lecture':'# 第2页的讲解\n\n原文证明中，直接把x+y除掉就得到x=y，所以$f(x)=x^2$是单射。\n\n## 总结\n\n因为定义域内$x+y$始终大于0，约掉$x+y$总是合法。',
     'question':'这个把x+y约掉的步骤靠谱吗？请先对照原资料核对，再用直观与专业并重的方式解释为什么；不布置习题。'},
    {'id':'causal','title':'记笔记调查与因果结论',
     'pages':['Study design: 20000 students were surveyed once. Students chose whether to take notes. No random assignment. Prior achievement and motivation were not measured.',
              'Frequent note-takers had higher average grades; the difference was statistically significant.'],
     'lecture':'# 第2页的讲解\n\n样本达到两万人，而且差异显著，所以可以断定多记笔记让成绩提高，调查已经证明因果。\n\n## 总结\n\n统计显著排除了混杂因素。',
     'question':'这份讲解把观察到的成绩差说成记笔记的因果作用，还说显著排除了混杂。请对照原资料核对这两句话，再解释为什么；不要出题。'},
]
(OUT / 'inputs.json').write_text(j({'cases':CASES,'tools':False,'network_tools':False,
    'model':'deepseek-flash','effort':'high','note':'independent_single_samples_not_a_quality_ranking'}),encoding='utf-8')
project = create_project('讲解核对原文范围实测（隔离）')
api = TestClient(server.app)
results = []
for index, case in enumerate(CASES):
    source = OUT / (case['id'] + '.pdf')
    with fitz.open() as document:
        for content in case['pages']:
            page = document.new_page()
            # Keep each original condition readable with no clipping or OCR.
            page.insert_textbox(fitz.Rect(50,50,545,180),content,fontsize=11)
        document.save(source)
    for phase in (['legacy','fixed'] if index == 0 else ['fixed','legacy']):
        chat = conversations.create(project['id'],'deepseek','deepseek-flash','high')
        if phase == 'legacy': legacy_chats.add(chat['id'])
        sid = uid()
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (sid,project['id'],case['id']+'.pdf','.pdf',str(source),'ready',now()))
        job = create_job(project['id'],'generate',{'source_ids':[sid],'conversation_id':chat['id'],
            'learning_mode':'deep','explanation_style':'balanced','output_language':'zh'})
        path = OUT / (case['id']+'-'+phase+'-old-lecture.md');path.write_text(case['lecture'],encoding='utf-8')
        server.add_artifact(project['id'],[sid],'explanation','md',case['title'],path,{'generation_job_id':job,'conversation_id':chat['id']})
        mid = uid()
        execute('INSERT INTO messages VALUES (?,?,?,?,?)',(mid,chat['id'],'assistant','已生成讲解文档：\n\n'+case['lecture'],now()))
        execute('INSERT INTO generation_dialogue_outputs VALUES (?,?,?)',(job,chat['id'],mid))
        execute("UPDATE jobs SET status='completed' WHERE id=?",(job,))
        root = lesson_feedback.ensure_questionnaire(job)
        section = api.get('/api/lesson-feedback/'+root['id']+'/sections').json()['items'][0]
        submitted = api.post('/api/lesson-feedback/'+root['id']+'/submit',json={'difficulties':['content_accuracy'],
            'other_text':case['question'],'focus_section_id':section['id']})
        assert submitted.status_code == 200, submitted.text
        start, client_start = time.perf_counter(), len(clients)
        response = api.post('/api/lesson-feedback/'+root['id']+'/followup')
        from studyforge.db import one
        row = one('SELECT reply_status,reply_message_id,error FROM lesson_questionnaires WHERE id=?',(root['id'],))
        used = clients[client_start:]
        answer = one('SELECT content FROM messages WHERE id=?',(row['reply_message_id'],)) if row['reply_message_id'] else None
        metadata = {'case':case['id'],'phase':phase,'status':row['reply_status'],'seconds':round(time.perf_counter()-start,2),
                    'http_status':response.status_code,'model_requests':sum(len(client.traces) for client in used),
                    'http_attempts':[trace.public() for client in used for trace in client.traces],
                    'error':row['error']}
        (OUT/(case['id']+'-'+phase+'-requests.json')).write_text(j([body for client in used for body in client.request_bodies]),encoding='utf-8')
        if answer:
            target=case['id']+'-'+phase+'-answer.md'
            (OUT/target).write_text(answer['content'],encoding='utf-8');metadata['answer_file']=target
        results.append(metadata)
        (OUT/'results.json').write_text(j(results),encoding='utf-8')
        print(j({key:metadata[key] for key in ('case','phase','status','seconds','model_requests')}),flush=True)
assert not many('SELECT * FROM learning_events') and not many('SELECT * FROM exercise_sets')
