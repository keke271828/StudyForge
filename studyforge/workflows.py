"""Durable task phases shared by reading, structures, exercises and grading."""
from contextvars import ContextVar
import asyncio
from pathlib import Path

from .db import execute, j, now, one, unj
from .generation_control import PausableClient
from .scheduling import run_owned_io


PAUSABLE_KINDS = frozenset({'generate','read','knowledge','coding_generate','quiz_grade','homework_grade',
                           'coding_grade','feynman','repair','advance','export'})
current_control = ContextVar('studyforge_workflow_control', default=None)


def resumable(row):
    if row['kind'].startswith('import'):
        from .task_retry import public
        state=public('project',row['id'])
        return bool(state and state['state']=='waiting')
    if row['kind'] not in PAUSABLE_KINDS: return False
    payload = unj(row['payload_json'], {})
    if row['kind']=='generate': return True  # Legacy generation checkpoints.
    if row['kind'] in ('read','knowledge'):
        return bool(payload.get('project_id') and payload.get('source_ids') and
                    (row['kind']!='knowledge' or payload.get('reading_id')))
    return payload.get('workflow_version')==1 and bool(payload.get('values'))


async def checkpoint():
    control=current_control.get()
    if control: await control.checkpoint()


def stage(name, progress):
    control=current_control.get()
    if control: control.stage(name,progress)


def client_with_pause(client, scope='assessment'):
    control=current_control.get()
    return PausableClient(client,control,scope) if control and not isinstance(client,PausableClient) else client


def snapshot(name, operation, control=None):
    """Keep non-model inputs stable when another conversation changes memory."""
    control=control or current_control.get()
    if not control: return operation()
    key='snapshot:'+name
    cached=one('SELECT response FROM generation_steps WHERE job_id=? AND step_key=?',(control.job_id,key))
    if cached:return unj(cached['response'])
    value=operation()
    execute('INSERT INTO generation_steps VALUES (?,?,?,?)',(control.job_id,key,j(value),now()))
    return value


async def phase(name, operation):
    """Cache a committed phase without counting nested model calls twice.

    Model calls pause at their own boundaries. After a phase commits a grade,
    its result is saved before the next await, so resume cannot grade twice.
    """
    control=current_control.get()
    if not control: return await operation()
    await control.checkpoint()
    key='phase:'+name
    cached=one('SELECT response FROM generation_steps WHERE job_id=? AND step_key=?',(control.job_id,key))
    if cached: result=unj(cached['response'])
    else:
        result=await operation()
        execute('INSERT OR REPLACE INTO generation_steps VALUES (?,?,?,?)',(control.job_id,key,j(result),now()))
    await control.checkpoint()
    return result


async def local_step(name, signature, operation):
    control=current_control.get()
    if not control: return await operation()
    return await control.step('local:'+name,signature,operation)


def pin_originals(control, records):
    from .learning import source_fingerprint, content_fingerprint
    job_id=getattr(control,'job_id',control)
    for key,value in [('source_fingerprint',source_fingerprint(records)),
                      ('source_content_fingerprint',content_fingerprint(records))]:
        old=one('SELECT response FROM generation_steps WHERE job_id=? AND step_key=?',(job_id,key))
        if old and old['response']!=value:
            raise RuntimeError('原资料在任务期间已变更，不能用旧步骤续做；请取消此任务并重新发起')
        if not old:
            execute('INSERT INTO generation_steps VALUES (?,?,?,?)',(job_id,key,value,now()))


async def originals(source_ids, project_id):
    from .materials import read_original_sources_async
    from .server import source_records_async
    control=current_control.get()
    await checkpoint()
    try:
        records=await read_original_sources_async(await source_records_async(source_ids,project_id,for_original=True))
    except ValueError as exc:
        if control and one("SELECT 1 FROM generation_steps WHERE job_id=? AND step_key='source_fingerprint'",(control.job_id,)):
            raise RuntimeError('原资料已删除或不可读，不能续做；请恢复原文件或重新发起任务') from exc
        raise
    if control: pin_originals(control,records)
    await checkpoint()
    return records


async def export(content, fmt, title, filename):
    from .exporters import export_document
    from .scheduling import run_local
    async def write():return str(await run_local('document_export',export_document,content,fmt,title,filename,label='成果本机排版'))
    value=await local_step('export',[content,fmt,title,filename],write)
    path=Path(value)
    if not path.is_file():
        # A user can remove an unregistered file during a long pause. Recreate
        # it from the saved content, without paying for another model request.
        path=Path(await write())
    await checkpoint()
    return path
