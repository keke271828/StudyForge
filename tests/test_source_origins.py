"""Known app provenance survives actual reads, scoped excerpts and batching."""
import asyncio
import json

import pytest

from studyforge import ai,artifact_sources,source_scope
from studyforge.agent_tools import AgentRuntime
from studyforge.config import artifacts_dir
from studyforge.db import create_project,execute,j,many,now,one,uid
from studyforge.materials import read_original_sources
from studyforge.source_origins import BEGIN,END,VERSION,header,identify


def seed(tmp_path):
    project=create_project('资料身份');path=artifacts_dir()/'成果.txt';path.write_text('AI讲解正文，不能当作已经回查的教材。',encoding='utf-8');aid=uid()
    execute('INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?)',(aid,project['id'],'[]','explanation','txt',str(path),'讲解','{}',now()))
    artifact_sources.sync_project(project['id'])
    row=one('SELECT s.* FROM sources s JOIN artifact_sources x ON x.source_id=s.id WHERE x.artifact_id=?',(aid,))
    imported=tmp_path/'导入.txt';imported.write_text('用户提供的完整资料。末尾仍须读取。',encoding='utf-8');sid=uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
        (sid,project['id'],imported.name,'.txt',str(imported),j([{'text':'STALE_PREVIEW','locator':'预览'}]),'ready',now()))
    return project,row,one('SELECT * FROM sources WHERE id=?',(sid,)),aid


def test_actual_ai_and_imported_files_keep_methods_and_separate_origin(tmp_path):
    _,generated,provided,aid=seed(tmp_path)
    output=read_original_sources([generated,provided])
    assert all(r['read_manifest']['method']=='original_file' for r in output)
    first,second=(r['read_manifest']['content_origin'] for r in output)
    assert first['role']=='ai_generated_artifact' and first['artifact_id']==aid and not first['via_excerpt']
    assert second=={'role':'provided_material','verification':'not_authenticated'}
    assert '末尾仍须读取' in j(output[1]['segments']) and 'STALE_PREVIEW' not in j(output)
    assert '权威原文' in j(output[0]['read_manifest']['limitations'])


@pytest.mark.parametrize('kind,role,notice',[('original','derived_source_record','自动识别误差'),
    ('external','attached_artifact','作者与真实性未认证'),('unknown','attached_artifact','作者与真实性未认证')])
def test_transcript_and_external_attachments_are_not_claimed_as_ai_lectures(tmp_path,kind,role,notice):
    _,row,_,aid=seed(tmp_path);execute('UPDATE artifacts SET kind=? WHERE id=?',(kind,aid))
    records=read_original_sources([row]);origin=records[0]['read_manifest']['content_origin']
    assert origin['role']==role and origin['artifact_id']==aid
    digest,_=ai._assemble_source_digest(records,records,False)
    assert digest.startswith(BEGIN) and role in digest and notice in digest
    assert 'ai_generated_artifact' not in digest


def test_nested_excerpts_inherit_origin_without_reading_unselected_parent(tmp_path,monkeypatch):
    _,generated,_,aid=seed(tmp_path)
    a=source_scope.derived_source(generated,source_scope.ParseIn(mode='text',selected_text='只讨论这一句',locator='第一处'))
    first=one('SELECT * FROM sources WHERE id=?',(a['source_id'],))
    b=source_scope.derived_source(first,source_scope.ParseIn(mode='text',selected_text='句中一段',locator='第二处'))
    second=one('SELECT * FROM sources WHERE id=?',(b['source_id'],))
    from studyforge import materials
    real=materials.parsed_original
    def restricted(path,digest):
        assert path.suffix=='.sfscope','Must not parse the unselected parent file'
        return real(path,digest)
    monkeypatch.setattr(materials,'parsed_original',restricted)
    value=read_original_sources([second])[0]
    assert value['read_manifest']['content_origin']['artifact_id']==aid and value['read_manifest']['content_origin']['via_excerpt']
    assert '句中一段' in j(value['segments']) and 'AI讲解正文' not in j(value['segments'])


def test_deleted_parent_does_not_turn_an_excerpt_into_authenticated_source(tmp_path):
    _,generated,_,_=seed(tmp_path)
    value=source_scope.derived_source(generated,source_scope.ParseIn(mode='text',selected_text='已保留片段'))
    execute('DELETE FROM sources WHERE id=?',(generated['id'],))
    row=one('SELECT * FROM sources WHERE id=?',(value['source_id'],))
    origin=read_original_sources([row])[0]['read_manifest']['content_origin']
    assert origin=={'role':'excerpt_material','lineage':'unresolved','verification':'not_authenticated'}


def test_owner_mismatch_stops_before_parsing_or_returning_other_project_content(tmp_path,monkeypatch):
    _,generated,_,_=seed(tmp_path);other=create_project('另一项目')
    execute('UPDATE sources SET project_id=? WHERE id=?',(other['id'],generated['id']))
    row=one('SELECT * FROM sources WHERE id=?',(generated['id'],))
    monkeypatch.setattr('studyforge.materials.parsed_original',lambda *a:pytest.fail('No file IO for owner mismatch'))
    with pytest.raises(ValueError,match='项目归属'):read_original_sources([row])


def test_spoofed_record_hint_is_not_used_as_generation_proof(tmp_path):
    _,generated,provided,_=seed(tmp_path)
    fake=dict(provided,artifact_id='not-real')
    result=read_original_sources([fake])[0]['read_manifest']
    assert result['content_origin']['role']=='provided_material' and 'artifact_id' not in result
    with pytest.raises(ValueError,match='项目归属'):
        identify([dict(generated,project_id='wrong-owner')])


@pytest.mark.parametrize('name',['讲解.docx','讲解｜结论.docx'])
def test_long_transport_repeats_role_with_normal_locators_and_preserves_every_unit(name):
    segments=[{'locator':'第1节','text':'\n'.join(f'正文单元{i:04}。' for i in range(600))}]
    source={'id':'a','name':name,'original_path':'/not-read','segments':segments,
        'read_manifest':{'content_origin':{'role':'ai_generated_artifact','artifact_kind':'explanation'}}}
    digest,_=ai._assemble_source_digest([source],[source],False)
    values=ai.explanation_batches(digest,2000);assert len(values)>2 and all(len(v)<=2000 for v in values)
    assert all(v.startswith(BEGIN) for v in values)
    for value in values:
        raw,_,_=value[len(BEGIN):].partition(END);info=json.loads(raw)
        assert info['materials'][0]['name']==name and info['materials'][0]['role']=='ai_generated_artifact'
    joined='\n'.join(values)
    assert all(joined.count(f'正文单元{i:04}。')==1 for i in range(600))


def test_many_small_generated_sources_fit_with_only_relevant_roles_per_batch():
    records=[{'id':str(i),'name':f'成果{i:02}'+('长题名'*20)+'.txt','original_path':'/not-read',
        'segments':[{'locator':'首段','text':f'唯一内容{i:02}。'}],
        'read_manifest':{'content_origin':{'role':'ai_generated_artifact','artifact_kind':'explanation'}}} for i in range(24)]
    digest,_=ai._assemble_source_digest(records,records,False);values=ai.explanation_batches(digest,2000)
    assert all(len(v)<=2000 for v in values)
    for i,row in enumerate(records):
        containing=next(v for v in values if f'唯一内容{i:02}。' in v)
        assert row['name'] in containing and containing.startswith(BEGIN)


def test_duplicate_names_do_not_merge_generated_and_imported_identities():
    records=[{'id':sid,'name':'同名｜资料.txt','original_path':'/not-read',
        'segments':[{'locator':'行1','text':'\n'.join(f'{tag}{i:04}。' for i in range(300))}],
        'read_manifest':{'content_origin':{'role':role}}}
        for sid,tag,role in [('g','生成句','ai_generated_artifact'),('p','导入句','provided_material')]]
    digest,_=ai._assemble_source_digest(records,records,False)
    assert '[资料ID:g]' in digest and '[资料ID:p]' in digest
    values=ai.explanation_batches(digest,2000);joined='\n'.join(values)
    for tag in ('生成句','导入句'):
        assert all(joined.count(f'{tag}{i:04}。')==1 for i in range(300))
    for value in values:
        if not ('生成句' in value or '导入句' in value):continue
        info=json.loads(value[len(BEGIN):].partition(END)[0]);roles={r['source_id']:r['role'] for r in info['materials']}
        if '生成句' in value:assert roles['g']=='ai_generated_artifact' and '[资料ID:g]' in value
        else:assert 'g' not in roles
        if '导入句' in value:assert roles['p']=='provided_material' and '[资料ID:p]' in value
        else:assert 'p' not in roles


@pytest.mark.parametrize('raw',['[]','null','false','{}','{"version":"old","materials":[]}'])
def test_malformed_or_unknown_marker_is_never_silently_removed(raw):
    value=BEGIN+raw+END+'无损正文。'
    assert ai.explanation_batches(value)==[value]


def test_plain_import_digest_is_unchanged_and_metadata_does_not_force_a_registry(tmp_path):
    _,_,row,_=seed(tmp_path);records=read_original_sources([row])
    value,_=ai._assemble_source_digest(records,records,False)
    assert not value.startswith(BEGIN) and '用户提供的完整资料' in value


def test_tool_reads_and_cached_reads_both_return_known_ai_role(tmp_path):
    project,row,_,_=seed(tmp_path);ai.save_settings({'agent_tools_enabled':True,'agent_permission_mode':'read_only'})
    runtime=AgentRuntime(project['id'],[row['id']])
    for _ in range(2):
        output=asyncio.run(runtime.execute('sf_read_source',{'source_id':row['id']}))
        assert output['content_origin']['role']=='ai_generated_artifact' and 'AI讲解正文' in output['text']
    assert many('SELECT * FROM mastery')==[]


def test_summary_labels_its_actual_input_and_keeps_one_existing_request():
    from studyforge.teaching import finish_explanation
    from studyforge.source_origins import SUMMARY_RULES
    calls=[]
    class Client:
        async def complete(self,system,user):
            calls.append((system,user))
            return '## 系统性总结\n已提供的讲解说明两个开邻域不相交。'
    text='# 已完成的AI讲解\n两个开邻域不相交。'
    result=asyncio.run(finish_explanation(Client(),text))
    assert len(calls)==1 and SUMMARY_RULES in calls[0][0] and text in calls[0][1]
    assert result.startswith(text) and result.count('## 系统性总结')==1


def test_mcp_actual_source_read_reports_ai_identity_and_current_full_text(tmp_path):
    from studyforge.mcp_server import read_source
    _,row,_,aid=seed(tmp_path)
    value=read_source(row['id'])
    assert value['read_manifest']['content_origin']['artifact_id']==aid
    assert value['read_manifest']['method']=='original_file' and 'AI讲解正文' in j(value['segments'])


def test_tutor_and_agent_page_reads_keep_artifact_identity_without_expanding_scope(tmp_path,monkeypatch):
    import fitz
    from fastapi.testclient import TestClient
    from studyforge import server,conversations
    project,row,_,aid=seed(tmp_path);path=artifacts_dir()/'已有AI讲解.pdf'
    with fitz.open() as doc:
        for text in ('UNSELECTED_FIRST_PAGE','SELECTED_SECOND_PAGE'):
            page=doc.new_page();page.insert_text((50,60),text)
        doc.save(path)
    execute('UPDATE sources SET kind=?,original_path=?,name=? WHERE id=?',('.pdf',str(path),path.name,row['id']))
    execute('UPDATE artifacts SET format=?,path=? WHERE id=?',('pdf',str(path),aid))
    prompts=[]
    class Teacher:
        model='scope-fixture'
        async def agent_stream(self,messages):
            prompts.append(j(messages));yield 'final','只讲所选第2页。'
    monkeypatch.setattr(server,'DeepSeekClient',lambda *a,**k:Teacher())
    monkeypatch.setattr(server,'client_for',lambda *a,**k:Teacher())
    chat=conversations.create(project['id'],'deepseek')
    response=TestClient(server.app).post('/api/chat/stream',json={'project_id':project['id'],'conversation_id':chat['id'],
        'provider':'deepseek','source_ids':[row['id']],'text':'请只解释第2页的内容'})
    assert response.status_code==200 and prompts,response.text
    from studyforge.source_origins import RULES
    assert RULES in prompts[0]
    assert 'ai_generated_artifact' in prompts[0] and 'SELECTED_SECOND_PAGE' in prompts[0] and 'UNSELECTED_FIRST_PAGE' not in prompts[0]
    runtime=AgentRuntime(project['id'],[row['id']]);runtime.source_read_request='请只解释第2页'
    value=asyncio.run(runtime.execute('sf_read_source',{'source_id':row['id'],'page_spec':'2'}))
    assert value['content_origin']['artifact_id']==aid and not value['whole_source_read']
    assert 'SELECTED_SECOND_PAGE' in j(value) and 'UNSELECTED_FIRST_PAGE' not in j(value)
