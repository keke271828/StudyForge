"""Learning plans change actual requests; grades remain bounded, scoped evidence."""
import asyncio
import hashlib
import json

import httpx
import pytest
from docx import Document
from fastapi.testclient import TestClient

from studyforge import ai, conversations, exercises, learning_goals as goals, server
from studyforge.db import create_project, execute, j, many, now, one, uid, unj
from studyforge.learning import source_fingerprint


def case(tmp_path):
    ai.save_settings({'chat_provider':'deepseek','deepseek_model':'route-model','agent_tools_enabled':False,
                     'background_learning_enabled':False,'agent_network_enabled':False})
    project=create_project('社会科学路线');other=create_project('独立物理项目')
    path=tmp_path/'论证.txt';path.write_text('描述性判断说明事实是什么。规范性判断讨论应该怎样。仅凭一种做法很普遍，不能推出它应当被接受；需要补充评价原则。',encoding='utf-8')
    source=uid();execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
        (source,project['id'],path.name,'.txt',str(path),j([{'locator':'旧预览','text':'NOT_THE_ORIGINAL'}]),'ready',now()))
    chat=conversations.create(project['id'],'deepseek','route-model');second=conversations.create(project['id'],'deepseek','route-model')
    foreign=conversations.create(other['id'],'deepseek','route-model')
    return project['id'],other['id'],source,path,chat['id'],second['id'],foreign['id']


def plan(project,source,name='描述与规范',**overrides):
    return goals.save(project,dict(name=name,domain='哲学',intent='deep',source_ids=[source])|overrides)


def edited(goal,**overrides):
    data={k:goal[k] for k in ('name','domain','intent','criterion','source_ids','paused','version')}
    return (data|{'prerequisite_ids':[x['id'] for x in goal['prerequisites']]})|overrides


def questions():
    return [{'index':i,'question':f'CHECK_{i}：解释论证并说明条件。','topic':'描述与规范（哲学）'} for i in range(3)]


def linked_check(goal,project,**spec_override):
    ident=uid();execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
        (ident,project,j(goal['source_ids']),'三题检查',j(questions()),j([{'index':i,'solution':f'PRIVATE_{i}','rubric':'完整解释100分'} for i in range(3)]),1,'assigned',now()))
    goals.register_check(ident,project,dict(goals.check_spec(goals.get(goal['id'],project)),**spec_override))
    return ident


def scored(set_id,scores,*,pending=False,notes=False,hints=None,delayed=False,created=None):
    ident=uid();grade={'scores':scores,'feedback':['PRIVATE_FEEDBACK']*len(scores),'grading_verification_required':pending,
        'practice_context':{'used_notes':notes,'hint_levels':hints or {},'is_review':delayed,
                            'timing':[{'question_index':i,'delay_hours':25 if delayed else 0,'same_question_verified':True} for i in range(len(scores))]}}
    execute('INSERT INTO submissions VALUES (?,?,?,?,?,?,?)',(ident,set_id,j(['PRIVATE_ANSWER']*len(scores)),j(grade),0 if pending else sum(scores)/len(scores),'{}',created or now()))
    execute("UPDATE exercise_sets SET status='completed' WHERE id=?",(set_id,))
    return ident


def review_set(project,origin):
    ident=uid();execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
        (ident,project,'[]','延迟检查',j(questions()),j([{'index':i,'solution':f'PRIVATE_{i}','rubric':'完整解释100分'} for i in range(3)]),1,'assigned',now()))
    execute('INSERT INTO review_sessions VALUES (?,?,?,?)',(ident,j([{'review_index':i,'origin_set_id':origin,'question_index':i} for i in range(3)]),now(),None))
    return ident


def knowledge_map(project,source,path):
    reading,ident=uid(),uid();sha=source_fingerprint([{'id':source,'read_manifest':{'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}}])
    execute('INSERT INTO reading_sessions VALUES (?,?,?,?,?,?,?,?,?,?)',(reading,project,j([source]),sha,'deepseek','route-model',None,'[]','[]',now()))
    graph={'concepts':[{'id':'descriptive','name':'判断','domain':'哲学','basis':'source','evidence':[{'source_id':source,'locator':'第1行','quote':'描述性判断'}]},
                       {'id':'normative','name':'判断','domain':'社会科学','basis':'source','evidence':[{'source_id':source,'locator':'第1行','quote':'规范性判断'}]}],
           'relations':[{'from_id':'descriptive','to_id':'normative','kind':'prerequisite','reason':'教学建议：先区分事实与评价','basis':'teaching'}]}
    execute('INSERT INTO knowledge_maps VALUES (?,?,?,?,?,?,?,?,?,?)',(ident,reading,project,1,'deepseek','route-model',None,sha,j(graph),now()))
    return ident


def test_goal_route_scopes_focus_and_reads_no_other_conversation(tmp_path):
    project,other,source,_,chat,second,foreign=case(tmp_path);goal=plan(project,source)
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),second,'user','DO_NOT_IMPORT_OTHER_CHAT',now()))
    goals.focus(project,chat,goal['id'])
    context,_=goals.context(project,chat,[])
    assert goal['criterion'] in context and '"all_goal_sources_selected": false' in context
    assert 'DO_NOT_IMPORT_OTHER_CHAT' not in context and 'NOT_THE_ORIGINAL' not in context
    assert goals.context(project,second,[source])==('',None)
    assert goals.context(other,foreign,[source])==('',None)
    assert conversations.detail(chat,project)['learning_goal']['id']==goal['id']
    assert conversations.detail(second,project)['source_ids']==[]
    assert conversations.detail(second,project)['learning_goal'] is None
    assert goals.list_goals(other,foreign)['items']==[]
    for scope,dialog,ident in [(other,foreign,goal['id']),(project,foreign,goal['id'])]:
        with pytest.raises(ValueError):goals.focus(scope,dialog,ident)


def test_optimistic_updates_and_prerequisite_cycles_are_transactional(tmp_path):
    project,other,source,_,*_=case(tmp_path)
    first=plan(project,source,'必要术语');second=plan(project,source,'方法理由',prerequisite_ids=[first['id']])
    api=TestClient(server.app);base=f'/api/projects/{project}/learning-goals/{first["id"]}'
    rejected=api.put(base,json=edited(first,name='不该写入的名称',prerequisite_ids=[second['id']]))
    assert rejected.status_code==400 and '循环' in rejected.text
    assert goals.get(first['id'],project)['name']=='必要术语'
    result=api.put(base,json=edited(first,name='基础术语'));assert result.status_code==200,result.text
    assert api.put(base,json=edited(first,name='陈旧覆盖')).status_code==409
    assert api.delete(base,params={'version':first['version']}).status_code==409
    assert api.put(f'/api/projects/{other}/learning-goals/{first["id"]}',json=edited(first)).status_code==400


def test_pause_preserves_missing_materials_and_evidence_scope(tmp_path):
    project,_,source,path,*_=case(tmp_path);goal=plan(project,source);before=goals.fingerprint(goals.get(goal['id'],project))
    path.rename(path.with_suffix('.bak'))
    api=TestClient(server.app);base=f'/api/projects/{project}/learning-goals/{goal["id"]}'
    paused=api.patch(base,json={'paused':True,'version':goal['version']});assert paused.status_code==200,paused.text
    assert paused.json()['source_ids']==[source] and not paused.json()['sources'][0]['available']
    path.with_suffix('.bak').rename(path)
    assert goals.fingerprint(goals.get(goal['id'],project))==before
    assert api.patch(base,json={'paused':False,'version':goal['version']}).status_code==409


def test_import_is_optional_source_bound_deduplicated_and_keeps_domains_and_basis(tmp_path):
    project,other,source,path,*_=case(tmp_path);ident=knowledge_map(project,source,path)
    result=goals.import_concepts(project,ident,['descriptive','normative'])
    assert result['created']==2 and goals.import_concepts(project,ident,['descriptive','normative'])['created']==0
    items=goals.list_goals(project)['items'];assert {g['domain'] for g in items}=={'哲学','社会科学'}
    assert all(g['intent']=='explore' and not any(e['latest'] for e in g['evidence']) for g in items)
    target=next(g for g in items if g['prerequisites']);assert target['prerequisites'][0]['basis']=='teaching'
    revised=goals.save(project,edited(target,intent='deep'),target['id'])
    assert revised['prerequisites'][0]['basis']=='teaching'
    with pytest.raises(ValueError):goals.import_concepts(other,ident,['descriptive'])
    path.write_text('原文已经改变',encoding='utf-8')
    with pytest.raises(ValueError,match='变更'):goals.import_concepts(project,ident,['descriptive'])
    assert many('SELECT * FROM mastery')==[]


@pytest.mark.parametrize('scores,notes,hints,action',[
    ([79,90,90],False,{},'repair'),([80,80,80],False,{},'review'),
    ([95,95,95],None,{},'unaided'),([95,95,95],False,{'1':1},'unaided')])
def test_recommendations_use_observed_dimensions_and_assistance_not_reading_feeling(tmp_path,scores,notes,hints,action):
    project,_,source,_,*_=case(tmp_path);goal=plan(project,source);ident=linked_check(goal,project)
    scored(ident,scores,notes=notes,hints=hints)
    current=goals.public_goal(goals.get(goal['id'],project))
    assert current['recommendation']['action']==action
    assert all(e['record_count']==1 for e in current['evidence'])
    assert 'PRIVATE_ANSWER' not in j(current) and 'PRIVATE_FEEDBACK' not in j(current) and 'PRIVATE_0' not in j(current)


def test_pending_scores_never_become_ability_and_removed_profile_evidence_stays_removed(tmp_path):
    project,_,source,_,*_=case(tmp_path);goal=plan(project,source);ident=linked_check(goal,project)
    submit=scored(ident,[100,100,100],pending=True)
    result=goals.public_goal(goals.get(goal['id'],project))
    assert result['recommendation']['action']=='recheck' and all(e['latest']['score'] is None for e in result['evidence'])
    assert all(not e['meets_threshold'] for e in result['evidence'])
    execute('INSERT INTO learning_events(event_key,project_id,kind,payload_json,created_at,updated_at) VALUES (?,?,?,?,?,?)',
                      (f'quiz:{submit}:0',project,'quiz','{}',now(),now()))
    event=one('SELECT id FROM learning_events WHERE event_key=?',(f'quiz:{submit}:0',))['id']
    execute('INSERT INTO learning_event_profile_blocks VALUES (?,?)',(event,now()))
    result=goals.public_goal(goals.get(goal['id'],project));assert result['evidence'][0]['latest'] is None


def test_changed_goal_or_original_keeps_old_grade_but_does_not_reuse_it(tmp_path):
    project,_,source,path,*_=case(tmp_path);goal=plan(project,source);ident=linked_check(goal,project);scored(ident,[90]*3)
    current=goals.public_goal(goals.get(goal['id'],project));assert current['evidence'][0]['meets_threshold']
    goal=goals.save(project,edited(current,intent='research'),goal['id'])
    assert goal['evidence'][0]['meets_threshold'],'Changing intent alone must preserve the same evidence'
    path.write_text(path.read_text(encoding='utf-8')+'补充了新的评价条件。',encoding='utf-8')
    current=goals.public_goal(goals.get(goal['id'],project))
    assert current['outdated_record_count']==3 and all(e['latest'] is None for e in current['evidence'])
    assert not current['checks'][0]['current_scope'] and len(many('SELECT * FROM submissions'))==1


def test_failed_or_assisted_delayed_reviews_are_not_retention_evidence_and_foreign_reviews_excluded(tmp_path):
    project,other,source,_,*_=case(tmp_path);goal=plan(project,source);ident=linked_check(goal,project)
    scored(ident,[90]*3,created='2026-10-01T00:00:00+00:00')
    review=review_set(project,ident);scored(review,[20]*3,delayed=True,created='2026-10-03T00:00:00+00:00')
    new_check=linked_check(goal,project);scored(new_check,[100]*3,created='2026-10-04T00:00:00+00:00')
    foreign=review_set(other,ident);scored(foreign,[100]*3,delayed=True,created='2026-10-05T00:00:00+00:00')
    result=goals.public_goal(goals.get(goal['id'],project));assert result['recommendation']['action']=='review'
    assert all(e['record_count']==3 for e in result['evidence'])
    second=review_set(project,ident);scored(second,[90]*3,notes=True,delayed=True,created='2026-10-06T00:00:00+00:00')
    third=linked_check(goal,project);scored(third,[95]*3,created='2026-10-07T00:00:00+00:00')
    assert goals.public_goal(goals.get(goal['id'],project))['recommendation']['action']=='review'
    scored(second,[90]*3,delayed=True,created='2026-10-08T00:00:00+00:00')
    assert goals.public_goal(goals.get(goal['id'],project))['recommendation']['action']=='new_context', 'Repeating the original problems is not a fresh-context check'


def test_deleting_plan_preserves_questions_grades_sources_and_clears_focus(tmp_path):
    project,_,source,path,chat,*_=case(tmp_path);goal=plan(project,source);goals.focus(project,chat,goal['id'])
    ident=linked_check(goal,project);scored(ident,[90]*3);spec=goals.check_spec(goals.get(goal['id'],project))
    goals.remove(goal['id'],project,goal['version']);goals.register_check(ident,project,spec)
    assert goals.focused(project,chat) is None and one('SELECT id FROM exercise_sets WHERE id=?',(ident,))
    assert len(many('SELECT * FROM submissions'))==1 and path.exists() and one('SELECT id FROM sources WHERE id=?',(source,))


def test_new_unsubmitted_check_does_not_block_review_of_previous_confirmed_current_scope(tmp_path):
    project,_,source,_,*_=case(tmp_path);goal=plan(project,source);completed=linked_check(goal,project);scored(completed,[90]*3)
    linked_check(goal,project)  # An unfinished new check is not the review baseline.
    api=TestClient(server.app);response=api.post(f'/api/projects/{project}/learning-goals/{goal["id"]}/review')
    assert response.status_code==200,response.text
    assert {r['origin_set_id'] for r in many('SELECT * FROM review_items')}=={completed}


def test_review_cannot_use_pending_or_old_scope_grades(tmp_path):
    project,_,source,_,*_=case(tmp_path);goal=plan(project,source);ident=linked_check(goal,project);scored(ident,[100]*3,pending=True)
    api=TestClient(server.app);url=f'/api/projects/{project}/learning-goals/{goal["id"]}/review'
    assert api.post(url).status_code==400 and many('SELECT * FROM review_items')==[]
    scored(ident,[100]*3)
    goals.save(project,edited(goal,criterion='不同的目标范围'),goal['id'])
    assert api.post(url).status_code==400 and many('SELECT * FROM review_items')==[]


def test_project_recycle_and_purge_include_new_plans_without_leaking_other_goals(tmp_path):
    project,other,source,path,chat,*_=case(tmp_path);goal=plan(project,source);goals.focus(project,chat,goal['id'])
    ident=linked_check(goal,project);scored(ident,[90]*3)
    untouched=goals.save(other,{'name':'力学','domain':'物理','intent':'explore'})
    api=TestClient(server.app);assert api.delete(f'/api/projects/{project}').status_code==200
    assert api.get(f'/api/projects/{project}/learning-goals').status_code==404
    response=api.request('DELETE',f'/api/recycle-bin/projects/{project}',json={'confirmation_name':'社会科学路线'})
    assert response.status_code==200,response.text
    assert goals.get(untouched['id'],other) and path.exists()
    assert not one('SELECT * FROM learning_goal_checks WHERE exercise_set_id=?',(ident,))


def install_model(monkeypatch,topic):
    monkeypatch.setattr(ai,'get_secret',lambda key:'fixture-key');monkeypatch.setattr(server,'get_secret',ai.get_secret)
    async def search(*a):return []
    monkeypatch.setattr(exercises,'search_exercises',search)
    native=httpx.AsyncClient;calls=[]
    def reply(request):
        body=json.loads(request.content);calls.append(body);system=body['messages'][0]['content']
        if '独立解题员' in system:result={'answers':[{'index':i,'solution':'规范结论需评价原则；普遍不等于应该','issues':[]} for i in range(3)]}
        elif '习题审查员' in system:result={'passed':True,'issues':[]}
        elif '习题设计者' in system:result={'questions':[{'question':f'第{i+1}题：请分析事实和评价之间的推理条件。','topic':topic,'assessment_dimension':dim,
            'solution':'PRIVATE_REFERENCE：事实不能独立推出规范结论。','rubric':'区分事实和评价50分，解释缺少的前提50分','source_url':''} for i,dim in enumerate(goals.DIMENSIONS)]}
        else:result=None
        text=j(result) if result else '# 描述与规范\n事实判断说明是什么，规范判断讨论应该怎样。从前者到后者需要评价原则。\n\n## 系统性总结\n普遍程度不能独立决定某做法是否应该被接受，缺少前提不意味着结论已经被否定。'
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':text},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:native(transport=httpx.MockTransport(reply)))
    return calls


def test_real_generation_pipeline_pins_goal_and_produces_docx_without_exposing_answers(tmp_path,monkeypatch):
    project,_,source,path,chat,second,*_=case(tmp_path);goal=plan(project,source);other=plan(project,source,'另一目标')
    goals.focus(project,chat,other['id']);calls=install_model(monkeypatch,'描述与规范（哲学）')
    monkeypatch.setattr(server,'start_job',lambda ident,coroutine:coroutine.close())
    api=TestClient(server.app);base=f'/api/projects/{project}/learning-goals/{goal["id"]}'
    payload={'version':goal['version'],'conversation_id':chat,'provider':'deepseek','model':'route-model'}
    launched=api.post(base+'/check',json=payload);assert launched.status_code==200,launched.text
    job_id=launched.json()['job_id'];snapshot=unj(one('SELECT payload_json FROM jobs WHERE id=?',(job_id,))['payload_json'])
    assert snapshot['only_exercises'] and snapshot['goal_check']['goal_id']==goal['id']
    assert goal['criterion'] in snapshot['resolved_requirements'] and '另一目标' not in snapshot['learning_goal_context']
    assert api.post(base+'/check',json=payload).json()['job_id']==job_id
    # New chat messages/goal edits must not alter the authorized task snapshot.
    revised=goals.save(project,edited(goal,criterion='新的目标范围'),goal['id'])
    assert api.post(base+'/check',json=payload).status_code==409
    asyncio.run(server._generate_job(job_id,server.GenerateIn(**snapshot)))
    job=one('SELECT * FROM jobs WHERE id=?',(job_id,));assert job['status']=='completed',job['error']
    assert len(calls)==4 and path.read_text(encoding='utf-8') in j(calls[0]) and 'NOT_THE_ORIGINAL' not in j(calls)
    linked=one('SELECT * FROM learning_goal_checks');assert linked['goal_id']==goal['id']
    public=api.get('/api/exercises/'+linked['exercise_set_id']).json();assert len(public['questions'])==3
    assert 'PRIVATE_REFERENCE' not in j(public) and public['learning_check']['goal_id']==goal['id']
    artifact=one("SELECT * FROM artifacts WHERE kind='exercise'")
    assert artifact['format']=='docx' and 'PRIVATE_REFERENCE' not in '\n'.join(p.text for p in Document(artifact['path']).paragraphs)
    assert revised['version']!=goal['version'] and not goals.public_goal(goals.get(goal['id'],project))['checks'][0]['current_scope']
    assert conversations.detail(second,project)['source_ids']==[]


def test_checkpoint_schema_requires_real_three_dimensions_and_private_solutions(tmp_path,monkeypatch):
    project,_,source,_,*_=case(tmp_path);goal=plan(project,source);spec=goals.check_spec(goals.get(goal['id'],project))
    async def search(*a):return []
    monkeypatch.setattr(exercises,'search_exercises',search)
    class Invalid:
        calls=0
        async def complete(self,*args,**kwargs):
            self.calls+=1
            return j({'questions':[{'question':'省略了题意条件','solution':'不可发布','rubric':'100','topic':spec['profile_topic']}]*3})
    client=Invalid()
    with pytest.raises(RuntimeError):asyncio.run(exercises.generate_set(client,project,[source],'原文','理解检查',check_spec=spec))
    assert client.calls==2 and many('SELECT * FROM exercise_sets')==[]


@pytest.mark.parametrize('role',['tutor','lecture'])
def test_selected_goal_reaches_actual_tutor_and_lecture_requests_without_implicit_quiz(tmp_path,monkeypatch,role):
    project,_,source,path,chat,second,*_=case(tmp_path);goal=plan(project,source)
    goals.focus(project,chat,goal['id']);calls=install_model(monkeypatch,'描述与规范（哲学）')
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),second,'user','NO_OTHER_DIALOGUE',now()))
    api=TestClient(server.app)
    body={'project_id':project,'conversation_id':chat,'source_ids':[source],'provider':'deepseek','model':'route-model'}
    if role=='tutor':
        response=api.post('/api/chat/stream',json=body|{'text':'只用当前原资料和目标，解释核心理由，不出题。'})
        assert response.status_code==200 and '"error"' not in response.text,response.text
    else:
        monkeypatch.setattr(server,'start_job',lambda ident,coroutine:coroutine.close())
        response=api.post('/api/generate',json=body|{'instructions':'只用当前原资料和目标，解释核心理由，不出题。','review_mode':'express'})
        assert response.status_code==200,response.text
        job_id=response.json()['job_id'];value=server.GenerateIn(**unj(one('SELECT payload_json FROM jobs WHERE id=?',(job_id,))['payload_json']))
        asyncio.run(server._generate_job(job_id,value))
        job=one('SELECT * FROM jobs WHERE id=?',(job_id,));assert job['status']=='completed',job['error']
        assert unj(one("SELECT metadata_json FROM artifacts WHERE kind='explanation'")['metadata_json'])['learning_goal_id']==goal['id']
    prompt=j(calls)
    assert goal['criterion'] in prompt and path.read_text(encoding='utf-8') in prompt
    assert 'NO_OTHER_DIALOGUE' not in prompt and 'NOT_THE_ORIGINAL' not in prompt
    assert len(calls)==1 and many('SELECT * FROM exercise_sets')==[]
