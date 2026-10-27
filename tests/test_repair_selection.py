"""Selecting one diagnosed error does not silently regenerate the whole paper."""
import asyncio
import json

import pytest
from docx import Document
from fastapi import HTTPException
from fastapi.testclient import TestClient

from scripts.repair_learning_fixture import seed
from studyforge import ai, exercises, homework, repair_learning as repair, server
from studyforge.db import execute, j, many, one, unj


def two_errors(tmp_path):
    value=seed(tmp_path)
    answers=['我认为内部净电荷为零就能推出里面每个点的电场为零。','我计算2+3=4。']
    submission=one('SELECT * FROM submissions WHERE id=?',(value['submission_id'],))
    grade=unj(submission['grade_json']);grade.update(scores=[90,60],score=75,feedback=['净通量与场未区分。','加法错误。'])
    attempt=homework.get_attempt(value['attempt_id']);analysis=unj(attempt['analysis_json'])
    analysis['items'].append({'index':1,'kind':'implementation','confidence':'supported','cause':'本次作答出现2+3=4。',
        'evidence':[{'source':'answer','quote':'2+3=4'}],
        'explanation':'从2开始逐次加三个1，依次得到3、4、5。加法结果是5，用5减去3恢复2；4减去3得到1，没有恢复原数。',
        'check':'用减法复核当前一步。'})
    execute('UPDATE submissions SET answers_json=?,grade_json=?,score=? WHERE id=?',(j(answers),j(grade),75,value['submission_id']))
    execute('UPDATE homework_attempts SET answers_json=?,grade_json=?,analysis_json=? WHERE id=?',
            (j(answers),j(grade),j(analysis),value['attempt_id']))
    execute("UPDATE exercise_sets SET status='repair_required' WHERE id=?",(value['set_id'],))
    return value,one('SELECT * FROM exercise_sets WHERE id=?',(value['set_id'],)),one('SELECT * FROM submissions WHERE id=?',(value['submission_id'],))


def activity():
    return {name:many('SELECT * FROM '+name) for name in ('submissions','learning_events','mastery','jobs')}


def test_subset_keeps_original_indices_order_difficulty_and_diagnosis_boundaries(tmp_path):
    _,worksheet,submission=two_errors(tmp_path)
    full=repair.build(worksheet,submission)
    assert repair.build(worksheet,submission,None)==full
    second=repair.build(worksheet,submission,[1])
    assert [target['index'] for target in second['targets']]==[1]
    assert second['targets'][0]['topic']=='算术' and second['difficulty']==full['difficulty']
    assert '电通量' not in j(second['targets'])
    assert repair.build(worksheet,submission,[1,0])==full
    assert second['signature']!=full['signature']


@pytest.mark.parametrize('selection',[[],[0,0],[-1],[2],[True],['1'],(1,)])
def test_invalid_explicit_selection_never_falls_back_to_all_errors(tmp_path,selection):
    _,worksheet,submission=two_errors(tmp_path)
    with pytest.raises(ValueError,match='题号'):repair.build(worksheet,submission,selection)


def test_correct_question_is_not_relabelled_as_a_repair_target(tmp_path):
    value=seed(tmp_path)
    worksheet=one('SELECT * FROM exercise_sets WHERE id=?',(value['set_id'],))
    submission=one('SELECT * FROM submissions WHERE id=?',(value['submission_id'],))
    with pytest.raises(ValueError,match='答对题'):repair.build(worksheet,submission,[1])


def test_options_only_lists_public_target_metadata_without_writes_or_answers(tmp_path):
    value,_,_=two_errors(tmp_path);before=activity()
    response=TestClient(server.app).get('/api/exercises/'+value['set_id']+'/repair-options')
    assert response.status_code==200,response.text
    data=response.json()
    assert [target['index'] for target in data['targets']]==[0,1]
    assert data['expected_submission_id']==value['submission_id']
    assert {target['basis'] for target in data['targets']}=={'student_self_report','answer_supported_tentative'}
    assert '2+3=4' not in response.text and 'solutions' not in response.text and 'explanation' not in response.text
    assert activity()==before


@pytest.mark.parametrize('extra',[{'question_indices':[]},{'question_indices':[True]},
    {'question_indices':['1']},{'expected_context_signature':'bad-hash'}])
def test_api_rejects_malformed_selection(tmp_path,extra):
    value,_,_=two_errors(tmp_path)
    result=TestClient(server.app).post('/api/exercises/'+value['set_id']+'/repair',json=extra)
    assert result.status_code==422
    assert not many("SELECT * FROM jobs WHERE kind='repair'")


@pytest.mark.parametrize('change',['submission','feedback','cause'])
def test_stale_selection_is_rejected_before_background_job_or_model(tmp_path,change):
    value,_,_=two_errors(tmp_path);client=TestClient(server.app)
    options=client.get('/api/exercises/'+value['set_id']+'/repair-options').json()
    payload={key:options[key] for key in ('expected_submission_id','expected_context_signature')}
    if change=='submission':payload['expected_submission_id']='different'
    elif change=='feedback':execute("UPDATE submissions SET grade_json=json_set(grade_json,'$.feedback[0]','复核后的新反馈') WHERE id=?",(value['submission_id'],))
    else:execute("UPDATE homework_attempts SET analysis_json=json_set(analysis_json,'$.items[0].cause','新错因线索') WHERE id=?",(value['attempt_id'],))
    response=client.post('/api/exercises/'+value['set_id']+'/repair',json=payload|{'question_indices':[1],'background':True})
    assert response.status_code==400 and '变化' in response.text
    assert not many("SELECT * FROM jobs WHERE kind='repair'")


class Model:
    provider='deepseek';model='isolated-repair-model';effort=None
    def __init__(self):self.calls=[];self.spec=None
    async def complete(self,system,user,**kwargs):
        self.calls.append((system,user))
        if '严谨的习题设计者' in system:
            self.spec,_=json.JSONDecoder().raw_decode(user.split('修复目标数据：',1)[1])
            return j({'questions':[{'question':f'新情境_{target["index"]}：比较不同条件，说明判断与理由。',
                'topic':target['topic'],'solution':'PRIVATE_SOLUTION：独立推导及边界条件。','rubric':'明确条件和理由',
                'source_url':'','repair_target_index':target['index'],
                'repair_focus':'PRIVATE_FOCUS：通过新条件区分对应知识点的不同推理步骤。'} for target in self.spec['targets']]})
        if '独立解题员' in system:return j({'answers':[{'index':i,'solution':'独立解题完成。','issues':[]} for i in range(len(self.spec['targets']))]})
        return j({'passed':True,'issues':[]})
    async def close(self):pass


def configured(monkeypatch):
    models=[]
    async def factory(*args,**kwargs):model=Model();models.append(model);return model
    async def choose(*args,**kwargs):pass
    monkeypatch.setattr(server,'assessment_client',factory);monkeypatch.setattr(server,'choose_generation_model',choose)
    monkeypatch.setattr(exercises,'search_exercises',lambda title:asyncio.sleep(0,result=[]))
    return models


def test_distinct_scopes_remain_reusable_and_unchanged_scores_do_not_duplicate(tmp_path,monkeypatch):
    value,_,_=two_errors(tmp_path);models=configured(monkeypatch);client=TestClient(server.app)
    endpoint='/api/exercises/'+value['set_id']+'/repair';before=activity();sets=[]
    for indices in ([0],[1],[0,1]):
        response=client.post(endpoint,json={'provider':'deepseek','question_indices':indices})
        assert response.status_code==200,response.text
        result=response.json();assert not result['cached'];sets.append(result['exercise_set']['id'])
        assert [target['index'] for target in result['exercise_set']['repair']['targets']]==indices
        assert len(result['exercise_set']['questions'])==len(indices)
        assert 'PRIVATE_' not in j(result)
        artifact=one('SELECT path FROM artifacts WHERE id=?',(result['artifact']['id'],))
        text='\n'.join(p.text for p in Document(artifact['path']).paragraphs)
        assert 'PRIVATE_' not in text and '新情境_' in text
    assert len(set(sets))==3 and [len(model.calls) for model in models]==[4,4,4]
    for indices,ident in zip(([0],[1],[0,1]),sets):
        result=client.post(endpoint,json={'provider':'deepseek','question_indices':indices}).json()
        assert result['cached'] and result['exercise_set']['id']==ident
    assert len(models)==3
    after=activity()
    assert all(after[name]==before[name] for name in ('submissions','learning_events','mastery'))


def test_invalid_saved_target_metadata_generates_fresh_instead_of_failing_forever(tmp_path,monkeypatch):
    value,_,_=two_errors(tmp_path);models=configured(monkeypatch);client=TestClient(server.app)
    endpoint='/api/exercises/'+value['set_id']+'/repair';payload={'provider':'deepseek','question_indices':[1]}
    first=client.post(endpoint,json=payload).json();ident=first['exercise_set']['id']
    execute("UPDATE exercise_sets SET solutions_json=json_remove(solutions_json,'$[0].repair_focus') WHERE id=?",(ident,))
    result=client.post(endpoint,json=payload)
    assert result.status_code==200,result.text
    assert not result.json()['cached'] and result.json()['exercise_set']['id']!=ident
    assert [len(model.calls) for model in models]==[4,4]


def test_background_payload_keeps_selected_indices_and_binding_on_resume(tmp_path,monkeypatch):
    value,_,_=two_errors(tmp_path);models=configured(monkeypatch)
    options=server.repair_options(value['set_id'])
    async def exercise():
        import studyforge.job_control as controls
        # Queue without executing; then run the same serialized job dispatcher
        # in a fresh control scope, as restart/resume does.
        queued=[]
        def delay(ident,coroutine):queued.append(ident);coroutine.close()
        monkeypatch.setattr(server,'start_job',delay)
        response=await server.repair_practice(value['set_id'],server.RepairIn(provider='deepseek',background=True,
            conversation_id=value['conversation_id'],question_indices=[1],
            expected_submission_id=options['expected_submission_id'],expected_context_signature=options['expected_context_signature']))
        ident=response['job_id'];assert queued==[ident]
        saved=unj(one('SELECT payload_json FROM jobs WHERE id=?',(ident,))['payload_json'])
        assert saved['values']['question_indices']==[1]
        await server._assessment_job(ident)
        job=one('SELECT * FROM jobs WHERE id=?',(ident,));assert job['status']=='completed',job
        result=unj(job['result_json'])['output']
        assert [target['index'] for target in result['exercise_set']['repair']['targets']]==[1]
    asyncio.run(exercise())
    assert len(models)==1 and len(models[0].calls)==4


def test_authenticated_phone_can_select_without_disclosing_private_data(tmp_path):
    from tests.test_mobile_access import mobile_client,pair
    value,_,_=two_errors(tmp_path);manager,phone=mobile_client()
    endpoint='/api/exercises/'+value['set_id']+'/repair-options'
    with phone:
        assert phone.get(endpoint).status_code==401
        pair(manager,phone)
        result=phone.get(endpoint);assert result.status_code==200,result.text
        assert len(result.json()['targets'])==2 and 'PRIVATE_' not in result.text
        for asset in ('repair_picker.js','repair_picker.css'):assert phone.get('/'+asset).status_code==200


def test_second_occupancy_check_stops_parallel_same_parent_queue(tmp_path,monkeypatch):
    value,_,_=two_errors(tmp_path);configured(monkeypatch);queued=[]
    def delay(ident,coroutine):queued.append(ident);coroutine.close()
    monkeypatch.setattr(server,'start_job',delay)
    async def choose(*args,**kwargs):await asyncio.sleep(.01)
    monkeypatch.setattr(server,'choose_generation_model',choose)
    async def exercise():
        return await asyncio.gather(*(server.repair_practice(value['set_id'],server.RepairIn(
            provider='deepseek',background=True,conversation_id=value['conversation_id'],question_indices=indices))
            for indices in ([0],[1])),return_exceptions=True)
    results=asyncio.run(exercise())
    assert len(queued)==1 and sum(isinstance(item,HTTPException) and item.status_code==409 for item in results)==1


def test_reader_only_offers_targeted_practice_for_current_published_error(tmp_path):
    from studyforge.exporters import export_document
    value,worksheet,submission=two_errors(tmp_path)
    attempt=homework.get_attempt(value['attempt_id'])
    path=export_document(homework.report_document(attempt,worksheet,unj(submission['grade_json']),unj(attempt['analysis_json'])),
        'docx','错题反馈','selected-feedback.docx')
    artifact=server.add_artifact(value['project_id'],[],'grading','docx','错题反馈',path,
        {'homework_attempt_id':value['attempt_id'],'exercise_set_id':value['set_id'],'conversation_id':value['conversation_id']})
    execute('UPDATE homework_attempts SET feedback_artifact_id=? WHERE id=?',(artifact['id'],value['attempt_id']))
    client=TestClient(server.app);endpoint='/api/homework/'+value['attempt_id']+'/reading?project_id='+value['project_id']+'&question_number=2'
    first=client.get(endpoint);assert first.status_code==200,first.text
    assert first.json()['repair_reference']['submission_id']==submission['id']
    # A newly added review requirement must hide the action; reading still works.
    execute("UPDATE exercise_sets SET status='feynman_required' WHERE id=?",(value['set_id'],))
    result=client.get(endpoint);assert result.status_code==200 and result.json()['repair_reference'] is None
    execute("UPDATE exercise_sets SET status='repair_required' WHERE id=?",(value['set_id'],))
    execute("UPDATE homework_attempts SET status='awaiting_causes' WHERE id=?",(value['attempt_id'],))
    result=client.get(endpoint);assert result.status_code==200 and result.json()['repair_reference'] is None
