import asyncio
import copy
import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from studyforge import ai, lesson_quality as quality, materials, server
from studyforge.db import create_project, create_job, execute, j, many, now, one, uid, unj
from studyforge.learning import source_fingerprint, content_fingerprint, reading_content_matches
from studyforge.generation_control import GenerationControl, PausableClient


def record(path, text='原文定义。末尾条件不能省略。', name=None):
    path.write_text(text, encoding='utf-8')
    return {'id': uid(), 'name': name or path.name, 'original_path': str(path),
            'segments': [{'locator': '预览', 'text': '错误概括不能使用'}]}


def counted_parser(monkeypatch):
    actual, calls = materials.parse_file, []
    def parse(path): calls.append(str(path)); return actual(path)
    monkeypatch.setattr(materials, 'parse_file', parse)
    return calls


def test_full_parse_cache_preserves_all_text_and_does_not_mutate_original(tmp_path, monkeypatch):
    calls = counted_parser(monkeypatch)
    source = record(tmp_path/'长文.txt', '定义。'+'不能省略细节。'*16000+'末尾重要条件。')
    first = materials.read_original_sources([source])[0]
    first['segments'][0]['text'] = '外部调用者误改'
    second = materials.read_original_sources([source])[0]
    assert len(calls)==1 and second['read_manifest']['parse_cache_hit']
    assert sum(x['text'].count('不能省略细节。') for x in second['segments'])==16000
    assert '末尾重要条件。' in second['segments'][-1]['text'] and '错误概括' not in j(second)


def test_same_size_and_timestamp_edit_does_not_reuse_old_parse(tmp_path, monkeypatch):
    calls=counted_parser(monkeypatch);source=record(tmp_path/'a.txt','初版条件：甲。')
    before=materials.read_original_sources([source])[0];stamp=os.stat(source['original_path'])
    (tmp_path/'a.txt').write_text('新版条件：乙。',encoding='utf-8')
    os.utime(source['original_path'],ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
    after=materials.read_original_sources([source])[0]
    assert len(calls)==2 and not after['read_manifest']['parse_cache_hit']
    assert before['read_manifest']['sha256']!=after['read_manifest']['sha256'] and '新版条件' in j(after)


@pytest.mark.parametrize('change',['delete','tamper'])
def test_missing_or_tampered_derived_image_is_reparsed_from_original(tmp_path, monkeypatch, change):
    source=record(tmp_path/'source.txt');image=tmp_path/'page.png';calls=[]
    def parse(path):
        calls.append(path);image.write_bytes(b'original pixels')
        return [{'locator':'第1页','text':'原文条件','meta':{'image_path':str(image)}}]
    monkeypatch.setattr(materials,'parse_file',parse)
    first=materials.read_original_sources([source])
    if change=='delete':image.unlink()
    else:image.write_bytes(b'changed pixels')
    second=materials.read_original_sources([source])
    assert len(calls)==2 and image.read_bytes()==b'original pixels'
    assert content_fingerprint(first)==content_fingerprint(second)


def test_parallel_requests_share_full_parse_and_never_use_preview(tmp_path,monkeypatch):
    source=record(tmp_path/'parallel.txt');actual=materials.parse_file;calls=[]
    def parse(path):calls.append(path);time.sleep(.04);return actual(path)
    monkeypatch.setattr(materials,'parse_file',parse)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(lambda _:materials.read_original_sources([source]),range(2)))
    assert len(calls)==1 and all('末尾条件' in j(x) and '错误概括' not in j(x) for x in results)


def test_cache_is_bounded_and_deleted_original_is_not_resurrected(tmp_path,monkeypatch):
    materials.clear_original_cache();calls=counted_parser(monkeypatch);sources=[]
    for index in range(9):
        source=record(tmp_path/f'{index}.txt');sources.append(source);materials.read_original_sources([source])
    assert not materials.read_original_sources([sources[0]])[0]['read_manifest']['parse_cache_hit'] and len(calls)==10
    (tmp_path/'0.txt').unlink()
    with pytest.raises(ValueError,match='原文件不存在'):materials.read_original_sources([sources[0]])


def test_change_during_parsing_fails_without_publishing_stale_content(tmp_path,monkeypatch):
    source=record(tmp_path/'unstable.txt');actual=materials.parse_file
    def parse(path):
        parts=actual(path);path.write_text('已经改版',encoding='utf-8');return parts
    monkeypatch.setattr(materials,'parse_file',parse)
    with pytest.raises(ValueError,match='解析期间变更'):materials.read_original_sources([source])


def test_vision_cache_uses_pixels_model_effort_and_does_not_turn_analysis_into_original(tmp_path):
    ai.clear_source_digest_cache();image=tmp_path/'frame.png';image.write_bytes(b'frame one')
    source={'id':'frame-source','name':'画面','segments':[{'locator':'00:01','text':'原文标注','meta':{'image_path':str(image)}}]}
    calls=[]
    class Vision:
        model='chosen';effort='high'
        async def analyze_image(self,*args):calls.append(args);return 'AI推测，不能作为原文引句'
    async def run():
        client=Vision()
        first,_=await ai.source_digest(client,[source]);second,_=await ai.source_digest(client,[source])
        assert first==second and len(calls)==1 and source['segments'][0]['text']=='原文标注'
        image.write_bytes(b'frame two');await ai.source_digest(client,[source])
        client.model='other';await ai.source_digest(client,[source])
        client.effort='low';await ai.source_digest(client,[source])
        ai.save_settings({'deepseek_vision_model':'other-vision'});await ai.source_digest(client,[source])
    asyncio.run(run());assert len(calls)==5
    checked=quality.citation_checks('> AI推测，不能作为原文引句 [画面｜00:01]',[source])
    assert checked['matched_quotes']==0 and checked['warning_count']==1


def test_failed_vision_is_marked_and_not_cached_as_success(tmp_path):
    ai.clear_source_digest_cache();image=tmp_path/'frame.png';image.write_bytes(b'frame');calls=[]
    source={'id':uid(),'name':'画面','segments':[{'locator':'00:01','text':'标注','meta':{'image_path':str(image)}}],
            'read_manifest':{'limitations':[]}}
    class Vision:
        async def analyze_image(self,*args):
            calls.append(args)
            if len(calls)==1:raise RuntimeError('temporary')
            return '已读图'
    async def run():
        failed,_=await ai.source_digest(Vision(),[copy.deepcopy(source)])
        success,_=await ai.source_digest(Vision(),[copy.deepcopy(source)])
        assert '待核实' in failed and '已读图' in success
    asyncio.run(run());assert len(calls)==2


def test_resumed_image_step_rechecks_image_content_and_vision_configuration(tmp_path):
    project=create_project('图像');job=create_job(project['id'],'generate',{});image=tmp_path/'x.png';image.write_bytes(b'a');calls=[]
    class Vision:
        model='same';effort='high'
        async def analyze_image(self,*args):calls.append(args);return f'图{len(calls)}'
    async def run():
        client=PausableClient(Vision(),GenerationControl(job))
        assert await client.analyze_image(image,'图')=='图1'
        assert await client.analyze_image(image,'图')=='图1'
        image.write_bytes(b'b');assert await client.analyze_image(image,'图')=='图2'
        ai.save_settings({'deepseek_vision_model':'new-vision'});assert await client.analyze_image(image,'图')=='图3'
    asyncio.run(run());assert len(calls)==3


def test_media_text_change_invalidates_enriched_reading_but_preserves_legacy_checks(tmp_path):
    path=tmp_path/'video.mp4';path.write_bytes(b'unchanged video')
    source={'id':'v','name':'视频','original_path':str(path),'segments':[{'locator':'00:01','text':'字幕第一版','meta':{}}]}
    first=materials.read_original_sources([source]);source['segments'][0]['text']='字幕修正版'
    second=materials.read_original_sources([source])
    assert source_fingerprint(first)==source_fingerprint(second) and content_fingerprint(first)!=content_fingerprint(second)
    assert not reading_content_matches([first[0]['read_manifest']],second)
    assert reading_content_matches([{'source_id':'v','sha256':first[0]['read_manifest']['sha256']}],second)


def example_records():
    return [{'id':'p','name':'原文.txt','segments':[{'locator':'行 1-3','text':'第一定义。关键方法与理由。最后条件。'}]}]


@pytest.mark.parametrize('locator', ['行 1', '行1-1', '行1—1', '第1行'])
def test_single_line_notation_equivalence_keeps_verbatim_quote_checks(locator):
    records = [{'name':'原文.txt','segments':[{'locator':'行 1-1','text':'这是一条相关描述。'}]}]
    result = quality.citation_checks(f'> 这是一条相关描述。 [原文.txt｜{locator}]', records)
    assert result['matched_citations'] == result['matched_quotes'] == 1
    assert result['warning_count'] == 0 and result['semantic_verified'] is False
    wrong = quality.citation_checks(f'> 这是已经证明的因果关系。 [原文.txt｜{locator}]', records)
    assert wrong['matched_citations'] == 1 and wrong['matched_quotes'] == 0 and wrong['warning_count'] == 1


@pytest.mark.parametrize('locator', ['行1', '第1行'])
def test_single_line_alias_cannot_validate_a_larger_original_range(locator):
    result = quality.citation_checks(f'> 第一定义。 [原文.txt｜{locator}]', example_records())
    assert result['matched_citations'] == result['matched_quotes'] == 0 and result['warning_count'] == 2


def test_line_alias_keeps_wrong_locations_and_ambiguous_sources_unverified():
    records = [{'name':'原文.txt','segments':[{'locator':'行1-1','text':'同一句原话。'}]}]
    result = quality.citation_checks('> 同一句原话。 [原文.txt｜行2]', records)
    assert result['matched_citations'] == result['matched_quotes'] == 0
    records.append({'name':'原文.txt','segments':[{'locator':'第1行','text':'同一句原话。'}]})
    ambiguous = quality.citation_checks('> 同一句原话。 [原文.txt｜行1]', records)
    assert ambiguous['matched_citations'] == ambiguous['matched_quotes'] == 0 and '不唯一' in j(ambiguous)


def test_citations_and_ellipsis_are_checked_in_source_order_not_as_semantic_truth():
    checks=quality.citation_checks('> 原文：第一定义。[…]最后条件。 [来源 原文.txt｜行1-3]',example_records())
    assert checks['matched_citations']==checks['matched_quotes']==1 and checks['warning_count']==0
    assert not checks['semantic_verified'] and '不证明' in checks['note']
    wrong=quality.citation_checks('> 最后条件。[…]第一定义。 [原文.txt｜行1-3]',example_records())
    assert wrong['matched_citations']==1 and wrong['matched_quotes']==0


@pytest.mark.parametrize('document',[
    '> 编造的原话 [原文.txt｜行1-3]', '> 第一定义。 [原文.txt｜第99页]', '> 第一定义。 [其他.txt｜行1-3]',
    '> 第一定义。', '只有解释没有定位'])
def test_missing_or_wrong_evidence_is_marked_without_another_model_call(document):
    checked=quality.citation_checks(document,example_records())
    assert checked['warning_count']>0 and not checked['semantic_verified']
    finished=quality.mark_source_warnings(document+'\n\n## 系统性总结\n总结已有内容。',checked)
    assert finished.endswith('总结已有内容。') and finished.count('## 系统性总结')==1
    assert '来源定位需核对' in finished


def test_same_named_sources_do_not_pass_as_uniquely_located():
    records=example_records();records.append(dict(records[0],id='another'))
    checked=quality.citation_checks('> 第一定义。 [原文.txt｜行1-3]',records)
    assert checked['matched_citations']==checked['matched_quotes']==0 and '不唯一' in j(checked)


def test_code_strings_are_not_citations_and_source_name_prefix_is_preserved():
    records=example_records();records[0]['name']='来源研究.txt'
    checked=quality.citation_checks('```python\ns="[不存在.txt｜第99页]"\n```\n第一定义。[来源研究.txt｜行1-3]',records)
    assert checked['citation_count']==checked['matched_citations']==1 and checked['warning_count']==0


def test_bounded_navigation_and_continuity_keep_tail_and_do_not_replace_full_source():
    records=[{'id':'book','name':'教材','segments':[{'locator':f'第{i}章','text':f'# 定义{i}\n完整推导与末尾条件{i}'} for i in range(300)]}]
    outline=quality.outline(records)
    assert len(outline['text'])<6000 and outline['omitted']>0 and '定义0' in outline['text'] and '定义299' in outline['text']
    chapters=['# 前一章\n## 系统性总结\n这是旧讲解，不是原文证据。'*20]*30
    from studyforge.reading_notes import context as note_context,input_scope
    notes=[{'part':1,'text':'其他部分笔记。','input_scope':input_scope('其他部分原文')},
           {'part':2,'text':'本部分笔记。','input_scope':input_scope('本部完整原文')}]
    preparation,receipt=note_context(notes,'本部完整原文')
    context=quality.chapter_context(outline,['前部完整原文与末尾公式','本部完整原文'],1,chapters,preparation)
    assert '本部分笔记' in context and '末尾公式' in context and '不是原文证据' in context and len(context)<17000
    assert '原文摘要' not in context and '不是内容摘要' in context
    assert '其他部分笔记' not in context and receipt['matched_notes']==1


def test_assembled_chapters_have_one_global_summary_and_code_fences_are_preserved():
    chapters=['# 文档\n## 系统性总结\n甲。',' # 下一章\n```python\n# 代码注释\n```\n## 系统性总结\n乙。']
    joined=quality.assemble_chapters(chapters)
    assert '第1部分小结' in joined and '第2部分小结' in joined and '# 代码注释' in joined
    assert '\n## 系统性总结' not in joined


@pytest.mark.parametrize('has_summary', [False, True])
def test_summary_only_input_is_bounded_and_keeps_chapter_boundaries_without_cutting_lesson(has_summary):
    from studyforge.teaching import finish_explanation, summary_context
    chapters = [f'# 章节{i}\n' + ('## 系统性总结\n' if has_summary else '') +
                f'目标{i}。' + '论证步骤。'*6000 + f'末尾条件{i}。' for i in range(8)]
    prepared = summary_context(chapters)
    assert prepared['excerpted'] and prepared['omitted_chapters'] == 0 and len(prepared['text']) <= 48000
    for i in range(8):
        assert f'第 {i+1} 部分结构' in prepared['text'] and f'末尾条件{i}' in prepared['text']
    calls = []
    class Client:
        async def complete(self, system, user):
            calls.append(user)
            assert '不声称覆盖全部细节' in user and len(user) <= 48000
            return '## 系统性总结\n据章节节选归纳。'
    document = quality.assemble_chapters(chapters)
    result = asyncio.run(finish_explanation(Client(), document, chapters=chapters))
    assert len(calls) == 1 and result.startswith(document) and result.endswith('据章节节选归纳。')


def test_hundreds_of_summary_parts_are_bounded_and_omissions_are_explicit():
    from studyforge.teaching import summary_context
    result = summary_context([f'# 独立章节{i}\n' + '具体论证。'*200 for i in range(400)])
    assert len(result['text']) <= 48000 and result['omitted_chapters'] > 0
    assert '第 1 部分结构' in result['text'] and '第 400 部分结构' in result['text']
    assert f"{result['omitted_chapters']}部分未列入" in result['text']


def seeded_job(tmp_path,text):
    project=create_project('讲解质量');source=record(tmp_path/'完整原文.txt',text)
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (source['id'],project['id'],source['name'],'.txt',source['original_path'],j(source['segments']),'ready',now()))
    value=server.GenerateIn(project_id=project['id'],source_ids=[source['id']],provider='deepseek',model='chosen',review_mode='express')
    job=create_job(project['id'],'generate',value.model_dump());return job,value,source


@pytest.mark.parametrize('oversized_summary', [False, True])
def test_long_lesson_has_full_inputs_continuity_single_summary_and_no_planning_requests(tmp_path,monkeypatch,oversized_summary):
    text='# 概念与目标\n'+'第一部分论证。'*9000+'\n# 方法与限制\n末尾条件不能省略。'
    job,value,source=seeded_job(tmp_path,text);calls=[]
    class Client:
        model='chosen'
        async def complete(self,system,user,**kwargs):
            calls.append((system,user))
            if '只补写整篇文章的系统性总结' in system:
                assert len(user) <= 48000
                return '## 系统性总结\n概念、方法与末尾条件。'
            return (f'# 第{len(calls)}章\n解释方法动机与条件。\n## 系统性总结\n' +
                    ('论证步骤。'*6000 if oversized_summary else '') + '本章结构与依据。')
    monkeypatch.setattr(server,'client_for',lambda *args,**kwargs:Client())
    asyncio.run(server._generate_job(job,value));row=one('SELECT * FROM jobs WHERE id=?',(job,));assert row['status']=='completed',row['error']
    artifact=one("SELECT * FROM artifacts WHERE kind='explanation'");meta=unj(artifact['metadata_json'])
    assert meta['original_batches']>=2 and len(calls)==meta['original_batches']+1
    assert all('全文来源导航' in user for _,user in calls[:-1]) and '已写内容衔接' in calls[1][1]
    assert '末尾条件不能省略' in calls[-2][1] and '错误概括' not in j(calls)
    assert meta['lesson_quality']['extra_model_requests']==0 and not meta['lesson_quality']['semantic_verified']
    assert meta['lesson_quality']['summary_context_excerpted'] is oversized_summary
    if oversized_summary:
        from docx import Document
        exported='\n'.join(p.text for p in Document(artifact['path']).paragraphs)
        assert '总结范围：' in exported and '不代表逐一覆盖全部细节' in exported


def test_original_change_during_model_response_stops_old_artifact_and_does_not_emit_exercises(tmp_path,monkeypatch):
    job,value,source=seeded_job(tmp_path,'第一个版本。')
    class Client:
        model='chosen'
        async def complete(self,*args,**kwargs):
            (tmp_path/'完整原文.txt').write_text('新版本。',encoding='utf-8')
            return '# 旧讲解\n正文。\n## 系统性总结\n旧总结。'
    monkeypatch.setattr(server,'client_for',lambda *args,**kwargs:Client())
    asyncio.run(server._generate_job(job,value));row=one('SELECT * FROM jobs WHERE id=?',(job,))
    assert row['status']=='failed' and '生成期间已变更' in row['error']
    assert many('SELECT * FROM artifacts')==[] and many('SELECT * FROM exercise_sets')==[]


@pytest.mark.parametrize('domain',['philosophy','social','math','physics','chemistry','biology'])
def test_multidisciplinary_eval_outputs_are_reproducible_but_do_not_claim_semantic_success(tmp_path,domain):
    from scripts.lesson_quality_eval import evaluate
    report=asyncio.run(evaluate(tmp_path/domain,[domain],repeat=True))
    assert report['simulated'] and report['passed_semantic_review'] is None
    first,second=report['cases'];assert first['status']==second['status']=='completed'
    assert first['checks']['matched_quotes']==second['checks']['matched_quotes']==1
    assert first['checks']['warning_count']==second['checks']['warning_count']==0
    assert not first['checks']['semantic_verified'] and second['source_reading'][0]['parse_cache_hit']
    assert all(value is None for value in second['human_review'].values()) and len(second['human_review_required'])==3
