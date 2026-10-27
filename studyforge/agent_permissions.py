"""Application tool permissions, single-operation approvals and reversible deletion."""
from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from pathlib import Path

from .config import data_dir
from .db import execute,one,many,j,unj,uid,now,connect

MODES = {'read_only','approval','full_access'}


def application_root():
    return Path(os.environ.get('STUDYFORGE_APPLICATION_ROOT') or
                (str(Path(sys.executable).parent.parent.parent) if getattr(sys,'frozen',False) else str(Path(__file__).resolve().parent.parent))).resolve()


def configuration(runtime=None):
    from .ai import settings
    from .mobile_context import remote_device
    mode = settings().get('agent_permission_mode','approval')
    device_id = getattr(runtime, 'mobile_device_id', None) or remote_device.get()
    if device_id:
        device = one('SELECT status,expires_at FROM mobile_devices WHERE id=?', (device_id,))
        if not device or device['status'] != 'active' or device['expires_at'] <= now():
            raise PermissionError('手机连接已撤销或失效，不能继续访问电脑文件')
        # Pairing grants a learning client, never unrestricted PC authority.
        return 'read_only' if mode == 'read_only' else 'approval'
    return mode


def file_state(path):
    path=Path(path)
    if not path.exists():return None
    info=path.stat()
    return {'bytes':info.st_size,'mtime':info.st_mtime_ns,'directory':path.is_dir()}


def public_request(row):
    return {key:row[key] for key in ('id','project_id','conversation_id','job_id','tool','status','created_at')} | {
        'details':unj(row['details_json'],{}),'error':row.get('error')}


def list_requests(project_id,conversation_id):
    from .dialogue_scope import validate_conversation
    validate_conversation(conversation_id,project_id)
    rows=many('SELECT * FROM agent_approvals WHERE project_id=? AND conversation_id=? AND status IN (?,?,?) ORDER BY created_at',
              (project_id,conversation_id,'pending','approved','denied'))
    for row in rows:
        if row['job_id']:
            job=one('SELECT status FROM jobs WHERE id=?',(row['job_id'],))
            if not job or job['status'] in {'cancelled','failed','completed'}:
                execute("UPDATE agent_approvals SET status='cancelled',error=? WHERE id=? AND status='pending'",('任务已结束',row['id']))
                row['status']='cancelled'
    return [public_request(row) for row in rows if row['status']=='pending']


def decide(request_id,project_id,conversation_id,approved):
    from .dialogue_scope import validate_conversation
    validate_conversation(conversation_id,project_id)
    row=one('SELECT * FROM agent_approvals WHERE id=? AND project_id=? AND conversation_id=?',(request_id,project_id,conversation_id))
    if not row:raise PermissionError('审批不属于当前项目和对话')
    if row['status']!='pending':raise ValueError('这一审批已经处理或失效')
    from .conversations import is_deleted
    if is_deleted(conversation_id):raise ValueError('对话已删除')
    if row['job_id']:
        job=one('SELECT status FROM jobs WHERE id=?',(row['job_id'],))
        if not job or job['status'] in {'cancelled','failed','completed'}:raise ValueError('任务已结束')
    with connect() as database:
        changed=database.execute("UPDATE agent_approvals SET status=?,resolved_at=? WHERE id=? AND status='pending'",('approved' if approved else 'denied',now(),request_id)).rowcount
        if changed!=1:raise ValueError('这一审批已经处理或失效')
    return {'id':request_id,'status':'approved' if approved else 'denied'}


async def authorize(runtime,tool,args,paths,*,preview='',operation_id=None):
    """paths is [(resolved path, requires write)]. Never broaden a directory grant."""
    mode=configuration(runtime)
    from .ai import settings
    if any(write for path,write in paths) and not settings().get('agent_file_write_enabled',True):raise PermissionError('AI 文件修改权限已关闭')
    if mode=='read_only' and any(write for path,write in paths):raise PermissionError('当前为只读模式，不能修改或删除文件；请在输入框中切换权限')
    if runtime.private_context and any(write for path,write in paths):raise PermissionError('出题和批改的私有上下文只能读取')
    if mode=='full_access':return
    needed=[]
    for path,write in paths:
        try:runtime.checked_path(str(path),write)
        except PermissionError as exc:
            if any(message in str(exc) for message in ('网页视频权限','原资料已变化','文件已变更','解析选择','页码范围','书库范围')):raise
            needed.append((path,write))
    if not needed:return
    if runtime.private_context:raise PermissionError('私有解题上下文只能读取所选资料和授权目录')
    if mode=='read_only':raise PermissionError('只读模式只能读取当前资料、软件代码和已授权目录，请明确授权需要的资料')
    # A caller without a live reply/job cannot wait for a student. Do not create
    # a clickable request whose originating operation has already returned.
    if not runtime.on_event and not runtime.job_id:
        raise PermissionError('该路径尚未授权，需要在学习对话中审批本次文件操作')
    states={str(path):file_state(path) for path,write in paths}
    details={'paths':[{'path':str(path),'operation':'修改／删除' if write else '读取','before':states[str(path)]} for path,write in paths],
             'preview':preview[:2200], 'scope':'仅本次操作；不修改整个目录的授权'}
    signature=hashlib.sha256(j([runtime.scope_key,tool,args.model_dump(),states]).encode('utf-8')).hexdigest()
    if signature in runtime.denied_operations:raise PermissionError('本次文件操作已拒绝；请停止尝试，等待用户重新明确要求')
    row=one("SELECT * FROM agent_approvals WHERE signature=? AND status IN ('pending','approved') ORDER BY created_at DESC LIMIT 1",(signature,))
    if not row:
        ident=uid()
        execute('INSERT INTO agent_approvals VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (ident,runtime.project_id,runtime.conversation_id,runtime.job_id,tool,signature,j(details),'pending',None,now(),None))
        row=one('SELECT * FROM agent_approvals WHERE id=?',(ident,))
    from .scheduling import current_step
    step=current_step.get()
    runtime.begin_approval_wait(row['id'])
    if step:step.set_waiting(True)
    try:
        await runtime.emit({'id':row['id'],'operation_id':operation_id,'tool':tool,'status':'waiting_approval',
                            'label':'等待文件操作审批','approval':public_request(row)})
        while True:
            current=one('SELECT * FROM agent_approvals WHERE id=?',(row['id'],))
            if not current:raise PermissionError('审批已移除')
            current_mode=configuration(runtime)
            if current_mode=='read_only' and any(write for path,write in paths):
                execute("UPDATE agent_approvals SET status='cancelled',error=? WHERE id=?",('权限已改为只读',row['id']))
                raise PermissionError('权限已改为只读，本次文件操作已停止')
            if current['status'] in {'denied','cancelled','consumed'}:
                if current['status']=='denied':runtime.denied_operations.add(signature)
                raise PermissionError('文件操作被拒绝或审批已失效；停止本次操作，等待用户重新明确要求')
            if runtime.conversation_id:
                from .conversations import is_deleted
                if is_deleted(runtime.conversation_id):raise asyncio.CancelledError()
            if runtime.job_id:
                job=one('SELECT status FROM jobs WHERE id=?',(runtime.job_id,))
                if not job or job['status'] in {'cancelled','failed','completed'}:raise asyncio.CancelledError()
            if step:await step.control.checkpoint()
            if current['status']=='approved' or current_mode=='full_access':break
            await asyncio.sleep(.2)
        if any(file_state(path)!=states[str(path)] for path,write in paths):
            execute("UPDATE agent_approvals SET status='cancelled',error=? WHERE id=?",('审批期间文件已变更',row['id']))
            raise PermissionError('审批期间文件已变更，请先重新读取并审批新的操作')
        with connect() as database:
            changed=database.execute("UPDATE agent_approvals SET status='consumed',resolved_at=? WHERE id=? AND status IN ('pending','approved')",(now(),row['id'])).rowcount
            if changed!=1:raise PermissionError('审批已使用或已失效')
        runtime.operation_grants.extend((str(path),write,states[str(path)]) for path,write in needed)
    except asyncio.CancelledError:
        execute("UPDATE agent_approvals SET status='cancelled',error=? WHERE id=? AND status IN ('pending','approved')",('操作已取消',row['id']))
        raise
    except BaseException:
        execute("UPDATE agent_approvals SET status='cancelled',error=? WHERE id=? AND status IN ('pending','approved')",('操作未能继续，审批已失效',row['id']))
        raise
    finally:
        runtime.end_approval_wait(row['id'])
        if step:step.set_waiting(False)


def permission_status(runtime=None):
    return {'mode':configuration(runtime),'application_root':str(application_root()),'data_root':str(data_dir()),
            'description':{'read_only':'读取当前资料、软件代码与授权目录；禁止 Agent 文件修改和删除',
                           'approval':'工作目录和明确授权目录内可操作；其他文件操作逐次审批',
                           'full_access':'当前 Windows 账户可访问的文件可读、修改和删除；不自动注入其他对话记录'}[configuration(runtime)]}
