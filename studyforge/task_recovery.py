"""Explicit retry of failed source-learning tasks using their immutable saved intent."""
from contextlib import asynccontextmanager
import asyncio
import hashlib
from weakref import WeakValueDictionary

from fastapi import HTTPException
from .db import connect,j,many,now,one,uid,unj
from . import task_retry

KINDS=frozenset({'generate','read','knowledge','export'})
REASONS=frozenset({'服务暂时异常或限流','网络连接中断或超时','模型返回空回复','模型返回格式不完整',
                  '模型响应未完成','网络或模型响应暂未完成'})
locks=WeakValueDictionary()


@asynccontextmanager
async def guard(job_id):
    lock=locks.setdefault(job_id,asyncio.Lock())
    async with lock:yield


def capabilities(rows):
    """One small batched projection. Never read full dialogue/lecture bodies for polling."""
    failed=[row for row in rows if row['status']=='failed']
    if not failed:return {}
    ids=[row['id'] for row in failed];facts={}
    for start in range(0,len(ids),300):
        batch=ids[start:start+300]
        values=many("""SELECT b.id,r.reason,r.state,
          EXISTS(SELECT 1 FROM removed_projects WHERE project_id=b.project_id) AS removed,
          EXISTS(SELECT 1 FROM deleted_job_records WHERE job_id=b.id) AS deleted,
          EXISTS(SELECT 1 FROM generation_steps s WHERE s.job_id=b.id AND s.step_key LIKE 'external-effect:%'
            AND NOT EXISTS(SELECT 1 FROM generation_steps c WHERE c.job_id=b.id AND c.step_key=substr(s.step_key,17))) AS unsafe,
          EXISTS(SELECT 1 FROM generation_steps s WHERE s.job_id=b.id AND length(s.step_key)=64)
            AND (NOT EXISTS(SELECT 1 FROM generation_steps s WHERE s.job_id=b.id AND s.step_key='source_fingerprint')
             OR NOT EXISTS(SELECT 1 FROM generation_steps s WHERE s.job_id=b.id AND s.step_key='source_content_fingerprint')) AS unpinned,
          (SELECT COUNT(*) FROM task_manual_retries WHERE job_id=b.id) AS count,
          CASE WHEN json_valid(b.payload_json) THEN CASE WHEN b.kind='export'
            THEN json_extract(b.payload_json,'$.workflow_version')=1 AND json_type(b.payload_json,'$.values')='object'
            ELSE json_extract(b.payload_json,'$.project_id')=b.project_id AND json_type(b.payload_json,'$.source_ids')='array'
              AND (b.kind!='knowledge' OR json_type(b.payload_json,'$.reading_id')='text') END ELSE 0 END AS intent_ok
          FROM jobs b LEFT JOIN task_retries r ON r.family='project' AND r.job_id=b.id
          WHERE b.id IN ("""+','.join('?' for _ in batch)+')',tuple(batch))
        facts.update({value['id']:value for value in values})
    from .job_control import active_jobs
    result={}
    for row in failed:
        f=facts.get(row['id'],{});reason=f.get('reason');available=False
        if f.get('deleted') or f.get('removed'):message='任务已删除或项目在回收站中，不能重试。'
        elif row['kind'] not in KINDS:message='这类任务请使用原作业或资料页面的恢复入口，保留原提交与评分。'
        elif not f.get('intent_ok'):message='旧任务缺少完整执行要求，请回原对话重新发起。'
        elif f.get('unsafe') or (reason and '可能已修改文件' in reason):message='未完成步骤可能已经修改文件，请先核对，不能直接重复执行。'
        elif f.get('unpinned') and row['kind']!='export':message='旧步骤缺少原资料的版本记录，请重新发起，避免混用旧内容。'
        elif active_jobs.get(row['id']) and not active_jobs[row['id']].done():message='上次任务正在收尾，请稍后刷新。'
        elif reason not in REASONS and not (not reason and task_retry.classify(row.get('error') or '')[0]):message='请先处理内容、配置或输入问题，再回原对话发起。'
        else:available=True;message='沿用原资料、模型和要求；核对版本后，只补做未完成的步骤。'
        result[row['id']]={'available':available,'reason':message,'manual_count':f.get('count',0)}
    return result


async def validate_originals(row,payload):
    from . import server
    from .learning import source_fingerprint,content_fingerprint
    saved={r['step_key']:r['response'] for r in many("SELECT step_key,response FROM generation_steps WHERE job_id=? AND step_key IN ('source_fingerprint','source_content_fingerprint')",(row['id'],))}
    if row['kind']=='export' and not saved:return
    if row['kind']=='generate':records=await server.generation_input_records(server.GenerateIn.model_validate(payload))
    else:records=await server.read_original_sources_async(await server.source_records_async(payload.get('source_ids') or [],row['project_id'],for_original=True))
    for key,actual in [('source_fingerprint',source_fingerprint(records)),('source_content_fingerprint',content_fingerprint(records))]:
        if key in saved and saved[key]!=actual:raise ValueError('原资料、页码范围或已识别内容已改变，不能混用旧步骤；请回原对话重新生成。')


def validate_intent(row,payload):
    from . import server
    if row['kind'] in ('generate','read','knowledge'):
        cls={'generate':server.GenerateIn,'read':server.ReadIn,'knowledge':server.KnowledgeIn}[row['kind']]
        cls.model_validate(payload)
    else:
        value=payload['values'];draft=one('SELECT content_sha256 FROM document_snapshots WHERE job_id=? AND project_id=?',(value['document_id'],row['project_id']))
        if not draft or draft['content_sha256']!=value['content_sha256']:raise ValueError('已保存讲解的版本已改变，请重新选择成果格式。')
    server.validate_task_conversation(payload.get('conversation_id'),row['project_id'])


async def retry(job_id,project_id,request_id):
    from . import server
    from .job_control import retry_operation,start_job
    from .generation_control import control_for
    async with guard(job_id):
        row=one('SELECT * FROM jobs WHERE id=? AND project_id=?',(job_id,project_id))
        if not row:raise HTTPException(404,'这个项目中没有该任务')
        if one('SELECT 1 FROM deleted_job_records WHERE job_id=?',(job_id,)) or one('SELECT 1 FROM removed_projects WHERE project_id=?',(project_id,)):
            raise HTTPException(409,'任务已删除或项目已移入回收站，不能重试')
        if one('SELECT 1 FROM task_manual_retries WHERE job_id=? AND request_id=?',(job_id,request_id)):
            return {'job_id':job_id,'status':row['status'],'reused':True}
        if row['status']!='failed':raise HTTPException(409,'只能重试已经失败的任务；请先查看当前进度。')
        info=capabilities([row])[job_id]
        if not info['available']:raise HTTPException(409,info['reason'])
        payload=unj(row['payload_json'],{})
        try:
            validate_intent(row,payload)
            await validate_originals(row,payload)
        except (ValueError,RuntimeError,KeyError) as exc:raise HTTPException(409,str(exc)) from exc
        # Validate first, then atomically fence deletion, changed intent and duplicate requests.
        retry_record=task_retry.public('project',job_id) or {}
        result=unj(row['result_json'],{});result.pop('pause_requested',None);result.pop('request_status',None)
        result.update(stage='接着原任务重试 · 已完成步骤保留',manual_retry_count=info['manual_count']+1)
        chat=payload.get('conversation_id');stamp=now()
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed=db.execute("""UPDATE jobs SET status='queued',progress=MIN(progress,95),result_json=?,error=NULL,updated_at=?
              WHERE id=? AND project_id=? AND status='failed' AND payload_json=? AND updated_at=?
              AND NOT EXISTS(SELECT 1 FROM deleted_job_records WHERE job_id=jobs.id)
              AND NOT EXISTS(SELECT 1 FROM removed_projects WHERE project_id=jobs.project_id)
              AND (? IS NULL OR EXISTS(SELECT 1 FROM conversations c WHERE c.id=? AND c.project_id=jobs.project_id
                 AND NOT EXISTS(SELECT 1 FROM deleted_conversations WHERE conversation_id=c.id)))""",
              (j(result),stamp,job_id,project_id,row['payload_json'],row['updated_at'],chat,chat))
            if changed.rowcount!=1:raise HTTPException(409,'任务、项目或对话状态已改变，请刷新后再查看。')
            db.execute('INSERT INTO task_manual_retries VALUES (?,?,?,?,?,?,?,?,?)',(uid(),job_id,request_id,
                hashlib.sha256(row['payload_json'].encode()).hexdigest(),hashlib.sha256((row['error'] or '').encode()).hexdigest(),
                retry_record.get('reason'),retry_record.get('retry_count',0),row['progress'],stamp))
            db.execute("UPDATE task_retries SET retry_count=0,state='queued',next_at=NULL,last_error=NULL,reason=NULL,updated_at=? WHERE family='project' AND job_id=?",(stamp,job_id))
        control_for(job_id)
        start_job(job_id,lambda:retry_operation(job_id))
        return {'job_id':job_id,'status':'queued','reused':False}
