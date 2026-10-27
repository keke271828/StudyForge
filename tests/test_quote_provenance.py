import asyncio
import json

from docx import Document
from fastapi.testclient import TestClient
import httpx
import pytest

from studyforge import ai, conversations, job_control, lesson_quality as quality, server
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid


def source(text='令x=1。'):
    return [{'name': 'source.txt', 'segments': [{'locator': '行1', 'text': text}]}]


@pytest.mark.parametrize('original,quoted,status', [
    ('令x=1。', '令x=1。', 'verbatim'),
    ('令x=1。', '令 x = 1。', 'whitespace_only'),
    ('a b', 'ab', 'whitespace_only'),
    ('令x=1。', r'令 $x=1$。', 'not_matched'),
    ("f'(x)=0", 'f(x)=0', 'not_matched'),
    ('x<1', 'x≤1', 'not_matched'),
    ('a […] b', 'a […] b', 'verbatim'),
])
def test_literal_status_does_not_treat_format_or_symbol_changes_as_verbatim(original, quoted, status):
    text = '> ' + quoted + '\n\n[source.txt｜行1]'
    checked = quality.citation_checks(text, source(original))
    assert checked['quote_results'][0]['status'] == status
    assert checked['verbatim_quotes'] == int(status == 'verbatim')
    assert checked['whitespace_only_quotes'] == int(status == 'whitespace_only')
    assert checked['semantic_verified'] is False
    annotated = quality.annotate_chat_quotes(text, source(original))
    assert annotated.endswith(text)
    assert ('软件引文核对' in annotated) == (status != 'verbatim')
    assert '已证明等价' not in annotated


@pytest.mark.parametrize('footer', [
    '> ——source.txt，行1', '——source.txt，行1', '> ——[source.txt｜行1]', '[source.txt｜行1]',
])
def test_common_trailing_source_labels_resolve_only_selected_names_and_real_locations(footer):
    text = '> 令x=1。\n' + ('' if footer.startswith('>') else '\n') + footer
    checked = quality.citation_checks(text, source())
    assert checked['citation_count'] == checked['matched_citations'] == checked['verbatim_quotes'] == 1
    assert not checked['warning_count'] and quality.annotate_chat_quotes(text, source()) == text
    wrong = text.replace('行1', '行99')
    assert quality.citation_checks(wrong, source())['verbatim_quotes'] == 0
    assert '没有唯一可识别' in quality.annotate_chat_quotes(wrong, source())


def test_missing_source_is_unresolved_not_fabricated_or_autoread():
    text = '原文说：\n\n> 令x=1。\n>\n> ——未选择.txt，行1'
    checked = quality.citation_checks(text, [])
    assert checked['quote_results'][0]['status'] == 'unresolved'
    assert checked['quote_results'][0]['attributed']
    assert '没有唯一可识别' in quality.annotate_chat_quotes(text, [])
    assert '编造' not in quality.annotate_chat_quotes(text, [])
    repeated = source() + source()
    assert quality.citation_checks('> 令x=1。[source.txt｜行1]', repeated)['verbatim_quotes'] == 0


@pytest.mark.parametrize('text', [
    '一个逻辑示意：\n\n> ∀ε>0 P(ε) ⇒ P(ε₀)\n\n这不是原文引语。',
    chr(96)*3 + 'markdown\n> 示例 [source.txt｜行99]\n' + chr(96)*3,
    '自己给出的解释，不引用原文。',
])
def test_unattributed_examples_code_and_ordinary_explanations_are_not_given_source_notices(text):
    assert quality.annotate_chat_quotes(text, source()) == text


def test_ellipsis_preserves_order_and_literal_fragments_without_semantic_certification():
    records = source('条件甲。中间论证。结论乙。')
    good = quality.citation_checks('> 条件甲。[…]结论乙。[source.txt｜行1]', records)
    assert good['verbatim_quotes'] == 1 and good['quote_results'][0]['omitted']
    bad = quality.citation_checks('> 结论乙。[…]条件甲。[source.txt｜行1]', records)
    assert bad['verbatim_quotes'] == 0 and not good['semantic_verified']


def test_bounded_receipts_do_not_hide_late_unverified_quotes():
    text = '\n\n'.join(['> 令x=1。[source.txt｜行1]'] * 50 + ['> 改写。[source.txt｜行1]'] * 12)
    checks = quality.citation_checks(text, source())
    assert len(checks['quote_results']) == 50 and checks['quote_results_omitted'] == 12
    assert checks['attributed_unverified_count'] == 12
    annotated = quality.annotate_chat_quotes(text, source())
    assert '12处原文引语待核对' in annotated and annotated.endswith(text)
    layout = '\n\n'.join(['> 令x=1。[source.txt｜行1]'] * 50 + ['> 令 x = 1。[source.txt｜行1]'])
    checks = quality.citation_checks(layout, source())
    assert checks['whitespace_only_quotes'] == 1
    assert '来源定位需核对' in quality.mark_source_warnings(layout, checks)


@pytest.mark.parametrize('language,title', [('en', 'Software quotation check'), ('bilingual', '软件引文核对 / Software quotation check')])
def test_notice_uses_selected_language(language, title):
    text = '> 令 x = 1。[source.txt｜行1]'
    result = quality.annotate_chat_quotes(text, source(), language)
    assert title in result and 'Matched only after ignoring whitespace' in result and result.endswith(text)
    if language == 'en': assert '空白' not in result


@pytest.mark.parametrize('saved', ['{}','[1]','[]','[{"role":"assistant","content":"stale"}]'])
def test_unexpected_private_cache_falls_back_to_public_history_without_losing_messages(saved):
    from studyforge.db import connect
    from studyforge.dialogue_scope import retain_public_annotation
    p=create_project('旧上下文');chat=conversations.create(p['id'],'deepseek')
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),chat['id'],'user','学生自己的原话。',now()))
    execute('INSERT INTO agent_dialogue_state VALUES (?,?,?,?,?)',(chat['id'],0,saved,now(),1))
    execute('UPDATE conversations SET remote_thread_id=? WHERE id=?',('old-thread',chat['id']))
    with connect() as database:
        retain_public_annotation(database,chat['id'],'旧AI原话','软件说明\n旧AI原话')
    assert not one('SELECT * FROM agent_dialogue_state WHERE conversation_id=?',(chat['id'],))
    assert one('SELECT remote_thread_id FROM conversations WHERE id=?',(chat['id'],))['remote_thread_id'] is None
    assert one('SELECT content FROM messages WHERE conversation_id=?',(chat['id'],))['content']=='学生自己的原话。'


def material(tmp_path, provider='deepseek'):
    ai.save_settings({'agent_tools_enabled': False, 'background_learning_enabled': False, 'library_reference_mode': 'off'})
    p = create_project('引语来源验收'); c = conversations.create(p['id'], provider, 'fixture')
    path = tmp_path / 'source.txt'; path.write_text('令x=1。', encoding='utf-8'); sid = uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (sid, p['id'], path.name, '.txt', str(path), 'ready', now()))
    return p, c, sid


@pytest.mark.parametrize('provider', ['deepseek', 'codex'])
def test_actual_chat_notice_is_saved_reopened_and_carried_into_next_turn(tmp_path, monkeypatch, provider):
    p, chat, sid = material(tmp_path, provider)
    monkeypatch.setattr(ai, 'get_secret', lambda *a: 'fixture-only')
    raw = '原资料那句话是：\n\n> 令 $x=1$。\n>\n> ——source.txt，行1\n\n这是公式排版后的解释。'
    posted = []
    if provider == 'deepseek':
        native = httpx.AsyncClient
        def respond(request):
            body = json.loads(request.content); posted.append(body)
            answer = raw if len(posted) == 1 else '引用应对照原文核对，排版不等于逐字。'
            return httpx.Response(200, text='data: ' + j({'choices': [{'delta': {'content': answer, 'reasoning_content': 'PRIVATE_QUOTE_PROTOCOL'},
                'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n')
        monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: native(transport=httpx.MockTransport(respond)))
    else:
        async def stream(prompt, remote_thread_id=None, *a, **kw):
            posted.append({'prompt': prompt, 'remote': remote_thread_id, 'history': json.loads(kw['fallback_history'])})
            yield 'thread', 'fixture-thread-' + str(len(posted))
            yield 'final', raw if len(posted) == 1 else '应核对引文。'
        monkeypatch.setattr(server, 'bridge_for', lambda *a: type('Bridge', (), {'stream_turn': staticmethod(stream)})())
    with TestClient(server.app) as api:
        args = {'project_id': p['id'], 'conversation_id': chat['id'], 'provider': provider, 'model': 'fixture', 'source_ids': [sid]}
        first = api.post('/api/chat/stream', json=args | {'text': '请解释这句。'})
        assert first.status_code == 200 and '"error"' not in first.text and 'PRIVATE_QUOTE_PROTOCOL' not in first.text
        public = next(r['content'] for r in conversations.detail(chat['id'], p['id'])['messages'] if r['role'] == 'assistant')
        assert public.startswith('**软件引文核对**') and public.endswith(raw)
        second = api.post('/api/chat/stream', json=args | {'text': '刚才的引文是否真的逐字相同？'})
        assert '"error"' not in second.text
    assert len(posted) == 2
    if provider == 'deepseek':
        assert any(row.get('content') == public for row in posted[-1]['messages'])
        assert any(row.get('reasoning_content') == 'PRIVATE_QUOTE_PROTOCOL' for row in posted[-1]['messages'])
    else:
        assert posted[-1]['remote'] is None and any(row['content'] == public for row in posted[-1]['history'])
    users = [r['content'] for r in conversations.detail(chat['id'], p['id'])['messages'] if r['role'] == 'user']
    assert users == ['请解释这句。', '刚才的引文是否真的逐字相同？']
    assert not many('SELECT * FROM mastery') and not many('SELECT * FROM learning_insights')


@pytest.mark.parametrize('quoted,status', [('令x=1。','verbatim'), ('令 x = 1。','whitespace_only'), ('令 $x=1$。','not_matched')])
def test_full_docx_job_exposes_literal_status_keeps_raw_quote_and_adds_no_model_round(tmp_path, monkeypatch, quoted, status):
    p, chat, sid = material(tmp_path)
    monkeypatch.setattr(ai, 'get_secret', lambda *a: 'fixture-only')
    native = httpx.AsyncClient; posted = []
    answer = '# 定义\n\n> ' + quoted + '\n>\n> [source.txt｜行1]\n\n解释。\n\n## 系统性总结\n保留条件。'
    def respond(request):
        posted.append(json.loads(request.content))
        return httpx.Response(200, text='data: ' + j({'choices': [{'delta': {'content': answer}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: native(transport=httpx.MockTransport(respond)))
    value = server.GenerateIn(project_id=p['id'], conversation_id=chat['id'], source_ids=[sid],
        provider='deepseek', model='fixture', format='docx', review_mode='express')
    job = create_job(p['id'], 'generate', value.model_dump() | {'dialogue_snapshot': server.mentor_snapshot(value)})
    async def run():
        await job_control.start_job(job, server._generate_job(job, value))
    asyncio.run(run())
    saved = one('SELECT status,error FROM jobs WHERE id=?', (job,))
    assert saved['status'] == 'completed', saved['error']
    artifact = one("SELECT * FROM artifacts WHERE project_id=? AND kind='explanation'", (p['id'],))
    check = json.loads(artifact['metadata_json'])['lesson_quality']
    assert check['quote_results'][0]['status'] == status
    body = '\n'.join(p.text for p in Document(artifact['path']).paragraphs)
    assert '保留条件' in body and ('来源定位需核对' in body) == (status != 'verbatim')
    assert len(posted) == 1 and not many('SELECT * FROM mastery') and not many('SELECT * FROM exercise_sets')
