"""Reuse a completed lecture body for local export, without a model client."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from .db import connect, j, many, now, one, uid, unj, update_job
from .generation_control import control_for
from .navigation import require_project
from .scheduling import run_owned_io, run_local

FORMATS = ('docx', 'pdf', 'pptx', 'mm', 'md', 'txt')
LEGACY_PREFIX = '已生成讲解文档：\n\n'


def save(job_id, project_id, title, content, source_ids, metadata, *, legacy=False):
    from .document_render import validate_document_text
    validate_document_text(content)
    require_project(project_id)
    digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
    with connect() as db:
        job = db.execute('SELECT project_id,kind,status FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not job or job['project_id'] != project_id or job['kind'] != 'generate' or (job['status'] == 'cancelled' and not legacy):
            raise ValueError('讲解任务已取消或归属不匹配，未保存待导出正文')
        previous = db.execute('SELECT content_sha256 FROM document_snapshots WHERE job_id=?',(job_id,)).fetchone()
        if previous and previous['content_sha256'] != digest:
            raise ValueError('该任务已保存另一版讲解正文，请新建生成任务，避免更改旧成果的导出依据')
        db.execute('INSERT OR IGNORE INTO document_snapshots '
                   '(job_id,project_id,title,content,content_sha256,source_ids_json,metadata_json,created_at) VALUES (?,?,?,?,?,?,?,?)',
                   (job_id, project_id, title, content, digest, j(source_ids), j(metadata), now()))
    return job_id


def available(rows, artifact=False, project_id=None):
    """Batch capabilities, never bring large lecture bodies into list polling."""
    roots = {}
    for row in rows:
        if artifact:
            meta = unj(row['metadata_json'], {})
            ident = meta.get('document_snapshot_id') or meta.get('generation_job_id')
            if row['kind'] != 'explanation': continue
        else:
            if row['kind'] != 'generate' or row['status'] == 'cancelled': continue
            ident = row['id']
        if ident: roots[row['id']] = ident
    if not roots: return {}
    found = set()
    # Keep placeholder counts bounded on legacy SQLite builds.
    identifiers = list(set(roots.values()))
    for start in range(0, len(identifiers), 400):
        batch = identifiers[start:start+400];marks = ','.join('?' for _ in batch)
        owner = ' AND project_id=?' if project_id else ''
        found.update(r['job_id'] for r in many('SELECT job_id FROM document_snapshots WHERE job_id IN ('+marks+')'+owner,
            (*batch,project_id) if project_id else batch))
        if artifact:
            found.update(r['job_id'] for r in many('SELECT d.job_id FROM generation_dialogue_outputs d '
                'JOIN messages m ON m.id=d.message_id JOIN conversations c ON c.id=m.conversation_id '
                'WHERE d.job_id IN ('+marks+') AND m.content LIKE ?'+(' AND c.project_id=?' if project_id else ''),
                (*batch, LEGACY_PREFIX+'%',project_id) if project_id else (*batch, LEGACY_PREFIX+'%')))
    return {ident: list(FORMATS) for ident, root in roots.items() if root in found}


def resolve(project_id, ident, artifact=False):
    require_project(project_id)
    origin = one('SELECT * FROM '+('artifacts' if artifact else 'jobs')+' WHERE id=? AND project_id=?', (ident, project_id))
    if not origin: raise LookupError('成果或任务不属于当前项目，或已经删除')
    if artifact:
        if origin['kind'] != 'explanation': raise ValueError('此入口只复用讲解正文，不读取私有习题答案')
        meta = unj(origin['metadata_json'], {})
        root = meta.get('document_snapshot_id') or meta.get('generation_job_id')
    else:
        if origin['kind'] != 'generate' or origin['status'] == 'cancelled' or one('SELECT 1 FROM deleted_job_records WHERE job_id=?', (ident,)):
            raise ValueError('这个任务没有可发布的讲解正文')
        root = ident;meta = {}
    draft = one('SELECT * FROM document_snapshots WHERE job_id=? AND project_id=?', (root, project_id))
    if not draft and artifact and root:
        # Old successful lectures have an exact canonical body in their own
        # generated public message. Do not OCR an exported file or guess TeX.
        old = one('SELECT m.content,j.source_ids_json FROM generation_dialogue_outputs d '
                  'JOIN messages m ON m.id=d.message_id JOIN artifacts j ON j.id=? '
                  'JOIN conversations c ON c.id=m.conversation_id '
                  'WHERE d.job_id=? AND j.project_id=? AND c.project_id=?', (ident,root,project_id,project_id))
        if old and old['content'].startswith(LEGACY_PREFIX):
            save(root,project_id,origin['title'],old['content'][len(LEGACY_PREFIX):],unj(old['source_ids_json'],[]),meta,legacy=True)
            draft = one('SELECT * FROM document_snapshots WHERE job_id=? AND project_id=?', (root,project_id))
    if not draft: raise ValueError('没有保存完整讲解正文；旧成果缺少生成记录时需重新生成')
    return draft, origin, meta


def launch(project_id, ident, fmt, request_id, artifact=False):
    if fmt not in FORMATS: raise ValueError('此入口支持 Word、PDF、PPT、思维导图、Markdown 和文本的直接排版')
    draft, origin, meta = resolve(project_id,ident,artifact)
    values = {'document_id':draft['job_id'], 'content_sha256':draft['content_sha256'], 'format':fmt,
              'title':origin['title'] if artifact else draft['title'], 'source_artifact_id':ident if artifact else None,
              'source_metadata':meta}
    from .mobile_context import remote_device
    payload = {'workflow_version':1, 'values':values, 'export_request_id':request_id,
               'conversation_id':(meta or unj(draft['metadata_json'],{})).get('conversation_id')}
    if remote_device.get(): payload['_mobile_device_id'] = remote_device.get()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute("SELECT id,payload_json FROM jobs WHERE project_id=? AND kind='export' "
                           "AND json_extract(payload_json,'$.export_request_id')=?", (project_id,request_id)).fetchone()
        if prior:
            if unj(prior['payload_json'])['values'] != values: raise ValueError('同一次另存请求的格式或正文已改变，请重新发起')
            return prior['id'], True
        # Double clicks with different request IDs still share an active export.
        prior = db.execute("SELECT id,payload_json FROM jobs WHERE project_id=? AND kind='export' "
                           "AND status IN ('queued','running','pausing','paused')", (project_id,)).fetchall()
        for row in prior:
            if unj(row['payload_json'])['values'] == values: return row['id'], True
        ident = uid();stamp = now()
        db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)', (ident,project_id,'export','queued',0,j(payload),'{}',None,stamp,stamp))
    return ident, False


def write_file(content, fmt, title, job_id):
    """Publish one complete local file atomically; discard failed partial files."""
    from .config import artifacts_dir
    from .exporters import export_document
    partial = artifacts_dir() / f'{job_id}-pending-{uid()}.{fmt}'
    target = artifacts_dir() / f'{job_id}-explanation.{fmt}'
    try:
        result = export_document(content,fmt,title,partial.name)
        result.replace(target)
        return target
    finally:
        partial.unlink(missing_ok=True)
        if (one('SELECT status FROM jobs WHERE id=?',(job_id,)) or {}).get('status')=='cancelled' and not one(
                "SELECT 1 FROM artifacts WHERE json_extract(metadata_json,'$.reexport_job_id')=?",(job_id,)):
            target.unlink(missing_ok=True)


def publish_lecture(draft):
    """A rescued layout joins its original chat once, without another AI call."""
    meta = unj(draft['metadata_json'],{});chat = meta.get('conversation_id')
    if meta.get('chat_export'):return
    if not chat: return
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM conversations WHERE id=? AND project_id=? AND NOT EXISTS '
                '(SELECT 1 FROM deleted_conversations WHERE conversation_id=conversations.id)',(chat,draft['project_id'])).fetchone(): return
        if not db.execute('SELECT 1 FROM generation_dialogue_outputs WHERE job_id=?',(draft['job_id'],)).fetchone():
            message_id = uid()
            db.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(message_id,chat,'assistant',LEGACY_PREFIX+draft['content'],now()))
            db.execute('INSERT INTO generation_dialogue_outputs VALUES (?,?,?)',(draft['job_id'],chat,message_id))
    from .lesson_feedback import ensure_questionnaire
    ensure_questionnaire(draft['job_id'])


async def run_job(job_id):
    from .deliverables import inspection
    from .server import add_artifact, artifact_download_name
    control = control_for(job_id);value = {}
    try:
        job = one('SELECT * FROM jobs WHERE id=?',(job_id,));value = unj(job['payload_json'])['values']
        await control.checkpoint()
        control.stage('读取已保存讲解正文 · 零新增模型请求',10,{'model_requests':0})
        draft = await run_owned_io(one,'SELECT * FROM document_snapshots WHERE job_id=? AND project_id=?',
                                   (value['document_id'],job['project_id']))
        if not draft or draft['content_sha256'] != value['content_sha256']:
            raise ValueError('保存的讲解版本已改变，未导出其他版本；请重新选择成果')
        require_project(job['project_id'])
        fmt = value['format'];title = value['title']
        control.stage('另存 '+fmt.upper()+' · 复用原讲解与来源',25)
        existing = one("SELECT * FROM artifacts WHERE project_id=? AND json_extract(metadata_json,'$.reexport_job_id')=?",
                       (job['project_id'],job_id))
        if existing:
            artifact = {key:existing[key] for key in ('id','title','kind','format')}
            artifact.update(download_url=f'/api/artifacts/{existing["id"]}/download',download_filename=artifact_download_name(existing))
        else:
            async def write():
                return str(await run_local('document_export',write_file,draft['content'],fmt,title,job_id,label='讲解本机排版'))
            path = Path(await control.step('local:export',[value['content_sha256'],fmt,title],write))
            if not path.is_file(): path = Path(await write())
            await control.checkpoint()
            control.stage('检查导出文件并加入本项目成果',85)
            delivery = await run_owned_io(inspection,path)
            metadata = unj(draft['metadata_json'],{}) | value['source_metadata']
            for key in ('delivery','download_filename','custom_name'): metadata.pop(key,None)
            metadata.update(document_snapshot_id=draft['job_id'], reexport_job_id=job_id,
                delivery=delivery, reexport={'model_requests':0,'content_sha256':draft['content_sha256'],
                                            'source_artifact_id':value['source_artifact_id'],
                                            'basis':'已公开导师回答' if metadata.get('chat_export') else '已保存的讲解正文'})
            if not metadata.get('chat_export'):metadata['generation_job_id']=draft['job_id']
            await control.checkpoint()
            artifact = add_artifact(job['project_id'],unj(draft['source_ids_json'],[]),'explanation',fmt,title,path,metadata)
        await control.checkpoint()
        publish_lecture(draft)
        update_job(job_id,'completed',100,{'stage':'另存完成 · 零新增模型请求','artifacts':[artifact],'model_requests':0})
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        from .task_retry import report_failure
        report_failure(exc)
        current = one('SELECT status FROM jobs WHERE id=?',(job_id,))
        if current and current['status'] != 'cancelled':
            update_job(job_id,'failed',100,{'stage':'排版未完成 · 已保存的讲解正文保留','model_requests':0},error=f'{type(exc).__name__}: {exc}')
    finally:
        current = one('SELECT status FROM jobs WHERE id=?',(job_id,))
        if value.get('format') in FORMATS and current and current['status'] in ('cancelled','failed') and not one(
                "SELECT 1 FROM artifacts WHERE json_extract(metadata_json,'$.reexport_job_id')=?",(job_id,)):
            from .config import artifacts_dir
            # Paused or interrupted jobs retain their cached file for resumption.
            (artifacts_dir()/f'{job_id}-explanation.{value["format"]}').unlink(missing_ok=True)
        control.finish()
