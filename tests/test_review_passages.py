"""Exact registered coordinates, stale-state rejection and native delivery."""
import asyncio
import copy
import hashlib
import json

import pytest

from studyforge.review_corrections import apply_local_corrections
from studyforge.review_passages import VERSION,build,validated_locations

CLAIM='只要在所讨论的有限区域没有电荷，且无穷远处电场趋于零，就一定能推出这个区域内部的电场处处为零。'
FIXED='有限区域内部无电荷且远处场趋于零，仍不能排除外部电荷在区域内产生非零电场。'
ISSUES=[{'location':'条件范围','problem':'有限区域条件不足以推出内部零场。'}]


def reference(plan,document,text=CLAIM):
    return next(item['passage_id'] for item in plan['public']
                if document[plan['locations'][item['passage_id']]['start']:plan['locations'][item['passage_id']]['end']]==text)


def test_identifier_targets_one_of_two_identical_paragraphs_without_fuzzy_matching():
    document='# 正文\n\n'+CLAIM+'\n\n## 系统性总结\n\n'+CLAIM
    plan=build(document);original=copy.deepcopy(plan);receipts=[]
    selected=reference(plan,document)
    result,done=apply_local_corrections(document,[{'issue_index':0,'passage_id':selected,'after':FIXED}],ISSUES,
        passage_registry=plan,match_receipts=receipts)
    assert done==[0] and result==document.replace(CLAIM,FIXED,1) and plan==original
    assert len(receipts)==1 and receipts[0]['mode']=='registered_passage' and receipts[0]['reported_before_sha256'] is None
    assert receipts[0]['passage_id']==selected and receipts[0]['document_sha256']==hashlib.sha256(document.encode()).hexdigest()
    assert receipts[0]['original_sha256']==hashlib.sha256(CLAIM.encode()).hexdigest()
    # The old ambiguous literal path remains rejected.
    assert apply_local_corrections(document,[{'issue_index':0,'before':CLAIM,'after':FIXED}],ISSUES)==(document,[])


def test_repeated_claim_in_body_and_recap_is_replaced_atomically_by_two_registered_ids():
    document='# 正文\n\n'+CLAIM+'\n\n## 系统性总结\n\n'+CLAIM
    plan=build(document)
    changes=[{'issue_index':0,'passage_id':item['passage_id'],'after':FIXED} for item in plan['public']]
    result,done=apply_local_corrections(document,changes,ISSUES,passage_registry=plan)
    assert done==[0] and CLAIM not in result and result.count(FIXED)==2
    changes[1]['passage_id']='not-sent-to-reviewer'
    assert apply_local_corrections(document,changes,ISSUES,passage_registry=plan)==(document,[])


@pytest.mark.parametrize('change',['document','version','digest','range','hash','invented_id','hidden_id','duplicate_id','partial_paragraph','malformed_public'])
def test_stale_or_tampered_coordinates_never_authorize_an_edit(change):
    document='# 解释\n\n'+CLAIM+'\n\n'+CLAIM
    plan=build(document);key=reference(plan,document);saved=copy.deepcopy(plan)
    if change=='document':document=document+'\n\n另一段新修改。'
    elif change=='version':plan['version']='future'
    elif change=='digest':plan['document_sha256']='0'*64
    elif change=='range':plan['locations'][key]['end']+=1
    elif change=='hash':plan['locations'][key]['sha256']='0'*64
    elif change=='invented_id':plan['locations']['invented']=plan['locations'].pop(key)
    elif change=='hidden_id':plan['public']=[]
    elif change=='duplicate_id':plan['public'].append(plan['public'][0])
    elif change=='partial_paragraph':plan['locations'][key]['start']+=1
    elif change=='malformed_public':plan['public'].append(None)
    assert not validated_locations(document,plan)
    assert apply_local_corrections(document,[{'issue_index':0,'passage_id':key,'after':FIXED}],ISSUES,
        passage_registry=plan)==(document,[])
    assert saved['version']==VERSION


@pytest.mark.parametrize('invalid',[{'before':CLAIM},{'before':None},{'after':''},{'after':CLAIM},{'passage_id':True}])
def test_mixed_modes_no_op_or_empty_replacement_does_not_hide_a_warning(invalid):
    document='# 解释\n\n'+CLAIM+'\n\n'+CLAIM;plan=build(document)
    patch={'issue_index':0,'passage_id':reference(plan,document),'after':FIXED}|invalid
    assert apply_local_corrections(document,[patch],ISSUES,passage_registry=plan)==(document,[])


def test_ineligible_quotes_code_source_math_tables_and_existing_cautions_are_not_registered():
    document=('# 标题\n\n> '+CLAIM+'\n\n```text\n'+CLAIM+'\n```\n\n$$\n'+CLAIM+'\n$$\n\n'
        +'col | value\n---|---\n'+CLAIM+' | 1\n\n- '+CLAIM+'\n\n'
        +CLAIM+' [教材｜第2页]\n\n'+CLAIM+' https://example.test\n\n'
        +'这段已经说明条件，不能把一组充分条件写成指定必要条件。\n\n'
        +'## 待核实事项\n\n'+CLAIM+'\n\n## 系统性总结\n\n这段已经说明条件，不能把一组充分条件写成指定必要条件。')
    plan=build(document)
    assert len(plan['public'])==2 and '充分条件' in plan['public'][0]['opening']
    assert len(validated_locations(document,plan))==2


def test_paragraph_replacement_still_cannot_change_headings_sources_links_or_audit_records():
    document='# 解释\n\n'+CLAIM+'\n\n'+CLAIM+'\n\n## 待核实事项\n\n- 核查记录应保留。'
    plan=build(document);key=reference(plan,document)
    for after in ['## 新标题\n\n'+FIXED,FIXED+' [教材｜第1页]',FIXED+' https://example.test']:
        receipts=[]
        assert apply_local_corrections(document,[{'issue_index':0,'passage_id':key,'after':after}],ISSUES,
            passage_registry=plan,match_receipts=receipts)==(document,[])
        assert not receipts


def test_identifier_and_literal_conflicts_remain_order_independent():
    document='# 解释\n\n'+CLAIM+'\n\n'+CLAIM;plan=build(document);key=reference(plan,document)
    edits=[{'issue_index':0,'passage_id':key,'after':FIXED},
           {'issue_index':1,'before':'# 解释\n\n'+CLAIM,'after':'# 解释\n\n'+FIXED}]
    for order in (edits,edits[::-1]):
        assert apply_local_corrections(document,order,ISSUES*2,passage_registry=plan)==(document,[])


def test_locator_budget_is_bounded_and_does_not_duplicate_the_whole_draft_in_receipts():
    document='\n\n'.join('只有充分考虑边界和范围，才可能判断某个条件是否足够。'+('补充解释。'*10) for i in range(300))
    plan=build(document,budget=600,max_entries=3)
    assert len(plan['public'])<=3 and plan['receipt']['locator_characters']<=600
    assert plan['receipt']['unregistered_passages']>=297 and plan['receipt']['eligible_passages']==300
    assert '补充解释' not in json.dumps(plan['receipt'],ensure_ascii=False)
    assert all(row['opening_is_excerpt'] for row in plan['public'])
    assert len(validated_locations(document,plan))==len(plan['public'])
    assert not plan['public']  # An occurrence group that cannot fit is not partly advertised.


def test_formula_spelling_crlf_and_non_bmp_prefix_keep_exact_unicode_positions():
    repeated=CLAIM+r' 记号写作 $N=\max\{N_1,N_2\}$，不替换公式内容。'
    document='# 😀实际草稿\r\n\r\n'+repeated+'\r\n\r\n'+repeated
    plan=build(document);key=reference(plan,document,repeated)
    receipts=[];after=FIXED+r' 记号仍为 $N=\max\{N_1,N_2\}$。'
    result,done=apply_local_corrections(document,[{'issue_index':0,'passage_id':key,'after':after}],ISSUES,
        passage_registry=plan,match_receipts=receipts)
    assert done==[0] and result==document.replace(repeated,after,1)
    first=receipts[0];assert document[first['start']:first['end']]==repeated
    assert first['coordinate_unit']==plan['receipt']['coordinate_unit']=='unicode_code_points'


def test_all_occurrences_are_registered_together_and_a_trimmed_registry_is_rejected():
    document=CLAIM+'\n\n'+CLAIM
    assert not build(document,max_entries=1)['public']
    plan=build(document);key=plan['public'][0]['passage_id']
    plan['public']=plan['public'][:1];plan['locations']={key:plan['locations'][key]}
    assert not validated_locations(document,plan)
    assert not build('\n\n'.join([CLAIM]*9))['public']  # One review permits at most eight edits.


@pytest.mark.parametrize('mode,expected', [('express',0),('fast',1),('balanced',1),('strict',3)])
def test_only_quick_review_receives_registered_ids_without_new_requests(mode,expected):
    from studyforge.review import review_explanation
    from studyforge.review_input import MARKER
    class Client:
        calls=0
        async def complete(self,system,user,**kwargs):
            self.calls+=1;packet=json.loads(user.split(MARKER,1)[1])
            assert ('editable_passages' in packet)==(mode=='fast')
            assert packet['explanation_text']==draft and packet['source_text']=='完整原文条件。'
            return '{"passed":true,"issues":[]}'
    draft=CLAIM+'\n\n'+CLAIM
    client=Client();result,reports=asyncio.run(review_explanation(client,'完整原文条件。',draft,mode=mode))
    assert result==draft and client.calls==expected
    if mode=='fast':assert reports[0]['editable_passage_input']['registered_passages']==2


def test_nonrepeated_prose_has_no_registry_or_extra_review_data():
    from studyforge.review import review_explanation
    from studyforge.review_input import MARKER
    class Capture:
        calls=0
        async def complete(self,system,user,**kwargs):
            self.calls+=1
            assert 'passage_id' not in system and 'editable_passages' not in system
            assert 'editable_passages' not in json.loads(user.split(MARKER,1)[1])
            return '{"passed":true,"issues":[]}'
    client=Capture();assert build(CLAIM)['public']==[]
    _,reports=asyncio.run(review_explanation(client,'原文条件。',CLAIM,mode='fast'))
    assert client.calls==1 and 'editable_passage_input' not in reports[0]


@pytest.mark.parametrize('bad_second',[False,True])
def test_native_quick_review_registered_edits_reach_docx_snapshot_and_public_dialogue(tmp_path,monkeypatch,bad_second):
    import httpx
    from docx import Document
    from studyforge import ai,conversations,server
    from studyforge.db import create_job,create_project,execute,j,many,now,one,uid,unj
    from studyforge.review_input import MARKER
    ai.save_settings({'background_learning_enabled':False,'agent_tools_enabled':False})
    project=create_project('快速核查段落定位');chat=conversations.create(project['id'],'deepseek')
    path=tmp_path/'原文.txt';path.write_text('只给定区域内部净电荷为零，不能推出内部电场处处为零。',encoding='utf-8');sid=uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
        (sid,project['id'],path.name,'.txt',str(path),'ready',now()))
    draft='# 高斯定律\n\n'+CLAIM+'\n\n## 系统性总结\n\n'+CLAIM
    requests=[];real_http=httpx.AsyncClient
    def respond(request):
        body=json.loads(request.content);requests.append(body)
        if body.get('response_format',{}).get('type')=='json_object':
            packet=json.loads(body['messages'][-1]['content'].split(MARKER,1)[1]);assert packet['explanation_text']==draft
            passages=packet['editable_passages'];assert len(passages)==2
            edits=[{'issue_index':0,'passage_id':p['passage_id'],'after':FIXED} for p in passages]
            if bad_second:edits[1]['passage_id']='unknown'
            answer=j({'passed':False,'issues':ISSUES,'corrections':edits})
        else:answer=draft
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr('studyforge.ai.get_secret',lambda key:'fixture-only')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**k:real_http(transport=httpx.MockTransport(respond)))
    value=server.GenerateIn(project_id=project['id'],conversation_id=chat['id'],source_ids=[sid],provider='deepseek',
        model='fixture-model',generation_quality='custom',format='docx',review_mode='fast',exercises=False)
    job=create_job(project['id'],'generate',value.model_dump());asyncio.run(server._generate_job(job,value))
    status=one('SELECT status,error FROM jobs WHERE id=?',(job,));assert status['status']=='completed',status['error']
    saved=one('SELECT * FROM document_snapshots WHERE job_id=?',(job,));report=unj(saved['metadata_json'])['reviews'][0]
    artifact=one("SELECT * FROM artifacts WHERE project_id=? AND kind='explanation'",(project['id'],))
    words='\n'.join(p.text for p in Document(artifact['path']).paragraphs)
    public=one("SELECT content FROM messages WHERE conversation_id=? AND role='assistant'",(chat['id'],))['content']
    for text in (saved['content'],words,public):
        if bad_second:assert CLAIM in text and '待核实事项' in text and FIXED not in text
        else:assert FIXED in text and CLAIM not in text and '尚未再次独立复核' in text
    if bad_second:assert not report.get('local_correction_anchors')
    else:assert [a['mode'] for a in report['local_correction_anchors']]==['registered_passage']*2
    assert report['passed'] is False and len(requests)==2
    assert not many('SELECT * FROM exercise_sets') and not many('SELECT * FROM mastery')
