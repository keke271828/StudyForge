"""A changed inline-math wrapper must not lose an otherwise exact review edit."""
import asyncio
import hashlib
import json

import pytest

from studyforge.review_corrections import apply_local_corrections

RAW = '而若 A 与 B 直接碰撞的一步就是基元步骤，才自然得到 $v=k[A][B]$。'
REPORTED = RAW.replace('A 与 B', '$A$ 与 $B$')
AFTER = '而若 A 与 B 直接碰撞的一步就是基元步骤，按给定模型可写成 $v=k[A][B]$；此处没有排除其他可能情况。'
ISSUES = [{'location': '正文和总结', 'problem': '把给定情境说成必要条件'}]


def patch(before=REPORTED, after=AFTER, index=0):
    return {'issue_index': index, 'before': before, 'after': after}


def test_single_letter_dollar_wrappers_can_anchor_a_sentence_inside_a_plain_paragraph():
    draft = '# 说明\n\n其他可能情形也没有排除；' + RAW + '这只是解释中的一部分。\n'
    receipts = []
    result, done = apply_local_corrections(draft, [patch()], ISSUES, match_receipts=receipts)
    assert result == draft.replace(RAW, AFTER) and done == [0]
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt['mode'] == 'single_letter_math_delimiters'
    assert draft[receipt['start']:receipt['end']] == RAW
    assert receipt['reported_before_sha256'] == hashlib.sha256(REPORTED.encode()).hexdigest()
    assert receipt['original_sha256'] == hashlib.sha256(RAW.encode()).hexdigest()
    assert not any(key in receipt for key in ('before', 'after', 'text'))


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_paragraph_start_and_newlines_remain_unchanged(newline):
    draft = '# 说明' + newline * 2 + RAW + newline
    result, done = apply_local_corrections(draft, [patch()], ISSUES)
    assert result == draft.replace(RAW, AFTER) and done == [0]


@pytest.mark.parametrize('wrapper', [
    lambda value: '> ' + value,
    lambda value: '# ' + value,
    lambda value: '- ' + value,
    lambda value: '1. ' + value,
    lambda value: '```text\n' + value + '\n```',
    lambda value: '~~~text\n' + value + '\n~~~',
    lambda value: '$$\n' + value + '\n$$',
    lambda value: '| 单元 | 解释 |\n|---|---|\n| 1 | ' + value + ' |',
    lambda value: '无法确定这句话的边界，' + value,
])
def test_format_alias_is_limited_to_whole_sentences_in_plain_paragraphs(wrapper):
    draft = wrapper(RAW)
    receipts = []
    assert apply_local_corrections(draft, [patch()], ISSUES, match_receipts=receipts) == (draft, [])
    assert receipts == []


@pytest.mark.parametrize('before', [
    REPORTED.replace('$A$', '$a$'),
    REPORTED.replace('$A$', '$A_1$'),
    REPORTED.replace('$A$', "$A'$"),
    REPORTED.replace('$A$', '$A′$'),
    REPORTED.replace('A][B', 'A][C'),
    REPORTED.replace('才自然', '会自然'),
    REPORTED.replace(' 与 ', '与'),
    REPORTED.replace('。', '！'),
    REPORTED.replace('$A$', '$$A$$'),
    REPORTED.replace('$A$', r'\(A\)'),
    REPORTED.replace('$A$', '`A`'),
    REPORTED.replace('$v=k[A][B]$', '$v=k[B][A]$'),
])
def test_alias_never_normalizes_symbols_formulas_words_spaces_or_prime_marks(before):
    assert apply_local_corrections(RAW, [patch(before=before)], ISSUES) == (RAW, [])


@pytest.mark.parametrize('replacement', ['A1', 'AA', 'A_1', "A'", 'A′', 'A^2', '$$A$$', r'\A'])
def test_plain_label_cannot_be_matched_inside_a_larger_token(replacement):
    draft = RAW.replace('A 与', replacement + ' 与')
    assert apply_local_corrections(draft, [patch()], ISSUES) == (draft, [])


@pytest.mark.parametrize('suffix', ['[教材｜第3页]', '[Source: Paper, page 3]', '[论文](https://example.com/p)', 'https://example.com/p'])
def test_source_metadata_in_an_alias_still_requires_literal_matching(suffix):
    raw = RAW[:-1] + suffix + '。'
    before = REPORTED[:-1] + suffix + '。'
    assert apply_local_corrections(raw, [patch(before=before)], ISSUES) == (raw, [])


def test_two_format_variants_are_ambiguous_and_do_not_create_receipts():
    second = RAW.replace('A 与', '$A$ 与')
    draft = RAW + '\n\n' + second
    receipts = []
    assert apply_local_corrections(draft, [patch()], ISSUES, match_receipts=receipts) == (draft, [])
    assert receipts == []


def test_a_literal_match_keeps_priority_over_a_different_format_variant():
    draft = RAW + '\n\n' + REPORTED
    receipts = []
    result, done = apply_local_corrections(draft, [patch()], ISSUES, match_receipts=receipts)
    assert result == RAW + '\n\n' + AFTER and done == [0]
    assert len(receipts) == 1 and receipts[0]['mode'] == 'literal'


@pytest.mark.parametrize('after', [RAW, REPORTED])
def test_delimiter_only_changes_do_not_resolve_a_substantive_issue(after):
    assert apply_local_corrections(RAW, [patch(after=after)], ISSUES) == (RAW, [])


def test_one_bad_anchor_keeps_the_whole_issue_unresolved_but_an_independent_fix_survives():
    draft = RAW + '\n\n另一个加法错误2+3=4。'
    changes = [patch(), patch('不存在的总结。', '这项不应单独执行。'),
               patch('另一个加法错误2+3=4。', '另一个加法修正2+3=5。', 1)]
    receipts = []
    result, done = apply_local_corrections(draft, changes, ISSUES * 2, match_receipts=receipts)
    assert result == draft.replace('错误2+3=4', '修正2+3=5') and done == [1]
    assert len(receipts) == 1 and receipts[0]['issue_index'] == 1


@pytest.mark.parametrize('reverse', [False, True])
def test_an_alias_conflict_keeps_both_issues_and_emits_no_success_receipt(reverse):
    changes = [patch(), patch('直接碰撞', '另一个修改', 1)]
    if reverse:
        changes.reverse()
    receipts = []
    assert apply_local_corrections(RAW, changes, ISSUES * 2, match_receipts=receipts) == (RAW, [])
    assert receipts == []


def test_fast_review_uses_the_same_single_request_and_records_actual_anchor_modes():
    from studyforge.review import review_explanation
    class Client:
        calls = 0
        async def complete(self, system, user, json_mode=False):
            self.calls += 1
            return json.dumps({'passed': False, 'issues': ISSUES, 'corrections': [patch()]}, ensure_ascii=False)
    client = Client()
    output, reports = asyncio.run(review_explanation(client, '只核对给定模型。', RAW, mode='fast'))
    assert client.calls == 1 and AFTER in output and RAW not in output
    assert '待核实事项' not in output and '尚未再次独立复核' in output
    assert reports[0]['locally_corrected_issues'] == [0]
    assert reports[0]['local_correction_anchors'][0]['mode'] == 'single_letter_math_delimiters'
    assert reports[0]['passed'] is False  # Applying an edit is not a second passed review.


@pytest.mark.parametrize('invalid_summary', [False, True])
def test_native_fast_review_saves_real_docx_with_atomic_alias_edits(tmp_path, monkeypatch, invalid_summary):
    import httpx
    from docx import Document
    from lxml import etree
    from studyforge import conversations, server
    from studyforge.ai import save_settings
    from studyforge.db import create_job, create_project, execute, j, many, now, one, uid, unj

    save_settings({'chat_provider': 'deepseek', 'deepseek_model': 'fixture-model', 'background_learning_enabled': False})
    project = create_project('公式格式差异修订验收')
    chat = conversations.create(project['id'], 'deepseek')
    source, path = uid(), tmp_path / '模型原文.txt'
    path.write_text('额外给定本例模型v=k[A][B]；不声明唯一机制。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (source, project['id'], path.name, '.txt', str(path), 'ready', now()))
    summary = '该情境被说成唯一解释，这是不恰当的总结。'
    fixed_summary = '该情境只是一个解释，没有排除其他可能。'
    draft = '# 模型说明\n\n' + RAW + '\n\n## 系统性总结\n' + summary
    requests, original_client = [], httpx.AsyncClient
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        answer = j({'passed': False, 'issues': ISSUES,
                    'corrections': [patch(), patch('未提供的总结。' if invalid_summary else summary, fixed_summary)]}) if body.get('response_format', {}).get('type') == 'json_object' else draft
        return httpx.Response(200, text='data: ' + j({'choices': [{'delta': {'content': answer}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n')
    monkeypatch.setattr('studyforge.ai.get_secret', lambda key: 'test-key')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **k: original_client(transport=httpx.MockTransport(respond)))
    value = server.GenerateIn(project_id=project['id'], source_ids=[source], conversation_id=chat['id'],
                              provider='deepseek', model='fixture-model', format='docx', exercises=False, review_mode='fast')
    job = create_job(project['id'], 'generate', value.model_dump())
    asyncio.run(server._generate_job(job, value))
    status = one('SELECT * FROM jobs WHERE id=?', (job,))
    assert status['status'] == 'completed', status['error']
    assert len(requests) == 2  # One draft and the existing one fast review.
    snapshot = one('SELECT * FROM document_snapshots WHERE job_id=?', (job,))
    report = unj(snapshot['metadata_json'])['reviews'][0]
    artifact = one("SELECT * FROM artifacts WHERE project_id=? AND kind='explanation'", (project['id'],))
    word = Document(artifact['path'])
    words = ''.join(etree.fromstring(word.part.blob).xpath('//*[local-name()="t"]/text()'))
    if invalid_summary:
        assert RAW in snapshot['content'] and summary in snapshot['content'] and '待核实事项' in snapshot['content']
        assert not report.get('locally_corrected_issues') and not report.get('local_correction_anchors')
        assert '才自然得到' in words and '待核实事项' in words
    else:
        assert AFTER in snapshot['content'] and fixed_summary in snapshot['content'] and '才自然得到' not in words
        assert report['locally_corrected_issues'] == [0]
        assert [r['mode'] for r in report['local_correction_anchors']] == ['single_letter_math_delimiters', 'literal']
        assert '尚未再次独立复核' in words
    assert not many('SELECT * FROM exercise_sets') and not many('SELECT * FROM mastery')
