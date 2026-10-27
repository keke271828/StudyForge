"""Real structure worker with source-matched math and isolated controlled transport."""
import asyncio,json
from scripts import smoke_library_ui as f
from studyforge import knowledge
from studyforge.db import create_job,execute,j,many,now,one,uid,unj,update_job
from studyforge.learning import source_fingerprint
from studyforge.materials import read_original_sources

f.enable_semantic(False);f.ai.save_settings({'library_reference_mode':'off','task_auto_retry':False})
f.server.discussion_completed=lambda *a:None
text='当质量 $m>0$ 不变时，合力满足 $F=ma$。因此 $a=F/m$，不能取 $m=0$。本段适用于经典质点动力学，且质量恒定。'
path=f.case_path.parent/'math.txt';path.write_text(text,encoding='utf-8');sid=uid()
execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
    (sid,f.p['id'],'公式与条件.txt','.txt',str(path),j([{'locator':'全文','text':text}]),'ready',now()))
records=read_original_sources(f.server.source_records([sid],f.p['id']));locator=records[0]['segments'][0]['locator']
rid=uid();execute('INSERT INTO reading_sessions VALUES (?,?,?,?,?,?,?,?,?,?)',(rid,f.p['id'],j([sid]),source_fingerprint(records),
    'deepseek','deepseek-flash','none',j([{'part':1,'text':'合成阅读记录，只用于流程验收，不评估学习掌握。'}]),j([r['read_manifest'] for r in records]),now()))
b=f.conversations.create(f.p['id'],'deepseek')
for chat in [f.c,b]:f.conversations.update(chat['id'],f.p['id'],{'source_ids':[sid],'model':'deepseek-flash','model_choice':'deepseek-flash','reasoning_effort':'none','reading_id':rid})
f.conversations.activate(f.c['id'])
paused_value=f.server.KnowledgeIn(project_id=f.p['id'],conversation_id=b['id'],source_ids=[sid],reading_id=rid,provider='deepseek',model='deepseek-flash',reasoning_effort='none')
paused=create_job(f.p['id'],'knowledge',paused_value.model_dump());update_job(paused,'paused',41,{'stage':'已保存本对话的整理进度'})
def evidence(quote):return {'source_id':sid,'locator':locator,'quote':quote}
graph={'concepts':[
    {'id':'force','name':'合力与加速度','domain':'力学','description':'质量恒定且 $m>0$ 时，$F=ma$ 给出合力和加速度的关系。<script>window.knowledgeUnsafe=true</script>',
     'basis':'source','evidence':[evidence('当质量 $m>0$ 不变时，合力满足 $F=ma$。')]},
    {'id':'division','name':'变形与适用条件','domain':'代数与力学','description':'从 $F=ma$ 到 $a=F/m$，要保留 $m>0$ 的条件。',
     'basis':'source','evidence':[evidence('因此 $a=F/m$，不能取 $m=0$。')]}],
    'relations':[{'from_id':'force','to_id':'division','kind':'supports','reason':'因为 $m>0$，两边可以同时除以 $m$，得到 $a=F/m$。',
     'boundary':'原文限定质量不变且 $m>0$，不能把 $m=0$ 代入分母。','basis':'source','evidence':[evidence('因此 $a=F/m$，不能取 $m=0$。')]}]}
async def respond(request):
    if request.method=='GET':return f.httpx.Response(200,json={'data':[{'id':'deepseek-flash'}]})
    payload=json.loads(request.content);f.calls.append(payload)
    assert '【资料知识结构整理】' in payload['messages'][0]['content'],'Only the structure request is expected'
    return f.httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':j(graph)},'finish_reason':'stop'}]})
f.respond=respond
f.case.update(second_chat=b['id'],source_id=sid,reading_id=rid,paused_knowledge=paused)

@f.server.app.get('/__knowledge_ui__/state')
def state():
    return {'model_calls':len(f.calls),'read_jobs':len(many("SELECT id FROM jobs WHERE kind='read'")),
        'maps':len(many('SELECT id FROM knowledge_maps')),'knowledge_jobs':many("SELECT id,status,payload_json FROM jobs WHERE kind='knowledge'"),
        'messages':len(many('SELECT id FROM messages')),'mastery':len(many('SELECT * FROM mastery')),
        'exercises':len(many('SELECT id FROM exercise_sets'))}
mount=next(r for r in f.server.app.routes if getattr(r,'name',None)=='web');f.server.app.router.routes.remove(mount);f.server.app.router.routes.append(mount)
if __name__=='__main__':asyncio.run(f.main())
