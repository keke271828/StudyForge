import asyncio
import zipfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from studyforge import practice, server
from studyforge.db import create_project, execute, j, many, now, one, uid, unj
from studyforge.exercises import grade_submission, public_set
from studyforge.learning_profile import effective_profile


class Grader:
    model = 'practice-test-model'
    def __init__(self, score=79, replies=None): self.score=score; self.calls=[]; self.replies=list(replies or [])
    async def complete(self, system, user, **kwargs):
        self.calls.append((system, user))
        if self.replies: return j(self.replies.pop(0))
        return j({'scores': [self.score], 'feedback': ['应区分理由与结论。'], 'uncertainties': [],
                  'diagnostics': [{'index': 0, 'kind': 'argumentation', 'quote': '因为相似', 'reason': '需补充论证依据，仍是暂定判断。'}]})


def make_set(project=None, topic='论证', difficulty=3, graded=False):
    project = project or create_project('练习')
    set_id = uid()
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)', (set_id, project['id'], '[]', topic+'练习',
        j([{'index':0,'question':'解释相似关系是否证明机制相同；公式 $a=b$ 仅作符号示例。','topic':topic}]),
        j([{'index':0,'solution':'PRIVATE_REFERENCE_SOLUTION','rubric':'PRIVATE_RUBRIC','generation_reviews':['PRIVATE_REVIEW']}]),
        difficulty, 'passed' if graded else 'assigned', now()))
    if graded:
        from studyforge.review_versions import assessment_basis
        basis=assessment_basis(one('SELECT * FROM exercise_sets WHERE id=?',(set_id,)))
        execute('INSERT INTO submissions VALUES (?,?,?,?,?,?,?)', (uid(),set_id,j(['因为相似还不够，需要更多证据。']),
            j({'score':90,'scores':[90],'feedback':['需要证据'],'assessment_version':basis}),90,'{}',practice.clock_now().isoformat()))
    return set_id, project


def grade(set_id, score=79, **options):
    client=Grader(score)
    result=asyncio.run(grade_submission(client,set_id,['因为相似，因此机制相同。'],**options))
    return result,client


def test_hint_scaffolds_never_read_or_release_private_answers_and_are_recorded_without_ai(monkeypatch):
    set_id,_=make_set()
    async def forbidden(*args,**kwargs):pytest.fail('思考提示不能调用模型')
    monkeypatch.setattr(server,'assessment_client',forbidden)
    client=TestClient(server.app)
    for level in (1,2,3):
        response=client.post(f'/api/exercises/{set_id}/hint',json={'question_index':0,'kind':'motivation','level':level})
        assert response.status_code==200 and response.json()['level']==level
        assert 'PRIVATE' not in response.text and 'solution' not in response.text
    assert len(many('SELECT * FROM practice_hints'))==3
    assert client.post(f'/api/exercises/{set_id}/hint',json={'question_index':0,'kind':'motivation','level':3}).status_code==200
    assert len(many('SELECT * FROM practice_hints'))==3
    assert 'solutions' not in client.get('/api/exercises/'+set_id).json()
    assert practice.attempt_context(set_id)['hint_levels']=={'0':3}


def test_hints_and_review_validate_bounds_and_do_not_schedule_without_full_submission():
    set_id,_=make_set();client=TestClient(server.app)
    for body in ({'question_index':0,'level':4},{'question_index':True,'level':1},{'question_index':0,'level':1,'kind':'fake'}):
        assert client.post(f'/api/exercises/{set_id}/hint',json=body).status_code==422
    assert client.post(f'/api/exercises/{set_id}/hint',json={'question_index':3,'level':1}).status_code==400
    assert client.post(f'/api/exercises/{set_id}/review',json={'interval_days':1}).status_code==400
    assert many('SELECT * FROM review_items')==[]
    # A status label alone is not evidence of a complete submission.
    execute("UPDATE exercise_sets SET status='passed' WHERE id=?",(set_id,))
    assert 'solutions' not in public_set(set_id,reveal=True)
    assert client.post(f'/api/exercises/{set_id}/hint',json={'question_index':0,'level':1}).status_code==400


def test_grading_freezes_hint_usage_for_that_attempt():
    set_id,_=make_set()
    with practice.submission_guard(set_id):
        with pytest.raises(ValueError,match='正在批改'):
            practice.get_hint(set_id,0,'unknown',1)
    assert practice.public_practice(set_id)['hint_usage']==[]
    assert practice.get_hint(set_id,0,'unknown',1)['level']==1


def test_hint_checks_current_status_after_acquiring_transaction(monkeypatch):
    set_id,_=make_set();original=practice.questions_for
    def concurrently_submitted(value):
        row,questions=original(value)
        execute("UPDATE exercise_sets SET status='passed' WHERE id=?",(value,))
        return row,questions
    monkeypatch.setattr(practice,'questions_for',concurrently_submitted)
    with pytest.raises(ValueError,match='已提交'):
        practice.get_hint(set_id,0,'unknown',1)
    assert practice.public_practice(set_id)['hint_usage']==[]


@pytest.mark.parametrize('mode,score,status,requires_feynman',[('adaptive',79,'repair_required',False),('adaptive',80,'passed',False),
    ('strict',79,'feynman_required',True),('strict',80,'passed',False)])
def test_adaptive_and_original_threshold_paths(mode,score,status,requires_feynman):
    set_id,_=make_set()
    result,client=grade(set_id,score,recovery_mode=mode,used_notes=False)
    assert result['requires_feynman'] is requires_feynman
    assert one('SELECT status FROM exercise_sets WHERE id=?',(set_id,))['status']==status
    assert len(client.calls)==2  # Diagnosis shares the existing grading requests.
    assert 'solutions' in public_set(set_id,reveal=True)
    assert result['diagnostics'][0]['quote']=='因为相似'
    assert result['diagnostics'][0]['status']=='暂定诊断'
    assert many('SELECT * FROM review_items')==[] and len(many('SELECT * FROM exercise_sets'))==1


def test_supported_high_score_is_not_used_to_raise_unassisted_difficulty():
    set_id,_=make_set()
    practice.get_hint(set_id,0,'argumentation',2)
    result,_=grade(set_id,100,recovery_mode='adaptive',used_notes=False)
    assert one('SELECT status FROM exercise_sets WHERE id=?',(set_id,))['status']=='passed_with_support'
    assert result['practice_context']['hint_levels']=={'0':2}
    row=effective_profile()[0]
    assert row['score']==100 and row['assisted_count']==1 and row['unaided_quiz_score'] is None
    assert server.profile_difficulty('论证',[row])==2
    assert '软件提示2层' in one('SELECT observation FROM learning_insights')['observation']


def test_diagnostics_require_actual_student_quote_and_unknown_is_not_low_ability():
    questions=[{'index':0,'topic':'概念'}]
    for item in ({'index':0,'kind':'prerequisites','quote':'编造的学生话','reason':'缺少基础'},
                 {'index':0,'kind':'personality','quote':'因为相似','reason':'不聪明'},
                 {'index':0,'kind':['argumentation'],'quote':'因为相似','reason':'错误类型'}):
        result=practice.diagnostics({'diagnostics':[item]},questions,['因为相似'])
        assert result[0]['kind']=='unknown' and result[0]['quote']=='' and '不能仅凭低分' in result[0]['reason']


@pytest.mark.parametrize('invalid',[float('nan'),float('inf'),True,'80'])
def test_invalid_grades_leave_answers_hidden_and_release_lock(invalid):
    set_id,_=make_set()
    client=Grader(replies=[{'scores':[invalid]}])
    with pytest.raises(RuntimeError):asyncio.run(grade_submission(client,set_id,['因为相似']))
    assert many('SELECT * FROM submissions')==[] and many('SELECT * FROM practice_submission_locks')==[]
    assert 'solutions' not in public_set(set_id,reveal=True)


def test_partial_answers_fail_before_model_and_concurrent_grading_is_single():
    set_id,_=make_set();client=Grader()
    with pytest.raises(ValueError):asyncio.run(grade_submission(client,set_id,[' ']))
    assert client.calls==[]
    async def run():
        entered,release=asyncio.Event(),asyncio.Event()
        class Waiting(Grader):
            async def complete(self,*args,**kwargs):entered.set();await release.wait();return await super().complete(*args,**kwargs)
        first=Waiting(80);second=Grader(80)
        task=asyncio.create_task(grade_submission(first,set_id,['因为相似']))
        await entered.wait()
        assert 'solutions' not in public_set(set_id,reveal=True)
        with pytest.raises(ValueError):await grade_submission(second,set_id,['因为相似'])
        assert second.calls==[]
        release.set();await task
    asyncio.run(run())
    assert len(many('SELECT * FROM submissions'))==1 and many('SELECT * FROM practice_submission_locks')==[]


def test_cancelled_grading_releases_guard_for_retry():
    set_id,_=make_set()
    async def run():
        entered=asyncio.Event()
        class Waiting(Grader):
            async def complete(self,*args,**kwargs):entered.set();await asyncio.Event().wait()
        task=asyncio.create_task(grade_submission(Waiting(),set_id,['因为相似']))
        await entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(run())
    assert many('SELECT * FROM practice_submission_locks')==[]
    assert grade(set_id,80)[0]['score']==80


def test_review_opt_in_reschedule_due_filter_and_indices_validation(monkeypatch):
    stamp=datetime(2026,10,3,8,tzinfo=timezone.utc)
    monkeypatch.setattr(practice,'clock_now',lambda:stamp)
    set_id,_=make_set(graded=True);practice.schedule_review(set_id,1)
    assert practice.review_queue(due_only=True)['total']==0
    practice.schedule_review(set_id,3)
    assert practice.review_queue()['total']==1
    stamp+=timedelta(days=3)
    assert practice.review_queue(due_only=True)['due_count']==1
    client=TestClient(server.app)
    assert client.post(f'/api/exercises/{set_id}/review',json={'question_indices':[True]}).status_code==422
    for indices in ([],[0,0],[9]):
        assert client.post(f'/api/exercises/{set_id}/review',json={'question_indices':indices}).status_code==400


def test_rescheduling_keeps_last_attempt_time_instead_of_plan_time(monkeypatch):
    stamp=datetime(2026,10,3,8,tzinfo=timezone.utc);monkeypatch.setattr(practice,'clock_now',lambda:stamp)
    origin,project=make_set(graded=True)
    stamp+=timedelta(days=3)
    practice.schedule_review(origin,1)
    baseline=practice.review_queue()['items'][0]['baseline_at']
    stamp+=timedelta(days=1)
    practice.schedule_review(origin,3)
    item=practice.review_queue()['items'][0]
    assert item['baseline_at']==baseline and practice.parse_time(item['due_at'])==stamp+timedelta(days=3)
    set_id,_=practice.start_review(project['id'],[item['id']])
    assert practice.attempt_context(set_id)['timing'][0]['delay_hours']==96
    grade(set_id,80,used_notes=False)
    current=practice.review_queue()['items'][0]['baseline_at']
    stamp+=timedelta(hours=12)
    practice.schedule_review(origin,7)
    assert practice.review_queue()['items'][0]['baseline_at']==current


def test_cross_project_mixed_review_hides_answers_is_idempotent_and_records_delay(monkeypatch):
    stamp=datetime(2026,10,3,8,tzinfo=timezone.utc);monkeypatch.setattr(practice,'clock_now',lambda:stamp)
    first,project=make_set(topic='论证',graded=True);second,_=make_set(topic='化学',graded=True)
    practice.schedule_review(first,1);practice.schedule_review(second,1)
    ids=[x['id'] for x in practice.review_queue()['items']]
    stamp+=timedelta(hours=25)
    set_id,reused=practice.start_review(project['id'],ids)
    assert not reused and practice.start_review(project['id'],ids)==(set_id,True)
    public=public_set(set_id,reveal=True)
    assert public['practice']['is_review'] and len(public['questions'])==2 and 'solutions' not in public
    assert 'PRIVATE' not in j(public) and 'generation_reviews' not in one('SELECT solutions_json FROM exercise_sets WHERE id=?',(set_id,))['solutions_json']
    with pytest.raises(ValueError):practice.schedule_review(first,1)
    class Two(Grader):
        async def complete(self,*args,**kwargs):return j({'scores':[90,90],'feedback':['依据','依据']})
    result=asyncio.run(grade_submission(Two(),set_id,['因为相似仍不够','因为相似仍不够'],used_notes=False))
    assert result['recovery_mode']=='adaptive' and all(x['delay_hours']==25 for x in result['practice_context']['timing'])
    assert all(row['delayed_count']==1 for row in effective_profile())
    assert all(x['active_set_id'] is None and not x['due'] for x in practice.review_queue()['items'])
    assert 'solutions' in public_set(set_id,reveal=True)
    practice.schedule_review(set_id,7)
    assert practice.review_queue()['total']==2  # Re-scheduling a mixed session updates originals, no duplicates.
    assert all(x['interval_days']==7 for x in practice.review_queue()['items'])


def test_early_review_and_notes_cannot_be_reported_as_verified_delayed_independence(monkeypatch):
    stamp=datetime(2026,10,3,8,tzinfo=timezone.utc);monkeypatch.setattr(practice,'clock_now',lambda:stamp)
    origin,project=make_set(graded=True);practice.schedule_review(origin,1)
    set_id,_=practice.start_review(project['id'],[practice.review_queue()['items'][0]['id']])
    result,_=grade(set_id,100,used_notes=True)
    assert result['practice_context']['timing'][0]['delay_hours']==0
    assert not result['practice_context']['timing'][0]['due_reached']
    row=effective_profile()[0]
    assert row['delayed_count']==0 and row['review_count']==1 and row['assisted_count']==1


def test_removing_active_review_does_not_recreate_it_after_submission():
    origin,project=make_set(graded=True);practice.schedule_review(origin,1)
    item=practice.review_queue()['items'][0];set_id,_=practice.start_review(project['id'],[item['id']])
    practice.remove_review(item['id']);grade(set_id,80)
    assert practice.review_queue()['total']==0 and one('SELECT completed_at FROM review_sessions')['completed_at']
    assert public_set(origin,reveal=True)['solutions']


def test_mixed_review_rejects_partial_or_stale_selection_atomically():
    origin,project=make_set(graded=True);practice.schedule_review(origin,1)
    item=practice.review_queue()['items'][0]
    with pytest.raises(ValueError):practice.start_review(project['id'],[item['id'],'nonexistent'])
    assert many('SELECT * FROM review_sessions')==[] and len(many('SELECT * FROM exercise_sets'))==1
    assert practice.review_queue()['items'][0]['active_set_id'] is None


def test_adaptive_feynman_passes_without_automatic_harder_questions(monkeypatch):
    set_id,_=make_set();grade(set_id,60,recovery_mode='adaptive')
    client=Grader(replies=[{'score':80,'feedback':'解释清楚','gaps':[]}])
    async def factory(*args,**kwargs):return client
    async def forbidden(*args,**kwargs):pytest.fail('自主修复不自动生成更难习题')
    monkeypatch.setattr(server,'assessment_client',factory);monkeypatch.setattr(server,'generate_set',forbidden)
    response=TestClient(server.app).post(f'/api/exercises/{set_id}/feynman',json={'explanation':'我会先区分相似的描述与共同的因果机制，再说明需要哪些证据来排除其他解释。'*4})
    assert response.status_code==200 and response.json()['passed'] and 'next_set' not in response.json()
    assert one('SELECT status FROM exercise_sets WHERE id=?',(set_id,))['status']=='repair_ready'


def test_explicit_repair_uses_full_original_keeps_difficulty_and_reuses_result(tmp_path,monkeypatch):
    set_id,project=make_set();grade(set_id,60,recovery_mode='adaptive')
    source=uid();original=tmp_path/'完整资料.txt';original.write_text('开头定义。\n'+('原资料论证。'*100)+'\n末尾适用条件不可遗漏。',encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
        (source,project['id'],original.name,'.txt',str(original),j([{'locator':'预览','text':'错误的缩略预览'}]),'ready',now()))
    execute('UPDATE exercise_sets SET source_ids_json=? WHERE id=?',(j([source]),set_id))
    calls=[]
    async def factory(*args,**kwargs):calls.append(args);return Grader()
    async def generate(client,pid,sources,digest,title,difficulty,repair_spec=None):
        assert '末尾适用条件不可遗漏' in digest and '错误的缩略预览' not in digest and '不因低分加难度' in digest
        assert difficulty==3 and sources==[source]
        assert repair_spec['targets'][0]['index']==0 and repair_spec['difficulty']==3
        fresh,_=make_set(project=project,difficulty=difficulty)
        fresh_row=one('SELECT questions_json,solutions_json FROM exercise_sets WHERE id=?',(fresh,))
        questions=unj(fresh_row['questions_json']);questions[0]['question']='新的情境：比较两个看似相同的机制时，还需要哪些独立证据？'
        private=unj(fresh_row['solutions_json']);private[0].update(repair_target_index=0,repair_focus='检查比较机制时如何说明证据条件，不重复原题。')
        execute('UPDATE exercise_sets SET questions_json=?,solutions_json=? WHERE id=?',(j(questions),j(private),fresh))
        return fresh,[{'stage':'题意'}]
    monkeypatch.setattr(server,'assessment_client',factory);monkeypatch.setattr(server,'generate_set',generate)
    client=TestClient(server.app);path=f'/api/exercises/{set_id}/repair'
    first=client.post(path,json={'provider':'deepseek','model':'chosen-repair'})
    assert first.status_code==200,first.text
    result=first.json();assert result['exercise_set']['difficulty']==3 and 'solutions' not in result['exercise_set']
    second=client.post(path,json={'provider':'deepseek','model':'chosen-repair'})
    assert second.json()['cached'] and second.json()['exercise_set']['id']==result['exercise_set']['id'] and len(calls)==1
    artifact=one('SELECT path FROM artifacts WHERE id=?',(result['artifact']['id'],))
    with zipfile.ZipFile(artifact['path']) as archive:assert 'PRIVATE_REFERENCE' not in archive.read('word/document.xml').decode()


def test_review_queue_pagination_and_no_automatic_queue_from_reading():
    assert practice.review_queue()['total']==0
    project=create_project('很多知识')
    for index in range(53):
        set_id,_=make_set(project=project,topic=f'概念{index}',graded=True);practice.schedule_review(set_id,1)
    first=practice.review_queue(limit=50);second=practice.review_queue(offset=50,limit=50)
    assert first['total']==53 and len(second['items'])==3
    assert not ({x['id'] for x in first['items']} & {x['id'] for x in second['items']})
