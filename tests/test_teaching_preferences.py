import asyncio
import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from studyforge import ai, conversations, server
from studyforge.config import data_dir
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid
from studyforge.generation_control import control_for
from studyforge.review import review_explanation
from studyforge.teaching import CLEAR_TEACHING_RULES, finish_explanation
from studyforge.teaching_styles import LANGUAGE_LABELS, STYLE_LABELS


def material(tmp_path):
    project = create_project('教学选项验收')
    source, path = uid(), tmp_path / '原材料.txt'
    original = '前提支持结论。\n类比不等于因果证明，论证需要依据和适用条件。'
    path.write_text(original, encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (source, project['id'], path.name, '.txt', str(path), j([{'locator':'预览','text':'这个摘要不能替代全文'}]), 'ready', now()))
    return project, source, original


def cloud(monkeypatch):
    ai.save_settings({'chat_provider':'deepseek', 'agent_tools_enabled':False, 'background_learning_enabled':False})
    monkeypatch.setattr(ai, 'get_secret', lambda key:'fixture-key')
    calls, native = [], httpx.AsyncClient

    def respond(request):
        body = json.loads(request.content); calls.append(body)
        system = body['messages'][0]['content']
        if '【Anki格式整理】' in system:
            text = j({'cards':[{'question':'What supports a conclusion?', 'answer':'Premises under stated conditions.', 'source':'[原材料.txt｜行 1-2]'}]})
        elif '【代码包格式整理】' in system:
            text = j({'files':[{'path':'example.py','content':'# Preserve the stated conditions.\nx = 1\n'}, {'path':'README.md','content':'Run python example.py. Not executed.'}]})
        elif '只返回一个带语言标记' in system:
            text = '```python\n# Preserve the stated conditions.\nx = 1\n```'
        elif body.get('response_format', {}).get('type') == 'json_object':
            text = j({'passed':True, 'issues':[]})
        elif '当前讲解语言：英语' in system:
            text = '# Explanation\n\nPremises support a conclusion under stated conditions.\n\n## Systematic summary\nDistinguish the claim from its evidence.'
        elif '当前讲解语言：中英双语' in system:
            text = '# 论证 / Argument\n\n前提在特定条件下支持结论。\n\nPremises support a conclusion under stated conditions.\n\n## 系统性总结 / Systematic summary\n区分主张与依据。\n\nDistinguish the claim from its evidence.'
        else:
            text = '# 论证\n\n前提在特定条件下支持结论。\n\n## 系统性总结\n区分主张与依据。'
        return httpx.Response(200, text='data: '+j({'choices':[{'delta':{'content':text}, 'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')

    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **k:native(transport=httpx.MockTransport(respond)))
    return calls


async def generate(value):
    result = await server.generate(value)
    for _ in range(300):
        row = one('SELECT * FROM jobs WHERE id=?', (result['job_id'],))
        if row['status'] in ('completed', 'failed'):
            assert row['status'] == 'completed', row['error']
            return result, json.loads(row['payload_json'])
        await asyncio.sleep(.01)
    raise AssertionError('生成未完成')


@pytest.mark.parametrize('style', ['clear','balanced','academic'])
@pytest.mark.parametrize('language', ['zh','bilingual','en'])
def test_generation_applies_real_style_language_mode_without_extra_calls(tmp_path, monkeypatch, style, language):
    project, source, original = material(tmp_path); calls = cloud(monkeypatch)
    mode = {'clear':'overview','balanced':'deep','academic':'research'}[style]
    result, payload = asyncio.run(generate(server.GenerateIn(project_id=project['id'], source_ids=[source],
        provider='deepseek', explanation_style=style, output_language=language, learning_mode=mode,
        review_mode='express', summary_level=1, instructions='只使用原资料，简短说明必要条件，不出题。')))
    assert len(calls) == 1, '风格、语言或双语总结不得自动追加模型调用'
    system = calls[0]['messages'][0]['content']
    user = '\n'.join(x['content'] for x in calls[0]['messages'][1:])
    assert system.count(CLEAR_TEACHING_RULES) == 1
    assert f'当前讲解风格：{STYLE_LABELS[style]}' in system
    assert f'当前讲解语言：{LANGUAGE_LABELS[language]}' in system
    assert '不硬套生活比喻' in system if style == 'clear' else True
    assert original in user and '简短说明必要条件' in user
    assert '这个摘要不能替代全文' not in user
    assert payload['explanation_style'] == style and payload['output_language'] == language
    assert payload['learning_mode'] == mode and payload['review_mode'] == 'express' and payload['summary_level'] == 1
    assert payload['dialogue_snapshot']['mentor']['explanation_style'] == style
    assert payload['dialogue_snapshot']['mentor']['output_language'] == language
    row = conversations.detail(result['conversation_id'], project['id'])
    assert row['explanation_style'] == style and row['output_language'] == language
    meta = json.loads(one("SELECT metadata_json FROM artifacts WHERE kind='explanation'")['metadata_json'])
    assert meta['explanation_style'] == style and meta['output_language'] == language
    assert len(many('SELECT * FROM artifacts')) == 1 and many('SELECT * FROM exercise_sets') == []


@pytest.mark.parametrize('fmt', ['py','ipynb','apkg','zip'])
def test_code_cards_and_bundle_receive_same_teaching_preferences(tmp_path, monkeypatch, fmt):
    project, source, _ = material(tmp_path); calls = cloud(monkeypatch)
    result, payload = asyncio.run(generate(server.GenerateIn(project_id=project['id'], source_ids=[source],
        provider='deepseek', format=fmt, explanation_style='academic', output_language='en',
        learning_mode='research', review_mode='express')))
    assert len(calls) == 2, '只有代码/格式整理所需的一次附加请求'
    actual = calls[-1]['messages'][0]['content']
    assert '当前讲解风格：学术专业' in actual and '当前讲解语言：英语' in actual and '当前学习模式：研究' in actual
    row = one("SELECT * FROM artifacts WHERE kind='explanation'")
    from pathlib import Path
    import zipfile
    path = Path(row['path'])
    if fmt == 'py':
        assert 'Execution status:' in path.read_text(encoding='utf-8')
    elif fmt == 'ipynb':
        notebook = json.loads(path.read_text(encoding='utf-8'))
        assert 'Execution status:' in ''.join(notebook['cells'][0]['source'])
        assert any(c['cell_type']=='code' and 'x = 1' in ''.join(c['source']) for c in notebook['cells'])
    else:
        with zipfile.ZipFile(path) as archive: assert archive.namelist()


@pytest.mark.parametrize('provider', ['codex','deepseek'])
def test_chat_all_styles_languages_inherit_in_one_conversation(tmp_path, monkeypatch, provider):
    project, source, original = material(tmp_path); calls = cloud(monkeypatch); codex = []

    async def stream(prompt, remote=None, model=None, effort=None, **kwargs):
        codex.append((prompt, remote))
        yield 'thread', 'one-private-thread'
        yield 'final', '功能测试回复。'
    monkeypatch.setattr('studyforge.codex_bridge.CodexBridge.stream_turn',lambda self,*args,**kwargs:stream(*args,**kwargs))
    api = TestClient(server.app); cid = None
    for style, language, mode in [('clear','zh','overview'), ('balanced','bilingual','deep'), ('academic','en','research'), (None,None,None)]:
        body = dict(project_id=project['id'], source_ids=[source], provider=provider, model='fixture', text='只用原文简短说明，不出题。', conversation_id=cid)
        if style: body.update(explanation_style=style, output_language=language, learning_mode=mode)
        response = api.post('/api/chat/stream', json=body)
        assert response.status_code == 200 and '"error"' not in response.text
        next_id = next(json.loads(line)['value'] for line in response.text.splitlines() if json.loads(line)['type'] == 'conversation')
        if cid: assert next_id == cid
        cid = next_id
        prompt = codex[-1][0] if provider == 'codex' else calls[-1]['messages'][0]['content']
        assert f'当前讲解风格：{STYLE_LABELS[style or "academic"]}' in prompt
        assert f'当前讲解语言：{LANGUAGE_LABELS[language or "en"]}' in prompt
        assert prompt.count(CLEAR_TEACHING_RULES) == 1 and original in prompt
    assert len(many('SELECT * FROM conversations')) == 1 and len(many('SELECT * FROM messages')) == 8
    assert len(codex if provider == 'codex' else calls) == 4
    if provider == 'codex': assert all(item[1] == 'one-private-thread' for item in codex[1:])


def test_preferences_are_independent_and_defaults_only_bind_new_chats(tmp_path):
    project, _, _ = material(tmp_path); api = TestClient(server.app)
    first = api.post(f'/api/projects/{project["id"]}/conversations', json={'provider':'deepseek'}).json()
    ai.save_settings({'explanation_style':'academic','output_language':'en','review_mode':'strict'})
    second = api.post(f'/api/projects/{project["id"]}/conversations', json={'provider':'deepseek'}).json()
    assert (second['explanation_style'], second['output_language'], second['review_mode']) == ('academic','en','strict')
    saved = api.get(f'/api/conversations/{first["id"]}?project_id={project["id"]}').json()
    assert (saved['explanation_style'], saved['output_language'], saved['review_mode']) == ('clear','zh','express')
    response = api.put('/api/conversations/'+first['id'], json={'project_id':project['id'],'output_language':'bilingual','review_mode':'fast'})
    assert response.status_code == 200 and response.json()['explanation_style'] == 'clear'
    assert conversations.detail(second['id'], project['id'])['review_mode'] == 'strict'
    with TestClient(server.app) as fresh:
        row = fresh.get(f'/api/conversations/{first["id"]}?project_id={project["id"]}').json()
    assert (row['explanation_style'], row['output_language'], row['review_mode']) == ('clear','bilingual','fast')


def test_omitted_generation_preferences_use_saved_chat(tmp_path, monkeypatch):
    project, source, _ = material(tmp_path); calls = cloud(monkeypatch)
    chat = conversations.create(project['id'], 'deepseek', explanation_style='academic', output_language='bilingual', review_mode='balanced')
    result, payload = asyncio.run(generate(server.GenerateIn(project_id=project['id'], source_ids=[source], provider='deepseek', conversation_id=chat['id'])))
    assert len(calls) == 2 and calls[1].get('response_format', {}).get('type') == 'json_object'
    assert (payload['explanation_style'], payload['output_language'], payload['review_mode']) == ('academic','bilingual','balanced')
    assert result['conversation_id'] == chat['id']


@pytest.mark.parametrize('review_mode,expected', [('fast',2),('balanced',2),('strict',4)])
def test_native_generation_and_audit_share_frozen_student_requirements(tmp_path, monkeypatch, review_mode, expected):
    project, source, original = material(tmp_path); calls = cloud(monkeypatch)
    chat = conversations.create(project['id'], 'deepseek')
    unrelated = conversations.create(project['id'], 'deepseek')
    execute('INSERT INTO messages VALUES (?,?,?,?,?)', (uid(),chat['id'],'user','EARLIER_SCOPE：只解释论证的依据，不要补其他学科。',now()))
    execute('INSERT INTO messages VALUES (?,?,?,?,?)', (uid(),unrelated['id'],'user','FOREIGN_CHAT_MUST_STAY_PRIVATE',now()))
    result, payload = asyncio.run(generate(server.GenerateIn(project_id=project['id'],source_ids=[source],
        conversation_id=chat['id'],provider='deepseek',review_mode=review_mode,summary_level=1,
        instructions='CURRENT_SCOPE：只讲第一行，保留必要条件，不展开第二行，不出题。',
        resolved_requirements='UNTRUSTED_REPLACEMENT_MUST_NOT_WIN')))
    assert len(calls) == expected
    digest = __import__('hashlib').sha256(payload['resolved_requirements'].encode()).hexdigest()
    for body in calls:
        text = '\n'.join(message['content'] for message in body['messages'])
        if body.get('response_format',{}).get('type')=='json_object':
            from studyforge.review_input import MARKER
            source_text=json.loads(body['messages'][-1]['content'].split(MARKER,1)[1])['source_text']
        else:
            source_text=text
        assert original in source_text and 'EARLIER_SCOPE' in text and 'CURRENT_SCOPE' in text
        assert 'FOREIGN_CHAT_MUST_STAY_PRIVATE' not in text
        assert 'UNTRUSTED_REPLACEMENT_MUST_NOT_WIN' not in text
    for body in calls[1:]:
        user = body['messages'][-1]['content']
        marker = '本次讲解交付约束（由本次生成任务提供，不属于原资料）：\n'
        scope = json.JSONDecoder().raw_decode(user.split(marker,1)[1])[0]
        assert 'CURRENT_SCOPE' in scope['student_requirements']
        assert scope['detail_guidance'] == ai.LEVEL_GUIDANCE[1]
    saved = one("SELECT metadata_json FROM artifacts WHERE kind='explanation'")
    # The persistent audit remains tied to the complete frozen task, including
    # history sent as separate native messages rather than a second transcript.
    reports = json.loads(saved['metadata_json'])['reviews']
    assert all(r['teaching_scope']['requirements_sha256'] == digest for r in reports)
    assert all(r['teaching_scope']['summary_level'] == 1 for r in reports)


def test_questionnaire_uses_original_context_without_overwriting_new_preferences(tmp_path, monkeypatch):
    project, source, _ = material(tmp_path); calls = cloud(monkeypatch)
    result, _ = asyncio.run(generate(server.GenerateIn(project_id=project['id'], source_ids=[source], provider='deepseek',
        learning_mode='overview', explanation_style='clear', output_language='en')))
    cid = result['conversation_id']
    conversations.update(cid, project['id'], {'learning_mode':'research','explanation_style':'academic','output_language':'zh','review_mode':'strict'})
    api = TestClient(server.app)
    q = api.get('/api/lesson-feedback/by-job/'+result['job_id']).json()
    metadata = api.get('/api/lesson-feedback/'+q['id']+'/dialogue').json()
    assert (metadata['learning_mode'], metadata['explanation_style'], metadata['output_language']) == ('overview','clear','en')
    api.post('/api/lesson-feedback/'+q['id']+'/submit', json={'difficulties':['motivation'],'other_text':'Explain the missing reason briefly; do not assign exercises.'})
    response = api.post('/api/lesson-feedback/'+q['id']+'/followup')
    assert response.status_code == 200 and '"error"' not in response.text
    prompt = calls[-1]['messages'][0]['content']
    assert all(s in prompt for s in ('当前学习模式：概览','当前讲解风格：通俗清晰','当前讲解语言：英语','Explain the missing reason briefly'))
    row = conversations.detail(cid, project['id'])
    # The followup explains the original document in its saved style/language,
    # but must preserve the user's newer conversation settings.
    assert (row['learning_mode'],row['explanation_style'],row['output_language'],row['review_mode']) == ('research','academic','zh','strict')
    assert len(calls) == 2 and many('SELECT * FROM exercise_sets') == []
    old_internal_user = calls[-1]['messages'][-1]['content']
    old_scope = one('SELECT scope_key FROM agent_dialogue_scopes WHERE conversation_id=?', (cid,))['scope_key']
    continued = api.post('/api/chat/stream', json={'project_id':project['id'], 'conversation_id':cid,
        'provider':'deepseek', 'model':row['model'], 'source_ids':[source], 'text':'请按现在的设置继续讨论。'})
    assert continued.status_code == 200 and '"error"' not in continued.text
    current = calls[-1]['messages']
    assert all(s in current[0]['content'] for s in ('当前学习模式：研究','当前讲解风格：学术专业','当前讲解语言：中文'))
    # With plain chat input, the old user text is also the public text. It
    # must survive the settings rebuild; the old policy is checked separately.
    assert any(message['role']=='user' and message['content'] == old_internal_user for message in current[1:-1])
    assert any('Explain the missing reason briefly' in message['content'] for message in current[1:-1])
    assert one('SELECT scope_key FROM agent_dialogue_scopes WHERE conversation_id=?', (cid,))['scope_key'] != old_scope
    assert len(calls) == 3 and many('SELECT * FROM exercise_sets') == []


@pytest.mark.parametrize('mode,defect,expected', [('express',False,0),('express',True,0),('fast',False,1),('fast',True,1),('balanced',False,1),('balanced',True,2),('strict',False,3),('strict',True,7)])
def test_review_levels_do_real_different_work_and_preserve_language(mode, defect, expected):
    class Client:
        def __init__(self): self.calls = []
        async def complete(self, system, user, json_mode=False):
            self.calls.append((system, user, json_mode))
            if json_mode:
                bad = defect and 'BAD_DRAFT' in user
                return j({'passed':not bad, 'issues':[{'location':'Definition','problem':'A required condition is missing.'}] if bad else []})
            return '# Fixed explanation\nThe required condition is stated.\n\n## Systematic summary\nCheck the condition.'
    client = Client()
    document, reports = asyncio.run(review_explanation(client, 'source', 'BAD_DRAFT', mode=mode,
        learning_mode='overview', explanation_style='academic', output_language='en'))
    assert len(client.calls) == expected
    assert all('当前学习模式：概览' in c[0] and '当前讲解风格：学术专业' in c[0] and '当前讲解语言：英语' in c[0] for c in client.calls)
    if defect and mode == 'fast': assert 'Items requiring verification' in document and '待核实事项' not in document
    if defect and mode in ('balanced','strict'): assert document.startswith('# Fixed explanation')
    if mode == 'strict': assert len([r for r in reports if r['attempt'] == 1]) == 3


def test_summary_and_bilingual_title_do_not_reset_preferences_or_add_calls():
    class Client:
        def __init__(self): self.calls=[]
        async def complete(self, system, user):
            self.calls.append((system,user));return '## Systematic summary\nKeep the stated conditions.'
    client = Client()
    answer = asyncio.run(finish_explanation(client, '# Explanation\nConditions matter.', language='en', explanation_style='academic', learning_mode='overview'))
    assert len(client.calls)==1 and '当前讲解语言：英语' in client.calls[0][0] and '当前讲解风格：学术专业' in client.calls[0][0]
    assert '证明与解题思路教学' not in client.calls[0][0] and answer.endswith('Keep the stated conditions.')
    answer = asyncio.run(finish_explanation(client, '# 讲解\n解释。\n\n## 系统性总结 / Systematic summary\n中文结论。\nEnglish conclusion.', language='bilingual'))
    assert len(client.calls)==1 and answer.endswith('English conclusion.')


@pytest.mark.parametrize('review_mode,expected', [('express',1),('fast',2),('strict',4)])
def test_paused_job_keeps_preferences_after_chat_changes(tmp_path, monkeypatch, review_mode, expected):
    project, source, _ = material(tmp_path)
    chat=conversations.create(project['id'],'deepseek',explanation_style='clear',output_language='en',review_mode='express')
    value=server.GenerateIn(project_id=project['id'],source_ids=[source],provider='deepseek',conversation_id=chat['id'],
        learning_mode='overview',explanation_style='clear',output_language='en',review_mode=review_mode,
        instructions='FROZEN_SCOPE：只讲必要条件，不要扩写成全章。',summary_level=1)
    # The public generate route saves this immutable task-start snapshot.
    job=create_job(project['id'],'generate',value.model_dump() | {'dialogue_snapshot':server.mentor_snapshot(value)});calls=[]
    class Client:
        model='fixture'
        async def complete(self,system,user,**kwargs):
            calls.append((system,user))
            if kwargs.get('json_mode'):return j({'passed':True,'issues':[]})
            if len(calls)==1:control_for(job).pause()
            return '# Explanation\nPreserve the condition.\n\n## Systematic summary\nConditions matter.'
    monkeypatch.setattr(server,'client_for',lambda *a,**k:Client())
    async def run():
        task=asyncio.create_task(server._generate_job(job,value))
        for _ in range(250):
            if one('SELECT status FROM jobs WHERE id=?',(job,))['status']=='paused':break
            await asyncio.sleep(.01)
        else: raise AssertionError('未暂停')
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        conversations.update(chat['id'],project['id'],{'learning_mode':'research','explanation_style':'academic','output_language':'bilingual','review_mode':'strict'})
        execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),chat['id'],'user','LATER_SCOPE：改成详细讲解全部内容。',now()))
        restored=server.GenerateIn(**json.loads(one('SELECT payload_json FROM jobs WHERE id=?',(job,))['payload_json']))
        control_for(job).resume();await server._generate_job(job,restored)
    asyncio.run(run())
    assert one('SELECT status FROM jobs WHERE id=?',(job,))['status']=='completed' and len(calls)==expected
    meta=json.loads(one("SELECT metadata_json FROM artifacts WHERE kind='explanation'")['metadata_json'])
    assert (meta['learning_mode'],meta['explanation_style'],meta['output_language'],meta['review_mode'])==('overview','clear','en',review_mode)
    for _, user in calls:
        assert 'FROZEN_SCOPE' in user and 'LATER_SCOPE' not in user
    assert all(report['teaching_scope']['summary_level']==1 for report in meta['reviews'] if 'teaching_scope' in report)


@pytest.mark.parametrize('parallel', [False,True])
def test_long_document_audit_receives_its_own_part_scope(tmp_path, monkeypatch, parallel):
    project, source, _ = material(tmp_path); calls = cloud(monkeypatch)
    monkeypatch.setattr(server, 'explanation_batches', lambda digest: [digest+'\nFIRST_PART',digest+'\nSECOND_PART'])
    _, _ = asyncio.run(generate(server.GenerateIn(project_id=project['id'],source_ids=[source],
        provider='deepseek',review_mode='fast',summary_level=2,parallel=parallel,
        instructions='PART_REQUIREMENT：先只学这个论证，不扩写其他主题。')))
    audits = [body for body in calls if body.get('response_format',{}).get('type')=='json_object']
    assert len(audits)==2
    scopes=[]
    for body in audits:
        user=body['messages'][-1]['content']
        marker='本次讲解交付约束（由本次生成任务提供，不属于原资料）：\n'
        scope=json.JSONDecoder().raw_decode(user.split(marker,1)[1])[0]
        scopes.append(scope['current_part'])
        assert 'PART_REQUIREMENT' in scope['student_requirements']
        assert scope['detail_guidance']==ai.LEVEL_GUIDANCE[2]
    assert any('第 1/2 部分' in scope for scope in scopes)
    assert any('第 2/2 部分' in scope for scope in scopes)
    reports=json.loads(one("SELECT metadata_json FROM artifacts WHERE kind='explanation'")['metadata_json'])['reviews']
    assert {r['section'] for r in reports}=={1,2}
    assert len({r['teaching_scope']['part_sha256'] for r in reports})==2


@pytest.mark.parametrize('field,bad', [('explanation_style','unknown'),('output_language','fr'),('review_mode','unknown'),('explanation_style',None),('output_language',None),('review_mode',None)])
def test_invalid_preferences_do_not_change_chat(field,bad):
    project=create_project('偏好验证');chat=conversations.create(project['id'],'deepseek');api=TestClient(server.app)
    response=api.put('/api/conversations/'+chat['id'],json={'project_id':project['id'],field:bad})
    assert response.status_code in (400,422)
    saved=conversations.detail(chat['id'],project['id'])
    assert (saved['explanation_style'],saved['output_language'],saved['review_mode'])==('clear','zh','express')


def test_existing_style_only_table_migrates_without_losing_conversation():
    path=data_dir()/'studyforge.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.executescript('CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT,created_at TEXT);'
            'CREATE TABLE conversations(id TEXT PRIMARY KEY,project_id TEXT,provider TEXT,remote_thread_id TEXT,created_at TEXT);'
            'CREATE TABLE conversation_teaching_styles(conversation_id TEXT PRIMARY KEY,explanation_style TEXT,updated_at TEXT);')
        conn.execute('INSERT INTO projects VALUES (?,?,?)',('old-project','原项目',now()))
        conn.execute('INSERT INTO conversations VALUES (?,?,?,?,?)',('old-chat','old-project','codex','saved-thread',now()))
        conn.execute('INSERT INTO conversation_teaching_styles VALUES (?,?,?)',('old-chat','academic',now()))
    row=conversations.detail('old-chat','old-project')
    assert row['remote_thread_id']=='saved-thread' and row['explanation_style']=='academic'
    assert row['output_language']=='zh' and row['review_mode']=='express'
    assert len(one('SELECT * FROM conversations WHERE id=?',('old-chat',)))==8
