"""Real UI on isolated data with explicit synthetic failed jobs and HTTP responses."""
import asyncio
from fastapi.responses import JSONResponse,StreamingResponse
from scripts import smoke_ui_copy as base
from studyforge.db import create_job,execute,j,many

f=base.f
failures={
    'json':'JSONDecodeError: Expecting value: line 1 column 1 (char 0) api_key=sk-fixture-only-abcdefghijkl <img src=x onerror="window.errorInjected=1">',
    'exercise':'RuntimeError:习题修订后仍有实质问题:第1题:独立解题未通过',
    'connection':'ConnectError: certificate verify failed',
    'limit':"exceeded retry limit, last status: 429 Too Many Requests",
}
ids={}
for key,kind in [('json','generate'),('exercise','coding_generate')]:
    ident=create_job(f.p['id'],kind,{'conversation_id':f.c['id'],'source_ids':[],'provider':'deepseek','format':'docx'})
    execute("UPDATE jobs SET status='failed',progress=100,error=? WHERE id=?",(failures[key],ident))
    execute("UPDATE task_retries SET enabled=0,state='exhausted' WHERE family='project' AND job_id=?",(ident,));ids[key]=ident
execute("UPDATE library_jobs SET status='failed',progress=100,error=? WHERE id=?",(failures['connection'],base.paused['id']))
execute("UPDATE task_retries SET enabled=0,state='exhausted' WHERE family='library' AND job_id=?",(base.paused['id'],))
request_counts={'model_catalog':0,'stream':0}
provider='svc_'+'e'*32

@f.server.app.get('/api/providers/'+provider+'/models')
def model_catalog(mode: str='rate'):
    request_counts['model_catalog']+=1
    if mode=='auth':return JSONResponse({'detail':'invalid_api_key'},status_code=401)
    if mode=='locked':return JSONResponse({'detail':'完整提交前不开放答案解析'},status_code=403)
    return JSONResponse({'detail':failures['limit']},status_code=429)

@f.server.app.post('/__error_ui__/stream')
async def stream():
    request_counts['stream']+=1
    async def body():
        yield j({'type':'status','value':'等待导师回复…'})+'\n'
        yield j({'type':'error','value':failures['limit']})+'\n'
    return StreamingResponse(body(),media_type='application/x-ndjson')

@f.server.app.get('/__error_ui__/state')
def state():return {'requests':request_counts,'model_requests':len(f.calls),
    'jobs':many('SELECT id,status,progress,error FROM jobs ORDER BY id'),
    'book_jobs':many('SELECT id,status,error FROM library_jobs ORDER BY id'),
    'grades':many('SELECT id,grade_json,status FROM homework_attempts ORDER BY id'),
    'messages':len(many('SELECT id FROM messages')),'learning_events':len(many('SELECT id FROM learning_events'))}

# Exact fixture route must precede the production provider parameter route.
route=next(r for r in f.server.app.routes if getattr(r,'path',None)=='/api/providers/'+provider+'/models')
f.server.app.router.routes.remove(route);f.server.app.router.routes.insert(0,route)
mount=next(r for r in f.server.app.routes if getattr(r,'name',None)=='web');f.server.app.router.routes.remove(mount);f.server.app.router.routes.append(mount)
f.case.update(error_jobs=ids,book_error_job=base.paused['id'],error_provider=provider,failures=failures)
if __name__=='__main__':asyncio.run(f.main())
