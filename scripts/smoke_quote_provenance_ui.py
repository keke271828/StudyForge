"""Isolated source-quote cards and native chat, with paired HTTPS mobile."""
import asyncio
import json
import os
from pathlib import Path
import sys

folder = Path(__file__).resolve().parents[1] / 'build' / sys.argv[1]
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(folder / 'isolated-model')
from scripts import smoke_library_ui as fixture
from docx import Document
from studyforge import lesson_quality
from studyforge.db import execute, j, now, uid

fixture.enable_semantic(False)
fixture.case['process_id'] = os.getpid()
path = folder / 'source.txt'; path.write_text('令x=1。', encoding='utf-8'); sid = uid()
execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
        (sid, fixture.p['id'], path.name, '.txt', str(path), 'ready', now()))
records = [{'name': 'source.txt', 'segments': [{'locator': '行1', 'text': '令x=1。'}]}]
old = {'citation_count':1,'matched_citations':1,'quote_count':1,'matched_quotes':1,'warning_count':0,'warnings':[],'note':'旧记录'}
base = {'chapter_count':1,'parse_cache_hits':0,'extra_model_requests':0}
for label, check in [
    ('旧版', old),
    ('逐字', lesson_quality.citation_checks('> 令x=1。[source.txt｜行1]', records)),
    ('空白', lesson_quality.citation_checks('> 令 x = 1。[source.txt｜行1]', records)),
]:
    output = folder / ('card-' + label + '.docx')
    doc = Document(); doc.add_paragraph('保留来源的讲解样例'); doc.save(output)
    fixture.server.add_artifact(fixture.p['id'], [sid], 'explanation', 'docx', '引文状态：' + label, output,
        {'conversation_id':fixture.c['id'],'lesson_quality':dict(base,**check)})
fixture.case['source_id'] = sid


async def respond(request):
    if request.method == 'GET': return await fixture.respond(request)
    body = json.loads(request.content); fixture.calls.append(body)
    answer = '原资料那句话是：\n\n> 令 $x=1$。\n>\n> ——source.txt，行1\n\n这是一种公式排版写法。'
    return fixture.httpx.Response(200, text='data: ' + j({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]}) + '\n\ndata: [DONE]\n\n')


@fixture.server.app.get('/__quote_test__/state')
def state():
    return {'requests':len(fixture.calls)}


mount = next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount); fixture.server.app.router.routes.append(mount)
fixture.httpx.AsyncClient = lambda *a,**kw: fixture.original(transport=fixture.httpx.MockTransport(respond))
if __name__ == '__main__': asyncio.run(fixture.main())
