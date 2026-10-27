"""AI lesson coordinates never authorize or restrict reading the original."""
import pytest
from fastapi.testclient import TestClient

from studyforge import conversations, lesson_feedback, server
from studyforge.db import create_job, execute, j, many, now, one, uid
from tests.test_source_request_scope import runtime


CASES = [
    ('第2章的讲解','ready','',(True,True,False)),
    ('第2页的讲解','ready','请核对这一步。',(True,True,False)),
    ('第2页的讲解','stored','请核对这一步。',(False,False,True)),
    ('第1章的讲解','ready','只核对原PDF第2页。',(False,True,False)),
    ('全文阅读与第2页','stored','',(False,False,True)),
    ('第1章的讲解','ready','只看这段原文，其余先不读取。',(False,False,True)),
]


def setup(tmp_path, monkeypatch, heading, status, provider):
    agent, sid = runtime(tmp_path)
    execute('UPDATE conversations SET provider=? WHERE id=?',(provider,agent.conversation_id))
    execute('UPDATE sources SET status=? WHERE id=?',(status,sid))
    project, chat = agent.project_id, agent.conversation_id
    job = create_job(project,'generate',{'source_ids':[sid],'conversation_id':chat,
        'learning_mode':'deep','explanation_style':'balanced','output_language':'zh'})
    text = '# '+heading+'\n\n这里只是旧AI解释，标题不是原PDF的读取要求。'
    path = tmp_path / (uid()+'.md');path.write_text(text,encoding='utf-8')
    server.add_artifact(project,[sid],'explanation','md',heading,path,{'generation_job_id':job,'conversation_id':chat})
    mid = uid()
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(mid,chat,'assistant','已生成讲解文档：\n\n'+text,now()))
    execute('INSERT INTO generation_dialogue_outputs VALUES (?,?,?)',(job,chat,mid))
    execute("UPDATE jobs SET status='completed' WHERE id=?",(job,))
    root = lesson_feedback.ensure_questionnaire(job)
    captured = []
    class Tutor:
        model = 'fixture-model'
        async def agent_stream(self, messages):
            captured.append((messages[0]['content'], self.agent_runtime.source_read_request))
            yield 'final','仅用于验证本次原文读取范围的受控回复。'
        async def close(self): pass
    monkeypatch.setattr(server,'DeepSeekClient',lambda *args,**kwargs:Tutor())
    async def codex_stream(self,prompt,*args,**kwargs):
        captured.append((prompt, kwargs['agent_runtime'].source_read_request))
        yield 'final','仅用于验证本次原文读取范围的受控回复。'
    monkeypatch.setattr('studyforge.codex_bridge.CodexBridge.stream_turn',codex_stream)
    return root, captured, sid, project, chat


@pytest.mark.parametrize('provider',['deepseek','codex'])
@pytest.mark.parametrize('heading,status,question,expected',CASES)
def test_both_tutors_classify_only_student_supplement_as_original_scope(tmp_path,monkeypatch,provider,heading,status,question,expected):
    root,captured,*_ = setup(tmp_path,monkeypatch,heading,status,provider)
    api = TestClient(server.app)
    section = api.get('/api/lesson-feedback/'+root['id']+'/sections').json()['items'][0]
    assert api.post('/api/lesson-feedback/'+root['id']+'/submit',json={'difficulties':['content_accuracy'],
        'other_text':question,'focus_section_id':section['id']}).status_code == 200
    response = api.post('/api/lesson-feedback/'+root['id']+'/followup')
    assert response.status_code == 200 and '"error"' not in response.text, response.text
    assert len(captured) == 1
    text, request = captured[0]
    assert request == question
    assert ('FIRST_PAGE_ONLY' in text,'SECOND_PAGE_ONLY' in text,'本次尚未读取正文' in text) == expected
    assert '历史讲解片段开始' in text and heading in text
    assert not many('SELECT * FROM learning_events') and not many('SELECT * FROM exercise_sets')


def test_repeat_content_check_uses_student_scope_and_preserves_current_selection(tmp_path,monkeypatch):
    root,captured,sid,project,chat = setup(tmp_path,monkeypatch,'第1章的讲解','ready','deepseek')
    api = TestClient(server.app)
    created = api.post('/api/lesson-feedback/'+root['id']+'/content-check',json={'project_id':project,'conversation_id':chat}).json()
    section = api.get('/api/lesson-feedback/'+created['id']+'/sections').json()['items'][0]
    conversations.update(chat,project,{'source_ids':[]})
    assert api.post('/api/lesson-feedback/'+created['id']+'/submit',json={'difficulties':['content_accuracy'],
        'other_text':'请只核对原PDF第2页。','focus_section_id':section['id']}).status_code == 200
    response = api.post('/api/lesson-feedback/'+created['id']+'/followup')
    assert '"error"' not in response.text
    assert 'SECOND_PAGE_ONLY' in captured[0][0] and 'FIRST_PAGE_ONLY' not in captured[0][0]
    assert one('SELECT source_ids_json FROM conversations WHERE id=?',(chat,))['source_ids_json']=='[]'


def test_normal_chat_still_obeys_actual_student_page_request(tmp_path,monkeypatch):
    _,captured,sid,project,chat = setup(tmp_path,monkeypatch,'第1章的讲解','ready','deepseek')
    response = TestClient(server.app).post('/api/chat/stream',json={'project_id':project,'conversation_id':chat,
        'provider':'deepseek','model':'fixture-model','source_ids':[sid],'text':'只解释原PDF第2页。'})
    assert response.status_code == 200 and '"error"' not in response.text
    assert len(captured)==1 and captured[0][1]=='只解释原PDF第2页。'
    assert 'SECOND_PAGE_ONLY' in captured[0][0] and 'FIRST_PAGE_ONLY' not in captured[0][0]
