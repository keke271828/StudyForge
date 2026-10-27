"""Hold a real original-assembly thread; exercise the desktop and paired phone.

Only the fixture model response is mocked. Source loading, task control, native
client protocol, server, mobile pairing, DOCX exporter and renderers are real.
"""
import asyncio
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / 'build' / sys.argv[1]
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(CASE / 'isolated-model')
from scripts import smoke_library_ui as fixture
from studyforge import ai, conversations, server
from studyforge.db import execute, j, now, uid

fixture.enable_semantic(False)
other_chat = conversations.create(fixture.p['id'], 'deepseek')
conversations.activate(fixture.c['id'])
ident = uid()
path = fixture.case_path.parent / '完整原文.txt'
path.write_text('数域对加法、减法、乘法和除以非零元素的运算封闭。原文末尾条件：除数不能为零。', encoding='utf-8')
execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
        (ident, fixture.p['id'], path.name, '.txt', str(path),
         j([{'locator': '旧预览', 'text': '旧缓存不会代替完整原文件。' * 400000}]), 'ready', now()))
entered, release = threading.Event(), threading.Event()
original_assemble = ai._assemble_source_digest
def held_assembly(sources, working, include_ids):
    if any(source['id'] == ident for source in sources):
        entered.set()
        if not release.wait(60): raise RuntimeError('UI fixture failed to release the original-assembly thread')
    return original_assemble(sources, working, include_ids)
ai._assemble_source_digest = held_assembly

@server.app.post('/__preparation_test__/launch')
async def launch():
    return await server.generate(server.GenerateIn(project_id=fixture.p['id'], conversation_id=fixture.c['id'],
        source_ids=[ident], provider='deepseek', model='deepseek-flash', reasoning_effort='none',
        format='docx', review_mode='express', explanation_style='balanced'))

@server.app.get('/__preparation_test__/state')
def state(): return {'assembly_entered': entered.is_set(), 'released': release.is_set(), 'model_calls': len(fixture.calls)}

@server.app.post('/__preparation_test__/release')
def finish(): release.set();return state()

fixture.case.update(source_id=ident, second_conversation_id=other_chat['id'])
mount = next(route for route in server.app.routes if getattr(route, 'name', None) == 'web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
if __name__ == '__main__': asyncio.run(fixture.main())
