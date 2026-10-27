import asyncio
from types import SimpleNamespace

import fitz
import pytest
from fastapi.testclient import TestClient

from studyforge import ai, conversations, library, library_models, library_ranges, library_worker, providers, server
from studyforge.db import create_project, execute, many, one, unj


def book(tmp_path):
    path=tmp_path/'model-test.pdf'
    with fitz.open() as pdf:
        page=pdf.new_page();page.insert_text((40,80),'SOURCE_ONLY: a number field is closed under addition and subtraction. This is the authorized original page.')
        pdf.save(path)
    b=library.import_book(path,path.name)['book']
    n=library.add_node(b['id'],'数域')
    n=library.update_node(n['id'],{'start_page':1,'end_page':1,'confirmed':True})
    return b,n


def preference(**values):
    return library_models.DEFAULTS | {'mode':'independent','provider':'deepseek','model':'reader-a','effort':'high'} | values


def test_independent_choice_survives_reload_without_changing_workbench_or_messages():
    p=create_project('独立工作台');c=conversations.create(p['id'],'deepseek',model='workbench-model',effort='low')
    before=ai.settings().copy()
    with TestClient(server.app) as client:
        assert client.get('/api/library/models').json()['selection']['mode']=='follow'
        response=client.put('/api/library/models',json=preference(vision_mode='custom',vision_model='vision-a',revision=0))
        assert response.status_code==200,response.text
        saved=client.get('/api/library/models').json()['selection']
    assert saved['model']=='reader-a' and saved['vision_model']=='vision-a' and saved['revision']==1
    assert one('SELECT model,reasoning_effort FROM conversations WHERE id=?',(c['id'],))=={'model':'workbench-model','reasoning_effort':'low'}
    assert not many('SELECT * FROM messages') and ai.settings()==before


def test_other_window_cannot_overwrite_newer_library_selection():
    first=library_models.save(preference(),0)
    with pytest.raises(library_models.ModelPreferenceConflict):library_models.save(preference(model='stale'),0)
    assert library_models.selection()==first
    with TestClient(server.app) as client:
        response=client.put('/api/library/models',json=preference(model='stale',revision=0))
        assert response.status_code==409
    assert library_models.selection()['model']=='reader-a'


@pytest.mark.parametrize('changes,status',[
    ({'effort':'nonsense'},400),({'vision_mode':'custom','vision_model':None},400),
    ({'model':'bad\nname'},400),({'provider':'removed-provider'},400),({'revision':True},422),
    ({'mode':'unknown'},422),({'api_key':'do-not-store'},422),
])
def test_invalid_configuration_never_replaces_saved_choice(changes,status):
    with TestClient(server.app) as client:
        response=client.put('/api/library/models',json=preference(**({'revision':0}|changes)))
        assert response.status_code==status,response.text
        assert client.get('/api/library/models').json()['selection']['revision']==0


def test_registry_allows_third_party_models_but_does_not_publish_secrets_or_urls(monkeypatch):
    monkeypatch.setattr(providers,'set_secret',lambda *args:None)
    service=providers.save_service({'name':'我的 Gemini 服务','protocol':'gemini','base_url':'https://example.com/v1beta',
        'default_model':'my-gemini','models':['my-gemini'],'requires_key':True,'api_key':'SECRET_NEVER_PUBLIC'})
    result=library_models.public();row=next(r for r in result['services'] if r['id']==service['id'])
    assert row['models']==['my-gemini'] and 'base_url' not in row and 'api_key' not in row
    assert 'SECRET_NEVER_PUBLIC' not in str(result)
    assert isinstance(row['supports_vision'],bool)
    saved=library_models.save(preference(provider=service['id'],model='my-gemini',effort=None),0)
    assert saved['provider']==service['id']
    with pytest.raises(ValueError):library_models.save(preference(provider=service['id'],effort='high'),saved['revision'])


def test_read_job_freezes_both_models_and_has_no_chat_context(tmp_path,monkeypatch):
    b,n=book(tmp_path)
    ai.save_settings({'deepseek_model':'reader-default','deepseek_vision_model':'vision-at-launch'})
    job=library_worker.new_read_job(b['id'],[n['id']],'deepseek',effort='high')
    payload=job['payload'];assert payload['model']=='reader-default' and payload['vision_model']=='vision-at-launch'
    assert 'conversation_id' not in payload and 'messages' not in payload
    ai.save_settings({'deepseek_model':'changed-reader','deepseek_vision_model':'changed-vision'})
    monkeypatch.setattr(ai,'get_secret',lambda name:'fixture-key')
    client=library_worker.default_client(payload)
    assert client.model=='reader-default' and client.vision_model=='vision-at-launch' and client.effort=='high'
    assert client.agent_runtime is None and client.conversation is None and not client.session_messages
    assert client.fork().vision_model=='vision-at-launch'
    captured=[]
    async def request(body,**kwargs):
        from studyforge.vision_batches import resolve_request_body
        captured.append(await resolve_request_body(body));return 'source-only note'
    monkeypatch.setattr(client,'_request_content',request)
    asyncio.run(client.complete('source rules','SOURCE_ONLY'))
    assert [r['content'] for r in captured[0]['messages']]==['source rules','SOURCE_ONLY']
    image=tmp_path/'image.png'
    from PIL import Image
    Image.new('RGB',(80,80),'white').save(image)
    asyncio.run(client.analyze_image(image,'PDF 1','SOURCE_ONLY'))
    assert captured[1]['model']=='vision-at-launch'
    assert one('SELECT payload_json FROM library_jobs WHERE id=?',(job['id'],)) is not None


def test_changed_vision_model_creates_new_reading_and_preserves_legacy_versions(tmp_path):
    b,n=book(tmp_path);inputs=[]
    class Client:
        def __init__(self,p):self.model=p['model'];self.effort=p['effort'];self.vision_model=p['vision_model']
        async def complete(self,system,user,**kwargs):inputs.append(user);return 'SOURCE_ONLY: closure definition. [PDF 1]'
        async def close(self):pass
    async def run(vision):
        job=library_worker.new_read_job(b['id'],[n['id']],'deepseek','reader-a','high',vision_model=vision)
        worker=library_worker.LibraryWorker(Client);worker.launch(job['id']);await worker.tasks[job['id']]
        return library.public_job(one('SELECT * FROM library_jobs WHERE id=?',(job['id'],)))
    a=asyncio.run(run('vision-a'));assert a['status']=='completed',a
    repeat=asyncio.run(run('vision-a'));assert repeat['status']=='completed' and len(inputs)==1
    changed=asyncio.run(run('vision-b'));assert changed['status']=='completed' and len(inputs)==2
    variants=library.reading_variants(n,b)
    assert len(variants)==2 and {r['vision_model'] for r in variants}=={'vision-a','vision-b'}
    assert all(library.valid_reading(r,n,b) for r in variants)
    assert library.directory_suggestions('数域')['nodes'][0]['state']=='read'
    p=conversations.create(create_project('引用项目')['id'],'deepseek')
    assert library.add_reference(p['id'],p['project_id'],n['id'])['references']


def test_range_to_read_handoff_keeps_launch_models(tmp_path):
    b,n=book(tmp_path)
    library.update_node(n['id'],{'confirmed':False})
    ai.save_settings({'deepseek_vision_model':'vision-range-launch'})
    range_job=library_ranges.range_job(b['id'],[n['id']],'deepseek','reader-a','high',read_after=True)
    payload=range_job['payload']
    ai.save_settings({'deepseek_vision_model':'changed-after-locating'})
    n=library.update_node(n['id'],{'confirmed':True})
    # The actual applied-range handoff checks its saved original scope.
    execute("UPDATE library_jobs SET status='completed' WHERE id=?",(range_job['id'],))
    output=library_ranges.finish_ranges(SimpleNamespace(job_id=range_job['id']),b,payload,
        {'output':{'pending_node_ids':[]},'versions':{n['id']:library.version(b,n)}})
    read=unj(one('SELECT payload_json FROM library_jobs WHERE id=?',(output['read_job_id'],))['payload_json'])
    assert read['vision_model']=='vision-range-launch' and read['model']=='reader-a' and read['effort']=='high'


def test_phone_models_route_requires_pairing_and_cannot_modify_other_settings():
    from test_mobile_access import mobile_client,pair
    manager,client=mobile_client()
    assert client.get('/api/library/models').status_code==401
    pair(manager,client)
    assert client.get('/api/library/models').status_code==200
    assert client.put('/api/library/models',json=preference(revision=0)).status_code==200
    assert client.put('/api/settings',json={'deepseek_model':'changed'}).status_code==403
    assert client.post('/api/library/models',json={}).status_code==403
