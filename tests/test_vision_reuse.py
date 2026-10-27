import asyncio
import copy
import json
from pathlib import Path

from PIL import Image
import pytest

from studyforge import ai, server, vision_cache
from studyforge.config import files_dir,temp_dir
from studyforge.db import connect, create_job, create_project, execute, j, many, now, one, uid
from studyforge.generation_control import GenerationControl, PausableClient


@pytest.fixture(autouse=True)
def empty_memory():
    ai._VISION_CACHE.clear()
    yield
    ai._VISION_CACHE.clear()


def material(tmp_path, count=9, project=None):
    ident=uid();parts=[]
    for index in range(count):
        path=(files_dir() if project else tmp_path)/f'{ident}-{index}.png'
        Image.new('RGB',(12,12),(index%255,1,2)).save(path)
        parts.append({'locator':f'{index} 秒','text':f'完整OCR {index}',
            'kind':'video_frame','meta':{'image_path':str(path)}})
    result={'id':ident,'name':'原图资料','segments':parts}
    if project:
        result.update(project_id=project['id'],kind='.png',original_path=str(parts[0]['meta']['image_path']),status='ready')
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
                (ident,project['id'],result['name'],'.png',result['original_path'],j(parts),'ready',now()))
    return result


class Vision:
    model='writer-model';effort='high';vision_model='vision-A'
    def __init__(self):self.calls=0
    async def analyze_images(self,frames):
        self.calls+=1
        return {frame['id']:self.vision_model+' '+frame['ocr'] for frame in frames}
    async def analyze_image(self,path,locator,text):
        self.calls+=1
        return self.vision_model+' '+text


def test_warm_images_never_rewrite_completed_descriptions(tmp_path,monkeypatch):
    value=material(tmp_path);client=Vision();statements=[];real_connect=vision_cache.connect
    from contextlib import contextmanager
    @contextmanager
    def traced():
        with real_connect() as database:
            database.set_trace_callback(statements.append)
            yield database
    monkeypatch.setattr(vision_cache,'connect',traced)
    async def run():
        first=await ai.source_digest(client,[value]);statements.clear();calls=client.calls
        second=await ai.source_digest(client,[value])
        assert first==second and client.calls==calls
        assert not any(sql.startswith(('INSERT','DELETE')) and 'source_vision_cache' in sql for sql in statements)
        ai._VISION_CACHE.clear();statements.clear()
        assert await ai.source_digest(client,[value])==first and client.calls==calls
        assert not any(sql.startswith(('INSERT','DELETE')) and 'source_vision_cache' in sql for sql in statements)
    asyncio.run(run())


def test_actual_vision_model_change_invalidates_reused_images(tmp_path):
    value=material(tmp_path,4);client=Vision();original=copy.deepcopy(value)
    async def run():
        first,_=await ai.source_digest(client,[value]);assert client.calls==1 and 'vision-A' in first
        client.vision_model='vision-B'
        second=await ai.source_digest(client,[value]);assert client.calls==2 and 'vision-B' in second[0]
        assert await ai.source_digest(client,[value])==second
        assert client.calls==2
    asyncio.run(run());assert value==original


def test_provider_endpoint_change_does_not_reuse_another_service_reading(tmp_path):
    value=material(tmp_path,1);client=Vision();client.service={'base_url':'https://one.example/v1','protocol':'openai'}
    async def run():
        await ai.source_digest(client,[value]);assert client.calls==1
        client.service={'base_url':'https://two.example/v1','protocol':'openai'}
        await ai.source_digest(client,[value]);assert client.calls==2
    asyncio.run(run())


def test_writer_model_change_keeps_matching_explicit_image_model(tmp_path):
    value=material(tmp_path,4);client=Vision()
    async def run():
        first=await ai.source_digest(client,[value]);client.model='new-writer'
        assert await ai.source_digest(client,[value])==first and client.calls==1
    asyncio.run(run())


def test_native_image_model_is_frozen_for_the_client(monkeypatch):
    monkeypatch.setattr(ai,'get_secret',lambda _: 'fixture-key')
    ai.save_settings({'deepseek_vision_model':'vision-A'})
    client=ai.DeepSeekClient('writer')
    ai.save_settings({'deepseek_vision_model':'vision-B'})
    assert client.vision_model=='vision-A'
    assert ai.DeepSeekClient('writer').vision_model=='vision-B'


def test_cache_failure_keeps_successful_model_observations(tmp_path,monkeypatch):
    value=material(tmp_path,4);value['read_manifest']={'limitations':[]};client=Vision();stats=[]
    def fail(rows):raise OSError('fixture cache error')
    monkeypatch.setattr(vision_cache,'remember_many',fail)
    result,_=asyncio.run(ai.source_digest(client,[value],on_cache=stats.append))
    assert all('vision-A 完整OCR '+str(i) in result for i in range(4))
    assert '[画面分析待核实' not in result
    assert stats[0]['new_images']==4 and stats[0]['cache_save_failures']==4 and stats[0]['failed_images']==0
    assert value['read_manifest']['limitations']


def test_reuse_stats_distinguish_memory_disk_and_fresh_reads(tmp_path):
    value=material(tmp_path,8);client=Vision();stats=[]
    async def run():
        first=await ai.source_digest(client,[value],on_cache=stats.append)
        assert stats[-1]['new_images']==8 and stats[-1]['memory_hits']==stats[-1]['disk_hits']==0
        assert await ai.source_digest(client,[value],on_cache=stats.append)==first
        assert stats[-1]['memory_hits']==8 and stats[-1]['new_images']==0
        ai._VISION_CACHE.clear()
        assert await ai.source_digest(client,[value],on_cache=stats.append)==first
        assert stats[-1]['disk_hits']==8 and stats[-1]['new_images']==0
    asyncio.run(run())


def test_project_cache_cleanup_preserves_other_projects_and_global_books(tmp_path):
    first_project=create_project('first');other_project=create_project('other')
    first=material(tmp_path,1,first_project);other=material(tmp_path,1,other_project);book=material(tmp_path,1);client=Vision()
    async def run():
        await ai.source_digest(client,[first]);other_before=await ai.source_digest(client,[other]);book_before=await ai.source_digest(client,[book])
        ai.clear_source_digest_cache(project_id=first_project['id'])
        assert len(many('SELECT cache_key FROM source_vision_cache'))==2
        assert await ai.source_digest(client,[other])==other_before
        assert await ai.source_digest(client,[book])==book_before and client.calls==3
    asyncio.run(run())


def test_cache_cleared_during_read_is_not_repopulated(tmp_path):
    value=material(tmp_path,1);client=Vision()
    async def reading(*args):
        ai.clear_source_digest_cache(source_id=value['id'])
        return '开始读取时的图像记录'
    client.analyze_image=reading
    result,_=asyncio.run(ai.source_digest(client,[value]))
    assert '开始读取时的图像记录' in result
    assert not many('SELECT cache_key FROM source_vision_cache') and not ai._VISION_CACHE


@pytest.mark.parametrize('batch',[False,True])
def test_saved_image_step_uses_the_actual_vision_model(tmp_path,batch):
    value=material(tmp_path,2);client=Vision();project=create_project('model identity')
    job=create_job(project['id'],'generate',{});control=GenerationControl(job)
    async def run():
        paused=PausableClient(client,control)
        frames=[dict(id=str(index),path=item['meta']['image_path'],locator=item['locator'],ocr=item['text']) for index,item in enumerate(value['segments'])]
        async def read():
            return await paused.analyze_images(frames) if batch else await paused.analyze_image(Path(frames[0]['path']),frames[0]['locator'],frames[0]['ocr'])
        first=await read();assert client.calls==1
        assert await read()==first and client.calls==1
        client.vision_model='vision-B';second=await read()
        assert second!=first and client.calls==2
    try:asyncio.run(run())
    finally:control.finish()


@pytest.mark.parametrize('same_project',[True,False])
def test_deleting_one_source_preserves_other_cached_readings(tmp_path,same_project):
    first_project=create_project('first');other_project=first_project if same_project else create_project('other')
    first=material(tmp_path,1,first_project);other=material(tmp_path,1,other_project);client=Vision()
    async def run():
        await ai.source_digest(client,[first]);before=await ai.source_digest(client,[other]);assert client.calls==2
        server.delete_source(first['id'])
        assert len(many('SELECT cache_key FROM source_vision_cache'))==1
        assert await ai.source_digest(client,[other])==before and client.calls==2
        ai._VISION_CACHE.clear()
        assert await ai.source_digest(client,[other])==before and client.calls==2
    asyncio.run(run())


def test_deleting_artifact_cleans_linked_source_cache_only(tmp_path):
    project=create_project('artifact');first=material(tmp_path,1,project);other=material(tmp_path,1,project)
    ident=uid()
    execute('INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?)',
            (ident,project['id'],'[]','external','png',first['original_path'],'图像成果','{}',now()))
    execute('INSERT INTO artifact_sources VALUES (?,?)',(ident,first['id']))
    client=Vision()
    async def run():
        await ai.source_digest(client,[first]);before=await ai.source_digest(client,[other])
        server.delete_artifact(ident)
        assert len(many('SELECT cache_key FROM source_vision_cache'))==1
        assert await ai.source_digest(client,[other])==before and client.calls==2
    asyncio.run(run())


def test_deleting_one_pdf_excerpt_keeps_shared_page_and_cache(tmp_path):
    project=create_project('shared PDF page');page=temp_dir()/'shared-pdf-page.png'
    Image.new('RGB',(20,20),'white').save(page)
    first=material(tmp_path,1,project);other=material(tmp_path,1,project)
    for value in (first,other):
        value['segments'][0]['meta']['image_path']=str(page)
        execute('UPDATE sources SET segments_json=? WHERE id=?',(j(value['segments']),value['id']))
    client=Vision()
    async def run():
        await ai.source_digest(client,[first]);before=await ai.source_digest(client,[other]);assert client.calls==2
        server.delete_source(first['id'])
        assert page.is_file()
        ai._VISION_CACHE.clear()
        assert await ai.source_digest(client,[other])==before and client.calls==2
    asyncio.run(run())


def test_source_cleanup_tolerates_unrelated_failed_url_and_legacy_segments(tmp_path):
    project=create_project('legacy references');value=material(tmp_path,1,project)
    for path,parts in [('https://example.org/blocked','[]'),('missing.txt','["legacy text"]')]:
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (uid(),project['id'],'旧记录','.txt',path,parts,'error',now()))
    assert server.delete_source(value['id'])['deleted']


def test_generation_persists_actual_reuse_in_diagnostics_and_artifact(tmp_path,monkeypatch):
    from studyforge import materials,task_timing
    value=material(tmp_path,1,create_project('generation reuse'));client=Vision()
    async def complete(system,user):return '# 原图讲解\n\n资料中的文字保留。\n\n## 系统性总结\n需要结合原图核对条件。'
    client.complete=complete
    monkeypatch.setattr(server,'client_for',lambda *args,**kwargs:client)
    monkeypatch.setattr(materials,'parse_file',lambda path:copy.deepcopy(value['segments']))
    request=server.GenerateIn(project_id=value['project_id'],source_ids=[value['id']],provider='deepseek',format='docx',review_mode='express')
    async def run():
        jobs=[]
        for _ in range(2):
            ident=create_job(value['project_id'],'generate',request.model_dump());jobs.append(ident)
            await server._generate_job(ident,request)
            assert one('SELECT status FROM jobs WHERE id=?',(ident,))['status']=='completed'
        assert task_timing.detail(jobs[0])['vision_reuse']['new_images']==1
        assert task_timing.detail(jobs[1])['vision_reuse']['memory_hits']==1
    asyncio.run(run())
    outputs=many("SELECT metadata_json FROM artifacts WHERE project_id=? AND kind='explanation' ORDER BY created_at",(value['project_id'],))
    assert json.loads(outputs[0]['metadata_json'])['vision_reuse']['vision_model']=='vision-A'
    assert json.loads(outputs[1]['metadata_json'])['vision_reuse']['new_images']==0


def test_memory_cache_is_bounded_by_characters(tmp_path,monkeypatch):
    value=material(tmp_path,9);client=Vision()
    async def large(frames):
        return {frame['id']:'独立图像记录'*120 for frame in frames}
    monkeypatch.setattr(client,'analyze_images',large)
    monkeypatch.setattr(client,'analyze_image',lambda *args:large([{'id':'0'}]))
    monkeypatch.setattr(ai,'_VISION_CACHE_CHAR_LIMIT',1000,raising=False)
    ai._VISION_CACHE.clear()
    async def run():
        # A divisible batch count avoids a single-image fixture response.
        await ai.source_digest(client,[dict(value,segments=value['segments'][:8])])
        assert sum(len(text) for text in ai._VISION_CACHE.values())<=1000
        assert len(many('SELECT cache_key FROM source_vision_cache'))==8
    asyncio.run(run())


def test_disk_cache_batch_is_bounded_and_eviction_stays_bounded(monkeypatch):
    assert hasattr(vision_cache,'remember_many') and hasattr(vision_cache,'lookup_many')
    monkeypatch.setattr(vision_cache,'MAX_ENTRIES',3)
    rows=[{'key':str(i),'description':'记录'+str(i),'source_id':'book-node'} for i in range(4)]
    saved=vision_cache.remember_many(rows)
    assert saved and len(many('SELECT cache_key FROM source_vision_cache'))==3
    assert len(vision_cache.lookup_many([str(i) for i in range(4)]))==3
    with pytest.raises(ValueError):vision_cache.lookup_many([str(i) for i in range(65)])


def test_late_reading_cannot_repopulate_deleted_source(tmp_path):
    value=material(tmp_path,1,create_project('delete during read'));client=Vision()
    async def reading(path,locator,text):
        execute('DELETE FROM sources WHERE id=?',(value['id'],))
        return '读取开始时的图像记录'
    client.analyze_image=reading
    asyncio.run(ai.source_digest(client,[value]))
    assert not many('SELECT cache_key FROM source_vision_cache')
    assert not ai._VISION_CACHE


def test_existing_cache_schema_migrates_without_changing_description(tmp_path,monkeypatch):
    import sqlite3
    from studyforge import db
    target=tmp_path/'old-data';target.mkdir();monkeypatch.setenv('STUDYFORGE_DATA_DIR',str(target))
    with sqlite3.connect(target/'studyforge.sqlite3') as database:
        database.execute('CREATE TABLE source_vision_cache(cache_key TEXT PRIMARY KEY,description TEXT NOT NULL,characters INTEGER NOT NULL,accessed_at TEXT NOT NULL,project_id TEXT)')
        database.execute('INSERT INTO source_vision_cache VALUES (?,?,?,?,?)',('old','旧识别记录',5,now(),None))
    with db.connect() as database:
        columns={row[1] for row in database.execute('PRAGMA table_info(source_vision_cache)')}
        assert 'source_id' in columns
        assert database.execute('SELECT description FROM source_vision_cache WHERE cache_key=?',('old',)).fetchone()[0]=='旧识别记录'


@pytest.mark.parametrize('size',[0,17,4096,262143,262144,1_048_593])
def test_adaptive_file_hash_stays_exact_for_small_and_large_files(tmp_path,size):
    import hashlib
    from studyforge.materials import file_sha256
    path=tmp_path/'input.bin';path.write_bytes((bytes(range(256))*((size+255)//256))[:size])
    with path.open('rb') as stream:expected=hashlib.file_digest(stream,'sha256').hexdigest()
    assert file_sha256(path)==expected
