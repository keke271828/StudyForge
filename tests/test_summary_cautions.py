"""Compression must not turn known concerns into apparently settled knowledge."""
import asyncio

import pytest

from studyforge.teaching import finish_explanation, summary_context, summary_section


def long_chapters():
    return ['# 第一部分\n' + '已完成的解释。' * 6000 +
        '\n## 系统性总结\n一个估计用于后续论证。\n\n## 待核实事项\n'
        '- 适用范围：该估计只保证 n>N，不能写成对所有 n 成立。',
        '# 第二部分\n' + '另一部分解释。' * 6000 + '\n## 系统性总结\n后续结论依赖第一部分的条件。']


def test_compressed_input_preserves_the_actual_caution_beside_the_recap():
    prepared = summary_context(long_chapters())
    assert prepared['excerpted'] and len(prepared['text']) <= 48000
    assert '该估计只保证 n>N，不能写成对所有 n 成立。' in prepared['text']
    assert prepared['caution_sections_total'] == prepared['caution_sections_included'] == 1
    assert prepared['caution_sections_omitted'] == 0


@pytest.mark.parametrize('budget', [400, 600, 1200, 8000, 48000])
def test_large_caution_volume_has_a_hard_budget_and_explicit_omissions(budget):
    chapters = [f'# 部分{i}\n' + '已完成解释。' * 200 +
        f'\n## 系统性总结\n结论{i}。\n## 待核实事项\n- 疑点{i}：' + '尚未核实的具体条件。' * 90 for i in range(100)]
    prepared = summary_context(chapters, budget=budget)
    assert len(prepared['text']) <= budget
    assert prepared['caution_sections_total'] == 100
    assert prepared['caution_sections_included'] + prepared['caution_sections_omitted'] == 100
    assert prepared['caution_sections_omitted'] > 0
    assert '核查记录' in prepared['text'] and '未列入' in prepared['text']


def test_short_input_keeps_the_full_caution_once_without_repeating_it():
    caution = '- 缺少边界条件，当前无法确认。'
    prepared = summary_context(['# 第一部分\n解释。\n## 待核实事项\n' + caution,
        '# 第二部分\n另一部分解释。'])
    assert not prepared['excerpted'] and prepared['text'].count(caution) == 1
    assert prepared['caution_sections_total'] == prepared['caution_sections_included'] == 1


def test_quotes_and_code_do_not_become_the_applications_review_records():
    document = '# 说明\n> ## 待核实事项\n> 作者的问题。\n\n```text\n## 待核实事项\n代码里的文本。\n```'
    prepared = summary_context([document])
    assert prepared['caution_sections_total'] == 0


@pytest.mark.parametrize('title', ['Items requiring verification', '待核实事项 / Items requiring verification',
    '来源定位需核对', 'Source citations requiring verification', '局部代数核对提示（待核对）',
    'Local algebra checks to confirm'])
def test_known_review_headings_are_recognized_across_languages(title):
    prepared = summary_context(['# 章节\n' + '解释。' * 20000 +
        f'\n## 系统性总结\n有条件结论。\n\n## {title}\n- CAUTION_DETAIL: conditions remain unverified.'])
    assert 'CAUTION_DETAIL' in prepared['text']
    assert prepared['unresolved_sections_total'] == 1


def test_applied_but_unrechecked_note_is_not_reported_as_a_confirmed_remaining_error():
    prepared = summary_context(['# 章节\n解释。\n## 核查说明\n已局部修订，尚未再次独立复核。'])
    assert prepared['caution_sections_total'] == 1 and prepared['unresolved_sections_total'] == 0


def test_caution_handoff_keeps_the_scope_of_a_doubt_distinct_from_other_conclusions():
    prepared = summary_context(['# 比较\n随机分配的是提醒。\n## 待核实事项\n- 提醒效果不等于行为效果。'])
    assert '疑点只限制它涉及的断言' in prepared['text'] and '待核实不等于已证错误' in prepared['text']


def test_final_summary_request_preserves_concern_and_uses_the_existing_one_call():
    calls = []
    class Client:
        async def complete(self, system, user):
            calls.append((system, user))
            assert '该估计只保证 n>N' in user and len(user) <= 48000
            return '## 系统性总结\n后续论证需要先核对第一部分的条件。'
    chapters = long_chapters()
    document = '\n\n'.join(chapters)
    result = asyncio.run(finish_explanation(Client(), document, chapters=chapters))
    assert len(calls) == 1 and result.startswith(document)
    assert result.endswith('后续论证需要先核对第一部分的条件。')


@pytest.mark.parametrize('language,marker', [('zh', '核查提示'), ('en', 'Review cautions'), ('bilingual', 'Review cautions')])
def test_final_summary_retains_visible_caution_even_if_model_ignores_it(language, marker):
    class Client:
        async def complete(self, *_): return '## Systematic summary\nCandidate summary.'
    chapters = ['# 章节\n讲解。\n## 待核实事项\n- 条件有疑点。', '# 后续\n讲解。']
    result = asyncio.run(finish_explanation(Client(), '\n\n'.join(chapters), language=language, chapters=chapters))
    start, end = summary_section(result)
    assert marker in result[start:end] and result.endswith('Candidate summary.')


def test_reusing_existing_summary_does_not_add_a_model_call_or_duplicate_caution_notice():
    class Client:
        async def complete(self, *_): raise AssertionError('Do not regenerate an already present summary.')
    document = '# 章节\n解释。\n## 待核实事项\n- 仍需核实条件。\n## 系统性总结\n有条件结论。'
    once = asyncio.run(finish_explanation(Client(), document))
    twice = asyncio.run(finish_explanation(Client(), once))
    assert once == twice and '核查提示' in once[summary_section(once)[0]:]


def test_model_written_caution_label_does_not_replace_the_applications_actual_notice():
    class Client:
        async def complete(self, *_): return '## 系统性总结\n**核查提示：**已经完全核实。\n候选总结。'
    chapters = ['# 章节\n## 待核实事项\n仍需核实条件。']
    result = asyncio.run(finish_explanation(Client(), chapters[0], chapters=chapters))
    assert '总结不表示这些疑点已被排除' in result


def test_reusing_a_prepared_context_does_not_rebuild_or_change_the_summary_input(monkeypatch):
    from studyforge import teaching
    chapters = long_chapters()
    plan = summary_context(chapters)
    monkeypatch.setattr(teaching, 'summary_context', lambda *a, **k: pytest.fail('Already prepared this immutable summary input.'))
    class Client:
        async def complete(self, system, user):
            assert user == plan['text']
            return '## 系统性总结\n保留条件。'
    result = asyncio.run(finish_explanation(Client(), '\n\n'.join(chapters), chapters=chapters, summary_plan=plan))
    assert result.endswith('保留条件。')


@pytest.mark.parametrize('parallel', [False, True])
def test_actual_long_generation_keeps_review_cautions_in_summary_word_and_receipt(tmp_path, monkeypatch, parallel):
    from docx import Document
    from studyforge import server
    from studyforge.ai import save_settings
    from studyforge.db import create_job, create_project, execute, j, many, now, one, uid, unj
    save_settings({'background_learning_enabled': False})
    project = create_project('长文核查衔接')
    path, source = tmp_path / '尾部估计.txt', uid()
    path.write_text('当n>N时才有尾部估计。\n' + '原文细节。'*14000, encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
        (source, project['id'], path.name, '.txt', str(path), 'ready', now()))
    calls, drafts = [], []
    class Client:
        model = 'fixture-model'
        async def complete(self, system, user, **kwargs):
            calls.append((system, user, kwargs))
            if kwargs.get('json_mode'):
                defect = len(drafts) == 1
                return j({'passed': not defect, 'issues': [{'location': '范围', 'problem':
                    '该估计只保证 n>N，不能写成对所有 n 成立。'}] if defect else [], 'corrections': []})
            if '只补写整篇文章的系统性总结' in system:
                assert '该估计只保证 n>N' in user and len(user) <= 48000
                return '## 系统性总结\n论证依赖尾部条件；未核实处保留疑点。'
            if drafts:
                assert '该估计只保证 n>N' in user, '下一部分的衔接也要保留前一部分的疑点'
            drafts.append(True)
            return '# 分部讲解\n' + '主体解释。'*7000 + '\n## 系统性总结\n尾部估计用于后续。'
    monkeypatch.setattr(server, 'client_for', lambda *a, **k: Client())
    if parallel:
        monkeypatch.setattr(server.lesson_quality, 'chapter_dependencies', lambda originals:
            [{'index': i, 'after': i-1 if i else None, 'reason': '受控的续接章节'} for i in range(len(originals))])
    value = server.GenerateIn(project_id=project['id'], source_ids=[source], provider='deepseek',
        model='fixture-model', review_mode='fast', format='docx', exercises=False, parallel=parallel)
    job = create_job(project['id'], 'generate', value.model_dump())
    asyncio.run(server._generate_job(job, value))
    status = one('SELECT * FROM jobs WHERE id=?', (job,))
    assert status['status'] == 'completed', status['error']
    assert len(drafts) == 2 and len(calls) == 5
    artifact = one("SELECT * FROM artifacts WHERE kind='explanation'")
    meta = unj(artifact['metadata_json'])
    assert meta['lesson_quality']['summary_caution_sections_total'] == 1
    assert meta['lesson_quality']['summary_caution_sections_included'] == 1
    assert meta['lesson_quality']['summary_caution_sections_omitted'] == 0
    document = one('SELECT content FROM document_snapshots WHERE job_id=?', (job,))['content']
    assert '该估计只保证 n>N' in document and '核查提示' in document[summary_section(document)[0]:]
    word = '\n'.join(p.text for p in Document(artifact['path']).paragraphs)
    assert '该估计只保证 n>N' in word and '总结不表示这些疑点已被排除' in word
    assert not many('SELECT * FROM exercise_sets')


def test_next_chapter_receives_cautions_with_the_original_part_number():
    from studyforge.lesson_quality import chapter_context
    chapters = ['# 部分\n## 系统性总结\n小结。'] * 30
    chapters[28] += '\n## 待核实事项\n- 第29部分的限定条件尚待核实。'
    context = chapter_context({'text': '全文来源导航，不是原文摘要。'}, ['原文。']*31, 30, chapters, '')
    assert '第29部分的限定条件尚待核实' in context and '【第29部分核查记录】' in context
    assert '仅列最近24部分' in context and len(context) < 17000


def test_an_older_caution_outside_the_continuity_window_is_not_reported_as_read():
    from studyforge.lesson_quality import chapter_context
    chapters = ['# 部分\n## 系统性总结\n小结。'] * 30
    chapters[0] += '\n## 待核实事项\n- EARLY_CAUTION_NOT_IN_WINDOW。'
    context = chapter_context({'text': '全文导航。'}, ['原文。']*31, 30, chapters, '')
    assert 'EARLY_CAUTION_NOT_IN_WINDOW' not in context and '不代表没有疑点' in context

