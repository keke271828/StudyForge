import asyncio
import copy
import json
import re
from types import SimpleNamespace

from PIL import Image
import pytest

from studyforge import ai, vision_inflight
from studyforge.db import create_job, create_project, many, one
from studyforge.generation_control import GenerationControl, PausableClient
from studyforge.scheduling import model_slot, resource_slot


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(ai, 'get_secret', lambda _: 'fixture-private-account')
    ai._VISION_CACHE.clear()
    yield
    ai._VISION_CACHE.clear()


def material(tmp_path, count=8):
    parts = []
    for i in range(count):
        path = tmp_path / f'{i}.png'
        Image.new('RGB', (40, 40), (i * 20, 40, 60)).save(path)
        parts.append(dict(locator=f'{i} 秒', text=f'原文 {i}', kind='image', meta={'image_path': str(path)}))
    return dict(id='same-source', name='同一原资料', segments=parts)


def frames(value):
    return [dict(id=str(i),path=part['meta']['image_path'],locator=value['name']+'｜'+part['locator'],ocr=part['text'])
            for i,part in enumerate(value['segments'])]


class Requests:
    def __init__(self):
        self.calls = []; self.started = asyncio.Event(); self.release = None
    async def request(self, client, body, **kwargs):
        from studyforge.vision_batches import admitted_request_body
        async with admitted_request_body(body, client.provider, client.agent_runtime) as body:
            content = body['messages'][1]['content']
            texts = [item['text'] for item in content if item['type'] == 'text']
            self.calls.append(texts); self.started.set()
            if self.release: await self.release.wait()
            else: await asyncio.sleep(.04)
            values=[dict(id=re.search('图片ID：([^；]+)',text)[1], observation='独立观察 '+text.split('\n')[-1]) for text in texts]
            return json.dumps({'frames':values},ensure_ascii=False) if 'frames' in body['messages'][0]['content'] else values[0]['observation']


def native(requests, project=None):
    client=ai.DeepSeekClient('same-writer',vision_model='same-vision',effort='high',
                             agent_runtime=SimpleNamespace(project_id=project,job_id=None,conversation_id=None))
    async def request(body, **kwargs):return await requests.request(client,body,**kwargs)
    client._request_content=request
    return client


def test_two_cold_source_reads_use_one_set_of_requests(tmp_path):
    value=material(tmp_path)
    async def run():
        requests=Requests();stats=[[],[]];a=native(requests);b=native(requests)
        outputs=await asyncio.gather(ai.source_digest(a,[value],on_cache=stats[0].append),
                                     ai.source_digest(b,[value],on_cache=stats[1].append))
        assert outputs[0]==outputs[1]
        assert len(requests.calls)==2
        assert sum(s[0]['inflight_hits'] for s in stats)==8
        assert sum(s[0]['new_images'] for s in stats)==8
        assert not vision_inflight._loops[asyncio.get_running_loop()]
    asyncio.run(run())


def test_partial_overlap_and_different_ids_share_only_same_images(tmp_path):
    value=material(tmp_path,6);items=frames(value)
    async def run():
        requests=Requests();requests.release=asyncio.Event();a=native(requests);b=native(requests)
        first=asyncio.create_task(a.analyze_images(items[:4]));await requests.started.wait()
        second_frames=[dict(item,id='other-'+item['id']) for item in items[2:]]
        second=asyncio.create_task(b.analyze_images(second_frames))
        await asyncio.sleep(.04);requests.release.set()
        one_result,two_result=await asyncio.gather(first,second)
        assert len(requests.calls)==2 and sum(len(call) for call in requests.calls)==6
        assert two_result['other-2']==one_result['2'] and two_result['other-3']==one_result['3']
        assert len(two_result)==4
    asyncio.run(run())


@pytest.mark.parametrize('difference',['vision_model','effort','endpoint','account','project','ocr','locator','pixels'])
def test_different_actual_inputs_never_share(tmp_path,difference):
    value=material(tmp_path,1);items=frames(value)
    async def run():
        requests=Requests();requests.release=asyncio.Event();a=native(requests,'project-A');b=native(requests,'project-A')
        first=asyncio.create_task(a.analyze_images(items));await requests.started.wait()
        different=copy.deepcopy(items)
        if difference=='vision_model':b._vision_model='different-image-model'
        elif difference=='effort':b.effort='low'
        elif difference=='endpoint':b.service={'base_url':'https://different.example','protocol':'openai'}
        elif difference=='account':b.key='different-private-key'
        elif difference=='project':b.agent_runtime.project_id='project-B'
        elif difference=='ocr':different[0]['ocr']='另一份OCR'
        elif difference=='locator':different[0]['locator']='其他位置'
        elif difference=='pixels':Image.new('RGB',(40,40),'black').save(items[0]['path'])
        second=asyncio.create_task(b.analyze_images(different));await asyncio.sleep(.04);requests.release.set()
        results=await asyncio.gather(first,second,return_exceptions=True)
        assert len(requests.calls)==2
        if difference=='pixels':assert isinstance(results[0],ValueError)
        else:assert all(isinstance(result,dict) for result in results)
        assert not vision_inflight._loops[asyncio.get_running_loop()]
    asyncio.run(run())


def test_cancelling_one_waiter_keeps_producer_and_other_waiter_alive(tmp_path):
    items=frames(material(tmp_path,1))
    async def run():
        requests=Requests();requests.release=asyncio.Event()
        owner=asyncio.create_task(native(requests).analyze_images(items));await requests.started.wait()
        cancelled=asyncio.create_task(native(requests).analyze_images(items))
        remaining=asyncio.create_task(native(requests).analyze_images(items));await asyncio.sleep(.03)
        cancelled.cancel();await asyncio.gather(cancelled,return_exceptions=True)
        requests.release.set();results=await asyncio.gather(owner,remaining)
        assert results[0]==results[1] and len(requests.calls)==1
        assert not vision_inflight._loops[asyncio.get_running_loop()]
    asyncio.run(run())


def test_cancelled_producer_hands_off_without_cancelling_waiter(tmp_path):
    items=frames(material(tmp_path,1))
    async def run():
        requests=Requests();requests.release=asyncio.Event()
        owner=asyncio.create_task(native(requests).analyze_images(items));await requests.started.wait()
        waiter=asyncio.create_task(native(requests).analyze_images(items));await asyncio.sleep(.03)
        owner.cancel();await asyncio.gather(owner,return_exceptions=True)
        requests.release.set();assert await asyncio.wait_for(waiter,2)
        assert len(requests.calls)==2 and not vision_inflight._loops[asyncio.get_running_loop()]
    asyncio.run(run())


def test_failing_producer_does_not_publish_its_error_as_an_observation(tmp_path):
    items=frames(material(tmp_path,1))
    async def run():
        started=asyncio.Event();release=asyncio.Event();calls=[]
        async def bad(selected):started.set();await release.wait();raise RuntimeError('fixture account failure')
        async def good(selected):calls.extend(selected);return {item['id']:'本任务自己的有效观察' for item in selected}
        first=asyncio.create_task(vision_inflight.observe(native(Requests()),items,bad));await started.wait()
        second=asyncio.create_task(vision_inflight.observe(native(Requests()),items,good));await asyncio.sleep(.03);release.set()
        values=await asyncio.gather(first,second,return_exceptions=True)
        assert isinstance(values[0],RuntimeError) and values[1]=={'0':'本任务自己的有效观察'} and len(calls)==1
    asyncio.run(run())


def test_missing_batch_id_is_not_shared_as_success(tmp_path):
    items=frames(material(tmp_path,2))
    async def run():
        started=asyncio.Event();release=asyncio.Event();calls=[]
        async def partial(selected):started.set();await release.wait();return {'0':'第0图的观察'}
        async def good(selected):calls.extend(selected);return {item['id']:'第'+item['id']+'图的观察' for item in selected}
        first=asyncio.create_task(vision_inflight.observe(native(Requests()),items,partial));await started.wait()
        second=asyncio.create_task(vision_inflight.observe(native(Requests()),items,good));await asyncio.sleep(.03);release.set()
        a,b=await asyncio.gather(first,second)
        assert a=={'0':'第0图的观察'} and b=={'0':'第0图的观察','1':'第1图的观察'}
        assert [item['id'] for item in calls]==['1']
    asyncio.run(run())


def test_paused_waiter_saves_completed_step_then_resumes_without_new_request(tmp_path):
    items=frames(material(tmp_path,1));project=create_project('separate lifecycle')
    async def run():
        requests=Requests();requests.release=asyncio.Event()
        job_a=create_job(project['id'],'generate',{});job_b=create_job(project['id'],'generate',{})
        ca=GenerationControl(job_a);cb=GenerationControl(job_b)
        a=asyncio.create_task(PausableClient(native(requests,project['id']),ca).analyze_images(items))
        await requests.started.wait()
        b=asyncio.create_task(PausableClient(native(requests,project['id']),cb).analyze_images(items))
        async def waiting():
            while not any(step.waiting for step in cb.operations):await asyncio.sleep(.005)
        await asyncio.wait_for(waiting(),2)
        cb.pause();assert one('SELECT status FROM jobs WHERE id=?',(job_b,))['status']=='paused'
        requests.release.set();result=await a;await asyncio.sleep(.03)
        assert not b.done() and many('SELECT response FROM generation_steps WHERE job_id=?',(job_b,))
        cb.resume();assert await asyncio.wait_for(b,2)==result and len(requests.calls)==1
    asyncio.run(run())


def test_paused_owner_before_admission_does_not_block_other_task(tmp_path):
    items=frames(material(tmp_path,1));project=create_project('paused owner')
    async def run():
        requests=Requests();job=create_job(project['id'],'generate',{});control=GenerationControl(job)
        async with resource_slot('image_prepare'):
            owner=asyncio.create_task(PausableClient(native(requests,project['id']),control).analyze_images(items))
            while not vision_inflight._loops.get(asyncio.get_running_loop()):await asyncio.sleep(.005)
            control.pause()
            other=asyncio.create_task(native(requests,project['id']).analyze_images(items));await asyncio.sleep(.03)
        assert await asyncio.wait_for(other,2)
        assert not owner.done() and one('SELECT status FROM jobs WHERE id=?',(job,))['status']=='paused'
        control.resume();assert await asyncio.wait_for(owner,2)
        assert not vision_inflight._loops[asyncio.get_running_loop()]
    asyncio.run(run())


def test_cancelled_source_read_leaves_no_sibling_image_workers(tmp_path):
    value=material(tmp_path,12)
    async def run():
        requests=Requests();requests.release=asyncio.Event();client=native(requests)
        task=asyncio.create_task(ai.source_digest(client,[value]));await requests.started.wait();await asyncio.sleep(.03)
        task.cancel();await asyncio.gather(task,return_exceptions=True)
        assert not vision_inflight._loops[asyncio.get_running_loop()]
        assert not [item for item in asyncio.all_tasks() if item is not asyncio.current_task()
                    and 'source_digest' in item.get_coro().__qualname__]
    asyncio.run(run())


def test_registry_saturation_falls_back_without_retaining_payloads(tmp_path,monkeypatch):
    monkeypatch.setattr(vision_inflight,'MAX_IMAGES',1)
    items=frames(material(tmp_path,4))
    async def run():
        client=native(Requests());peak=[]
        async def operation(selected):
            registry=vision_inflight._loops[asyncio.get_running_loop()]
            peak.append(len(registry));assert all(len(key)==64 for key in registry)
            return {item['id']:'完整观察 '+item['ocr'] for item in selected}
        assert len(await vision_inflight.observe(client,items,operation))==4
        assert max(peak)==1 and not vision_inflight._loops[asyncio.get_running_loop()]
    asyncio.run(run())


def test_concurrent_generation_saves_reuse_evidence_and_separate_artifacts(tmp_path,monkeypatch):
    from studyforge import server,materials
    from studyforge.db import execute,j,now,uid
    value=material(tmp_path,8);project=create_project('concurrent generation')
    value.update(project_id=project['id'],original_path=value['segments'][0]['meta']['image_path'],status='ready',kind='.png')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
        (value['id'],project['id'],value['name'],'.png',value['original_path'],j(value['segments']),'ready',now()))
    monkeypatch.setattr(materials,'parse_file',lambda path:copy.deepcopy(value['segments']))
    requests=Requests()
    def factory(*args,**kwargs):
        client=native(requests,project['id'])
        async def complete(system,user,**options):
            return '# 原资料讲解\n\n完整原图与文字保留。\n\n## 系统性总结\n结合原图核对各项条件。'
        client.complete=complete
        return client
    monkeypatch.setattr(server,'client_for',factory)
    request=server.GenerateIn(project_id=project['id'],source_ids=[value['id']],provider='deepseek',format='docx',review_mode='express')
    async def run():
        jobs=[create_job(project['id'],'generate',request.model_dump()) for _ in range(2)]
        await asyncio.gather(*(server._generate_job(job,request) for job in jobs))
        rows=[one('SELECT status,error,result_json FROM jobs WHERE id=?',(job,)) for job in jobs]
        assert all(row['status']=='completed' for row in rows),rows
        stats=[json.loads(row['result_json'])['vision_reuse'] for row in rows]
        assert sum(row['inflight_hits'] for row in stats)==8 and len(requests.calls)==2
        artifacts=many('SELECT path,metadata_json FROM artifacts WHERE project_id=?',(project['id'],))
        assert len(artifacts)==2 and artifacts[0]['path']!=artifacts[1]['path']
        assert sum(json.loads(row['metadata_json'])['vision_reuse']['inflight_hits'] for row in artifacts)==8
    asyncio.run(run())


def test_agent_or_unknown_image_adapter_is_not_coalesced(tmp_path):
    value=material(tmp_path,1)
    async def run():
        calls=[]
        class Independent:
            model='agent-model';effort='high'
            async def analyze_image(self,path,locator,ocr):
                calls.append(ocr);await asyncio.sleep(.03);return '本对话独立处理的观察'
        await asyncio.gather(ai.source_digest(Independent(),[value]),ai.source_digest(Independent(),[value]))
        assert len(calls)==2 and not vision_inflight._loops.get(asyncio.get_running_loop())
    asyncio.run(run())


def test_unknown_native_subclass_does_not_inherit_request_sharing(tmp_path):
    items=frames(material(tmp_path,1))
    async def run():
        class CustomTransport(ai.DeepSeekClient):pass
        requests=Requests()
        a=CustomTransport('writer',vision_model='image');b=CustomTransport('writer',vision_model='image')
        for client in (a,b):
            async def request(body,client=client,**kwargs):return await requests.request(client,body,**kwargs)
            client._request_content=request
        await asyncio.gather(a.analyze_images(items),b.analyze_images(items))
        assert len(requests.calls)==2 and not vision_inflight._loops.get(asyncio.get_running_loop())
    asyncio.run(run())


def test_background_owner_not_admitted_yet_does_not_block_foreground(tmp_path,monkeypatch):
    from studyforge import scheduling
    items=frames(material(tmp_path,1));busy={'value':True}
    monkeypatch.setattr(scheduling,'library_foreground_busy',lambda:busy['value'])
    async def run():
        requests=Requests()
        async with scheduling.execution_scope(background_library=True,priority=10):
            background=asyncio.create_task(native(requests).analyze_images(items))
        async def claimed():
            while not vision_inflight._loops.get(asyncio.get_running_loop()):await asyncio.sleep(.005)
        await asyncio.wait_for(claimed(),2)
        assert await asyncio.wait_for(native(requests).analyze_images(items),2)
        assert not background.done()
        busy['value']=False;scheduling.wake_schedulers()
        assert await asyncio.wait_for(background,2) and len(requests.calls)==2
        assert not vision_inflight._loops[asyncio.get_running_loop()]
    asyncio.run(run())


def test_large_observation_is_preserved_but_not_shared_in_future(tmp_path):
    items=frames(material(tmp_path,1))
    async def run():
        started=asyncio.Event();release=asyncio.Event();calls=[]
        async def large(selected):started.set();await release.wait();return {'0':'原始完整观察'*6000}
        async def independent(selected):calls.extend(selected);return {'0':'独立观察'}
        first=asyncio.create_task(vision_inflight.observe(native(Requests()),items,large));await started.wait()
        second=asyncio.create_task(vision_inflight.observe(native(Requests()),items,independent));await asyncio.sleep(.02);release.set()
        a,b=await asyncio.gather(first,second)
        assert len(a['0'])>32000 and b['0']=='独立观察' and len(calls)==1
    asyncio.run(run())
