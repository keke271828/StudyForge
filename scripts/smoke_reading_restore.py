"""Isolated real reading worker, held at a controlled checkpoint during UI switches."""
import asyncio
from scripts import smoke_library_ui as f
from studyforge.db import create_job,execute,j,many,now,one,uid,unj,update_job

f.enable_semantic(False)
f.ai.save_settings({'library_reference_mode':'off','task_auto_retry':False})
f.server.discussion_completed=lambda *a:None
path=f.case_path.parent/'reading.txt'
path.write_text('数域对加减乘除封闭，但除数不能为零。该条件来自除法的定义，不能省略。',encoding='utf-8')
source=uid()
execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
    (source,f.p['id'],'阅读接续测试.txt','.txt',str(path),j([{'locator':'全文','text':path.read_text(encoding='utf-8')}]),'ready',now()))
d=f.conversations.create(f.p['id'],'deepseek')
for chat in [f.c,d]:f.conversations.update(chat['id'],f.p['id'],{'source_ids':[source],'model':'deepseek-flash','model_choice':'deepseek-flash','reasoning_effort':'none'})
f.conversations.activate(f.c['id'])
paused_value=f.server.ReadIn(project_id=f.p['id'],conversation_id=d['id'],source_ids=[source],provider='deepseek',model='deepseek-flash',reasoning_effort='none')
paused=create_job(f.p['id'],'read',paused_value.model_dump());update_job(paused,'paused',23,{'stage':'已保存通读进度'})
empty=f.conversations.create(f.p['id'],'deepseek')
set_id=uid()
execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(set_id,f.p['id'],j([source]),'来源对话的合成题单',
    j([{'index':0,'topic':'数域','statement':'除法需要什么条件？'}]),j([{'index':0,'answer':'除数非零','explanation':'来自定义','rubric':'说明条件'}]),1,'assigned',now()))
set_job=create_job(f.p['id'],'coding_generate',{'conversation_id':f.c['id'],'source_ids':[source]})
f.case.update(restore_chat=d['id'],empty_chat=empty['id'],paused_job=paused,source_id=source,routing_job=set_job,routing_set=set_id)
gate=asyncio.Event();starts=[]
original=f.server._read_job
async def held_read(ident,value):
    starts.append(ident)
    if value.conversation_id==f.c['id']:
        update_job(ident,'running',37,{'stage':'正在读取所选资料（合成等待点）'})
        await gate.wait()
    await original(ident,value)
f.server._read_job=held_read

@f.server.app.get('/__reading_ui__/state')
def state():
    return {'starts':starts,'model_calls':len(f.calls),'readings':len(many('SELECT id FROM reading_sessions')),
        'jobs':[{**row,'result':unj(row.pop('result_json'))} for row in many('SELECT id,kind,status,progress,result_json FROM jobs')],
        'learning_events':len(many('SELECT * FROM learning_events')),'mastery':len(many('SELECT * FROM mastery'))}

@f.server.app.post('/__reading_ui__/release')
async def release():gate.set();return {'released':True}

@f.server.app.post('/__reading_ui__/complete-set')
def complete_set():update_job(set_job,'completed',100,{'output':{'id':set_id}});return {'saved':True}

mount=next(r for r in f.server.app.routes if getattr(r,'name',None)=='web')
f.server.app.router.routes.remove(mount);f.server.app.router.routes.append(mount)
if __name__=='__main__':asyncio.run(f.main())
