"""Model rewrites/patches cannot silently clear older source/review doubts."""
import asyncio
import json

import pytest

from studyforge import lesson_cautions
from studyforge.review import review_explanation
from studyforge.review_corrections import apply_local_corrections
from studyforge.teaching import summary_section


NOTE='## 来源定位需核对\n\n- 引用块2：未能逐字匹配，需对照原文件。'
OLD='# 讲解\n\n旧正文。\n\n'+NOTE+'\n\n## 核查说明\n\n已修订，尚未独立复核。\n\n## 系统性总结\n\n旧总结。'
REVISED='# 讲解\n\n新正文。\n\n## 系统性总结\n\n新总结。'


def test_exact_records_survive_without_repeating_and_summary_stays_last():
    retained,info=lesson_cautions.retain_records(REVISED,OLD)
    assert NOTE in retained and '已修订，尚未独立复核。' in retained
    assert info['previous_sections']==info['restored_sections']==2
    assert retained.endswith('新总结。') and retained.index(NOTE)<summary_section(retained)[0]
    assert lesson_cautions.retain_records(retained,OLD)[0]==retained
    assert lesson_cautions.retain_records(retained,OLD)[1]['restored_sections']==0


def test_false_resolution_preserves_historical_doubt_without_overwriting_new_body():
    revised=REVISED.replace('新正文。','新正文。\n\n## 来源定位需核对\n\n已经完全核实，无需再查看来源。')
    retained,_=lesson_cautions.retain_records(revised,OLD)
    assert '新正文。' in retained and NOTE in retained and retained.endswith('新总结。')
    assert '已经完全核实' not in retained
    assert '没有确认' not in retained,'Retention does not invent a new verdict'


def test_local_correction_cannot_edit_a_notice_body_or_clear_related_issue_group():
    issues=[{'problem':'声称旧核对提示可删除'},{'problem':'正文应修正'}]
    patches=[{'issue_index':0,'before':'- 引用块2：未能逐字匹配，需对照原文件。','after':'- 引用已核实。'},
             {'issue_index':0,'before':'旧总结。','after':'关联总结的修改。'},
             {'issue_index':1,'before':'旧正文。','after':'正确正文。'}]
    revised,used=apply_local_corrections(OLD,patches,issues)
    assert used==[1] and NOTE in revised and revised.endswith('旧总结。') and '正确正文。' in revised


@pytest.mark.parametrize('mode,calls',[('balanced',2),('strict',7)])
def test_whole_revision_keeps_old_doubts_before_independent_recheck(mode,calls):
    captured=[]
    class Client:
        async def complete(self,system,user,json_mode=False):
            captured.append((system,user))
            if not json_mode:return REVISED
            if '新正文。' in user:
                assert '未能逐字匹配' in user and '尚未独立复核' in user
                return '{"passed":true,"issues":[]}'
            return json.dumps({'passed':False,'issues':[{'problem':'旧正文需要修正'}]})
    document,reports=asyncio.run(review_explanation(Client(),'原资料。',OLD,mode=mode))
    assert len(captured)==calls and NOTE in document and '尚未独立复核' in document
    assert any(r.get('revision_cautions',{}).get('restored_sections')==2 for r in reports)


def test_quoted_or_code_headings_are_not_protected_caution_records():
    original='# 原文\n\n> ## 来源定位需核对\n> 这是引用中的标题。\n\n```text\n## 核查说明\n代码里的示例。\n```'
    assert lesson_cautions.retain_records(REVISED,original)==(REVISED,{
        'previous_sections':0,'restored_sections':0,'meaning':'retained_prior_cautions_not_new_verification'})


def test_record_hidden_in_code_cannot_replace_a_visible_caution():
    disguised=REVISED.replace('新正文。','新正文。\n\n```text\n'+NOTE+'\n```')
    retained,info=lesson_cautions.retain_records(disguised,OLD)
    assert len(lesson_cautions.records([retained]))==2 and info['restored_sections']==2


def test_identical_notices_from_multiple_parts_keep_their_occurrence_count():
    original='# 第一章\n\n'+NOTE+'\n\n# 第二章\n\n'+NOTE+'\n\n## 系统性总结\n\n总结。'
    revised=REVISED.replace('新正文。','新正文。\n\n'+NOTE)
    retained,info=lesson_cautions.retain_records(revised,original)
    assert len(lesson_cautions.records([retained]))==2
    assert info['previous_sections']==2 and info['restored_sections']==1
    assert lesson_cautions.retain_records(retained,original)[0]==retained


def test_nested_records_restore_once_with_their_original_hierarchy():
    original='# 讲解\n\n## 待核实事项\n\n外层疑点。\n\n### 来源定位需核对\n\n内层来源疑点。\n\n## 系统性总结\n\n总结。'
    retained,info=lesson_cautions.retain_records(REVISED,original)
    assert len(lesson_cautions.records([retained]))==2
    assert retained.count('内层来源疑点。')==1 and retained.count('外层疑点。')==1
    assert info['previous_sections']==info['restored_sections']==2
    assert lesson_cautions.retain_records(retained,original)[0]==retained
