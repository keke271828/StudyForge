import pytest

from studyforge.review_corrections import apply_local_corrections


ISSUES = [{'problem': '这一段的条件不足'}]
PROSE = '这是一段用于讲解的普通中文句子，把"通常成立"说成了已经验证的事实，但没有提供足够的条件或证据。'
FIXED = '这是一段用于讲解的普通中文句子；当前缺少方向判断的依据，不能因为一句通常成立就把未知条件当成事实。'


def patch(before=PROSE.replace('"', '“', 1).replace('"', '”'), after=FIXED, index=0):
    return {'issue_index': index, 'before': before, 'after': after}


def test_typographic_double_quotes_in_a_unique_plain_paragraph_can_anchor_a_real_fix():
    draft = '# 讲解\n\n'+PROSE+'\n\n## 系统性总结\n保留确定结论。'
    result, used = apply_local_corrections(draft, [patch()], ISSUES)
    assert result == draft.replace(PROSE, FIXED) and used == [0]


@pytest.mark.parametrize('wrapper', [
    lambda p: '> '+p,
    lambda p: '# '+p,
    lambda p: '```python\n'+p+'\n```',
    lambda p: '~~~text\n'+p+'\n~~~',
    lambda p: '$$\n'+p+'\n$$',
    lambda p: '- '+p,
    lambda p: '1. '+p,
    lambda p: '前面还有其他内容，'+p,
    lambda p: p+'后面还有其他内容。',
])
def test_quote_alias_does_not_enter_protected_or_partial_blocks(wrapper):
    draft = wrapper(PROSE)
    assert apply_local_corrections(draft, [patch()], ISSUES) == (draft, [])


@pytest.mark.parametrize('changed', ['通常成立2', '通常 成立', '往往成立'])
def test_alias_does_not_fuzzily_match_changed_words_spaces_or_numbers(changed):
    before = patch()['before'].replace('通常成立', changed)
    assert apply_local_corrections(PROSE, [patch(before)], ISSUES) == (PROSE, [])


@pytest.mark.parametrize('extra', [r'$x^2$', '`x`', r'\alpha', '[教材｜第3页]', 'https://example.com/a', ' | 表格单元'])
def test_formula_code_locator_and_url_paragraphs_still_require_exact_anchors(extra):
    text = PROSE+extra+'。'
    before = text.replace('"', '“', 1).replace('"', '”')
    assert apply_local_corrections(text, [patch(before)], ISSUES) == (text, [])


def test_normalized_duplicate_is_ambiguous_even_when_typography_differs():
    draft = PROSE+'\n\n'+PROSE.replace('"', '“')
    assert apply_local_corrections(draft, [patch()], ISSUES) == (draft, [])


def test_one_failed_alias_keeps_the_whole_issue_unresolved():
    changes = [patch(), patch('不存在的第二个段落。', '不能只改第一处。')]
    assert apply_local_corrections(PROSE, changes, ISSUES) == (PROSE, [])


def test_punctuation_only_or_no_op_alias_does_not_hide_a_substantive_issue():
    assert apply_local_corrections(PROSE, [patch(after=PROSE)], ISSUES) == (PROSE, [])
    assert apply_local_corrections(PROSE, [patch(after=PROSE.replace('"', '”'))], ISSUES) == (PROSE, [])


def test_quote_alias_conflicts_with_an_exact_patch_in_either_order():
    changes = [patch(), patch(PROSE[8:18], '另一处改动', 1)]
    for values in (changes, list(reversed(changes))):
        assert apply_local_corrections(PROSE, values, ISSUES*2) == (PROSE, [])


def test_crlf_alias_preserves_other_newlines_and_short_anchors_remain_exact_only():
    draft = '# 标题\r\n\r\n'+PROSE+'\r\n'
    result, used = apply_local_corrections(draft, [patch()], ISSUES)
    assert result == draft.replace(PROSE, FIXED) and used == [0]
    assert apply_local_corrections('说"会"。', [patch('说“会”。', '说不会。')], ISSUES) == ('说"会"。', [])
