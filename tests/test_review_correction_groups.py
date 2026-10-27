"""A partly applied review must never hide a still unresolved concern."""
import asyncio
import json

import pytest

from studyforge.review import apply_local_corrections, review_explanation


def patch(index, before, after):
    return {'issue_index': index, 'before': before, 'after': after}


def test_one_issue_with_an_unmatched_second_anchor_is_atomic():
    draft = '# 说明\n2+3=4。\n\n总结仍写2+3等于4。'
    changes = [patch(0, '2+3=4。', '2+3=5。'), patch(0, '不存在的总结句。', '总结也应为5。')]
    result, resolved = apply_local_corrections(draft, changes, [{'problem': '正文和总结的加法都错了'}])
    assert result == draft and resolved == []


def test_a_rejected_group_does_not_discard_an_independent_valid_group():
    draft = '# 说明\n加法2+3=4。\n乘法2乘3等于5。'
    changes = [patch(0, '加法2+3=4。', '加法2+3=5。'),
               patch(0, '不存在的原句。', '补充。'),
               patch(1, '乘法2乘3等于5。', '乘法2乘3等于6。')]
    result, resolved = apply_local_corrections(draft, changes, [{'problem': '加法'}, {'problem': '乘法'}])
    assert '加法2+3=4。' in result and '乘法2乘3等于6。' in result
    assert resolved == [1]


@pytest.mark.parametrize('reverse', [False, True])
def test_overlapping_issues_cannot_be_resolved_by_arbitrary_patch_order(reverse):
    draft = '# 说明\n原说法甲和原说法乙。'
    changes = [patch(0, '原说法甲和原说法乙。', '修订整句。'), patch(1, '原说法乙', '修订乙')]
    if reverse: changes.reverse()
    assert apply_local_corrections(draft, changes, [{'problem': '甲'}, {'problem': '乙'}]) == (draft, [])


def test_two_valid_edits_for_one_issue_are_applied_together():
    draft = '# 说明\n正文的加法错误。\n\n## 系统性总结\n总结的加法错误。'
    result, resolved = apply_local_corrections(draft, [patch(0, '正文的加法错误。', '正文的加法正确。'),
        patch(0, '总结的加法错误。', '总结的加法正确。')], [{'problem': '正文和总结'}])
    assert result == draft.replace('加法错误', '加法正确') and resolved == [0]


def test_invalid_fence_repair_does_not_undo_an_unrelated_valid_repair():
    draft = '# 说明\n加法错误。\n\n另一个错误。'
    result, resolved = apply_local_corrections(draft, [patch(0, '加法错误。', '加法正确。'),
        patch(1, '另一个错误。', '```python\n未闭合')], [{'problem': '加法'}, {'problem': '另一处'}])
    assert result == draft.replace('加法错误', '加法正确') and resolved == [0]


@pytest.mark.parametrize('before,after', [
    ('[教材｜第3页]', '[教材｜第30页]'),
    ('第3页', '第30页'),
    ('教材', '其他书'),
    ('[来源：教材，第3页]', '删除定位'),
    ('> 原话正确。', '改写原话。'),
])
def test_source_locations_and_quoted_text_are_protected_even_with_partial_anchors(before, after):
    draft = '# 说明\n> 原话正确。\n\n解释。[教材｜第3页]\n[来源：教材，第3页]'
    # Choose the full locator when the partial locator occurs twice.
    if before == '第3页': draft = '# 说明\n解释。[教材｜第3页]'
    if before == '教材': draft = '# 说明\n解释。[教材｜第3页]'
    assert apply_local_corrections(draft, [patch(0, before, after)], [{'problem': '核对'}]) == (draft, [])


def test_patch_containing_unchanged_source_citation_can_repair_the_explanation():
    draft = '# 说明\n加法2+3=4。[教材｜第3页]'
    result, resolved = apply_local_corrections(draft, [patch(0, '加法2+3=4。[教材｜第3页]',
        '加法2+3=5。[教材｜第3页]')], [{'problem': '计算错误'}])
    assert result == draft.replace('2+3=4', '2+3=5') and resolved == [0]


def test_patch_limit_cannot_hide_unprocessed_edits_of_the_same_issue():
    draft = '# 说明\n' + '\n'.join(f'错误{i}。' for i in range(9))
    changes = [patch(0, f'错误{i}。', f'正确{i}。') for i in range(9)]
    assert apply_local_corrections(draft, changes, [{'problem': '九处重复错误'}]) == (draft, [])


def test_fast_review_still_shows_a_partially_anchored_issue_without_an_extra_model_call():
    class Client:
        calls = 0
        async def complete(self, system, user, json_mode=False):
            self.calls += 1
            return json.dumps({'passed': False, 'issues': [{'location': '正文与总结', 'problem': '两处加法错误'}],
                'corrections': [patch(0, '2+3=4。', '2+3=5。'), patch(0, '不存在。', '正确。')]})
    client = Client()
    result, reports = asyncio.run(review_explanation(client, '只核对加法', '# 说明\n2+3=4。', mode='fast'))
    assert client.calls == 1 and '两处加法错误' in result and '待核实事项' in result
    assert not reports[0].get('locally_corrected_issues')


@pytest.mark.parametrize('invalid', [None, '', False, [], {'after': '缺少原句'}])
def test_malformed_edit_for_a_known_issue_keeps_the_whole_group_unapplied(invalid):
    draft = '# 说明\n2+3=4。'
    changes = [patch(0, '2+3=4。', '2+3=5。'), {'issue_index': 0, 'before': invalid, 'after': '修订。'}]
    assert apply_local_corrections(draft, changes, [{'problem': '加法'}]) == (draft, [])


def test_unprintable_patch_is_rejected_without_losing_an_independent_fix():
    draft = '# 说明\n第一处错误。\n第二处错误。'
    result, resolved = apply_local_corrections(draft, [patch(0, '第一处错误。', '第一处\x00。'),
        patch(1, '第二处错误。', '第二处修正。')], [{'problem': '第一处'}, {'problem': '第二处'}])
    assert result == draft.replace('第二处错误', '第二处修正') and resolved == [1]


def test_edit_guard_does_not_reparse_every_paragraph_as_a_table(monkeypatch):
    from studyforge import document_render
    def table_check(*args): raise AssertionError('结构保护不需要解析表格单元')
    monkeypatch.setattr(document_render, 'table_start', table_check)
    draft = '# 说明\n\n普通解释段落。\n\n需要修正。'
    result, resolved = apply_local_corrections(draft, [patch(0, '需要修正。', '已经修正。')], [{'problem': '解释'}])
    assert result == draft.replace('需要修正', '已经修正') and resolved == [0]


def test_edit_guard_keeps_math_quotes_and_ignores_headings_inside_code():
    draft = '# 说明\n> $$x=1$$\n\n```python\n# 代码注释\n```\n\n另一处错误。'
    assert apply_local_corrections(draft, [patch(0, 'x=1', 'x=2')], [{'problem': '引文'}]) == (draft, [])
    result, resolved = apply_local_corrections(draft, [patch(0, '# 代码注释', '# 合法代码注释')], [{'problem': '代码注释'}])
    assert '# 合法代码注释' in result and resolved == [0]


@pytest.mark.parametrize('unassigned', [None, {'before': '其他。', 'after': '修订。'},
    {'issue_index': False, 'before': '其他。', 'after': '修订。'},
    {'issue_index': 1, 'before': '其他。', 'after': '修订。'}])
def test_unassigned_patch_cannot_be_silently_dropped_while_hiding_an_issue(unassigned):
    draft = '# 说明\n错误。'
    assert apply_local_corrections(draft, [patch(0, '错误。', '正确。'), unassigned],
        [{'problem': '需要全部修订'}]) == (draft, [])


@pytest.mark.parametrize('draft,before,after', [
    ('# 说明\n解释。[论文](https://example.com/paper)', 'paper', 'other'),
    ('# 说明\n解释。https://example.com/paper', 'paper', 'other'),
    ('# 说明\n解释。[Paper | page 3]', 'page 3', 'page 30'),
])
def test_external_source_links_and_english_locations_are_also_protected(draft, before, after):
    assert apply_local_corrections(draft, [patch(0, before, after)], [{'problem': '引用'}]) == (draft, [])


@pytest.mark.parametrize('invalid_second_anchor', [False, True])
def test_full_generation_preserves_audit_status_in_word_and_saved_body(tmp_path, monkeypatch, invalid_second_anchor):
    """Native streaming response -> fast review -> snapshot -> real DOCX."""
    import httpx
    from docx import Document
    from studyforge import conversations, server
    from studyforge.ai import save_settings
    from studyforge.db import create_job, create_project, execute, j, many, now, one, uid, unj

    save_settings({'chat_provider': 'deepseek', 'deepseek_model': 'fixture-model', 'background_learning_enabled': False})
    project = create_project('局部修订交付验收')
    chat = conversations.create(project['id'], 'deepseek')
    source, path = uid(), tmp_path / '计算原文.txt'
    path.write_text('加法2+3=5。正文与总结应一致。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
        (source, project['id'], path.name, '.txt', str(path), 'ready', now()))
    draft = '# 计算解释\n\n正文2+3=4。\n\n## 系统性总结\n总结仍说2+3等于4。'
    requests, original_client = [], httpx.AsyncClient
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if body.get('response_format', {}).get('type') == 'json_object':
            answer = j({'passed': False, 'issues': [{'location': '正文和总结', 'problem': '正文和总结两处加法错误'}],
                'corrections': [patch(0, '正文2+3=4。', '正文2+3=5。'),
                    patch(0, '不存在的总结。' if invalid_second_anchor else '总结仍说2+3等于4。', '总结2+3等于5。')]})
        else: answer = draft
        return httpx.Response(200, text='data: ' + j({'choices': [{'delta': {'content': answer}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n')
    monkeypatch.setattr('studyforge.ai.get_secret', lambda key: 'test-key')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *args, **kwargs: original_client(transport=httpx.MockTransport(respond)))
    value = server.GenerateIn(project_id=project['id'], source_ids=[source], conversation_id=chat['id'],
        provider='deepseek', model='fixture-model', format='docx', exercises=False, review_mode='fast')
    job = create_job(project['id'], 'generate', value.model_dump())
    asyncio.run(server._generate_job(job, value))
    row = one('SELECT * FROM jobs WHERE id=?', (job,))
    assert row['status'] == 'completed', row['error']
    # One writing request and one review request; no repair or summary request.
    assert len(requests) == 2
    saved = one('SELECT * FROM document_snapshots WHERE job_id=?', (job,))
    report = unj(saved['metadata_json'])['reviews'][0]
    artifact = next(a for a in many('SELECT * FROM artifacts') if a['kind'] == 'explanation')
    word = '\n'.join(p.text for p in Document(artifact['path']).paragraphs)
    if invalid_second_anchor:
        assert '正文2+3=4。' in word and '正文和总结两处加法错误' in word and '待核实事项' in word
        assert '待核实事项' in saved['content'] and not report.get('locally_corrected_issues')
    else:
        assert '正文2+3=5。' in word and '总结2+3等于5。' in word and '待核实事项' not in word
        assert report['locally_corrected_issues'] == [0] and '尚未再次独立复核' in word
    assert len(report['issues']) == 1 and len(report['corrections']) == 2
    assert not many('SELECT * FROM exercise_sets')

