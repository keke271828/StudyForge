"""Exact old-lesson selections, long sections, isolation and native followup."""
import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from studyforge import ai, lesson_feedback, lesson_focus, server
from studyforge.db import execute, j, many, one
from tests.test_lesson_focus import lesson, selected
from test_mobile_access import mobile_client, pair


TAIL='真正卡住的原句😀：两个开区间在中点相接，但严格不等号排除了那个中点。'


def long_lesson(tmp_path):
    text='# 很长的证明\r\n'+'前面的说明并不是本次的问题。\r\n'*540+TAIL+'\r\n后面仍有其他讨论。'
    return lesson(tmp_path,document=text)


def choice(text, quote=TAIL):
    start=text.index(quote)
    return {'start':start,'end':start+len(quote),'text':quote}


def test_long_section_windows_are_bounded_and_reach_the_selected_tail_without_a_model(tmp_path):
    _,_,q,text,_=long_lesson(tmp_path)
    api=TestClient(server.app); row=lesson_feedback.get_questionnaire(q['id'])
    section=lesson_focus.section_options(row)['items'][0]['id']
    offset=0;chunks=[]
    while True:
        response=api.get('/api/lesson-feedback/'+q['id']+'/passage',params={'section_id':section,'offset':offset})
        assert response.status_code==200
        body=response.json(); assert len(body['text'])<=4000 and body['offset']==offset
        chunks.append(body['text'])
        if body['next_offset'] is None:break
        offset=body['next_offset']
    assert ''.join(chunks)==text and TAIL in chunks[-1] and len(chunks)>2
    assert not many('SELECT * FROM learning_events') and not many('SELECT * FROM mastery')
    assert one('SELECT status FROM lesson_questionnaires')['status']=='pending'


@pytest.mark.parametrize('offset',[-1,True,1.5,'0',100000])
def test_invalid_window_positions_do_not_guess_or_expand_scope(tmp_path,offset):
    _,_,q,_,_=long_lesson(tmp_path); row=lesson_feedback.get_questionnaire(q['id'])
    section=lesson_focus.section_options(row)['items'][0]['id']
    with pytest.raises(ValueError,match='片段位置无效'):lesson_focus.passage_window(row,section,offset)


def test_selection_centres_on_the_tail_and_retains_exact_crlf_emoji_and_old_version(tmp_path):
    _,_,q,text,message=long_lesson(tmp_path); row=lesson_feedback.get_questionnaire(q['id'])
    section=lesson_focus.section_options(row)['items'][0]['id']; selection=choice(text)
    assert selection['start']>7000
    submitted=lesson_feedback.submit_questionnaire(q['id'],['motivation'],'我不明白为什么能取等号。',
        focus_section_id=section,focus_selection=selection)
    stored=lesson_feedback.get_questionnaire(q['id']); focus=lesson_focus.saved_focus(stored)
    assert focus['selection']['text']==TAIL and len(focus['excerpt'])<=4400
    assert TAIL in focus['excerpt'] and focus['excerpt_start']>0 and focus['excerpt_cut']
    assert focus['document_sha256']==hashlib.sha256(text.encode()).hexdigest()
    assert submitted['focus']['selection']['text_sha256']==hashlib.sha256(TAIL.encode()).hexdigest()
    assert 'text' not in submitted['focus']['selection'] and 'excerpt' not in submitted['focus']
    context=lesson_focus.focus_context(stored)
    assert TAIL in context and '不是学生作答' in context and '只含开头7000' not in context
    assert context.count(TAIL)==1, 'Do not duplicate the selected passage inside the bounded focus packet'
    execute('UPDATE messages SET content=content||? WHERE id=?',('\r\n后来修订。',message))
    assert lesson_feedback.remediation_policy(lesson_feedback.get_questionnaire(q['id']))==lesson_feedback.remediation_policy(stored)
    assert TAIL not in lesson_feedback.feedback_text(stored)
    assert TAIL not in j(many('SELECT * FROM learning_events')+many('SELECT * FROM learning_insights'))
    assert not many('SELECT * FROM mastery')


@pytest.mark.parametrize('bad',[
    {'start':0,'end':8,'text':TAIL},
    {'start':8,'end':3,'text':'反向'},
    {'start':-1,'end':3,'text':'负数'},
    {'start':True,'end':3,'text':'布尔'},
    {'start':1,'end':4,'text':'   '},
    {'start':0,'end':3001,'text':'字'*3001},
])
def test_wrong_quote_or_coordinates_leave_questionnaire_and_profile_unmodified(tmp_path,bad):
    _,_,q,_,_=long_lesson(tmp_path); row=lesson_feedback.get_questionnaire(q['id'])
    section=lesson_focus.section_options(row)['items'][0]['id']
    result=TestClient(server.app).post('/api/lesson-feedback/'+q['id']+'/submit',json={
        'difficulties':['motivation'],'focus_section_id':section,'focus_selection':bad})
    assert result.status_code in (400,422)
    assert one('SELECT status,focus_json FROM lesson_questionnaires')=={'status':'pending','focus_json':'{}'}
    assert not many('SELECT * FROM learning_events')


def test_repeated_quote_anchors_are_disambiguated_by_position_and_submission_is_idempotent(tmp_path):
    quote='同样的原句出现在两处，但不能静默换到另一处。'
    text='# 证明\n'+quote+'\n解释第一处。\n'+quote
    _,_,q,_,message=lesson(tmp_path,document=text);row=lesson_feedback.get_questionnaire(q['id'])
    section=lesson_focus.section_options(row)['items'][0]['id']; selection={'start':text.rindex(quote),'end':len(text),'text':quote}
    payload={'difficulties':['argumentation'],'focus_section_id':section,'focus_selection':selection}
    api=TestClient(server.app);url='/api/lesson-feedback/'+q['id']+'/submit'
    assert api.post(url,json=payload).status_code==200
    execute('UPDATE messages SET content=content||? WHERE id=?',('\n新版本。',message))
    assert api.post(url,json=payload).status_code==200
    assert api.post(url,json=dict(payload,focus_selection=choice(text,quote))).status_code==400
    assert api.post(url,json=dict(payload,focus_selection=None)).status_code==400
    assert len(many('SELECT * FROM learning_events'))==1


def test_stale_foreign_deleted_or_archived_passage_cannot_replace_the_original(tmp_path):
    project,chat,q,text,message=long_lesson(tmp_path); row=lesson_feedback.get_questionnaire(q['id'])
    section=lesson_focus.section_options(row)['items'][0]['id']
    _,_,other,_,_=lesson(tmp_path,document='# OTHER_LESSON\n另一份内容。')
    foreign=lesson_focus.section_options(lesson_feedback.get_questionnaire(other['id']))['items'][0]['id']
    api=TestClient(server.app);url='/api/lesson-feedback/'+q['id']+'/passage'
    assert api.get(url,params={'section_id':foreign}).status_code==400
    execute('UPDATE messages SET content=content||? WHERE id=?',('\n版本已改。',message))
    assert api.get(url,params={'section_id':section}).status_code==400
    execute('INSERT INTO deleted_conversations VALUES (?,?)',(chat['id'],'now'))
    assert api.get(url,params={'section_id':section}).status_code==404


def test_paired_phone_gets_same_bounded_text_and_public_widget_assets(tmp_path):
    _,_,q,text,_=long_lesson(tmp_path); row=lesson_feedback.get_questionnaire(q['id'])
    section=lesson_focus.section_options(row)['items'][0]['id']; manager,client=mobile_client()
    with client:
        url='/api/lesson-feedback/'+q['id']+'/passage?section_id='+section+'&offset=8000'
        assert client.get(url).status_code==401
        pair(manager,client)
        response=client.get(url); assert response.status_code==200 and response.json()['text']==text[8000:12000]
        assert client.get('/lesson_passage.js').status_code==200
        assert client.get('/lesson_passage.css').status_code==200
        assert 'OTHER_LESSON' not in response.text


def test_native_tutor_receives_selected_tail_as_ai_context_without_claiming_student_knowledge(tmp_path,monkeypatch):
    _,_,q,text,_=long_lesson(tmp_path); row=lesson_feedback.get_questionnaire(q['id'])
    section=lesson_focus.section_options(row)['items'][0]['id'];api=TestClient(server.app)
    url='/api/lesson-feedback/'+q['id']
    assert api.post(url+'/submit',json={'difficulties':['motivation'],'other_text':'我不明白为什么要排除中点。',
        'focus_section_id':section,'focus_selection':choice(text)}).status_code==200
    calls=[];native=httpx.AsyncClient
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':'这里需要区分开区间与它的端点；半径可取等号，中点仍不属于区间。'},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(ai,'get_secret',lambda key:'fixture-key')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:native(transport=httpx.MockTransport(respond)))
    response=api.post(url+'/followup')
    assert response.status_code==200 and '"error"' not in response.text and len(calls)==1
    system=calls[0]['messages'][0]['content']
    assert TAIL in system and '学生选中的历史AI原句，不是学生作答' in system
    assert '不归咎于学生' in system
    user=one("SELECT content FROM messages WHERE role='user'")['content']
    assert TAIL not in user and '我不明白为什么要排除中点' in user
    assert TAIL not in j(many('SELECT * FROM learning_insights'))
    assert not many('SELECT * FROM mastery') and not many('SELECT * FROM exercise_sets')
