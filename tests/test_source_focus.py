import hashlib

import pytest

from studyforge import source_focus as focus, source_origins as origin


def digest(*pages):
    return ''.join(f'\n[来源 {name}｜第 {page} 页] [资料ID:{sid}]\n{text}\n'
                   for name, sid, page, text in pages)


def validate(original, text, receipt):
    assert receipt['model_calls'] == 0
    assert receipt['input_characters'] == len(original)
    assert receipt['input_sha256'] == hashlib.sha256(original.encode()).hexdigest()
    assert receipt['context_sha256'] == hashlib.sha256(text.encode()).hexdigest()
    assert receipt['context_characters'] == len(text)
    for item in receipt['included']:
        raw = original[item['start']:item['end']]
        assert item['sha256'] == hashlib.sha256(raw.encode()).hexdigest()
        assert raw in text and item['locator'] in text


def test_page_neighbours_preserve_definition_proof_and_exception_in_order():
    original = digest(('教材','a',1,'定义只用于实数。'),('教材','a',2,'中心主题：平方和展开。'),
                      ('教材','a',3,'例外条件：零向量时不能相除。'),('另一本','b',1,'另一文件不能误称相邻条件。'))
    text, receipt = focus.prepare(original,'平方和')
    assert [item['source_id'] for item in receipt['included']] == ['a','a','a']
    assert text.index('定义只用于实数') < text.index('中心主题') < text.index('例外条件')
    assert '另一文件不能误称相邻条件' not in text
    validate(original,text,receipt)


@pytest.mark.parametrize('wrapper', ['$$\n{}\n$$',r'\['+'\n{}\n'+r'\]',
    '```python\n{}\n```','~~~~javascript\n{}\n~~~~',r'\('+'\n{}\n'+r'\)'])
def test_no_internal_cut_through_multiline_math_or_code(wrapper):
    block = wrapper.format('条件开始\n'+'\n'.join('保持这一步完整。'*70 for _ in range(12))+'\n\n中心主题：正交分解。\n条件结束')
    original = digest(('教材','a',1,('无关介绍。\n\n'*850)+block+'\n\n结尾条件。\n'))
    text, receipt = focus.prepare(original,'正交分解')
    assert block in text
    validate(original,text,receipt)


def test_tail_of_single_long_segment_and_unicode_coordinates():
    original = digest(('教材😀','a',1,'无关开头。\n\n'*14000+'尾部定义：商环可逆元🧮。\n\n尾部限制：模6时非零不等于可逆。'))
    text, receipt = focus.prepare(original,'商环可逆元')
    assert '尾部定义' in text and '尾部限制' in text
    assert receipt['included'][0]['start'] > 45000
    assert len(text) < 16000
    validate(original,text,receipt)


def test_explicit_reference_is_query_but_ids_and_neighbouring_topic_are_not():
    from studyforge.message_focus import retrieval_query
    reference = {'message_id':'do-not-search','selection':{'text':'浅复制'},'excerpt':'无关的高斯定律。浅复制'}
    query = retrieval_query('这里为什么？',reference)
    original = digest(('编程','a',1,'浅复制：外层新建，内层仍共享。'),('物理','b',1,'高斯定律：净通量。'))
    text, receipt = focus.prepare(original,query)
    assert '浅复制：' in text and '高斯定律：' not in text
    assert 'do-not-search' not in query
    validate(original,text,receipt)


@pytest.mark.parametrize('question', ['这里为什么？只讲这一点，不出题。','a completely absent topic','柯西不等式'])
def test_no_match_does_not_disguise_notes_or_first_page_as_original_evidence(question):
    original = digest(('教材','a',1,'NONMATCHING_PROSE\n\n'*6000))
    text, receipt = focus.prepare(original,question,[{'text':'笔记声称教材证明了万能公式。'}])
    assert receipt['reason'] == 'no_complete_match' and not receipt['included']
    assert 'NONMATCHING_PROSE' not in text and '没有找到' in text and '仅供导航，不是原文证据' in text
    assert '笔记声称教材证明了万能公式。' in text
    validate(original,text,receipt)


def test_english_words_do_not_match_inside_other_identifiers():
    original = digest(('代码','a',1,'scatter concatenation category'),('代码2','b',1,'cat is a token'))
    text, receipt = focus.prepare(original,'cat')
    assert 'cat is a token' in text and 'scatter' not in text
    validate(original,text,receipt)


def test_oversized_atomic_block_is_not_blindly_cut_and_does_not_crowd_out_other_match():
    original = digest(('大段','a',1,'中心主题：对称性。'+'不可拆公式'*30000),
                      ('可用','b',1,'中心主题：对称性。\n\n这个完整段落可供核对。'))
    text, receipt = focus.prepare(original,'对称性',limit=4000)
    assert '不可拆公式' not in text and '完整段落可供核对' in text
    assert receipt['skipped_neighbourhoods'] >= 1
    validate(original,text,receipt)


def test_neighbourhood_is_not_silently_shortened_when_its_conditions_do_not_fit():
    original = digest(('教材','a',1,'必要条件。'*1000),('教材','a',2,'中心主题：可逆元。'),
                      ('教材','a',3,'结尾限制。'*1000))
    text, receipt = focus.prepare(original,'可逆元',limit=4000)
    assert not receipt['included'] and '中心主题：可逆元' not in text
    assert '没有找到预算内可完整提供' in text


def test_selected_generated_material_keeps_identity_but_does_not_claim_its_cited_textbook_was_read():
    prefix = origin.header([{'name':'讲解','source_id':'a','role':'ai_generated_artifact','kind':'explanation'},
                            {'name':'别的','source_id':'b','role':'provided_material'}])
    original = prefix + digest(('讲解','a',1,'关于可逆元的AI讲解，引用未读教材。'),('别的','b',1,'无关内容。'))
    text, receipt = focus.prepare(original,'可逆元')
    assert 'ai_generated_artifact' in text and '"source_id":"a"' in text
    assert '"source_id":"b"' not in text and '原资料全文' not in text
    validate(original,text,receipt)


def test_navigation_is_bounded_and_does_not_emit_half_a_formula_or_code():
    note='## 整体导航\n\n有效笔记段落。\n\n```python\n'+('unfinished = 1\n'*5000)
    original=digest(('教材','a',1,'中心主题：直和分解。'))
    text, receipt=focus.prepare(original,'直和分解',[{'text':note},{'text':'其他笔记。'*10000}])
    assert '有效笔记段落' in text and 'unfinished' not in text and '```python' not in text
    assert len(text) < 2500
    validate(original,text,receipt)


def test_missing_locator_does_not_invent_one():
    text, receipt = focus.prepare('裸文本：这里讨论可逆元。','可逆元')
    assert not receipt['included'] and '[来源 ' not in text


def test_old_context_version_invalidates_private_chat_signature_only(monkeypatch):
    from studyforge.teaching_policy import chat_policy_signature
    before = chat_policy_signature('deep','clear','zh')
    monkeypatch.setattr(focus,'VERSION','changed-input')
    assert before != chat_policy_signature('deep','clear','zh')


def test_budget_validation():
    with pytest.raises(ValueError,match='至少'):
        focus.prepare('x','x',limit=0)


@pytest.mark.parametrize('opening,closing',[('```python','```'),('$$','$$'),(r'\[',r'\]')])
def test_container_split_between_source_pages_is_extended_to_both_delimiters(opening,closing):
    original=digest(('教材','a',1,'上下文。\n\n'+opening+'\nBLOCK_BEGIN\n'),
                    ('教材','a',2,'必须保留的前半步骤\n'),
                    ('教材','a',3,'中心主题：正交分解\n'),
                    ('教材','a',4,'必须保留的后半步骤\n'),
                    ('教材','a',5,'BLOCK_END\n'+closing+'\n'))
    text,receipt=focus.prepare(original,'正交分解')
    assert len(receipt['included'])==5 and 'BLOCK_BEGIN' in text and 'BLOCK_END' in text
    assert text.count(opening)>=1 and text.count(closing)>=1
    validate(original,text,receipt)


def test_container_without_closure_is_not_delivered_as_complete_code():
    original=digest(('教材','a',1,'```python\n'),('教材','a',2,'中心主题：浅复制\n'),
                    ('教材','a',3,'没有提供结束代码围栏\n'))
    text,receipt=focus.prepare(original,'浅复制')
    assert not receipt['included'] and '中心主题：浅复制' not in text


def test_neighbour_expansion_never_closes_a_code_block_using_a_different_file():
    original=digest(('教材','a',1,'```python\n中心主题：浅复制\n'),('另一本','b',1,'```\n'))
    text,receipt=focus.prepare(original,'浅复制')
    assert not receipt['included']
