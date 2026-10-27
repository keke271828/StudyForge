import asyncio
import json
import time

import httpx
import pytest
from docx import Document
from fastapi.testclient import TestClient

from studyforge import ai, exercises, learning_goals as goals, server
from studyforge.db import execute, j, many, now, one, uid, unj
from test_learning_goals import case, plan, linked_check, scored, review_set, edited


def seed(tmp_path):
    project,other,source,path,chat,second,foreign=case(tmp_path)
    goal=plan(project,source);base=linked_check(goal,project);submission=scored(base,[85]*3,created='2026-10-13T00:00:00+00:00')
    return project,other,source,path,chat,second,foreign,goal,base,submission


def proposed(spec):
    return [{'question':f'NEW_{i}：在改变的评价条件中重建第{i+1}个论证，不只复述结论。',
        'topic':spec['profile_topic'],'assessment_dimension':dim,'source_url':'',
        'solution':f'SOLUTION_PRIVATE_{i}：完整核对该条件与推理。','rubric':'依据、条件与理由分别计分。',
        'context_change':f'CHANGE_PRIVATE_{i}：改为新的评价原则，并检查其能否支持变化后的结论。'}
        for i,dim in enumerate(spec['dimensions'])]


def payload(goal,chat,kind='new_context'):
    return {'version':goal['version'],'conversation_id':chat,'provider':'deepseek','model':'route-model',
            'kind':kind,'explanation_style':'balanced','output_language':'zh'}


def test_baseline_snapshot_contains_only_completed_public_questions_not_answers_or_feedback(tmp_path):
    project,*_,goal,base,submission=seed(tmp_path)
    spec=goals.check_spec(goals.get(goal['id'],project),'new_context')
    assert spec['kind']=='new_context' and spec['baseline']['exercise_set_id']==base
    assert spec['baseline']['submission_id']==submission and len(spec['baseline']['questions'])==3
    assert spec['baseline']['difficulty']==1
    text=j(spec)
    assert 'CHECK_0' in text and all(secret not in text for secret in ['PRIVATE_ANSWER','PRIVATE_FEEDBACK','PRIVATE_0'])
    requirements=goals.check_requirements(spec)
    assert '不只换数字' in requirements and '不因它已做完就自动加难' in requirements


@pytest.mark.parametrize('change',['pending','source','goal','foreign','unsubmitted'])
def test_reference_must_be_current_scope_same_goal_and_confirmed(tmp_path,change):
    project,other,source,path,chat,_,_,goal,base,_=seed(tmp_path)
    if change=='pending':scored(base,[95]*3,pending=True)
    elif change=='source':path.write_text(path.read_text(encoding='utf-8')+'不同的范围。',encoding='utf-8')
    elif change=='goal':goal=goals.save(project,edited(goal,criterion='不同的判断标准'),goal['id'])
    elif change=='foreign':base=linked_check(goals.save(other,{'name':'外部目标','domain':'哲学','source_ids':[]}),other);scored(base,[95]*3)
    else:base=linked_check(goal,project)
    with pytest.raises(ValueError):goals.check_spec(goals.get(goal['id'],project),'new_context',base)


def test_reference_uses_actual_latest_submission_not_check_creation_order(tmp_path):
    project,*_,goal,base,_=seed(tmp_path)
    second=linked_check(goal,project);scored(second,[90]*3,created='2026-10-13T10:00:00+00:00')
    scored(base,[92]*3,created='2026-10-13T11:00:00+00:00')
    assert goals.reviewable_check(goals.get(goal['id'],project))==base


def test_duplicate_questions_are_rejected_but_math_operator_changes_are_preserved(tmp_path):
    project,*_,goal,base,_=seed(tmp_path);spec=goals.check_spec(goals.get(goal['id'],project),'new_context')
    items=proposed(spec);items[0]['question']=spec['baseline']['questions'][1]['question'].replace('：',':').replace('。','.')
    with pytest.raises(ValueError,match='复用'):goals.validate_context_changes(items,spec)
    items=proposed(spec);items[2]['question']=items[0]['question']
    with pytest.raises(ValueError,match='重复'):goals.validate_context_changes(items,spec)
    items=proposed(spec);items[0]['context_change']='短'
    with pytest.raises(ValueError,match='context_change'):goals.validate_context_changes(items,spec)
    spec['baseline']['questions'][0]['question']='判断 a>b 时条件是否满足'
    items=proposed(spec);items[0]['question']='判断 a<b 时条件是否满足'
    goals.validate_context_changes(items,spec)


def test_original_review_never_counts_as_another_fresh_context_and_aids_are_kept(tmp_path):
    project,*_,goal,base,_=seed(tmp_path)
    old_repeat=review_set(project,base);scored(old_repeat,[90]*3,delayed=True,created='2026-10-13T18:00:00+00:00')
    row=goals.get(goal['id'],project)
    assert goals.public_goal(row)['recommendation']['action']=='new_context'
    changed=linked_check(goal,project,kind='new_context');scored(changed,[90]*3,created='2026-10-13T19:00:00+00:00')
    result=goals.public_goal(row)
    assert result['recommendation']['action']=='extend'
    assert all(e['new_context_record_count']==1 for e in result['evidence'])
    repeat=review_set(project,changed);scored(repeat,[92]*3,delayed=True,created='2026-10-13T20:00:00+00:00')
    assert goals.public_goal(row)['recommendation']['action']=='extend'
    assert all(e['latest']['kind']=='original_repeat' and e['new_context_record_count']==1 for e in goals.public_goal(row)['evidence'])
    scored(changed,[95]*3,notes=True,created='2026-10-13T21:00:00+00:00')
    result=goals.public_goal(row)
    assert result['recommendation']['action']=='unaided' and all(not e['new_context_meets_threshold'] for e in result['evidence'])


def test_identical_timestamps_use_database_order_not_random_identifiers(tmp_path):
    project,*_,goal,base,older=seed(tmp_path)
    execute('UPDATE submissions SET id=?,created_at=? WHERE id=?',('z'*32,'2026-10-13T15:00:00+00:00',older))
    later=linked_check(goal,project);ident=scored(later,[79,90,90],created='2026-10-13T15:00:00+00:00')
    execute('UPDATE submissions SET id=? WHERE id=?',('a'*32,ident))
    result=goals.public_goal(goals.get(goal['id'],project))
    assert result['evidence'][0]['latest']['score']==79 and result['recommendation']['action']=='repair'
    assert goals.reviewable_check(goals.get(goal['id'],project))==later


def test_review_cannot_relabel_swapped_unchanged_questions_as_three_correct_dimensions(tmp_path,monkeypatch):
    project,*_,goal,base,_=seed(tmp_path);spec=goals.check_spec(goals.get(goal['id'],project),'new_context')
    async def search(*args):return []
    async def review(client,digest,items,**kwargs):
        return [{key:value for key,value in item.items() if key not in ('assessment_dimension','context_change')}
                for item in reversed(items)],[]
    class Client:
        async def complete(self,*args,**kwargs):return j({'questions':proposed(spec)})
    monkeypatch.setattr(exercises,'search_exercises',search);monkeypatch.setattr(exercises,'review_exercises',review)
    with pytest.raises(ValueError,match='assessment_dimension'):
        asyncio.run(exercises.generate_set(Client(),project,spec['source_ids'],'原文','检查',check_spec=spec))
    assert {row['id'] for row in many('SELECT id FROM exercise_sets')}=={base}


def test_duplicate_task_reuse_keeps_kinds_independent_and_rebuilds_reference(tmp_path,monkeypatch):
    project,*_,chat,second,foreign,goal,base,_=seed(tmp_path)
    requests=[]
    async def start(value):
        requests.append(value.model_dump());return {'job_id':uid()}
    monkeypatch.setattr(server,'generate',start)
    api=TestClient(server.app);url=f'/api/projects/{project}/learning-goals/{goal["id"]}/check'
    standard={'goal_check':goals.check_spec(goals.get(goal['id'],project)),'conversation_id':chat}
    from studyforge.db import create_job
    running=create_job(project,'generate',standard)
    assert api.post(url,json=payload(goal,chat,'standard')).json()['job_id']==running
    response=api.post(url,json=payload(goal,chat))
    assert response.status_code==200 and len(requests)==1
    assert requests[0]['goal_check']['kind']=='new_context' and requests[0]['goal_check']['baseline']['exercise_set_id']==base
    assert requests[0]['only_exercises'] and requests[0]['exercise_format']=='docx'


def native_transport(monkeypatch,spec):
    calls=[];real=httpx.AsyncClient
    def respond(request):
        body=json.loads(request.content);calls.append(body);system=body['messages'][0]['content']
        if '严谨的习题设计者' in system:answer={'questions':proposed(spec)}
        elif '独立解题员' in system:answer={'answers':[{'index':i,'solution':f'INDEPENDENT_{i}','issues':[]} for i in range(3)]}
        elif '习题审查员' in system:answer={'passed':True,'issues':[]}
        elif '批改' in system:answer={'scores':[90]*3,'feedback':['理由与条件均满足']*3,'uncertainties':[]}
        else:answer={'questions':proposed(spec)}
        if body.get('stream'):
            packet={'choices':[{'delta':{'content':j(answer)},'finish_reason':'stop'}]}
            return httpx.Response(200,text='data: '+j(packet)+'\n\ndata: [DONE]\n\n')
        return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':j(answer)},'finish_reason':'stop'}]})
    monkeypatch.setattr(ai,'get_secret',lambda key:'fixture-only')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:real(transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(exercises,'search_exercises',lambda title:asyncio.sleep(0,result=[]))
    return calls


def test_paired_mobile_check_preserves_scope_and_selected_settings(tmp_path,monkeypatch):
    from test_mobile_access import mobile_client,pair
    project,other,source,path,chat,second,foreign,goal,base,_=seed(tmp_path)
    captured=[]
    async def start(value):
        captured.append(value.model_dump());return {'job_id':uid()}
    monkeypatch.setattr(server,'generate',start)
    manager,api=mobile_client();url=f'/api/projects/{project}/learning-goals/{goal["id"]}/check'
    request=payload(goal,chat)|{'reasoning_effort':'high','output_language':'bilingual'}
    with api:
        assert api.get('/learning-check.js').status_code==200
        assert api.get(f'/api/projects/{project}/learning-goals').status_code==401
        assert api.post(url,json=request).status_code==401
        pair(manager,api)
        listed=api.get(f'/api/projects/{project}/learning-goals?conversation_id={chat}')
        assert listed.status_code==200 and listed.json()['items'][0]['id']==goal['id']
        unrelated=api.get(f'/api/projects/{project}/learning-goals?conversation_id={foreign}')
        assert unrelated.status_code==200 and unrelated.json()['focused_goal_id'] is None
        assert [item['id'] for item in unrelated.json()['items']]==[goal['id']]
        assert api.post(url,json=request|{'conversation_id':foreign}).status_code==400
        assert api.post(url,json=request|{'provider':'codex'}).status_code==400
        accepted=api.post(url,json=request)
        assert accepted.status_code==200,accepted.text
        assert len(captured)==1
        saved=captured[0]
        assert saved['project_id']==project and saved['conversation_id']==chat
        assert saved['model']=='route-model' and saved['reasoning_effort']=='high'
        assert saved['output_language']=='bilingual' and saved['explanation_style']=='balanced'
        assert saved['goal_check']['kind']=='new_context' and saved['goal_check']['baseline']['exercise_set_id']==base
        assert api.put(f'/api/projects/{project}/learning-goals/{goal["id"]}',json={}).status_code==403
        api.post('/mobile/logout')
        assert api.get(f'/api/projects/{project}/learning-goals').status_code==401


def test_actual_native_request_export_answer_isolation_and_frozen_task_reference(tmp_path,monkeypatch):
    project,other,source,path,chat,second,foreign,goal,base,_=seed(tmp_path)
    spec=goals.check_spec(goals.get(goal['id'],project),'new_context');calls=native_transport(monkeypatch,spec)
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),second,'user','OTHER_CHAT_PRIVATE_MARKER',now()))
    # Admission and execution are tested separately here; the real background
    # dispatch, pause and paired device are exercised in the Electron fixture.
    monkeypatch.setattr(server,'start_job',lambda ident,coroutine:coroutine.close())
    with TestClient(server.app) as api:
        response=api.post(f'/api/projects/{project}/learning-goals/{goal["id"]}/check',json=payload(goal,chat))
        assert response.status_code==200,response.text
        job_id=response.json()['job_id']
        saved=unj(one('SELECT payload_json FROM jobs WHERE id=?',(job_id,))['payload_json'])
        asyncio.run(server._generate_job(job_id,server.GenerateIn(**saved)))
        for _ in range(220):
            job=api.get('/api/jobs/'+job_id).json()
            if job['status'] in ('completed','failed'):break
            time.sleep(.025)
        assert job['status']=='completed',job.get('error')
        saved=job['payload']['goal_check'];assert saved['kind']=='new_context' and saved['baseline']['exercise_set_id']==base
        assert len(calls)==4 and all('OTHER_CHAT_PRIVATE_MARKER' not in j(body) for body in calls)
        design=calls[0]['messages'][-1]['content']
        assert path.read_text(encoding='utf-8') in design and 'NOT_THE_ORIGINAL' not in design
        assert 'CHECK_0' in design and 'context_change' in design and '难度级别：1/5' in design
        assert design.count('"questions_sha256"')==1, 'The captured reference must not be repeated in the same request'
        assert 'PRIVATE_ANSWER' not in design and 'PRIVATE_FEEDBACK' not in design
        assert any('不只换数字' in body['messages'][-1]['content'] for body in calls)
        artifact=next(a for a in api.get('/api/projects/'+project+'/artifacts').json() if a['kind']=='exercise')
        ident=artifact['metadata']['exercise_set_id'];public=api.get('/api/exercises/'+ident).json()
        assert public['learning_check']['kind']=='new_context' and len(public['questions'])==3
        assert 'SOLUTION_PRIVATE' not in j(public) and 'CHANGE_PRIVATE' not in j(public)
        path_doc=one('SELECT path FROM artifacts WHERE id=?',(artifact['id'],))['path']
        text='\n'.join(p.text for p in Document(path_doc).paragraphs)
        assert 'NEW_0' in text and 'SOLUTION_PRIVATE' not in text and 'CHANGE_PRIVATE' not in text
        assert public['difficulty']==1 and not many("SELECT * FROM artifacts WHERE kind='explanation'")
        # Completed submission releases the separate answer document and its
        # explanation of the changed context, without altering original marks.
        grade=asyncio.run(exercises.grade_submission(ai.DeepSeekClient('route-model'),ident,['完整理由。']*3,recovery_mode='adaptive',used_notes=False))
        assert grade['score']==90
        assert 'CHANGE_PRIVATE_0' in exercises.student_document(ident,include_solutions=True)
        assert one('SELECT score FROM submissions WHERE exercise_set_id=?',(base,))['score']==85
        context,_=goals.context(project,chat,[source]);assert '"question_kind": "new_context"' in context
