"""Recent scored evidence must be distinguishable from averages and old doubts."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from studyforge import ai,conversations,learning_memory as memory,learning_profile as profile,server
from studyforge.db import create_project,execute,j,many,one,uid
from tests.test_profile_focus import capture_http,insight


def record(key,score,*,kind='做题',at='2026-10-20T10:00:00+00:00',context=None):
    memory.assessment_record(key,'高斯定律',kind,score,'PRIVATE_STUDENT_ANSWER','PRIVATE_FEEDBACK',practice_context=context)
    event=one('SELECT id FROM learning_events WHERE event_key=?',(key,))
    execute('UPDATE learning_events SET created_at=? WHERE id=?',(at,event['id']))
    execute('UPDATE learning_insights SET created_at=? WHERE event_id=?',(at,event['id']))
    return one('SELECT id FROM learning_insights WHERE event_id=?',(event['id'],))['id']


def row():return next(item for item in profile.effective_profile() if item['topic']=='高斯定律')


def test_recent_scores_are_not_the_weighted_average_and_do_not_rewrite_grades():
    record('earlier',40)
    record('later',90,at='2026-10-21T10:00:00+00:00',context={'hint_levels':{},'used_notes':False})
    before={table:many('SELECT * FROM '+table) for table in ('learning_events','learning_insights','mastery')}
    result=row()
    assert result['score']==55
    assert [entry['score'] for entry in result['recent_assessments']]==[90,40]
    assert result['recent_assessments'][0]['aid_status']=='reported_no_aids'
    assert result['recent_assessments'][1]['aid_status']=='unknown'
    text=profile.assessment_context([result],'高斯定律')
    assert '近期评估' in text and '90' in text and '40' in text and '55' in text
    assert {table:many('SELECT * FROM '+table) for table in before}==before


@pytest.mark.parametrize('context,expected',[
    (None,'unknown'),({'used_notes':False},'unknown'),
    ({'hint_levels':{},'used_notes':False,'recording_status':'partial'},'unknown'),
    ({'hint_levels':{},'used_notes':False,'recording_status':'not_recorded'},'unknown'),
    ({'hint_levels':{},'used_notes':True},'assisted'),
    ({'hint_levels':{'0':2},'used_notes':False},'assisted'),
    ({'hint_levels':{'1':2},'question_index':0,'used_notes':False},'reported_no_aids'),
])
def test_recent_record_retains_assistance_boundaries(context,expected):
    record('condition',85,context=context)
    assert row()['recent_assessments'][0]['aid_status']==expected


def test_self_reports_static_review_and_removed_scores_are_not_recent_measured_scores():
    record('quiz',70);latest=record('later',90,at='2026-10-21T10:00:00+00:00')
    record('self',100,kind='自评',at='2026-10-22T10:00:00+00:00')
    record('static',None,kind='编程作业',at='2026-10-23T10:00:00+00:00')
    profile.change_insight(latest,0,deleted=True)
    assert [x['score'] for x in row()['recent_assessments']]==[70]
    profile.change_insight(latest,1,deleted=False)
    assert [x['score'] for x in row()['recent_assessments']]==[90,70]
    assert row()['self_rating']==100


def test_recent_order_uses_actual_time_then_event_order_and_is_bounded():
    record('newer',90,at='2026-10-22T10:00:00+00:00')
    record('backfilled',20,at='2026-10-19T10:00:00+00:00')
    record('same_utc',80,kind='费曼讲解',at='2026-10-22T03:00:00-07:00')
    record('older',60,at='2026-10-21T10:00:00+00:00')
    result=row()['recent_assessments']
    assert [x['score'] for x in result]==[80,90,60]
    assert result[0]['kind']=='费曼讲解'
    assert all(set(x)=={'kind','score','recorded_at','aid_status','is_review','delay_hours','same_question_verified'} for x in result)


def old_gap():
    project=create_project('原画像项目');ident=insight('高斯定律','HISTORICAL_GAP：学生自报不清楚净通量。',project['id'])
    event=one('SELECT event_id FROM learning_insights WHERE id=?',(ident,))['event_id']
    execute("UPDATE learning_events SET created_at='2026-10-18T10:00:00+00:00' WHERE id=?",(event,))
    execute("UPDATE learning_insights SET created_at='2026-10-18T10:00:00+00:00' WHERE id=?",(ident,))
    return ident


@pytest.mark.parametrize('score',[30,90])
def test_later_assessment_marks_old_doubt_for_rechecking_without_auto_resolving_it(score):
    old_gap();record('new',score)
    packet=profile.mentor_profile('高斯定律')['topics'][0]
    gap=next(x for x in packet['observations'] if x['kind']=='gap')
    assert gap['later_assessment_recorded'] is True
    assert 'HISTORICAL_GAP' in gap['observation']
    assert '核对当前卡点' in packet['history_notice']
    text=memory.profile_context('高斯定律')
    assert '历史疑问' in text and 'HISTORICAL_GAP' in text and '近期评估' in text
    assert '自动解决' not in j(packet)


def test_user_correction_is_not_downgraded_to_an_old_doubt():
    ident=old_gap();record('new',90)
    profile.change_insight(ident,0,correction='我现在想集中看边界条件。')
    packet=profile.mentor_profile('高斯定律')['topics'][0]
    gap=next(x for x in packet['observations'] if x['kind']=='gap')
    assert gap['user_corrected'] and not gap['later_assessment_recorded']
    assert 'HISTORICAL_GAP' not in memory.profile_context('高斯定律')


@pytest.mark.parametrize('operation',['late_background_extraction','restore_original'])
def test_old_evidence_does_not_become_a_new_doubt_when_processed_or_restored_later(operation):
    ident=old_gap();record('new',90)
    if operation=='late_background_extraction':
        execute("UPDATE learning_insights SET created_at='2026-10-23T10:00:00+00:00' WHERE id=?",(ident,))
    else:
        profile.change_insight(ident,0,deleted=True)
        profile.change_insight(ident,1,deleted=False)
    packet=profile.mentor_profile('高斯定律')['topics'][0]
    gap=next(item for item in packet['observations'] if item['kind']=='gap')
    assert gap['later_assessment_recorded'] and gap['evidence_recorded_at']=='2026-10-18T10:00:00+00:00'
    assert '2026-10-18' in memory.profile_context('高斯定律')


def test_new_recent_records_do_not_export_answers_ids_feedback_or_other_chats():
    old_gap();record('first',40);record('new',90,at='2026-10-21T10:00:00+00:00')
    text=j(profile.mentor_profile('高斯定律'))
    assert 'recent_assessments' in text and '90' in text
    assert 'PRIVATE_STUDENT_ANSWER' not in text and 'PRIVATE_RAW_STUDENT' not in text
    assert 'PRIVATE_' not in j(profile.mentor_profile('高斯定律')['topics'][0]['recent_assessments'])
    assert all(key not in text for key in ('event_key','event_id','student_text','feedback','conversation_id','project_id'))


def test_actual_tutor_receives_recent_evidence_in_an_independent_project(monkeypatch):
    old_gap();record('first',40);record('new',90,at='2026-10-21T10:00:00+00:00')
    project=create_project('独立的新项目');chat=conversations.create(project['id'],'deepseek')
    posted=capture_http(monkeypatch)
    response=TestClient(server.app).post('/api/chat/stream',json={
        'project_id':project['id'],'conversation_id':chat['id'],'provider':'deepseek','model':'fixture',
        'source_ids':[],'text':'高斯定律里为什么净电通量为零不等于电场处处为零？'})
    assert response.status_code==200 and '"error"' not in response.text
    system=posted[0]['messages'][0]['content']
    assert '近期评估' in system and '90' in system and '40' in system and '历史疑问' in system
    assert 'PRIVATE_STUDENT_ANSWER' not in system and 'PRIVATE_RAW_STUDENT' not in system


def test_new_question_after_assessment_is_not_labelled_as_a_historical_doubt():
    record('quiz',90);project=create_project('新疑问')
    insight('高斯定律','现在仍不清楚边界条件。',project['id'])
    packet=profile.mentor_profile('高斯定律')['topics'][0]
    gap=next(item for item in packet['observations'] if item['kind']=='gap')
    assert not gap['later_assessment_recorded'] and not packet['history_notice']


def test_recent_review_keeps_delay_and_assistance_in_tutor_context():
    record('review',90,context={'hint_levels':{},'used_notes':False,'is_review':True,
        'timing':[{'question_index':0,'delay_hours':25,'due_reached':True}]})
    recent=row()['recent_assessments'][0]
    assert recent['is_review'] and recent['delay_hours']==25
    assert '复习作答' in memory.profile_context('高斯定律') and '间隔25小时' in memory.profile_context('高斯定律')


def test_paused_generation_keeps_original_recent_evidence_until_user_control_changes():
    from studyforge.db import create_job
    project=create_project('原文讲解');job=create_job(project['id'],'generate',{})
    first=record('first',40);before=profile.generation_profile(job)
    record('new',90,at='2026-10-21T10:00:00+00:00')
    assert profile.generation_profile(job)==before
    profile.change_insight(first,0,deleted=True)
    assert profile.generation_profile(job)[0]['recent_assessments'][0]['score']==90


def test_native_document_request_receives_recent_scores_and_historical_doubt(monkeypatch):
    from studyforge.agent_tools import AgentRuntime
    old_gap();record('first',40);record('new',90,at='2026-10-21T10:00:00+00:00')
    posted=capture_http(monkeypatch)
    project=create_project('文档输入验收');chat=conversations.create(project['id'],'deepseek','fixture')
    async def scenario():
        runtime=AgentRuntime(project['id'],[],'deepseek','fixture',conversation_id=chat['id'],publishing=False)
        client=ai.DeepSeekClient('fixture',runtime,dict(chat,messages=[],remote_thread_id=None),effort='none')
        try:return await ai.generate_explanation(client,'高斯定律约束整体净通量，不直接给出各点的场。',3,
            profile.effective_profile(),requirements='说明整体和局部的区别，不出题。')
        finally:await client.close()
    assert '系统性总结' in asyncio.run(scenario())
    text=j(posted)
    assert '近期评估' in text and '历史疑问' in text and '90' in text and '40' in text
    assert 'PRIVATE_STUDENT_ANSWER' not in text and 'PRIVATE_RAW_STUDENT' not in text
