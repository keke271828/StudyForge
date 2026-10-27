"""Isolated desktop/paired-phone copy acceptance; synthetic files, no cloud calls."""
import asyncio
import io
import os
from pathlib import Path
import sys
from fastapi.responses import FileResponse
from starlette.datastructures import UploadFile

folder=Path(__file__).resolve().parents[1]/'build'/sys.argv[1]
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
from scripts import smoke_library_ui as f
from studyforge import library_worker
from studyforge.db import execute, many
from tests.test_homework_context import case

f.enable_semantic(False)
project,chat,attempt,worksheet,artifacts=case(folder,project=f.p,chat=f.c)
execute('UPDATE library_nodes SET confirmed=1,start_y=0,end_y=1 WHERE book_id=?',(f.b['id'],))
paused=library_worker.new_read_job(f.b['id'],[f.nodes[1]['id']],'deepseek','deepseek-flash','none')
execute("UPDATE library_jobs SET status='paused' WHERE id=?",(paused['id'],))
stored=asyncio.run(f.server.import_file(project_id=f.p['id'],file=UploadFile(io.BytesIO(f.path.read_bytes()),filename='只想读一页.pdf'),category_id=None,parse_immediately=False))
f.case.update(homework_attempt_id=attempt,exercise_set_id=worksheet['id'],stored_source_id=stored['source_id'],paused_job_id=paused['id'])

@f.server.app.get('/__copy_test__/before-library.js')
def before():return FileResponse(f.root/'build/ui-copy-audit-20261026-2/before/web/library.js',media_type='application/javascript')

@f.server.app.get('/__copy_test__/state')
def state():return {'model_requests':len(f.calls),'messages':len(many('SELECT id FROM messages')),
    'sources':many('SELECT id,status FROM sources'),'jobs':many('SELECT id,status FROM library_jobs')}

mount=next(route for route in f.server.app.routes if getattr(route,'name',None)=='web')
f.server.app.router.routes.remove(mount);f.server.app.router.routes.append(mount)
if __name__=='__main__':asyncio.run(f.main())
