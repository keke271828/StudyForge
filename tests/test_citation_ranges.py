from studyforge.lesson_quality import citation_checks, expand_single_source_labels


def test_contiguous_asr_sentences_can_be_quoted_as_one_real_time_range():
    source = {'name': '课程', 'segments': [
        {'locator': '1.2-2.4 秒', 'text': '先选一个容差，'},
        {'locator': '约 2.1 秒画面', 'text': '无关界面文字'},
        {'locator': '2.4-3.6 秒', 'text': '再找统一门槛。'}]}
    result = citation_checks('> 先选一个容差，再找统一门槛。\n\n[课程｜1.20–3.60 秒]', [source])
    assert result['matched_citations'] == result['matched_quotes'] == 1
    assert result['warning_count'] == 0 and not result['semantic_verified']
    missing = citation_checks('[课程｜1.2-9.8 秒]', [source])
    assert missing['matched_citations'] == 0 and missing['warning_count'] == 1


def test_line_subranges_are_checked_against_actual_original_lines():
    source = {'name': '证明.txt', 'segments': [{'locator': '行1-4', 'text': '标题\n条件\n构造\n结论'}]}
    result = citation_checks('> 条件\n> 构造\n\n[证明.txt｜第2–3行]', [source])
    assert result['warning_count'] == 0 and result['matched_quotes'] == 1
    assert citation_checks('[证明.txt｜行3-5]', [source])['matched_citations'] == 0
    source['segments'][0]['text'] = '被概括成一句，未保留原行'
    assert citation_checks('[证明.txt｜行2-3]', [source])['matched_citations'] == 0


def test_page_range_cannot_include_an_unread_page():
    source = {'name': '教材', 'segments': [{'locator': '第39页', 'text': '定义'}, {'locator': '第40页', 'text': '证明'}]}
    assert citation_checks('[教材｜第39–40页]', [source])['matched_citations'] == 1
    assert citation_checks('[教材｜第38–40页]', [source])['matched_citations'] == 0
    source['segments'].append({'locator': '第39页', 'text': '重复位置'})
    assert citation_checks('[教材｜第39–40页]', [source])['matched_citations'] == 0


def test_approximate_frame_rounding_must_identify_a_unique_original_frame():
    source = {'name': '课程', 'segments': [{'locator': '约 200.177 秒画面', 'text': '原始板书'}]}
    assert citation_checks('[课程｜约200.18秒画面]', [source])['matched_citations'] == 1
    assert citation_checks('[课程｜约205秒画面]', [source])['matched_citations'] == 0
    source['segments'].append({'locator': '约 200.179 秒画面', 'text': '另一幅板书'})
    assert citation_checks('[课程｜约200.18秒画面]', [source])['matched_citations'] == 0


def test_duplicate_source_names_still_require_unambiguous_provenance():
    records = [{'name': '同名', 'segments': [{'locator': '行1-2', 'text': text}]} for text in ('甲\n乙', '丙\n丁')]
    result = citation_checks('> 甲\n\n[同名｜行1]', records)
    assert result['matched_citations'] == result['matched_quotes'] == 0


def test_single_source_label_expansion_requires_real_positions_and_preserves_code():
    source = {'name': '教材', 'segments': [{'locator': '第39页', 'text': '定义'}]}
    text = '[来源｜第39页]\n[来源｜第40页]\n[无关出处｜第39页]\n```text\n[来源｜第39页]\n```\n'
    document, count = expand_single_source_labels(text, [source])
    assert count == 1 and document.startswith('[来源 教材｜第39页]\n[来源｜第40页]')
    assert '[无关出处｜第39页]' in document and '```text\n[来源｜第39页]\n```' in document
    assert expand_single_source_labels(text, [source, source]) == (text, 0)


def test_shortened_label_does_not_resolve_ambiguous_source_positions():
    source = {'name': '教材', 'segments': [{'locator': '第39页', 'text': text} for text in ('甲', '乙')]}
    assert expand_single_source_labels('[来源｜第39页]', [source]) == ('[来源｜第39页]', 0)
