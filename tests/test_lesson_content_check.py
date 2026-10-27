"""AI-content criticism is not a learner deficit; explicit mixed needs remain."""
import json

from fastapi.testclient import TestClient

from studyforge import server
from studyforge.db import many,one,unj,update_mastery
from tests.test_lesson_feedback import completed_lesson


def setup(tmp_path,monkeypatch):
    project,job,chat,calls,*_=completed_lesson(tmp_path,monkeypatch)
    api=TestClient(server.app);item=api.get('/api/lesson-feedback/by-job/'+job).json()
    return api,item,chat,calls


def test_only_content_check_preserves_critique_without_profile_or_score(tmp_path,monkeypatch):
    api,item,chat,calls=setup(tmp_path,monkeypatch)
    update_mastery('规训权力',quiz=90);before=many('SELECT * FROM mastery')
    text='讲解对规训概念的解释可能有误，请核对原文。CRITIQUE_ONLY'
    submitted=api.post(f"/api/lesson-feedback/{item['id']}/submit",json={'difficulties':['content_accuracy'],'other_text':text})
    assert submitted.status_code==200 and submitted.json()['content_check']
    assert submitted.json()['other_text']==text and len(calls)==1
    assert many('SELECT * FROM learning_insights')==[] and many('SELECT * FROM learning_events')==[]
    assert many('SELECT * FROM mastery')==before and many('SELECT * FROM exercise_sets')==[]
    restored=api.get('/api/projects/'+item['project_id']+'/lesson-feedback').json()[0]
    assert restored['content_check'] and restored['difficulties']==['content_accuracy']


def test_mixed_feedback_records_only_explicit_learning_needs(tmp_path,monkeypatch):
    api,item,_,calls=setup(tmp_path,monkeypatch)
    result=api.post(f"/api/lesson-feedback/{item['id']}/submit",json={
        'difficulties':['content_accuracy','motivation'],'other_text':'原讲解的规训概念可能说错了。AI_CRITIQUE_NOT_A_DEFICIT'})
    assert result.status_code==200 and result.json()['content_check'] and len(calls)==1
    insights=many('SELECT * FROM learning_insights');assert len(insights)==1
    assert insights[0]['kind']=='self_report' and insights[0]['dimension']=='reasoning'
    assert '构造动机' in str(insights) and 'AI_CRITIQUE_NOT_A_DEFICIT' not in str(insights)
    payload=unj(one('SELECT payload_json FROM learning_events')['payload_json'])
    assert payload['difficulties']==['motivation'] and payload['other_text']==''
    assert 'content_accuracy' not in json.dumps(payload) and 'AI_CRITIQUE_NOT_A_DEFICIT' not in json.dumps(payload)


def test_same_tutor_receives_content_check_before_teaching_and_does_not_profile_it_twice(tmp_path,monkeypatch):
    api,item,chat,calls=setup(tmp_path,monkeypatch)
    text='请核对旧讲解是否把规训说成只有外部命令。CONTENT_QUESTION'
    body={'difficulties':['content_accuracy'],'other_text':text}
    for _ in range(2):assert api.post(f"/api/lesson-feedback/{item['id']}/submit",json=body).status_code==200
    response=api.post(f"/api/lesson-feedback/{item['id']}/followup")
    assert response.status_code==200 and '"error"' not in response.text
    assert len(calls)==2 and calls[-1]['model']=='lesson-model'
    prompt=json.dumps(calls[-1]['messages'],ensure_ascii=False)
    assert text in prompt and '先处理内容疑点' in prompt and '不能从别段借更强条件' in prompt
    assert '不默认学生的指正必定成立' in prompt and '福柯' in prompt and '已生成讲解文档' in prompt
    assert many('SELECT * FROM learning_events')==[] and many('SELECT * FROM learning_insights')==[]
    assert many('SELECT * FROM mastery')==[] and many('SELECT * FROM exercise_sets')==[]
    assert one('SELECT conversation_id,reply_status FROM lesson_questionnaires')=={'conversation_id':chat,'reply_status':'completed'}


def test_content_check_remains_optional_and_does_not_replace_six_learning_choices(tmp_path,monkeypatch):
    api,item,_,_=setup(tmp_path,monkeypatch)
    assert [option['id'] for option in item['options'][:6]]==[
        'terminology','prerequisites','motivation','method_selection','argumentation','implementation']
    assert item['options'][6]['id']=='content_accuracy'
    assert api.post(f"/api/lesson-feedback/{item['id']}/submit",json={'difficulties':['unknown_choice']}).status_code==400
    assert api.post(f"/api/lesson-feedback/{item['id']}/submit",json={'difficulties':['content_accuracy','content_accuracy']}).status_code==400
    assert many('SELECT * FROM learning_events')==[]
