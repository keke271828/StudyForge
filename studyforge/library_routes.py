"""Desktop and paired-mobile access to the shared textbook shelf."""
import asyncio
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from . import library
from .config import temp_dir
from .db import many, one, uid, unj
from .library_worker import create_job, new_read_job
from .library_outline import OutlineConflict
from .library_batches import SELECTION_LIMIT
from .library_reading import FOCUS_LIMIT, profile
from . import library_annotations

router=APIRouter(prefix='/api/library',tags=['library'])


def invoke(operation,*args,**kwargs):
    try:return operation(*args,**kwargs)
    except OutlineConflict as exc:raise HTTPException(409,str(exc)) from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc


@router.get('/books')
def books():return {'books':library.catalogue()}


@router.post('/books')
async def upload(file:UploadFile=File(...)):
    filename=Path(file.filename or '教材.pdf').name
    if Path(filename).suffix.lower()!='.pdf':raise HTTPException(400,'全局书库首版支持 PDF；其他资料请放入项目资料库')
    target=temp_dir()/('library-upload-'+uid()+'.pdf')
    task=None
    try:
        size=0
        with target.open('wb') as stream:
            while data:=await file.read(2*1024*1024):
                size+=len(data)
                if size>512*1024*1024:raise HTTPException(413,'教材超过 512 MB；请压缩扫描图像或拆分书籍')
                await asyncio.to_thread(stream.write,data)
        task=asyncio.create_task(asyncio.to_thread(library.import_book,target,filename))
        return await asyncio.shield(task)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    finally:
        # Shielded copy may still be reading this file after a phone disconnects.
        if task and not task.done():await asyncio.gather(task,return_exceptions=True)
        target.unlink(missing_ok=True)
        await file.close()


@router.get('/books/{book_id}')
def details(book_id:str):return invoke(library.details,book_id)


@router.get('/books/{book_id}/page')
async def page(book_id:str,page:int=Query(ge=1)):
    try:return Response(await asyncio.to_thread(library.preview,book_id,page),media_type='image/png',headers={'Cache-Control':'no-store'})
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc


class TocIn(BaseModel):
    page_spec:str|None=Field(default=None,min_length=1,max_length=100)
    auto_discover:bool=False
    scan_limit:int=Field(default=32,ge=1,le=64)
    first_printed:int|None=Field(default=None,ge=1)
    first_pdf:int|None=Field(default=None,ge=1)
    foreground:bool=False


@router.post('/books/{book_id}/toc')
def toc(book_id:str,value:TocIn):
    from .source_scope import page_numbers
    row=invoke(library.book,book_id)
    if many('SELECT id FROM library_nodes WHERE book_id=?',(book_id,)):raise HTTPException(409,'目录已存在，请编辑节点或新增节点')
    if many("SELECT id FROM library_jobs WHERE book_id=? AND kind='toc' AND status IN ('queued','running','paused','pausing')",(book_id,)):
        raise HTTPException(409,'目录任务已存在，请继续或取消原任务')
    if value.auto_discover:
        if value.page_spec:raise HTTPException(400,'自动查找与手动指定目录页请选择一种')
    else:
        if not value.page_spec:raise HTTPException(400,'请自动查找目录，或填写目录所在的 PDF 页码')
        pages=invoke(page_numbers,value.page_spec,row['page_count'])
        if len(pages)>12:raise HTTPException(400,'一次目录识别最多 12 页')
    if (value.first_printed is None)!=(value.first_pdf is None):raise HTTPException(400,'纸面页码和对应 PDF 页码需同时填写，或均留空')
    if value.first_pdf and value.first_pdf>row['page_count']:raise HTTPException(400,'正文起始 PDF 页码超出书籍页数')
    return create_job(book_id,'toc',value.model_dump())


class NodeIn(BaseModel):
    title:str|None=Field(default=None,min_length=1,max_length=200)
    start_page:int|None=Field(default=None,ge=1)
    end_page:int|None=Field(default=None,ge=1)
    start_y:float|None=Field(default=None,ge=0,lt=1)
    end_y:float|None=Field(default=None,gt=0,le=1)
    confirmed:bool|None=None


@router.put('/nodes/{node_id}')
def update(node_id:str,value:NodeIn):
    return invoke(library.update_node,node_id,{key:val for key,val in value.model_dump(exclude_unset=True).items() if val is not None})


class AddNodeIn(BaseModel):
    title:str=Field(min_length=1,max_length=200)
    parent_id:str|None=None


@router.post('/books/{book_id}/nodes')
def add(book_id:str,value:AddNodeIn):return invoke(library.add_node,book_id,value.title,value.parent_id)


class MoveNodeIn(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    node_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    parent_id:str|None=Field(pattern=r'^[a-f0-9]{32}$')
    before_id:str|None=Field(pattern=r'^[a-f0-9]{32}$')
    revision:str=Field(pattern=r'^[a-f0-9]{64}$')


@router.post('/books/{book_id}/outline/move')
def move(book_id:str,value:MoveNodeIn):
    from .library_outline import move as move_node
    return invoke(move_node,book_id,value.node_id,value.parent_id,value.before_id,value.revision)


@router.get('/nodes/{node_id}/notes')
def notes(node_id:str,reading_id:str|None=None,depth:Literal['index','deep']|None=None,
          focus:Annotated[str,Query(max_length=FOCUS_LIMIT)]=''):
    n=invoke(library.node,node_id);variants=library.reading_variants(n)
    preferred=[r for r in variants if not depth or r['depth']==depth]
    focused=next((r for r in preferred if depth=='deep' and r['focus']==focus.strip()),None)
    selected=(next((r for r in variants if r['id']==reading_id),None) if reading_id
              else focused or (preferred[0] if preferred else variants[0] if variants else None))
    if reading_id and not selected:raise HTTPException(400,'这个阅读版本不属于当前节点或范围已失效，请重新打开笔记')
    r=one('SELECT * FROM library_readings WHERE id=?',(selected['id'],)) if selected else None
    if not r:raise HTTPException(400,'这个节点尚未完成阅读，不提供猜测生成的笔记')
    marks={a['reading_id']:bool(a['suspect']) for a in many('SELECT a.reading_id,a.suspect FROM library_reading_annotations a '
        'JOIN library_readings r ON r.id=a.reading_id WHERE r.node_id=?',(node_id,))}
    return {'node':library.public_node(n),'notes':r['notes'],'warnings':unj(r['warnings_json'],[]),
            'annotation':library_annotations.get(r['id']),
            'reading':{key:r[key] for key in ('id','depth','focus','model','provider','effort','vision_model','updated_at')},
            'versions':[{**{key:v[key] for key in ('id','depth','focus','model','provider','effort','vision_model','updated_at')},
                         'suspect':marks.get(v['id'],False)} for v in variants],
            'pages':many('SELECT page,locator FROM library_chunks WHERE reading_id=? ORDER BY page',(r['id'],))}


class NoteAnnotationIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    suspect:bool=False
    comment:str=Field(default='',max_length=1200)
    revision:int=Field(ge=0)
    reading_updated_at:str|None=Field(default=None,max_length=80)


@router.put('/nodes/{node_id}/notes/{reading_id}/annotation')
def annotate_note(node_id:str,reading_id:str,value:NoteAnnotationIn):
    try:return library_annotations.save(node_id,reading_id,value.suspect,value.comment,value.revision,value.reading_updated_at)
    except library_annotations.AnnotationConflict as exc:raise HTTPException(409,str(exc)) from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc


class LibraryModelsIn(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    mode:Literal['follow','independent']='follow'
    provider:str=Field(default='deepseek',min_length=1,max_length=100)
    model:str|None=Field(default=None,max_length=120)
    effort:str|None=Field(default=None,max_length=16)
    vision_mode:Literal['configured','same','custom']='configured'
    vision_model:str|None=Field(default=None,max_length=120)
    revision:int=Field(ge=0)


@router.get('/models')
def reading_models():
    from .library_models import public
    return public()


@router.put('/models')
def save_reading_models(value:LibraryModelsIn):
    from .library_models import save,ModelPreferenceConflict
    payload=value.model_dump();revision=payload.pop('revision')
    try:return {'selection':save(payload,revision)}
    except ModelPreferenceConflict as exc:raise HTTPException(409,str(exc)) from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc


async def select_reading_models(value):
    from .providers import default_model
    from .server import ReadIn as ModelSelection,choose_generation_model
    from .library_models import snapshot
    selection=ModelSelection(project_id='library',source_ids=[],provider=value.provider,model=value.model,reasoning_effort=value.effort)
    await choose_generation_model(selection)
    value.model=selection.model or default_model(value.provider)
    value.vision_model=invoke(snapshot,value.provider,value.model,value.effort,value.vision_model)['vision_model']


class ReadIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    node_ids:list[str]=Field(min_length=1,max_length=SELECTION_LIMIT)
    provider:str=Field(min_length=1,max_length=100)
    model:str|None=Field(default=None,max_length=120)
    effort:str|None=Field(default=None,max_length=16)
    vision_model:str|None=Field(default=None,max_length=120)
    parallel:bool=False
    force:bool=False
    foreground:bool=False
    depth:Literal['index','deep']='index'
    focus:str=Field(default='',max_length=FOCUS_LIMIT)


@router.post('/books/{book_id}/read')
async def read(book_id:str,value:ReadIn):
    invoke(profile,value.depth,value.focus)
    await select_reading_models(value)
    return invoke(new_read_job,book_id,value.node_ids,value.provider,value.model,value.effort,value.parallel,value.force,value.foreground,
                  depth=value.depth,focus=value.focus,vision_model=value.vision_model)


class RangesIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    node_ids:list[str]=Field(min_length=1,max_length=SELECTION_LIMIT)
    provider:str|None=Field(default=None,max_length=100)
    model:str|None=Field(default=None,max_length=120)
    effort:str|None=Field(default=None,max_length=16)
    vision_model:str|None=Field(default=None,max_length=120)
    foreground:bool=False
    allow_ai:bool=False
    read_after:bool=False
    parallel:bool=False
    depth:Literal['index','deep']='index'
    focus:str=Field(default='',max_length=FOCUS_LIMIT)


class ConfirmRangesIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revisions:dict[str,str]=Field(min_length=1,max_length=SELECTION_LIMIT)


@router.post('/books/{book_id}/ranges/confirm')
def confirm_ranges(book_id:str,value:ConfirmRangesIn):
    from .library_range_review import confirm
    return invoke(confirm,book_id,value.revisions)


@router.post('/books/{book_id}/ranges')
async def ranges(book_id:str,value:RangesIn):
    from .library_ranges import range_job
    invoke(profile,value.depth,value.focus)
    if value.read_after or value.allow_ai:
        if not value.provider:raise HTTPException(400,'继续阅读需选择AI服务')
        await select_reading_models(value)
    return invoke(range_job,book_id,**value.model_dump())


@router.post('/jobs/{job_id}/{action}')
async def action(job_id:str,action:Literal['pause','resume','cancel'],request:Request):
    worker=getattr(request.app.state,'library_worker',None)
    if not worker:raise HTTPException(503,'后台阅读服务尚未启动，请重开软件')
    try:return await worker.action(job_id,action)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc


@router.get('/jobs')
def jobs():return {'jobs':[library.public_job(row) for row in many('SELECT * FROM library_jobs ORDER BY created_at DESC,rowid DESC LIMIT 80')]}


class PolicyIn(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    window_enabled:bool
    start:str=Field(pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    end:str=Field(pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    weekdays:list[int]=Field(min_length=1,max_length=7)
    daily_tokens:int=Field(ge=0,le=50_000_000)


@router.get('/policy')
def policy():
    from .library_policy import status
    return status()


@router.put('/policy')
def policy_settings(value:PolicyIn):
    from .library_policy import save
    return invoke(save,value.model_dump())


@router.get('/nodes/suggest')
def suggest(query:str=Query(default='',max_length=160),book_id:str|None=None,limit:int=Query(default=12,ge=1,le=20)):
    return invoke(library.directory_suggestions,query,book_id,limit)


@router.get('/search')
async def search(query:str=Query(min_length=1,max_length=1000),limit:int=Query(default=12,ge=1,le=40),mode:Literal['auto','keyword','hybrid']='auto'):
    return await asyncio.to_thread(library.search,query,limit,None,mode,True)


@router.get('/semantic')
def semantic_status():
    from .library_semantic import status
    return status()


class SemanticIn(BaseModel):
    enabled:bool


@router.put('/semantic')
def semantic_settings(value:SemanticIn):
    from .library_semantic import set_enabled
    return set_enabled(value.enabled)


@router.post('/semantic/download')
async def semantic_download(request:Request):
    worker=getattr(request.app.state,'library_semantic_worker',None)
    if not worker:raise HTTPException(503,'本地索引服务尚未启动，请重开软件')
    await worker.download()
    from .library_semantic import status
    return await asyncio.to_thread(status)


@router.post('/semantic/cancel-download')
def semantic_cancel(request:Request):
    worker=getattr(request.app.state,'library_semantic_worker',None)
    if worker:worker.cancel_download.set()
    return {'cancel_requested':True}


@router.get('/conversations/{conversation_id}')
def preferences(conversation_id:str,project_id:str):return invoke(library.preferences,conversation_id,project_id)


@router.get('/conversations/{conversation_id}/history')
def lookup_history(conversation_id:str,project_id:str):
    from .library_history import history
    return invoke(history,conversation_id,project_id)


@router.delete('/conversations/{conversation_id}/history')
def clear_history(conversation_id:str,project_id:str):
    from .library_history import clear
    return invoke(clear,conversation_id,project_id)


class ReferenceIn(BaseModel):
    node_id:str
    purpose:Literal['reference','primary']='reference'


class ReferenceAddIn(ReferenceIn):
    project_id:str


@router.post('/conversations/{conversation_id}/references')
def add_reference(conversation_id:str,value:ReferenceAddIn):
    return invoke(library.add_reference,conversation_id,value.project_id,value.node_id,value.purpose)


class PreferencesIn(BaseModel):
    project_id:str
    mode:Literal['auto','manual','off']='auto'
    references:list[ReferenceIn]=Field(default_factory=list,max_length=12)


@router.put('/conversations/{conversation_id}')
def save_preferences(conversation_id:str,value:PreferencesIn):
    return invoke(library.set_preferences,conversation_id,value.project_id,value.mode,[r.model_dump() for r in value.references])


@router.get('/conversations/{conversation_id}/references')
async def references(conversation_id:str,project_id:str,query:str=Query(max_length=1000)):
    try:
        snapshot=await asyncio.to_thread(library.reference_snapshot,conversation_id,project_id,query)
        content=await asyncio.to_thread(library.reference_content,snapshot,query)
        from .library_history import record
        saved=await asyncio.to_thread(record,conversation_id,project_id,query,content)
        return {'snapshot':snapshot,**content,'receipt':library.reference_receipt(content),'history':saved}
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc


@router.delete('/books/{book_id}')
def remove(book_id:str):invoke(library.delete_book,book_id);return {'deleted':True}
