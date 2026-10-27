"""Exercise shared teaching/review boundaries without using the real user DB."""
import asyncio
import json

import pytest
from docx import Document
from fastapi.testclient import TestClient

from studyforge import ai, conversations, review, server
from studyforge.db import create_job, create_project, execute, many, now, one, uid, unj
from studyforge.teaching_policy import DATA_SCOPE_RULES


SOURCE = ('材料给定反应A+B→C的速率模型v=k[A][B]。浓度单位mol/L，'
          '速率单位mol/(L·s)。设k=0.2 L/(mol·s)，[A]=0.5 mol/L，[B]=0.3 mol/L。'
          '反应式不能单独推出这个速率律。')
WRONG = '给定的初始浓度是[A]=0.5、[B]=0.3 mol/L。'
FIXED = '给定浓度是[A]=0.5、[B]=0.3 mol/L；资料未说明是否为初始浓度。'
SUPPLEMENT = ('补充假设：若这组数值恰好是初始浓度，0.03就是相应初始时刻的速率；'
              '这个假设只作说明，不是原文已知条件。')
DRAFT = ('# 速率与条件\n\n> v=k[A][B]。[材料.txt｜行 1-1]\n\n' + WRONG +
         '\n\n代入给定模型得到v=0.03 mol/(L·s)。\n\n' + SUPPLEMENT +
         '\n\n## 系统性总结\n反应式本身不决定速率律。')


def correction():
    return {'passed': False, 'issues': [{'location': '给定条件',
        'problem': '原资料没有把给定浓度限定为初始浓度。', 'evidence': SOURCE}],
        'corrections': [{'issue_index': 0, 'before': WRONG, 'after': FIXED}]}


@pytest.mark.parametrize('mode,style,language', [
    ('overview', 'clear', 'zh'), ('deep', 'balanced', 'zh'), ('research', 'academic', 'en'),
])
def test_document_authoring_receives_shared_scope_once_without_extra_calls(mode, style, language):
    calls = []
    class Client:
        async def complete(self, system, user):
            calls.append((system, user))
            return '# 讲解\n' + FIXED + '\n\n## 系统性总结\n只按给定时刻解释。'
    question = '说明每个量、单位和给定时刻的含义，原资料没有说明初始条件，不出题。'
    asyncio.run(ai.generate_explanation(Client(), SOURCE, 3, [], style=style,
        learning_mode=mode, language=language, requirements=question))
    assert len(calls) == 1
    system, user = calls[0]
    assert system.count(DATA_SCOPE_RULES) == 1
    assert SOURCE in user and question in user
    assert '需要额外条件来解释时' in system and '补充假设' in system
    assert '未勾选' in user and '不生成习题' in user


def test_live_chat_transport_keeps_question_original_and_does_not_invent_profile_evidence(tmp_path, monkeypatch):
    from tests.test_teaching_session_state import prepared_chat, post_chat
    project, chat, args, requests = prepared_chat(tmp_path, monkeypatch)
    question = '这些数只是某时刻给定的，能举一个明确假设的例子吗？不要出题。'
    post_chat(TestClient(server.app), args, question)
    assert len(requests) == 1
    assert requests[0]['messages'][0]['content'].count(DATA_SCOPE_RULES) == 1
    assert requests[0]['messages'][-1]['content'] == question
    assert len(conversations.detail(chat['id'], project['id'])['messages']) == 2
    assert not many('SELECT * FROM exercise_sets')


def test_fast_review_retains_conditional_supplement_and_quote_while_fixing_given_status():
    calls = []
    class Client:
        async def complete(self, system, user, **kwargs):
            calls.append((system, user))
            return json.dumps(correction(), ensure_ascii=False)
    document, reports = asyncio.run(review.review_explanation(Client(), SOURCE, DRAFT,
        mode='fast', requirements='讲清给定模型、数据和补充假设，不出题。'))
    assert len(calls) == 1 and calls[0][0].count(DATA_SCOPE_RULES) == 1
    assert '假设的示意按其假设核对' in calls[0][0]
    assert FIXED in document and WRONG not in document
    assert SUPPLEMENT in document and '> v=k[A][B]。[材料.txt｜行 1-1]' in document
    assert reports[0]['locally_corrected_issues'] == [0]
    assert reports[0]['inference_scope']['version'] == review.INFERENCE_SCOPE_VERSION
    assert reports[0]['inference_scope']['meaning'] == 'requested_checks_not_accuracy_certification'


def test_full_generation_uses_one_author_and_one_fast_review_and_delivers_fixed_word(tmp_path, monkeypatch):
    import httpx
    ai.save_settings({'agent_tools_enabled': False, 'background_learning_enabled': False})
    project = create_project('给定条件验收')
    chat = conversations.create(project['id'], 'deepseek', 'fixture-model')
    source, path = uid(), tmp_path/'材料.txt'
    path.write_text(SOURCE, encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
        (source, project['id'], path.name, '.txt', str(path), 'ready', now()))
    requests, native = [], httpx.AsyncClient
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body['messages'][0]['content'].count(DATA_SCOPE_RULES) == 1
        answer = json.dumps(correction(), ensure_ascii=False) if body.get('response_format') else DRAFT
        return httpx.Response(200, text='data: '+json.dumps({'choices': [{'delta': {'content': answer},
            'finish_reason': 'stop'}]}, ensure_ascii=False)+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(ai, 'get_secret', lambda key: 'fixture-only')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: native(transport=httpx.MockTransport(respond)))
    value = server.GenerateIn(project_id=project['id'], conversation_id=chat['id'], source_ids=[source],
        provider='deepseek', model='fixture-model', format='docx', exercises=False,
        review_mode='fast', requirements='讲清给定时刻的条件，可以用明确的假设补充，不出题。')
    job = create_job(project['id'], 'generate', value.model_dump())
    asyncio.run(server._generate_job(job, value))
    assert one('SELECT status,error FROM jobs WHERE id=?', (job,)) == {'status': 'completed', 'error': None}
    assert len(requests) == 2, 'No added review rounds or rewrite calls.'
    snapshot = one('SELECT * FROM document_snapshots WHERE job_id=?', (job,))
    assert FIXED in snapshot['content'] and WRONG not in snapshot['content']
    assert SUPPLEMENT in snapshot['content']
    receipt = unj(snapshot['metadata_json'])['reviews'][0]
    assert receipt['locally_corrected_issues'] == [0]
    assert receipt['inference_scope']['version'] == review.INFERENCE_SCOPE_VERSION
    artifacts = many('SELECT * FROM artifacts WHERE project_id=?', (project['id'],))
    assert len(artifacts) == 1 and artifacts[0]['kind'] == 'explanation'
    text = '\n'.join(p.text for p in Document(artifacts[0]['path']).paragraphs)
    assert FIXED in text and WRONG not in text and SUPPLEMENT in text
    assert not many('SELECT * FROM exercise_sets')
