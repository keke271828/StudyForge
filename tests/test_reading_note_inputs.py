"""Do not promote a different reading slice to current source evidence."""
import asyncio
import copy
import hashlib
import json
import re

import pytest

from studyforge.reading_notes import VERSION, context, input_scope


def note(original, text, part=1):
    return {'part':part,'text':text,'input_scope':input_scope(original)}


def test_note_follows_identical_input_instead_of_ordinal_after_reordering():
    notes=[note('甲原文','只属于甲的笔记。',1),note('乙原文','只属于乙的笔记。',2)]
    before=copy.deepcopy(notes)
    text,receipt=context(notes,'乙原文')
    assert '只属于乙' in text and '只属于甲' not in text and '[通读记录2]' in text
    assert receipt['matched_notes']==receipt['unmatched_notes']==1 and receipt['reason']=='exact_original_input'
    assert receipt['included'][0]['reading_part']==2 and '不证明笔记正确' in text
    assert receipt['original_input']==input_scope('乙原文') and notes==before


@pytest.mark.parametrize('original',['甲原文\n乙原文','甲原文\n','甲原文。','甲原文 '[::-1]])
def test_regrouped_or_changed_input_does_not_guess_a_note_match(original):
    notes=[note('甲原文','UNRELATED_NOTE',1)]
    text,receipt=context(notes,original)
    assert 'UNRELATED_NOTE' not in text and '未按部分编号猜配' in text
    assert receipt['reason']=='no_matching_original_input' and not receipt['included']


def test_even_equivalent_math_and_renamed_source_locators_are_not_fuzzy_matched():
    before='[来源 教材｜第1页]\nx+x=2x'
    for after in ['[来源 教材｜第1页]\nx + x = 2x','[来源 教材｜第2页]\nx+x=2x']:
        text,receipt=context([note(before,'不是当前输入的笔记。')],after)
        assert '不是当前输入的笔记' not in text and receipt['matched_notes']==0


def test_legacy_notes_are_labelled_unassigned_without_pretending_part_alignment():
    notes=[{'part':1,'text':'旧笔记甲。'},{'part':2,'text':'旧笔记乙。'}]
    text,receipt=context(notes,'本次原文')
    assert all(term in text for term in ('旧版整体','未确认对应当前分段','旧笔记甲','旧笔记乙'))
    assert receipt['reason']=='legacy_unassigned' and receipt['legacy_notes']==2 and receipt['matched_notes']==0


def test_exact_match_excludes_unassigned_and_other_source_notes():
    notes=[{'part':1,'text':'LEGACY_NOTE'},note('其他原文','OTHER_NOTE'),note('当前原文','正确对应。',3)]
    text,receipt=context(notes,'当前原文')
    assert '正确对应' in text and 'LEGACY_NOTE' not in text and 'OTHER_NOTE' not in text
    assert receipt['legacy_notes']==receipt['unmatched_notes']==receipt['matched_notes']==1


@pytest.mark.parametrize('stamp',[None,{},'fake',{'version':'future','sha256':'a'*64,'characters':3},
    {'version':VERSION,'sha256':'a'*64,'characters':True},{'version':VERSION,'sha256':'invalid','characters':3}])
def test_malformed_new_stamps_never_degrade_to_legacy_context(stamp):
    text,receipt=context([{'part':1,'text':'INVALID_NOTE','input_scope':stamp}],'当前原文')
    assert 'INVALID_NOTE' not in text and receipt['invalid_notes']==1 and not receipt['included']


def test_stamp_length_must_match_and_receipts_do_not_duplicate_text_or_original():
    value=note('私人原文','私人笔记。')
    value['input_scope']['characters']+=1
    assert context([value],'私人原文')[1]['matched_notes']==0
    value['input_scope']['characters']-=1
    text,receipt=context([value],'私人原文')
    assert '私人笔记。' in text and '私人' not in json.dumps(receipt,ensure_ascii=False)
    saved=receipt['included'][0]
    assert hashlib.sha256(value['text'].encode()).hexdigest()==saved['text_sha256']
    assert value['text'][saved['start']:saved['end']] in text


@pytest.mark.parametrize('tail',[
    '完整长段。'*1000,
    '$$\n'+'a+b=c\n'*1000+'$$',
    '\\[\n'+'a+b=c\n'*1000+'\\]',
    '````python\n'+'x = 1\n'*1000+'````',
    '```python\nnever closed',
    '$$\nnever closed',
])
def test_prefix_keeps_whole_paragraphs_and_never_sends_truncated_math_or_code(tail):
    value=note('原文','完整首段。\n\n## 后续标题\n\n'+tail)
    text,receipt=context([value],'原文',600)
    assert len(text)<=600 and '完整首段' in text and '后续标题' not in text
    assert 'a+b=c' not in text and 'never closed' not in text and 'x = 1' not in text
    saved=receipt['included'][0]
    assert value['text'][:saved['end']]=='完整首段。' and saved['excerpted']


@pytest.mark.parametrize('body',['$$\n\na+b=c\n\n$$','```python\nx=1\n```',r'\[ a+b=c \]'])
def test_complete_math_and_code_survive_as_note_data(body):
    value=note('原文','段落。\n\n'+body)
    text,receipt=context([value],'原文')
    assert body in text and not receipt['included'][0]['excerpted']


def test_empty_huge_and_duplicate_notes_remain_bounded_without_new_reads():
    assert context([],'原文')[0]==''
    empty=note('原文','只有一个超长段落。'*1000)
    text,receipt=context([empty],'原文',400)
    assert len(text)<=400 and not receipt['included'] and '没有可完整提供' in text
    value=note('原文','同一完整段落。')
    text,receipt=context([value,copy.deepcopy(value)],'原文')
    assert text.count('同一完整段落。')==1 and receipt['matched_notes']==2 and len(receipt['included'])==1
    with pytest.raises(ValueError):context([value],'原文',399)


def test_understanding_records_only_supplied_input_scope_and_does_not_copy_original():
    from studyforge.learning import understand_material
    from studyforge.ai import explanation_batches
    digest='[来源 教材｜行1]\n完整原文。'
    calls=[]
    class Client:
        async def complete(self,system,user):
            calls.append(user)
            return '笔记只作参考。'
    notes=asyncio.run(understand_material(Client(),digest,lambda *a:None))
    assert len(calls)==len(notes)==1 and notes[0]['input_scope']==input_scope(explanation_batches(digest)[0])
    assert set(notes[0])=={'part','text','input_scope'} and '完整原文' not in json.dumps(notes,ensure_ascii=False)


@pytest.mark.parametrize('parallel',[False,True])
@pytest.mark.parametrize('reordered',[False,True])
def test_native_read_then_generate_persists_matching_or_unmatched_receipts_and_docx(tmp_path,monkeypatch,parallel,reordered):
    """Real parsers, native HTTP protocol, review/export, isolated controlled model."""
    import httpx
    from docx import Document
    from studyforge import ai, conversations, learning, server
    from studyforge.db import create_job,create_project,execute,many,now,one,uid,unj
    ai.save_settings({'background_learning_enabled':False,'agent_tools_enabled':False})
    project=create_project('通读与生成分段对应')
    chat=conversations.create(project['id'],'deepseek')
    ids=[]
    for key in ('甲','乙'):
        path=tmp_path/(key+'教材.txt');path.write_text((f'原文{key}条件：只讨论本资料的范围。'*45),encoding='utf-8')
        sid=uid();ids.append(sid)
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
                (sid,project['id'],path.name,'.txt',str(path),'ready',now()))
    def split(value):
        # The full file manifest contains absolute test paths. Keep one whole
        # file after that variable-size manifest, rather than allowing a long
        # Windows --basetemp path to manufacture an unintended third batch.
        preface,marker,body=value.partition('\n[来源 ')
        blocks=re.split(r'(?=\n\[来源 )',marker+body) if marker else [value]
        budget=len(preface)+max(map(len,blocks))+64
        return ai.explanation_batches(value,max_chars=budget)
    monkeypatch.setattr(learning,'explanation_batches',split)
    monkeypatch.setattr(server,'explanation_batches',split)
    requests=[];real_client=httpx.AsyncClient
    def respond(request):
        body=json.loads(request.content);requests.append(body)
        system,user=body['messages'][0]['content'],body['messages'][-1]['content']
        if '通读理解资料' in system:
            answer='甲专属笔记。' if '原文甲' in user else '乙专属笔记。'
        elif body.get('response_format',{}).get('type')=='json_object':
            answer='{"passed":true,"issues":[]}'
        elif '只补写整篇' in system:
            answer='## 系统性总结\n各资料只讨论各自范围。'
        else:
            original=user.split('所选资料内容：',1)[1]
            is_a='原文甲' in original
            wanted,other=('甲专属笔记','乙专属笔记') if is_a else ('乙专属笔记','甲专属笔记')
            if reordered:
                # File-manifest order also changes the first transport input;
                # neither resulting slice is identical. Do not guess a match.
                assert '未按部分编号猜配' in user and wanted not in user and other not in user
            else:
                assert wanted in user and other not in user
            answer=f'# {"甲" if is_a else "乙"}资料讲解\n\n完整原文的条件保留。\n\n## 系统性总结\n只讨论本资料范围。'
        return httpx.Response(200,text='data: '+json.dumps({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]},ensure_ascii=False)+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr('studyforge.ai.get_secret',lambda key:'fixture-only')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**k:real_client(transport=httpx.MockTransport(respond)))
    async def run():
        reading=server.ReadIn(project_id=project['id'],source_ids=ids,provider='deepseek',model='fixture-model',generation_quality='custom')
        read_job=create_job(project['id'],'read',reading.model_dump())
        await server._read_job(read_job,reading)
        saved=one('SELECT * FROM jobs WHERE id=?',(read_job,))
        assert saved['status']=='completed',saved['error']
        rid=unj(saved['result_json'])['reading_id']
        notes=unj(one('SELECT notes_json FROM reading_sessions WHERE id=?',(rid,))['notes_json'])
        assert len(notes)==2 and all(row.get('input_scope',{}).get('version')==VERSION for row in notes)
        value=server.GenerateIn(project_id=project['id'],source_ids=ids[::-1] if reordered else ids,conversation_id=chat['id'],provider='deepseek',model='fixture-model',
            reading_id=rid,format='docx',review_mode='fast',parallel=parallel,exercises=False)
        job=create_job(project['id'],'generate',value.model_dump())
        await server._generate_job(job,value)
        status=one('SELECT * FROM jobs WHERE id=?',(job,))
        assert status['status']=='completed',status['error']
        saved=one('SELECT * FROM document_snapshots WHERE job_id=?',(job,))
        receipts=unj(saved['metadata_json'])['lesson_quality']['reading_note_inputs']
        assert len(receipts)==2
        if reordered:
            assert all(r['reason']=='no_matching_original_input' and not r['included'] for r in receipts)
        else:
            assert [r['included'][0]['reading_part'] for r in receipts]==[1,2]
            assert all(r['reason']=='exact_original_input' and r['matched_notes']==1 for r in receipts)
        actual=await server.generation_input_records(value)
        digest,_=await ai.source_digest(object(),actual)
        assert [r['original_input'] for r in receipts]==[input_scope(b) for b in split(digest)]
        artifact=one("SELECT * FROM artifacts WHERE project_id=? AND kind='explanation'",(project['id'],))
        words='\n'.join(p.text for p in Document(artifact['path']).paragraphs)
        assert '甲资料讲解' in words and '乙资料讲解' in words and '系统性总结' in words
        assert unj(artifact['metadata_json'])['lesson_quality']['reading_note_inputs']==receipts
    asyncio.run(run())
    assert len(requests)==7  # 2 read, 2 draft, 2 existing quick reviews, 1 global summary.
    assert many('SELECT * FROM exercise_sets')==[] and many('SELECT * FROM mastery')==[]
