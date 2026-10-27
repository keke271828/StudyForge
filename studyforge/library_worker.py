"""Checkpointed book reading, with bounded independent chapter workers."""
from __future__ import annotations

import asyncio
import hashlib
import inspect

from . import library
from .db import connect, execute, j, many, now, one, uid, unj
from .scheduling import StepState, current_step, execution_scope, execution_context, run_local, scheduler, library_foreground_busy
from . import library_policy
from . import library_reading

READ_RULES = library_reading.INDEX_RULES


class LibraryControl:
    def __init__(self, ident):
        self.job_id=ident; self.pause_requested=False; self.operations=set()
        self.page_totals={}; self.processed_pages={}

    def progress(self, percent):
        execute('UPDATE library_jobs SET progress=MAX(progress,?),updated_at=? WHERE id=?',
                (max(0,min(95,int(percent))),now(),self.job_id))

    def record_pages(self,node_id,count):
        self.processed_pages[node_id]=max(count,self.processed_pages.get(node_id,0))
        total=sum(self.page_totals.values())
        if not total:return
        done=sum(self.processed_pages.values())
        self.stage('已保存分批阅读',pages_processed=done,total_pages=total)
        self.progress(min(90,90*done/total))

    def refresh_idle(self):
        row=one('SELECT status FROM library_jobs WHERE id=?',(self.job_id,))
        if row and row['status']=='pausing' and not any(s.started or not s.waiting for s in self.operations):
            execute("UPDATE library_jobs SET status='paused',updated_at=? WHERE id=?",(now(),self.job_id))

    def stage(self, label, **values):
        row=one('SELECT status,result_json FROM library_jobs WHERE id=?',(self.job_id,))
        if not row or row['status'] in ('cancelled','completed','failed'): return
        result=unj(row['result_json'],{})|values|{'stage':label}
        execute('UPDATE library_jobs SET result_json=?,updated_at=? WHERE id=?',(j(result),now(),self.job_id))

    async def checkpoint(self):
        while True:
            row=one('SELECT status FROM library_jobs WHERE id=?',(self.job_id,))
            if not row or row['status']=='cancelled': raise asyncio.CancelledError()
            self.pause_requested=row['status'] in ('paused','pausing')
            if self.pause_requested:
                self.refresh_idle()
            elif not execution_context.get().get('background_library') or not library_foreground_busy():
                if execution_context.get().get('library_reading'):
                    library_policy.check_window()
                return
            else: self.stage('等待前台空闲 · 已完成步骤已保存')
            scheduler().wake()
            await asyncio.sleep(.4)

    async def step(self, key, signature, operation):
        await self.checkpoint()
        cache_key=hashlib.sha256(j([key,signature]).encode()).hexdigest()
        name=key[-1] if isinstance(key,list) else key
        def valid(result):
            if name in ('batch-note','deep-navigation','node-index'):
                return isinstance(result,str) and bool(result.strip())
            if name == 'range-ai-choice':
                from .ai import parse_json_response
                try: parse_json_response(result)
                except (ValueError,TypeError,AttributeError): return False
            return True
        saved=one('SELECT response_json FROM library_steps WHERE job_id=? AND step_key=?',(self.job_id,cache_key))
        if saved:
            result=unj(saved['response_json'])
            if valid(result):return result
            execute('DELETE FROM library_steps WHERE job_id=? AND step_key=?',(self.job_id,cache_key))
        step=StepState(self); self.operations.add(step); token=current_step.set(step)
        try:
            result=await operation()
            row=one('SELECT status FROM library_jobs WHERE id=?',(self.job_id,))
            if not row or row['status']=='cancelled': raise asyncio.CancelledError()
            if valid(result):execute('INSERT OR REPLACE INTO library_steps VALUES (?,?,?,?)',(self.job_id,cache_key,j(result),now()))
        finally:
            current_step.reset(token); self.operations.discard(step); self.refresh_idle()
        return result


def create_job(book_id, kind, payload):
    library.book(book_id)
    ident=uid()
    execute('INSERT INTO library_jobs(id,book_id,kind,status,payload_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
            (ident,book_id,kind,'queued',j(payload),now(),now()))
    from .task_retry import ensure
    ensure('library',ident)
    return library.public_job(one('SELECT * FROM library_jobs WHERE id=?',(ident,)))


def new_read_job(book_id, ids, provider, model=None, effort=None, parallel=False, force=False, foreground=False, *, origin_job_id=None,
                 depth='index', focus='', vision_model=None):
    from .library_batches import batch_plan
    depth, focus = library_reading.profile(depth, focus)
    selected=library.normalize_nodes(book_id,ids)
    book=library.book(book_id)
    active=many("SELECT payload_json FROM library_jobs WHERE book_id=? AND kind='read' AND status IN ('queued','running','pausing','paused')",(book_id,))
    wanted={n['id'] for n in selected}
    if any(wanted & set(unj(r['payload_json'])['node_ids']) for r in active):
        raise ValueError('所选节点已有阅读任务；请查看任务进度或继续该任务，避免重复收费')
    from .library_models import snapshot
    return create_job(book_id,'read',{'node_ids':[n['id'] for n in selected],**snapshot(provider,model,effort,vision_model),
        'parallel':parallel,'force':force,'foreground':foreground,
        'scopes':{n['id']:library.version(book,n) for n in selected},'origin_job_id':origin_job_id,'depth':depth,'focus':focus,
        **batch_plan(selected)})


def default_client(payload):
    from .ai import client_for
    client=client_for(payload['provider'],model=payload.get('model'),effort=payload.get('effort'),vision_model=payload.get('vision_model'))
    # No project/dialogue is attached. Background reading is not an agent turn
    # with access to the student's chats or filesystem-changing tools.
    client.agent_runtime=None
    if hasattr(client,'conversation'): client.conversation=None
    if payload['provider']=='codex': client=client.fork()
    return client


async def close_client(client):
    close=getattr(client,'close',None)
    if close:
        value=close()
        if inspect.isawaitable(value): await value


async def run_directory(control, row, payload):
    from .source_scope import page_numbers
    from . import library_toc
    saved=library_toc.applied_result(control.job_id)
    if saved is not None:return saved
    discovery=None
    if payload.get('auto_discover'):
        discovery=await library_toc.discover(control,row,payload.get('scan_limit',32))
        control.stage('目录查找已完成',toc_discovery=discovery)
        if discovery['status']!='found':
            return {'stage':'目录查找需要核对 · 可查看候选原页或手动指定','nodes':0,'toc_discovery':discovery}
        pages=discovery['candidate_pages']
        page_spec=','.join(str(p) for p in pages)
    else:
        page_spec=payload['page_spec']
        pages=page_numbers(page_spec,row['page_count'])
    if len(pages)>12: raise ValueError('一次目录识别最多 12 页；不会自动扫描全书')
    results=[]
    for index,page in enumerate(pages):
        control.stage(f'识别目录页 {index+1}/{len(pages)} · 不通读正文',pages_done=index)
        rows=await control.step('toc-page',[library.TOC_OCR_VERSION,row['sha256'],page],lambda p=page:run_local('image',library.directory_page,row['id'],p))
        results.append((page,rows))
        progress=(40 if discovery else 0)+int((50 if discovery else 90)*(index+1)/len(pages))
        execute('UPDATE library_jobs SET progress=MAX(progress,?) WHERE id=?',(progress,control.job_id))
    await control.checkpoint()
    nodes=library.parse_directory(results,payload.get('first_printed'),payload.get('first_pdf'))
    if discovery:
        expected={e['page']:e for e in discovery['evidence']}
        for page,rows in results:
            count=len(library.parse_directory([(page,rows)]))
            expected[page]['recognized_entries']=count
            if count<max(1,(expected[page]['entries']*7+9)//10):
                discovery['warnings'].append(f'PDF 第 {page} 页的目录条目明显减少，请核对原页；没有省略后自动建立。')
        if discovery['warnings']:
            discovery['status']='review'
            return {'stage':'目录条目需要核对 · 尚未建立目录','nodes':0,'toc_discovery':discovery}
    result={'stage':'目录已建立 · 正文尚未阅读，范围待确认','nodes':len(nodes),'toc_pages':pages}
    if discovery:result['toc_discovery']=discovery
    return library_toc.commit_outline(row['id'],nodes,page_spec,control.job_id,result)


async def read_one(control, row, n, payload, client_factory):
    if library.version(row,n)!=payload['scopes'][n['id']]: raise ValueError('阅读范围已改变，请重新启动该节点')
    client=client_factory(payload)
    reading_id=None
    try:
        model=getattr(client,'model',payload.get('model')); effort=getattr(client,'effort',payload.get('effort'))
        depth,focus=library_reading.profile(payload.get('depth','index'),payload.get('focus',''))
        vision_model=(getattr(client,'vision_model',model) if 'vision_model' in payload else None)
        signature=library.reading_signature(row,n,payload['provider'],model,effort,depth,focus,vision_model)
        completed_key = 'node-completed:'+n['id']+':'+signature
        completed = one('SELECT response_json FROM library_steps WHERE job_id=? AND step_key=?', (control.job_id,completed_key))
        if completed:
            saved = unj(completed['response_json'], {})
            reading=one('SELECT * FROM library_readings WHERE id=?',(saved['reading_id'],))
            if reading and reading['status']=='completed' and library.valid_reading(reading,n,row):
                control.record_pages(n['id'],n['end_page']-n['start_page']+1)
                return saved | {'cached':True}
        visual_identity=library_reading.visual_identity(client,payload['provider'])
        existing=one('SELECT id,status FROM library_readings WHERE signature=?',(signature,))
        if existing and existing['status']=='completed' and not payload.get('force'):
            control.record_pages(n['id'],n['end_page']-n['start_page']+1)
            return {'node_id':n['id'],'reading_id':existing['id'],'cached':True,'title':n['title'],'depth':depth,'focus':focus}
        reading_id=existing['id'] if existing else uid()
        if not existing:
            execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,created_at,updated_at,depth,focus,vision_model) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (reading_id,n['id'],signature,payload['provider'],model,effort,'reading',now(),now(),depth,focus,vision_model))
        else: execute("UPDATE library_readings SET status='reading',updated_at=? WHERE id=?",(now(),reading_id))
        page_notes=[]; warnings=[];visual_reused=0
        for start in range(n['start_page'],n['end_page']+1,4):
            await control.checkpoint()
            pages=[]
            for page in range(start,min(n['end_page']+1,start+4)):
                control.stage(f"读取 {n['title']} · PDF 第 {page} 页",current_node=n['id'],current_page=page)
                p=await control.step('extract',[library.version(row,n),page],lambda p=page:run_local('image',library.extract_page,row,n,p))
                pages.append(p)
            found={};scanned=[p for p in pages if p['scanned']]
            if not payload.get('force'):
                for p in scanned:
                    cached_visual=library_reading.saved_visual(row,n,p,visual_identity)
                    if cached_visual:
                        found[str(p['page'])]=cached_visual;visual_reused+=1
            unverified=[p for p in scanned if str(p['page']) not in found]
            batch=getattr(client,'analyze_images',None)
            if len(unverified)>1 and callable(batch):
                frames=[{'id':str(p['page']),'path':__import__('pathlib').Path(p['image_path']),
                         'locator':row['title']+'｜'+p['locator'],'ocr':p['original_text']} for p in unverified]
                try:
                    observations=await control.step('verify-images',[signature,visual_identity,[(p['page'],p['image_sha256']) for p in unverified]],lambda:batch(frames))
                    if isinstance(observations,dict):found.update(observations)
                except library_policy.ReadingDeferred: raise
                except Exception:pass
            excerpts=[]
            for p in pages:
                visual=found.get(str(p['page']),'')
                if p['scanned'] and not isinstance(visual,str):visual=''
                if p['scanned'] and not visual.strip():
                    analyze=getattr(client,'analyze_image',None)
                    if callable(analyze):
                        try:
                            visual=await control.step('verify-image',[signature,visual_identity,p['image_sha256'],p['page']],
                                lambda p=p:analyze(__import__('pathlib').Path(p['image_path']),row['title']+'｜'+p['locator'],p['original_text']))
                        except library_policy.ReadingDeferred: raise
                        except Exception as exc:
                            warnings.append(f"{p['locator']}：原图核对未完成（{type(exc).__name__}），OCR 公式不能作为确定结论")
                    if not isinstance(visual,str) or not visual.strip():
                        warnings.append(f"{p['locator']}：没有有效图像核对记录，扫描公式待核对")
                if not isinstance(visual,str):visual=''
                if p['scanned']:library_reading.save_visual(row,n,p,visual_identity,visual)
                if not p['original_text'].strip() and not visual.strip():raise ValueError(f"{p['locator']}没有可用内容")
                if '[OCR 未完成' in p['original_text']:warnings.append(f"{p['locator']}：本地 OCR 未完成")
                evidence_state=('扫描页尚无有效原图核对；OCR 公式、符号及条件不能视为已确认。' if p['scanned'] and not visual.strip()
                                else '扫描页 OCR 与原图观察分别保留；观察也可能出错，疑点回查原页。' if p['scanned'] else '可直接抽取文字的 PDF 原页。')
                excerpts.append(f"[来源：{p['locator']}]\n核对状态：{evidence_state}\n原页文字（OCR）：\n{p['original_text']}\n图像核对记录（非原文）：\n{visual}")
                execute('INSERT OR REPLACE INTO library_chunks VALUES (?,?,?,?,?,?,?)',
                        (reading_id,p['page'],p['locator'],p['original_text'],visual,p['image_path'],p['image_sha256']))
            excerpt=library_reading.reading_request(row,n,excerpts,depth,focus)
            note=await control.step('batch-note',[signature,hashlib.sha256(excerpt.encode()).hexdigest()],
                                   lambda:client.complete(library_reading.rules(depth),excerpt))
            if not isinstance(note,str) or not note.strip(): raise ValueError('阅读整理返回空内容，没有标记为已理解')
            await control.checkpoint()
            page_notes.append({'page':f"{pages[0]['page']}–{pages[-1]['page']}",'notes':note})
            control.record_pages(n['id'],pages[-1]['page']-n['start_page']+1)
            control.stage(f"已保存 {n['title']} · PDF {pages[0]['page']}–{pages[-1]['page']}",pages_in_node_done=pages[-1]['page']-n['start_page']+1)
        # One synthesis per node, rather than repeated multi-agent discussions.
        await control.checkpoint()
        note_text='\n\n'.join(f"PDF 第 {x['page']} 页：\n{x['notes']}" for x in page_notes)
        if depth=='deep':
            # Detailed page records are the deliverable. Never discard their
            # later proof steps to make a shorter synthesis fit its context.
            header=f"# 重点精读 · {n['title']}\n\n阅读范围：PDF 第 {n['start_page']}–{n['end_page']} 页。"
            if focus:header+='\n\n精读问题：'+focus
            guide=''
            if len(page_notes)>1 and len(note_text)<=44000:
                guide=await control.step('deep-navigation',[signature,hashlib.sha256(note_text.encode()).hexdigest()],
                    lambda:client.complete(library_reading.EVIDENCE_RULES+'\n根据已完成的精读记录，写一份简洁的阅读路线：主线、关键构造之间的关系、前置依赖与仍待核对处。标注来源；不再重复整篇讲解，不声称重新核对了原图。',
                        f"本节点：{n['title']}\n精读问题：{focus or '理解本节点的概念和论证'}\n"+note_text))
                if not isinstance(guide,str) or not guide.strip():raise ValueError('精读路线返回空内容；分页记录已保存，可重试')
            elif len(page_notes)>1:
                warnings.append('精读较长，保留完整分页记录；没有执行全篇统一推导核查')
            notes=header+('\n\n## 阅读路线\n\n'+guide if guide else '')+'\n\n## 原页精读记录\n\n'+note_text
        elif len(page_notes)>1:
            # Bound the synthesis context without dropping the persisted raw pages.
            pieces=[f"PDF 第 {x['page']} 页：\n{x['notes']}" for x in page_notes]
            if sum(map(len,pieces))>44000:
                warnings.append('节点较长，索引为分页整理汇编；没有声称完成全文统一推导核查')
                notes=note_text
            else:
                notes=await control.step('node-index',[signature,hashlib.sha256(note_text.encode()).hexdigest()],
                    lambda:client.complete(READ_RULES+'\n汇总这些已完成分页记录，保持每个概念的来源位置。不要把笔记当作新增原文。',
                                           f"本节点：{n['title']}\n"+'\n\n'.join(pieces)))
        else: notes=note_text
        if not isinstance(notes,str) or not notes.strip(): raise ValueError('节点索引为空')
        await control.checkpoint()
        execute("UPDATE library_readings SET status='completed',notes=?,warnings_json=?,updated_at=? WHERE id=?",
                (notes,j(warnings),now(),reading_id))
        result = {'node_id':n['id'],'reading_id':reading_id,'cached':False,'warnings':warnings,'title':n['title'],
                'pages':n['end_page']-n['start_page']+1,'model':model,'depth':depth,'focus':focus,'visual_pages_reused':visual_reused}
        execute('INSERT OR REPLACE INTO library_steps VALUES (?,?,?,?)', (control.job_id,completed_key,j(result),now()))
        return result
    except BaseException:
        if reading_id: execute("UPDATE library_readings SET status='interrupted',updated_at=? WHERE id=? AND status<>'completed'",(now(),reading_id))
        raise
    finally: await close_client(client)


async def run_read(control, row, payload, client_factory):
    # IDs were already normalized and ordered when this job was submitted.
    # Directory moves while queued/paused must not drop or reorder those IDs.
    saved={n['id']:n for n in many('SELECT * FROM library_nodes WHERE book_id=?',(row['id'],))}
    if not payload['node_ids'] or any(ident not in saved for ident in payload['node_ids']):
        raise ValueError('任务中的目录节点已不存在，请重新选择阅读范围')
    nodes=[saved[ident] for ident in payload['node_ids']]
    control.page_totals={n['id']:n['end_page']-n['start_page']+1 for n in nodes}
    results=[]; failures=[]; deferred=[]; failure_errors=[]; queue=asyncio.Queue()
    for n in nodes: queue.put_nowait(n)
    # Independent chapter workers share only source metadata, never chats or
    # unfinished sibling notes. Both modes still obey global model/resource caps.
    from .scheduling import configuration
    limits=configuration()
    workers=min(2,limits['model_concurrency'],len(nodes)) if payload['parallel'] and limits['task_parallel_enabled'] else 1
    reason=''
    if payload['parallel'] and workers==1:
        reason=('全软件并行已关闭' if not limits['task_parallel_enabled'] else
                '仅选择了一个独立节点' if len(nodes)==1 else '模型并发上限为 1')
    control.stage(('前台' if payload.get('foreground') else '后台')+('精读开始' if payload.get('depth')=='deep' else '阅读开始'),
                  depth=payload.get('depth','index'),workers=workers,parallel=payload['parallel'],parallel_reason=reason,nodes_total=len(nodes))
    async def worker():
        while not queue.empty():
            n=queue.get_nowait()
            try:
                async with execution_scope(label='书库阅读 · '+n['title']):
                    result=await read_one(control,row,n,payload,client_factory)
                results.append(result)
            except asyncio.CancelledError: raise
            except library_policy.ReadingDeferred as exc:
                deferred.append(exc); return
            except Exception as exc:
                failures.append({'node_id':n['id'],'title':n['title'],'error':str(exc)})
                failure_errors.append(exc)
            completed=len(results)+len(failures)
            control.progress(95*completed/len(nodes))
            control.stage(f'节点已处理 {completed}/{len(nodes)}',nodes_completed=list(results),failures=list(failures),workers=workers)
    tasks=[asyncio.create_task(worker()) for _ in range(workers)]
    try: await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
    if deferred: raise deferred[0]
    if failures:
        from .task_retry import NodeFailures
        raise NodeFailures('部分节点未完成；已完成记录保留，可只重试失败节点：'+j(failures),failure_errors)
    return {'stage':'所选节点整理完成 · 不代表学生已掌握','nodes_completed':results,'workers':workers,
            'parallel':payload['parallel'],'parallel_reason':reason,
            'pages_processed':sum(control.processed_pages.values()),'total_pages':sum(control.page_totals.values())}


class LibraryWorker:
    def __init__(self, client_factory=default_client):
        self.client_factory=client_factory; self.tasks={}; self.controls={}; self.loop_task=None

    async def start(self):
        # Previously completed steps are retained; user-paused jobs stay paused.
        execute("UPDATE library_jobs SET status=CASE WHEN status='pausing' THEN 'paused' ELSE 'queued' END,updated_at=? WHERE status IN ('running','pausing')",(now(),))
        library_policy.recover_requests()
        self.loop_task=asyncio.create_task(self.loop())

    async def loop(self):
        while True:
            scheduler().wake()
            # A waiting background book must not block an explicitly foreground
            # request. Admit at most one foreground and one background book job;
            # all of their actual IO/model steps still share the global limits.
            active=many("SELECT id,status,payload_json FROM library_jobs WHERE status IN ('running','pausing')")
            active_modes=[bool(unj(row['payload_json'],{}).get('foreground')) for row in active if row['id'] in self.tasks]
            queued=many("SELECT * FROM library_jobs WHERE status='queued' ORDER BY created_at,rowid")
            queued.sort(key=lambda row:(not bool(unj(row['payload_json']).get('foreground')),row['created_at']))
            for row in queued:
                from .task_retry import ready
                if not ready('library',row['id']): continue
                front=bool(unj(row['payload_json']).get('foreground'))
                if row['id'] in self.tasks or front in active_modes or (not front and (True in active_modes or library_foreground_busy())):continue
                wait=library_policy.wait_for_job(row)
                if wait: library_policy.mark_wait(row['id'],wait); continue
                self.launch(row['id']); break
            await asyncio.sleep(.4)

    def launch(self, ident):
        if ident in self.tasks: return
        control=LibraryControl(ident); self.controls[ident]=control
        task=asyncio.create_task(self.run(control)); self.tasks[ident]=task
        def finished(done):
            self.tasks.pop(ident,None); self.controls.pop(ident,None)
            if not done.cancelled(): done.exception()
        task.add_done_callback(finished)

    async def run(self, control):
        ident=control.job_id
        row=one('SELECT * FROM library_jobs WHERE id=?',(ident,))
        if not row:return
        from . import task_retry
        attempt = task_retry.Attempt('library',ident)
        token = task_retry.current_attempt.set(attempt)
        task_retry.begin('library',ident)
        try:
            payload=unj(row['payload_json']);front=bool(payload.get('foreground'))
            async with execution_scope(priority=5 if front else 20,background_library=not front,
                                       library_foreground=front,library_reading=row['kind'] in ('read','ranges'),
                                       job_id=ident,project_id=None,conversation_id=None):
                await control.checkpoint()
                execute("UPDATE library_jobs SET status='running',error=NULL,updated_at=? WHERE id=? AND status='queued'",(now(),ident))
                control.stage(('前台' if front else '后台')+'任务准备',policy_wait=None,foreground=front)
                b=library.book(row['book_id'])
                if await asyncio.to_thread(library.file_sha256,__import__('pathlib').Path(b['original_path'])) != b['sha256']:
                    raise ValueError('原书文件已改变，请重新导入版本')
                if row['kind']=='toc':result=await run_directory(control,b,payload)
                elif row['kind']=='ranges':
                    from .library_ranges import run_ranges
                    if payload.get('batch_size'):
                        from .library_batches import run_range_batches
                        result=await run_range_batches(control,b,payload,self.client_factory)
                    else:result=await run_ranges(control,b,payload,self.client_factory)
                elif payload.get('batch_size'):
                    from .library_batches import run_read_batches
                    result=await run_read_batches(control,b,payload,self.client_factory)
                else:result=await run_read(control,b,payload,self.client_factory)
                result['foreground']=front
                await control.checkpoint()
                execute("UPDATE library_jobs SET status='completed',progress=100,result_json=?,updated_at=? WHERE id=? AND status NOT IN ('cancelled','paused','pausing')",
                        (j(result),now(),ident))
                task_retry.finish('library',ident,'completed')
                from .desktop_notifications import enqueue
                with connect() as database:
                    enqueue(database,'library:'+ident,'complete','书库整理完成',b['title']+' · '+result['stage'],{'view':'library','book_id':b['id'],'library_job_id':ident})
        except asyncio.CancelledError: raise
        except library_policy.ReadingDeferred as exc:
            library_policy.mark_wait(ident,exc.wait)
        except Exception as exc:
            if task_retry.schedule('library',ident,exc,unsafe=attempt.unsafe_replay): return
            execute("UPDATE library_jobs SET status='failed',error=?,updated_at=? WHERE id=? AND status<>'cancelled'",(str(exc),now(),ident))
            from .desktop_notifications import enqueue
            with connect() as database:
                enqueue(database,'library-failed:'+ident,'failure','书库阅读未完成',str(exc),{'view':'library','book_id':row['book_id'],'library_job_id':ident})
        finally:
            task_retry.current_attempt.reset(token)

    async def action(self, ident, action):
        row=one('SELECT * FROM library_jobs WHERE id=?',(ident,))
        if not row: raise ValueError('书库任务不存在')
        if action=='pause' and row['status'] in ('running','queued'):
            control=self.controls.get(ident)
            execute("UPDATE library_jobs SET status=?,updated_at=? WHERE id=?",('pausing' if control else 'paused',now(),ident))
            if control: control.pause_requested=True; control.refresh_idle()
        elif action=='resume' and row['status'] in ('paused','pausing','failed'):
            if row['status']=='failed':
                from .task_retry import reset
                reset('library',ident)
            execute("UPDATE library_jobs SET status=?,error=NULL,updated_at=? WHERE id=?",('running' if ident in self.tasks else 'queued',now(),ident))
            if ident in self.controls: self.controls[ident].pause_requested=False
        elif action=='cancel' and row['status'] in ('running','queued','paused','pausing'):
            execute("UPDATE library_jobs SET status='cancelled',updated_at=? WHERE id=?",(now(),ident))
            from .task_retry import finish
            finish('library',ident,'cancelled')
            task=self.tasks.get(ident)
            if task: task.cancel(); await asyncio.gather(task,return_exceptions=True)
            # Wait for owned native IO before allowing removal of its files.
            from .scheduling import _local_work
            pending=[item for item,meta in list(_local_work.items()) if meta.get('job_id')==ident]
            if pending: await asyncio.gather(*pending,return_exceptions=True)
        else: raise ValueError('当前任务状态不支持这项操作')
        scheduler().wake()
        return library.public_job(one('SELECT * FROM library_jobs WHERE id=?',(ident,)))

    async def close(self):
        if self.loop_task: self.loop_task.cancel(); await asyncio.gather(self.loop_task,return_exceptions=True)
        tasks=list(self.tasks.values())
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks,return_exceptions=True)
        # Interrupted running jobs are recovered on next application start.
