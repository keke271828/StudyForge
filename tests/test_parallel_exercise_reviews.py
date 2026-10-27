"""Both unchanged auditors overlap only with separate branches and capacity."""
import asyncio
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from studyforge import ai,review,server
from studyforge.db import create_project,create_job,j,many,one,unj
from studyforge.generation_control import GenerationControl,PausableClient
from studyforge.scheduling import model_slot,scheduler


QUESTIONS=[{'question':'PUBLIC_STEM：解释关键理由。','solution':'PRIVATE_REFERENCE','rubric':'正确判断40分、理由60分。','topic':'边界','source_url':''}]


class Root:
    model='same-model';effort='high'
    def __init__(self,hold=False,fail_once=False,repair=False):
        self.children=[];self.calls=Counter();self.active=0;self.peak=0
        self.release=asyncio.Event();self.both=asyncio.Event();self.started=0
        self.hold=hold;self.fail_once=fail_once;self.repair=repair;self.repaired=False
        if not hold:self.release.set()
    def fork(self):
        root=self
        class Branch:
            model=root.model;effort=root.effort
            closed=False
            async def close(self):self.closed=True
            async def complete(self,system,user,**kwargs):
                assert root.calls['independent']>0
                assert 'PRIVATE_REFERENCE' in user and self.model==root.model and self.effort==root.effort
                stage='解析核查' if '阶段：解析核查。' in user else '成品核查'
                root.calls[stage]+=1
                async with model_slot('test'):
                    root.active+=1;root.started+=1;root.peak=max(root.peak,root.active)
                    if root.started>=2:root.both.set()
                    try:
                        await root.release.wait();await asyncio.sleep(.025)
                        if root.fail_once and stage=='解析核查' and root.calls[stage]==1:raise RuntimeError('controlled transport failure')
                        if root.repair and not root.repaired:
                            return j({'passed':False,'issues':[{'index':0,'category':'solution' if stage=='解析核查' else 'answer_leak',
                                'problem':'PRIVATE_A' if stage=='解析核查' else 'PRIVATE_B'}],'corrected_questions':[]})
                        return j({'passed':True,'issues':[]})
                    finally:root.active-=1
        child=Branch();self.children.append(child);return child
    async def complete(self,system,user,**kwargs):
        if '你是独立解题员' in system:
            assert 'PRIVATE_REFERENCE' not in user
            self.calls['independent']+=1
            return j({'answers':[{'index':0,'solution':'独立重新求解。','issues':[]}]})
        if '正在修订当前题单' in system:
            assert 'PRIVATE_A' in user and 'PRIVATE_B' in user
            self.calls['repair']+=1;self.repaired=True
            return j({'questions':[QUESTIONS[0]|{'question':'REPAIRED_STEM：解释关键理由。'}]})
        # Serial operation must retain the original parent context/scope.
        temporary=self.fork()
        try:return await temporary.complete(system,user,**kwargs)
        finally:await temporary.close()


@pytest.mark.parametrize('parallel,limit,peak',[(False,2,1),(True,2,2),(True,1,1)])
def test_real_scheduler_and_two_reports_respect_the_selected_mode(parallel,limit,peak):
    ai.save_settings({'model_concurrency':limit,'task_parallel_enabled':True})
    async def run():
        client=Root();questions,reports=await review.review_exercises(client,'SOURCE',QUESTIONS,parallel=parallel)
        assert questions==QUESTIONS and client.peak==peak
        assert [r['stage'] for r in reports]==['独立解题','解析核查','成品核查']
        assert client.calls=={'independent':1,'解析核查':1,'成品核查':1}
        assert all(child.closed for child in client.children)
    asyncio.run(run())


def test_parallel_repair_collects_both_findings_then_solves_and_checks_again():
    ai.save_settings({'model_concurrency':2})
    async def run():
        client=Root(repair=True);questions,reports=await review.review_exercises(client,'SOURCE',QUESTIONS,parallel=True)
        assert questions[0]['question'].startswith('REPAIRED_STEM')
        assert client.calls=={'independent':2,'repair':1,'解析核查':2,'成品核查':2}
        assert [r['stage'] for r in reports]==['独立解题','解析核查','成品核查','修订','独立解题','解析核查','成品核查']
        assert all(child.closed for child in client.children) and client.peak==2
    asyncio.run(run())


def test_successful_sibling_is_cached_when_other_audit_fails_and_retry_reuses_it():
    ai.save_settings({'model_concurrency':2})
    project=create_project('retry');job=create_job(project['id'],'generate',{});control=GenerationControl(job)
    async def run():
        root=Root(fail_once=True)
        with pytest.raises(RuntimeError,match='transport failure'):
            await review.review_exercises(PausableClient(root,control,'exercise'),'SOURCE',QUESTIONS,parallel=True)
        assert root.calls=={'independent':1,'解析核查':1,'成品核查':1}
        await review.review_exercises(PausableClient(root,control,'exercise'),'SOURCE',QUESTIONS,parallel=True)
        assert root.calls=={'independent':1,'解析核查':2,'成品核查':1}
        assert all(child.closed for child in root.children) and control.in_flight==0
    asyncio.run(run())


def test_pause_after_both_requests_start_can_restart_without_repeating_either():
    ai.save_settings({'model_concurrency':2})
    project=create_project('pause');job=create_job(project['id'],'generate',{});control=GenerationControl(job)
    async def run():
        root=Root(hold=True)
        task=asyncio.create_task(review.review_exercises(PausableClient(root,control,'exercise'),'SOURCE',QUESTIONS,parallel=True))
        await asyncio.wait_for(root.both.wait(),2);control.pause();root.release.set()
        await asyncio.wait_for(control.idle_event.wait(),2)
        assert one('SELECT status FROM jobs WHERE id=?',(job,))['status']=='paused'
        task.cancel();await asyncio.gather(task,return_exceptions=True)
        assert len(many('SELECT * FROM generation_steps WHERE job_id=?',(job,)))==3
        resumed=GenerationControl(job);resumed.resume()
        await review.review_exercises(PausableClient(root,resumed,'exercise'),'SOURCE',QUESTIONS,parallel=True)
        assert root.calls=={'independent':1,'解析核查':1,'成品核查':1}
        assert all(child.closed for child in root.children) and control.in_flight==0
    asyncio.run(run())


def test_cancel_releases_both_provider_branches_and_model_slots():
    ai.save_settings({'model_concurrency':2})
    async def run():
        root=Root(hold=True);task=asyncio.create_task(review.review_exercises(root,'SOURCE',QUESTIONS,parallel=True))
        await asyncio.wait_for(root.both.wait(),2);task.cancel();await asyncio.gather(task,return_exceptions=True)
        assert root.active==0 and all(child.closed for child in root.children)
        assert scheduler().snapshot()['model']['active']==0
    asyncio.run(run())


def test_provider_without_a_real_fork_uses_serial_fallback():
    class NoFork:
        active=0;peak=0
        async def complete(self,system,user,**kwargs):
            self.active+=1;self.peak=max(self.peak,self.active);await asyncio.sleep(.005);self.active-=1
            return j({'answers':[{'index':0,'solution':'已求解','issues':[]}]}) if '独立解题员' in system else j({'passed':True,'issues':[]})
    async def run():
        client=NoFork();_,reports=await review.review_exercises(client,'SOURCE',QUESTIONS,parallel=True)
        assert client.peak==1 and len(reports)==3
    asyncio.run(run())


@pytest.mark.parametrize('selected',[True,False])
def test_new_job_pins_checkbox_and_discards_conflicting_client_internal_field(tmp_path,monkeypatch,selected):
    from tests.test_lesson_checks import completed_lesson
    p,c,q,*_=completed_lesson(tmp_path)
    monkeypatch.setattr(server,'start_job',lambda ident,operation:operation.close())
    api=TestClient(server.app)
    response=api.post('/api/generate',json={'project_id':p['id'],'conversation_id':c['id'],'source_ids':[],
        'provider':'deepseek','only_exercises':True,'instructions':'检查本次补讲','lesson_check':{'questionnaire_id':q['id']},
        'parallel':selected,'exercise_review_parallel':not selected})
    assert response.status_code==200,response.text
    saved=unj(one('SELECT payload_json FROM jobs WHERE id=?',(response.json()['job_id'],))['payload_json'])
    assert saved['exercise_review_parallel']==selected and saved['parallel']==selected
    assert saved['model']=='fixture-model'


def test_check_button_entry_uses_explicit_parallel_choice_without_overwriting_global_defaults(tmp_path,monkeypatch):
    from tests.test_lesson_checks import completed_lesson
    p,c,q,*_=completed_lesson(tmp_path);ai.save_settings({'generation_parallel':False})
    monkeypatch.setattr(server,'start_job',lambda ident,operation:operation.close())
    response=TestClient(server.app).post(f'/api/lesson-feedback/{q["id"]}/check',json={
        'project_id':p['id'],'conversation_id':c['id'],'parallel':True})
    assert response.status_code==200,response.text
    saved=unj(one('SELECT payload_json FROM jobs WHERE id=?',(response.json()['job_id'],))['payload_json'])
    assert saved['exercise_review_parallel'] and not ai.settings()['generation_parallel']
