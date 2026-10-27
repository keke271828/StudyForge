"""Review plans survive recycling, without copying hidden projects or changing scope."""
from datetime import datetime,timedelta,timezone

import pytest
from fastapi.testclient import TestClient

from studyforge import practice,server
from studyforge.db import create_project,execute,j,many,one
from tests.test_practice import make_set,grade


def snapshot():
    return {table:many('SELECT * FROM '+table) for table in ('exercise_sets','review_items','review_sessions','submissions','learning_events')}


def plan(monkeypatch):
    stamp=datetime(2026,10,25,12,tzinfo=timezone.utc)
    monkeypatch.setattr(practice,'clock_now',lambda:stamp)
    first,project=make_set(topic='ORIGIN_VISIBLE',graded=True)
    second,other=make_set(topic='ORIGIN_RECYCLED',graded=True)
    practice.schedule_review(first,1);practice.schedule_review(second,1)
    monkeypatch.setattr(practice,'clock_now',lambda:stamp+timedelta(days=2))
    items={item['origin_set_id']:item for item in practice.review_queue()['items']}
    return first,project,second,other,items


def test_recycled_origin_is_hidden_from_queue_and_count_then_restores_same_plan(monkeypatch):
    first,project,second,other,items=plan(monkeypatch);api=TestClient(server.app)
    before=one('SELECT * FROM review_items WHERE id=?',(items[second]['id'],))
    assert api.delete('/api/projects/'+other['id']).status_code==200
    for suffix in ('','?due_only=true'):
        response=api.get('/api/reviews'+suffix);result=response.json()
        assert result['total']==result['due_count']==1
        assert [item['origin_set_id'] for item in result['items']]==[first]
        assert 'ORIGIN_RECYCLED' not in response.text
    assert one('SELECT * FROM review_items WHERE id=?',(items[second]['id'],))==before
    assert api.post('/api/projects/'+other['id']+'/restore').status_code==200
    restored=next(item for item in api.get('/api/reviews').json()['items'] if item['origin_set_id']==second)
    assert restored['id']==before['id'] and restored['due_at']==before['due_at']


def test_stale_selection_cannot_copy_a_recycled_origin_into_another_project(monkeypatch):
    first,project,second,other,items=plan(monkeypatch);api=TestClient(server.app)
    api.delete('/api/projects/'+other['id']);before=snapshot()
    response=api.post('/api/reviews/start',json={'project_id':project['id'],'item_ids':[items[first]['id'],items[second]['id']]})
    assert response.status_code==400,response.text
    assert '回收站' in response.text
    assert snapshot()==before


def test_recycled_destination_cannot_receive_new_mixed_review(monkeypatch):
    first,project,second,other,items=plan(monkeypatch);api=TestClient(server.app)
    target=create_project('已回收的目标项目');api.delete('/api/projects/'+target['id']);before=snapshot()
    response=api.post('/api/reviews/start',json={'project_id':target['id'],'item_ids':[items[first]['id']]})
    assert response.status_code==400,response.text
    assert snapshot()==before


def test_recycled_active_destination_hides_broken_entry_and_restores_original_review(monkeypatch):
    first,project,second,other,items=plan(monkeypatch);api=TestClient(server.app)
    active,_=practice.start_review(other['id'],[items[first]['id']])
    before=one('SELECT * FROM review_items WHERE id=?',(items[first]['id'],))
    api.delete('/api/projects/'+other['id'])
    result=api.get('/api/reviews').json()
    assert result['total']==result['due_count']==0 and result['items']==[]
    assert one('SELECT * FROM review_items WHERE id=?',(items[first]['id'],))==before
    denied=api.post('/api/reviews/start',json={'project_id':project['id'],'item_ids':[items[first]['id']]})
    assert denied.status_code==400
    api.post('/api/projects/'+other['id']+'/restore')
    restored=next(item for item in api.get('/api/reviews').json()['items'] if item['origin_set_id']==first)
    assert restored['active_set_id']==active
    assert practice.start_review(other['id'],[items[first]['id']])==(active,True)


def test_existing_mixed_review_requires_the_same_complete_selection(monkeypatch):
    first,project,second,other,items=plan(monkeypatch)
    ids=[items[first]['id'],items[second]['id']]
    active,_=practice.start_review(project['id'],ids);before=snapshot()
    with pytest.raises(ValueError,match='范围|原复习'):
        practice.start_review(project['id'],ids[:1])
    assert snapshot()==before
    assert practice.start_review(project['id'],list(reversed(ids)))==(active,True)


def test_removing_one_active_queue_item_does_not_silently_reuse_a_larger_worksheet(monkeypatch):
    first,project,second,other,items=plan(monkeypatch);ids=[items[first]['id'],items[second]['id']]
    active,_=practice.start_review(project['id'],ids)
    practice.remove_review(items[second]['id']);before=snapshot()
    with pytest.raises(ValueError,match='范围|原复习'):
        practice.start_review(project['id'],ids[:1])
    assert snapshot()==before
    assert one('SELECT id FROM exercise_sets WHERE id=?',(active,))


def test_rescheduling_completed_cross_project_review_cannot_modify_recycled_origins(monkeypatch):
    first,project,second,other,items=plan(monkeypatch)
    active,_=practice.start_review(project['id'],[items[second]['id']]);grade(active,90,used_notes=False)
    api=TestClient(server.app);api.delete('/api/projects/'+other['id']);before=snapshot()
    response=api.post('/api/exercises/'+active+'/review',json={'interval_days':7})
    assert response.status_code==400 and '回收站' in response.text
    assert snapshot()==before


def test_visible_queue_pagination_and_due_count_share_recycle_filter(monkeypatch):
    first,project,second,other,items=plan(monkeypatch)
    TestClient(server.app).delete('/api/projects/'+other['id'])
    page=practice.review_queue(offset=1,limit=1)
    assert page['items']==[] and page['total']==page['due_count']==1


def test_same_selection_validation_precedes_reuse_of_a_now_hidden_origin(monkeypatch):
    first,project,second,other,items=plan(monkeypatch);ids=[items[first]['id'],items[second]['id']]
    active,_=practice.start_review(project['id'],ids)
    TestClient(server.app).delete('/api/projects/'+other['id']);before=snapshot()
    with pytest.raises(ValueError,match='回收站'):
        practice.start_review(project['id'],ids)
    assert snapshot()==before


def test_selected_ids_are_reconciled_across_pages_without_fetching_hidden_topics(monkeypatch):
    first,project,second,other,items=plan(monkeypatch);api=TestClient(server.app)
    api.delete('/api/projects/'+other['id'])
    result=api.get('/api/reviews',params=[('offset',1),('limit',1),('selected_ids',items[first]['id']),('selected_ids',items[second]['id'])]).json()
    assert result['items']==[] and result['selected_ids']==[items[first]['id']]
    assert 'ORIGIN_RECYCLED' not in j(result)


def test_active_or_removed_items_leave_selection_without_changing_the_plan(monkeypatch):
    first,project,second,other,items=plan(monkeypatch);api=TestClient(server.app)
    practice.start_review(project['id'],[items[first]['id']]);practice.remove_review(items[second]['id'])
    before=snapshot()
    result=api.get('/api/reviews',params=[('selected_ids',items[first]['id']),('selected_ids',items[second]['id'])]).json()
    assert result['selected_ids']==[] and snapshot()==before


def test_selection_reconciliation_is_bounded_before_database_mutation(monkeypatch):
    first,project,second,other,items=plan(monkeypatch);before=snapshot()
    response=TestClient(server.app).get('/api/reviews',params=[('selected_ids',str(i)) for i in range(7)])
    assert response.status_code==422 and snapshot()==before
    response=TestClient(server.app).get('/api/reviews',params={'selected_ids':''})
    assert response.status_code==400 and snapshot()==before
