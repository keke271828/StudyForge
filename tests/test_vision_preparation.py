"""Image payload parity and service responsiveness under slow native encoding."""
import asyncio
import base64
import io
import threading

import pytest
from PIL import Image, ImageDraw

from studyforge import ai, vision_batches
from studyforge.scheduling import scheduler


@pytest.mark.parametrize('mode',['RGB','RGBA','L'])
def test_visual_payload_matches_previous_pixels_encoding_and_size(tmp_path,mode):
    path=tmp_path/'page.png'
    image=Image.new(mode,(1600,2000));draw=ImageDraw.Draw(image)
    draw.rectangle((50,60,1550,1900),fill='white');draw.text((100,100),'Formula x + y = 3',fill='black')
    image.save(path)
    with Image.open(path) as original:
        legacy=original.convert('RGB');legacy.thumbnail((1280,1280));buffer=io.BytesIO();legacy.save(buffer,'JPEG',quality=82)
    actual=vision_batches.image_content(path)['image_url']['url']
    assert base64.b64decode(actual.split(',',1)[1])==buffer.getvalue()


def test_queued_encoding_never_blocks_loop_or_overlaps_native_preparation(monkeypatch):
    first_entered=threading.Event();release=threading.Event();state={'active':0,'peak':0,'calls':0}
    def slow(frames,*,structured):
        state['calls']+=1;state['active']+=1;state['peak']=max(state['peak'],state['active'])
        try:
            if state['calls']==1:first_entered.set();assert release.wait(3)
            return [{'role':'user','content':'Prepared original image'}]
        finally:state['active']-=1
    monkeypatch.setattr(vision_batches,'image_messages',slow)
    monkeypatch.setattr(ai,'get_secret',lambda name:'fixture-only')
    async def scenario():
        class Client(ai.DeepSeekClient):
            async def _request_content(self,body,**kwargs):
                assert body['messages']==[{'role':'user','content':'Prepared original image'}]
                return '本图原始观察'
        client=Client('fixture');first=asyncio.create_task(client.analyze_image('first','第1页'))
        try:
            for _ in range(100):
                if first_entered.is_set():break
                await asyncio.sleep(.005)
            assert first_entered.is_set()
            second=asyncio.create_task(client.analyze_image('second','第2页'))
            # A status/chat coroutine still gets time while the first native
            # encoder runs, and the second allocates no decoded image yet.
            await asyncio.wait_for(asyncio.sleep(.025),.2)
            assert state['calls']==1 and scheduler().snapshot()['image_prepare']['queued']==1
            release.set()
            assert await first=='本图原始观察' and await second=='本图原始观察'
            assert state['peak']==1
        finally:release.set();await client.close()
    asyncio.run(scenario())


def test_cancelled_preparation_keeps_slot_until_real_encoder_finishes(monkeypatch):
    entered=threading.Event();release=threading.Event();calls=[]
    def encode(frames,*,structured):
        calls.append(frames[0]['id'])
        if len(calls)==1:entered.set();assert release.wait(3)
        return []
    monkeypatch.setattr(vision_batches,'image_messages',encode)
    async def scenario():
        first=asyncio.create_task(vision_batches.prepare_image_messages([{'id':'first'}],structured=True))
        for _ in range(100):
            if entered.is_set():break
            await asyncio.sleep(.005)
        assert entered.is_set()
        first.cancel();await asyncio.gather(first,return_exceptions=True)
        second=asyncio.create_task(vision_batches.prepare_image_messages([{'id':'second'}],structured=True))
        await asyncio.sleep(.025);assert calls==['first']
        release.set();await second;assert calls==['first','second']
    asyncio.run(scenario())


def test_cancelling_book_waits_for_its_own_encoder_without_waiting_other_projects(tmp_path,monkeypatch):
    from studyforge import library_worker
    from studyforge.scheduling import execution_scope,run_owned_io
    from test_library_policy import job
    row,_,_=job(tmp_path);entered=threading.Event();release=threading.Event();other_entered=threading.Event();other_release=threading.Event()
    def encoder(frames,*,structured):entered.set();assert release.wait(3);return []
    monkeypatch.setattr(vision_batches,'image_messages',encoder)
    async def run(control):
        async with execution_scope(job_id=row['id'],project_id=None):
            await vision_batches.prepare_image_messages([{'id':'book'}],structured=True)
    def unrelated():other_entered.set();assert other_release.wait(3)
    async def scenario():
        worker=library_worker.LibraryWorker();monkeypatch.setattr(worker,'run',run)
        worker.launch(row['id']);other=asyncio.create_task(run_owned_io(unrelated))
        try:
            for _ in range(100):
                if entered.is_set() and other_entered.is_set():break
                await asyncio.sleep(.005)
            assert entered.is_set() and other_entered.is_set()
            cancelled=asyncio.create_task(worker.action(row['id'],'cancel'))
            await asyncio.sleep(.025);assert not cancelled.done()
            release.set();result=await asyncio.wait_for(cancelled,1)
            assert result['status']=='cancelled' and not other.done()
        finally:release.set();other_release.set();await other;await worker.close()
    asyncio.run(scenario())


def test_directory_status_does_not_load_book_reading_bodies(tmp_path,monkeypatch):
    from studyforge import library,library_worker
    from studyforge.db import execute
    from test_global_library import setup_book,scoped_node,tracker,run_nodes
    book,_=setup_book(tmp_path);node=scoped_node(book)
    asyncio.run(run_nodes(book,[node],tracker()))
    execute('UPDATE library_readings SET notes=?',('正文'*100_000,))
    from contextlib import contextmanager
    statements=[];native=library.connect
    @contextmanager
    def record():
        with native() as database:
            database.set_trace_callback(statements.append)
            yield database
    monkeypatch.setattr(library,'connect',record)
    detail=library.details(book['id']);assert detail['nodes'][0]['state']=='read'
    reads=[sql for sql in statements if 'FROM library_readings' in sql]
    assert reads and all('SELECT * ' not in sql and 'notes' not in sql for sql in reads)
    assert library.ready_reading(library.node(node['id']))['notes']=='正文'*100_000
