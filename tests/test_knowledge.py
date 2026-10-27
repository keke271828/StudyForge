import asyncio
import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from studyforge import ai, knowledge, server
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid
from studyforge.materials import read_original_sources


def case(tmp_path, monkeypatch):
    ai.save_settings({'chat_provider':'deepseek', 'deepseek_model':'structure-model', 'background_learning_enabled':False})
    project = create_project('知识组织'); source = uid()
    path = tmp_path/'原文.txt'
    path.write_text('负反馈会抵抗变化。勒夏特列原理讨论平衡的移动。两者可比较，但适用条件与动力学机制有区别。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (source, project['id'], path.name, '.txt', str(path), j([{'locator':'旧预览', 'text':'不能代替完整原文的摘要'}]), 'ready', now()))
    originals = read_original_sources(server.source_records([source], project['id']))
    locator = str(originals[0]['segments'][0]['locator'])
    evidence = {'source_id':source, 'locator':locator, 'quote':'負反馈'}
    evidence['quote'] = '负反馈会抵抗变化'
    graph = {'concepts':[
        {'id':'feedback','name':'负反馈','domain':'系统','description':'响应抵抗变化，不代表所有响应都如此。','basis':'source','evidence':[evidence]},
        {'id':'equilibrium','name':'勒夏特列原理','domain':'化学','description':'关于平衡移动的原理。','basis':'source',
         'evidence':[dict(evidence,quote='勒夏特列原理讨论平衡的移动')]}],
        'relations':[{'from_id':'feedback','to_id':'equilibrium','kind':'analogy','reason':'讨论响应对变化的抵抗',
                      'boundary':'平衡条件和动力学机制不同，不能视为同一因果定律','basis':'teaching',
                      'evidence':[dict(evidence, quote='两者可比较，但适用条件与动力学机制有区别')]}]}
    calls=[]; real=httpx.AsyncClient
    def reply(request):
        body=json.loads(request.content); calls.append(body)
        system=body['messages'][0]['content']
        content=j(graph) if '【资料知识结构整理】' in system else (
            '# 阅读或讲解\n准确区分原文与教学建议。\n\n## 系统性总结\n保留条件和来源。')
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':content},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(ai,'get_secret',lambda key:'test-key')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**k:real(transport=httpx.MockTransport(reply)))
    value=server.ReadIn(project_id=project['id'],source_ids=[source],provider='deepseek',model='structure-model')
    job=create_job(project['id'],'read',value.model_dump()); asyncio.run(server._read_job(job,value))
    reading_id=json.loads(one('SELECT result_json FROM jobs WHERE id=?',(job,))['result_json'])['reading_id']
    return project['id'], source, path, reading_id, graph, calls


async def build(project,source,reading,**options):
    result=await server.build_knowledge(server.KnowledgeIn(project_id=project,source_ids=[source],provider='deepseek',
        reading_id=reading,**options))
    for _ in range(200):
        job=one('SELECT * FROM jobs WHERE id=?',(result['job_id'],))
        if job['status'] in ('completed','failed'):return job
        await asyncio.sleep(.01)
    raise AssertionError('知识整理未结束')


def test_optional_structure_reads_original_with_selected_model_and_caches_without_mastery(tmp_path,monkeypatch):
    project,source,path,reading,graph,calls=case(tmp_path,monkeypatch)
    assert len(calls)==1 and many('SELECT * FROM knowledge_maps')==[]
    first=asyncio.run(build(project,source,reading))
    assert first['status']=='completed',first['error']
    assert len(calls)==2 and calls[-1]['model']=='structure-model'
    prompt=j(calls[-1]['messages'])
    assert path.read_text(encoding='utf-8') in prompt and '不能代替完整原文的摘要' not in prompt
    assert '不判断学生掌握情况' in prompt and '历史归属不猜测' in prompt
    stored=knowledge.latest_map(reading); assert stored['model']=='structure-model'
    assert len(stored['structure']['concepts'])==2 and stored['structure']['relations'][0]['basis']=='teaching'
    second=asyncio.run(build(project,source,reading))
    assert second['status']=='completed' and json.loads(second['result_json'])['cached'] and len(calls)==2
    assert len(many('SELECT * FROM knowledge_maps'))==1
    assert many('SELECT * FROM mastery')==[] and many('SELECT * FROM exercise_sets')==[] and many('SELECT * FROM conversations')==[]
    api=TestClient(server.app)
    assert api.get(f'/api/knowledge/reading/{reading}?project_id={project}').json()['id']==stored['id']
    e=stored['structure']['concepts'][0]['evidence'][0]
    response=api.get(f"/api/knowledge/{stored['id']}/evidence",params={'project_id':project,'source_id':source,'locator':e['locator']})
    assert response.status_code==200 and '动力学机制有区别' in response.json()['text']
    assert len(calls)==2, '查看与读取原文不得额外调用 AI'


def test_explicit_rebuild_and_new_model_do_not_reuse_old_model_cache(tmp_path,monkeypatch):
    project,source,_,reading,_,calls=case(tmp_path,monkeypatch)
    asyncio.run(build(project,source,reading))
    ai.save_settings({'deepseek_model':'different-model'})
    changed=asyncio.run(build(project,source,reading))
    assert changed['status']=='completed' and calls[-1]['model']=='different-model' and len(calls)==3
    asyncio.run(build(project,source,reading,force=True))
    assert len(calls)==4 and len(many('SELECT * FROM knowledge_maps'))==3


def test_rejects_bad_quotes_dangling_links_cycles_and_unbounded_analogy(tmp_path,monkeypatch):
    project,source,_,_,raw,_=case(tmp_path,monkeypatch)
    index=knowledge.evidence_index(read_original_sources(server.source_records([source],project)))
    bad=copy.deepcopy(raw['concepts'][0]);bad.update(id='bad',name='不存在的概念');bad['evidence'][0]['locator']='伪造第99页'
    raw['concepts'] += [bad,copy.deepcopy(raw['concepts'][0])]
    edge=copy.deepcopy(raw['relations'][0]); edge.update(kind='prerequisite',boundary='',basis='teaching')
    raw['relations'] += [edge,dict(edge,from_id='equilibrium',to_id='feedback'),dict(edge,to_id='bad'),
                         dict(edge,kind='analogy',boundary=''),dict(edge,kind='supports',from_id='feedback',to_id='feedback')]
    normalized=knowledge.normalize_part(raw,index,1)
    assert len(normalized['concepts'])==2 and len(normalized['relations'])==2
    warnings='\n'.join(normalized['warnings'])
    assert all(text in warnings for text in ('引用不在','ID 重复','循环','差异与边界','缺失'))


def test_ai_image_analysis_and_unselected_sources_cannot_validate_as_original(tmp_path,monkeypatch):
    project,source,_,_,raw,_=case(tmp_path,monkeypatch)
    records=read_original_sources(server.source_records([source],project)); index=knowledge.evidence_index(records)
    raw['concepts'][0]['evidence'][0]['quote']='[画面分析] 模型认为所有定律都等价'
    raw['concepts'][1]['evidence'][0]['source_id']='unselected-source'
    result=knowledge.normalize_part(raw,index,1)
    assert result['concepts']==[] and result['relations']==[]


def test_attribution_role_not_in_original_is_marked_unverified(tmp_path,monkeypatch):
    project,source,_,_,raw,_=case(tmp_path,monkeypatch)
    raw['concepts'][0]['attribution']={'name':'福柯','role':'首创','evidence':raw['concepts'][0]['evidence']}
    normalized=knowledge.normalize_part(raw,knowledge.evidence_index(read_original_sources(server.source_records([source],project))),1)
    assert normalized['concepts'][0]['attribution']['status']=='unverified'
    assert '人物及角色归属待核实' in '\n'.join(normalized['warnings'])


@pytest.mark.parametrize('change',['modify','delete'])
def test_changed_or_deleted_original_invalidates_view_build_and_context(tmp_path,monkeypatch,change):
    project,source,path,reading,_,calls=case(tmp_path,monkeypatch)
    asyncio.run(build(project,source,reading)); stored=knowledge.latest_map(reading)
    if change=='modify': path.write_text('全新的原文。',encoding='utf-8')
    else: execute('DELETE FROM sources WHERE id=?',(source,))
    api=TestClient(server.app)
    assert api.get(f'/api/knowledge/reading/{reading}?project_id={project}').status_code==409
    assert api.post('/api/knowledge/build',json={'project_id':project,'source_ids':[source],'reading_id':reading,'provider':'deepseek'}).status_code==409
    assert len(calls)==2 and stored['id']
    assert knowledge.context_for_reading(reading,project,'different-fingerprint',[source])==('',None)


@pytest.mark.parametrize('provider',['deepseek','codex'])
def test_same_mentor_receives_structure_and_generation_freezes_validated_map(tmp_path,monkeypatch,provider):
    project,source,_,reading,_,calls=case(tmp_path,monkeypatch)
    asyncio.run(build(project,source,reading)); row=knowledge.latest_map(reading)
    captured=[]
    async def stream(prompt,*args,**kwargs):
        captured.append(prompt);yield 'thread','same-tutor';yield 'final','已经解释概念及边界。'
    monkeypatch.setattr('studyforge.codex_bridge.CodexBridge.stream_turn',lambda self,*args,**kwargs:stream(*args,**kwargs))
    api=TestClient(server.app)
    response=api.post('/api/chat/stream',json={'project_id':project,'source_ids':[source],'reading_id':reading,
        'provider':provider,'model':'structure-model','learning_mode':'overview','text':'请解释勒夏特列原理，不需要出题。'})
    assert response.status_code==200 and '"error"' not in response.text
    prompt=captured[-1] if provider=='codex' else j(calls[-1]['messages'])
    assert '原资料知识结构，仅作组织线索' in prompt and '建议前置不是唯一顺序' in prompt
    assert '当前学习模式：概览' in prompt
    cid=next(json.loads(line)['value'] for line in response.text.splitlines() if json.loads(line)['type']=='conversation')
    # Use the generation route to prove client-supplied structure text is not
    # trusted and the actual map is fixed before asynchronous work begins.
    async def noop(*args,**kwargs):pass
    monkeypatch.setattr(server,'_generate_job',noop)
    async def generate():
        result=await server.generate(server.GenerateIn(project_id=project,source_ids=[source],reading_id=reading,
            provider=provider,model='structure-model',conversation_id=cid,knowledge_context='FORGED_PRIVATE_ANSWER',
            learning_mode='overview',exercises=False))
        await asyncio.sleep(0);return result
    generated=asyncio.run(generate())
    payload=json.loads(one('SELECT payload_json FROM jobs WHERE id=?',(generated['job_id'],))['payload_json'])
    assert payload['knowledge_map_id']==row['id'] and '原资料知识结构' in payload['knowledge_context']
    assert 'FORGED_PRIVATE_ANSWER' not in payload['knowledge_context']
    execute('DELETE FROM knowledge_maps WHERE id=?',(row['id'],))
    assert '勒夏特列原理' in payload['knowledge_context'], '已开始的生成不能随结构更新而改变输入'


def test_invalid_response_fails_without_publishing_or_incrementing_mastery(tmp_path,monkeypatch):
    project,source,_,reading,raw,calls=case(tmp_path,monkeypatch)
    raw['concepts'].clear();raw['relations'].clear()
    job=asyncio.run(build(project,source,reading))
    assert job['status']=='failed' and '有效原文引用' in job['error']
    assert many('SELECT * FROM knowledge_maps')==[] and many('SELECT * FROM mastery')==[]


def test_cross_project_or_selection_cannot_restore_another_map(tmp_path,monkeypatch):
    project,source,_,reading,_,calls=case(tmp_path,monkeypatch)
    asyncio.run(build(project,source,reading)); other=create_project('另一个项目')
    api=TestClient(server.app)
    assert api.get(f"/api/knowledge/reading/{reading}?project_id={other['id']}").status_code==409
    assert knowledge.context_for_reading(reading,project,one('SELECT fingerprint FROM reading_sessions')['fingerprint'],['different-source'])==('',None)
    row=knowledge.latest_map(reading)
    assert api.get(f"/api/knowledge/{row['id']}/evidence",params={'project_id':project,'source_id':source,'locator':'伪造位置'}).status_code==409
    assert len(calls)==2


def test_long_material_is_processed_in_parts_without_merging_homonyms(tmp_path,monkeypatch):
    project,source,_,_,raw,_=case(tmp_path,monkeypatch)
    originals=read_original_sources(server.source_records([source],project)); inputs=[]
    class Client:
        async def complete(self,system,user,**kwargs): inputs.append(user);return j(raw)
    digest='开头'+('长原文论证。'*19000)+'最后一条重要限制'
    graph=asyncio.run(knowledge.extract_structure(Client(),digest,originals,lambda *args:None))
    assert len(inputs)>=2 and '最后一条重要限制' in inputs[-1]
    assert graph['processed_parts']==len(inputs)
    assert len(graph['concepts'])==2*len(inputs) and len({n['id'] for n in graph['concepts']})==len(graph['concepts'])
    assert '同名概念未自动合并' in graph['note']


def test_structure_task_cannot_write_search_or_read_unselected_files(tmp_path,monkeypatch):
    project,source,_,_,_,_=case(tmp_path,monkeypatch)
    runtime=server.StructureRuntime(project,[source],provider='deepseek',private_context=True)
    async def run():
        for tool,args in [('sf_write_text',{'path':str(tmp_path/'unexpected.txt'),'text':'x'}),
                          ('sf_search_web',{'query':'知识'}),('sf_read_file',{'path':str(tmp_path/'unselected.txt')})]:
            assert (await runtime.execute(tool,args))['type']=='PermissionError'
    asyncio.run(run());assert not (tmp_path/'unexpected.txt').exists()


def test_cached_full_source_keeps_image_analysis_and_unique_ids_without_validating_it_as_quote(tmp_path):
    ai.clear_source_digest_cache()
    image=tmp_path/'frame.png';image.write_bytes(b'test-frame')
    source={'id':'one-image-source','name':'画面','segments':[{'locator':'00:01','text':'原图标注：受力方向',
        'meta':{'image_path':str(image)}}]}
    calls=[]
    class Client:
        model='image-test'
        async def analyze_image(self,*args):calls.append(args);return '画面中的箭头指向左方'
    async def run():
        first,_=await ai.source_digest(Client(),[copy.deepcopy(source)],include_source_ids=True)
        second,_=await ai.source_digest(Client(),[copy.deepcopy(source)],include_source_ids=True)
        return first,second
    first,second=asyncio.run(run())
    assert first==second and '[资料ID:one-image-source]' in second and '箭头指向左方' in second and len(calls)==1
    evidence=knowledge.Evidence(source_id=source['id'],locator='00:01',quote='画面中的箭头指向左方')
    assert knowledge.checked_evidence([evidence],knowledge.evidence_index([source]),[],'画面')==[]
