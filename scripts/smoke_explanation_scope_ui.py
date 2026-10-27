"""Actual desktop/paired-phone controls with an isolated native model transport."""
import asyncio
import json
import os
from pathlib import Path
import sys

folder = Path(__file__).resolve().parents[1] / 'build' / sys.argv[1]
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(folder / 'isolated-model')
from scripts import smoke_library_ui as fixture
from studyforge.db import execute, j, many, now, uid

fixture.enable_semantic(False)
source = uid()
path = folder / '论证原文.txt'
original = 'FULL_ORIGINAL：极限定义中的N可依赖ε，但选定后必须对所有n>N有效。\n第二节的有界性在这次请求范围以外。'
path.write_text(original, encoding='utf-8')
execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
        (source, fixture.p['id'], path.name, '.txt', str(path), j([{'locator': '预览', 'text': 'PREVIEW_IS_NOT_THE_ORIGINAL'}]), 'ready', now()))
fixture.conversations.update(fixture.c['id'], fixture.p['id'], {'source_ids': [source], 'review_mode': 'fast',
    'explanation_style': 'balanced', 'learning_mode': 'deep'})
execute('INSERT INTO messages VALUES (?,?,?,?,?)', (uid(), fixture.c['id'], 'user',
        'EARLIER_SCOPE：我不懂为什么需要统一门槛。请不布置习题。', now()))
fixture.case.update(source_id=source, original=original, process_id=os.getpid())


async def respond(request):
    if request.method == 'GET': return await fixture.respond(request)
    body = json.loads(request.content)
    fixture.calls.append(body)
    system, user = body['messages'][0]['content'], body['messages'][-1]['content']
    if body.get('response_format', {}).get('type') == 'json_object':
        bad = 'DRAFT_NEEDS_FIX' in user
        answer = j({'passed': not bad, 'issues': [{'location': '正文', 'problem': '遗漏所有后续项这一条件。'}] if bad else []})
    elif '只输出简洁的阅读笔记' in system:
        answer = '## 阅读笔记\n原文区分一个统一门槛与逐项门槛。[来源：论证原文.txt｜行 1-2]'
    elif '根据核查报告修订讲解' in system:
        answer = '# 统一门槛的修订讲解\n\n取定N后，需要所有n>N同时满足所需条件。[来源：论证原文.txt｜行 1]\n\n## 系统性总结\n先选统一门槛，再验证全部后续项。'
    elif 'PHONE_SCOPE' in user:
        answer = '# 统一门槛\n\nDRAFT_NEEDS_FIX：需要同一个门槛。\n\n## 系统性总结\n保证后续项。'
    else:
        answer = '# 为什么需要统一门槛\n\n同一个N要对每个n>N生效；逐项选择N(n)不能直接代替它。[来源：论证原文.txt｜行 1]\n\n## 系统性总结\n统一的N给全部后续项同一保证。'
    if body.get('stream'):
        return fixture.httpx.Response(200, text='data: ' + j({'choices': [{'delta': {'content': answer}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n')
    return fixture.httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', 'content': answer}, 'finish_reason': 'stop'}]})


fixture.httpx.AsyncClient = lambda *a, **kw: fixture.original(transport=fixture.httpx.MockTransport(respond))


@fixture.server.app.get('/__scope_test__/outputs')
def outputs():
    return {'documents': many('SELECT job_id,content,metadata_json FROM document_snapshots'),
            'exercise_count': len(many('SELECT id FROM exercise_sets'))}


mount = next(route for route in fixture.server.app.routes if getattr(route, 'name', None) == 'web')
fixture.server.app.router.routes.remove(mount)
fixture.server.app.router.routes.append(mount)
if __name__ == '__main__': asyncio.run(fixture.main())
