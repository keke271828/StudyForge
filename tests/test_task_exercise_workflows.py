import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from studyforge import conversations, exercises, server
from studyforge.ai import complete_json
from studyforge.codex_bridge import CodexBridge
from studyforge.config import artifacts_dir
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid, unj, update_job
from studyforge.exercise_requests import wants_exercises, asks_for_answers
from studyforge.generation_control import active_generations
from studyforge.job_control import active_jobs, remove_job, start_job


PRIVATE = 'PRIVATE_SOLUTION_DO_NOT_PUBLISH'


class Model:
    model = 'same-selected-model'
    effort = None
    def __init__(self, malformed=0):
        self.calls = []
        self.malformed = malformed

    async def complete(self, system, user, **kwargs):
        self.calls.append((system, user, kwargs))
        if '习题设计者' in system:
            if self.malformed:
                self.malformed -= 1
                return '' if self.malformed else '这不是 JSON'
            return j({'questions':[{'question':'说明相关为何不能推出因果。', 'solution':PRIVATE,
                                   'rubric':'完整说明推断条件', 'topic':'因果推断', 'source_url':''}]})
        if '独立解题员' in system:
            return j({'answers':[{'index':0,'solution':PRIVATE,'issues':[]}]})
        if '习题审查员' in system:
            return j({'passed':True,'issues':[]})
        return '# 因果推断\n相关不能推出因果。\n\n## 系统性总结\n推断需要排除共同原因。'


def fixture(tmp_path, monkeypatch, *, only=False, both=False, malformed=0):
    project = create_project('学习项目')
    chat = conversations.create(project['id'],'deepseek','same-selected-model')
    sid = uid(); original = tmp_path/'原资料.txt'
    original.write_text('相关不能推出因果；还需排除共同原因。',encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (sid,project['id'],original.name,'.txt',str(original),'[]','ready',now()))
    model = Model(malformed)
    monkeypatch.setattr(server,'client_for',lambda *a,**kw:model)
    async def no_network(topic): return []
    monkeypatch.setattr(exercises,'search_exercises',no_network)
    value = server.GenerateIn(project_id=project['id'],source_ids=[sid],conversation_id=chat['id'],
        provider='deepseek',model=model.model,format='pdf',only_exercises=only,exercises=both or only,
        review_mode='express',instructions='只出一道因果推断题，不显示答案。')
    return value, model


def run_job(value):
    job = create_job(value.project_id,'generate',value.model_dump())
    asyncio.run(server._generate_job(job,value))
    return job, one('SELECT * FROM jobs WHERE id=?',(job,))


@pytest.mark.parametrize('parallel',[False,True])
def test_exercise_stages_merge_existing_stage_without_duplicate_keyword(tmp_path,monkeypatch,parallel):
    from studyforge.generation_control import GenerationControl
    value,model=fixture(tmp_path,monkeypatch,both=True)
    value.parallel=parallel
    job=create_job(value.project_id,'generate',value.model_dump())
    update_job(job,'queued',0,{'stage':'上次保存的阶段','kept':'保留的数据'})
    control=GenerationControl(job)
    control.stage('恢复后的阶段',1,{'stage':'调用方也传入阶段','parallel':parallel})
    assert unj(one('SELECT result_json FROM jobs WHERE id=?',(job,))['result_json'])=={'stage':'恢复后的阶段','kept':'保留的数据','parallel':parallel}
    asyncio.run(server._generate_job(job,value))
    result=one('SELECT * FROM jobs WHERE id=?',(job,))
    assert result['status']=='completed',result['error']
    assert {a['kind'] for a in many('SELECT * FROM artifacts')}=={'explanation','exercise'}


def test_only_exercises_skips_explanation_and_keeps_answers_private(tmp_path,monkeypatch):
    value, model = fixture(tmp_path,monkeypatch,only=True)
    async def forbidden(*a,**kw): pytest.fail('只出题不应撰写、审查或总结讲解')
    for name in ('generate_explanation','review_explanation','finish_explanation'):
        monkeypatch.setattr(server,name,forbidden)
    job,row = run_job(value)
    assert row['status']=='completed',row['error']
    assert len(model.calls)==4
    files=many('SELECT * FROM artifacts');assert len(files)==1
    assert files[0]['kind']=='exercise' and files[0]['format']=='docx'
    assert files[0]['title']=='因果推断 · 习题（无答案）'
    assert unj(files[0]['metadata_json'])['conversation_id']==value.conversation_id
    from docx import Document
    assert PRIVATE not in '\n'.join(p.text for p in Document(files[0]['path']).paragraphs)
    assert PRIVATE not in str(server.artifacts(value.project_id))
    assert PRIVATE not in str(server.job(job))
    assert PRIVATE not in str(conversations.detail(value.conversation_id,value.project_id))
    assert many('SELECT * FROM lesson_questionnaires')==[]
    set_id=unj(files[0]['metadata_json'])['exercise_set_id']
    assert 'solutions' not in exercises.public_set(set_id,reveal=True)
    class Grader:
        async def complete(self,*a,**kw):return j({'scores':[80],'feedback':['作答完整'],'uncertainties':[]})
    with pytest.raises(ValueError):asyncio.run(exercises.grade_submission(Grader(),set_id,[' ']))
    assert 'solutions' not in exercises.public_set(set_id,reveal=True)
    asyncio.run(exercises.grade_submission(Grader(),set_id,['共同原因可能同时导致二者变化。']))
    assert exercises.public_set(set_id,reveal=True)['solutions'][0]['solution']==PRIVATE


def test_topic_only_without_original_file_generates_real_questions(tmp_path,monkeypatch):
    value,model=fixture(tmp_path,monkeypatch,only=True)
    value.source_ids=[]
    _,row=run_job(value)
    assert row['status']=='completed',row['error']
    assert many('SELECT kind FROM artifacts')==[{'kind':'exercise'}]
    assert '学生未提供原资料' in model.calls[0][1]


@pytest.mark.parametrize('malformed',[1,2])
def test_both_generation_repairs_json_once_and_preserves_finished_lecture(tmp_path,monkeypatch,malformed):
    value, model=fixture(tmp_path,monkeypatch,both=True,malformed=malformed)
    job,row=run_job(value)
    assert row['status']==('completed' if malformed==1 else 'failed'),row['error']
    assert len([c for c in model.calls if '习题设计者' in c[0]])==2
    kinds=[f['kind'] for f in many('SELECT * FROM artifacts')]
    assert 'explanation' in kinds and ('exercise' in kinds)==(malformed==1)
    assert len(many('SELECT * FROM exercise_sets'))==int(malformed==1)
    assert PRIVATE not in str(conversations.detail(value.conversation_id,value.project_id))
    if malformed==2:
        assert 'JSON' in row['error'] and 'JSONDecodeError' not in row['error']


def test_empty_or_wrong_json_repair_is_bounded_and_validates_shape():
    class Bad:
        calls=0
        async def complete(self,*a,**kw):self.calls+=1;return '{}'
    model=Bad()
    def validate(value):
        if 'questions' not in value:raise ValueError('缺少questions')
    with pytest.raises(RuntimeError):asyncio.run(complete_json(model,'任务','原文',validate=validate))
    assert model.calls==2


def test_cancel_running_and_paused_work_stops_publication_and_releases_scope(tmp_path,monkeypatch):
    value,model=fixture(tmp_path,monkeypatch)
    async def run():
        entered=asyncio.Event();closed=asyncio.Event()
        async def waiting(*a,**kw):
            entered.set()
            try:await asyncio.Event().wait()
            finally:closed.set()
        model.complete=waiting
        job=create_job(value.project_id,'generate',value.model_dump())
        task=start_job(job,server._generate_job(job,value))
        await asyncio.wait_for(entered.wait(),3)
        await server.pause_generation(job)
        assert (await remove_job(job))['status']=='cancelled'
        assert task.cancelled() and closed.is_set()
        assert job not in active_generations and job not in active_jobs
        assert server.jobs(value.project_id)==[] and many('SELECT * FROM artifacts')==[]
        update_job(job,'completed',100,{'stage':'不应恢复'})
        assert one('SELECT status FROM jobs WHERE id=?',(job,))['status']=='cancelled'
        with pytest.raises(Exception):await server.resume_generation(job)
        later=create_job(value.project_id,'generate',{})
        update_job(later,'paused',12)
        assert (await remove_job(later))['status']=='cancelled'
        return job
    asyncio.run(run())


def test_history_delete_preserves_project_files_and_origin_without_restoring_messages(tmp_path,monkeypatch):
    value,model=fixture(tmp_path,monkeypatch,only=True)
    _,row=run_job(value);assert row['status']=='completed'
    other=conversations.create(value.project_id,'deepseek','same-selected-model')
    execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),other['id'],'user','保留其他对话',now()))
    conversations.update(value.conversation_id,value.project_id,{'title':'可重命名的来源对话','draft':'应删除的草稿'})
    api=TestClient(server.app)
    response=api.delete('/api/conversations/'+value.conversation_id,params={'project_id':value.project_id})
    assert response.status_code==200,response.text
    assert many('SELECT * FROM messages WHERE conversation_id=?',(value.conversation_id,))==[]
    assert conversations.detail(other['id'],value.project_id)['messages'][0]['content']=='保留其他对话'
    assert value.conversation_id not in [c['id'] for c in conversations.list_project(value.project_id)['conversations']]
    assert api.get('/api/conversations/'+value.conversation_id,params={'project_id':value.project_id}).status_code==404
    files=server.artifacts(value.project_id);assert len(files)==1
    assert files[0]['origin']=={'conversation_id':value.conversation_id,'title':'可重命名的来源对话','deleted':True}
    assert len(many('SELECT * FROM sources'))>=1
    conversations.backfill(value.project_id)
    assert value.conversation_id not in [c['id'] for c in conversations.list_project(value.project_id)['conversations']]


def test_artifact_origin_uses_job_fallback_and_rejects_cross_project():
    a,b=create_project('A'),create_project('B');chat=conversations.create(a['id'],'deepseek','same')
    job=create_job(a['id'],'generate',{'conversation_id':chat['id']})
    path=artifacts_dir()/'artifact.txt';path.write_text('内容',encoding='utf-8')
    server.add_artifact(a['id'],[],'explanation','txt','有来源',path,{'generation_job_id':job})
    server.add_artifact(b['id'],[],'explanation','txt','错项目',path,{'conversation_id':chat['id']})
    conversations.update(chat['id'],a['id'],{'title':'新标题'})
    assert server.artifacts(a['id'])[0]['origin']['title']=='新标题'
    assert server.artifacts(b['id'])[0]['origin'] is None


@pytest.mark.parametrize('text,expected', [('给我出两道题，不要答案',True),('出题并给答案',True),
    ('不要出题，只讲解',False),('指出题目有哪些错误',False),('如何出题比较好',False),('quiz me',True)])
def test_explicit_exercise_intent(text,expected):assert wants_exercises(text) is expected


def test_pending_answer_guard_allows_other_teaching():
    assert asks_for_answers('给我这道题的解析')
    assert asks_for_answers('第1题怎么做')
    assert not asks_for_answers('先不要给答案，我说一下思路')
    assert not asks_for_answers('解析这篇哲学文章')


def test_chat_exercise_requests_use_private_pipeline_and_followup_does_not_reveal_answers(tmp_path,monkeypatch):
    value,model=fixture(tmp_path,monkeypatch,only=True)
    class Tutor:
        def __init__(self,model=None,**kwargs):self.model=model or 'same-selected-model'
        async def agent_stream(self,*a,**kw):
            pytest.fail('出题和未批改题目的答案请求不能走普通公开模型回复')
            yield 'final','不可达'
    monkeypatch.setattr(server,'DeepSeekClient',Tutor)
    async def consume(text):
        response=await server._chat_response(server.ChatIn(project_id=value.project_id,conversation_id=value.conversation_id,
            provider='deepseek',model=model.model,source_ids=value.source_ids,text=text))
        output=[json.loads(line) async for line in response.body_iterator]
        for event in output:
            if event['type']=='job':
                task=active_jobs.get(event['value'])
                if task:await task
        return output
    first=asyncio.run(consume('给我出两道题，并把答案给我'))
    job=next(event['value'] for event in first if event['type']=='job')
    assert server.job(job)['status']=='completed'
    assert len(model.calls)==4 and PRIVATE not in j(first)
    second=asyncio.run(consume('给我这道题的答案与解析'))
    assert '暂不开放' in j(second) and PRIVATE not in j(second)
    assert len(model.calls)==4


def test_selected_question_file_keeps_answer_gate_in_another_chat(tmp_path,monkeypatch):
    value,model=fixture(tmp_path,monkeypatch,only=True);run_job(value)
    from studyforge.exercise_requests import pending_sets
    linked=one('SELECT source_id FROM artifact_sources')
    other=conversations.create(value.project_id,'deepseek','same-selected-model')
    assert pending_sets(other['id'])=={}
    assert len(pending_sets(other['id'],[linked['source_id']]))==1


def test_only_exercise_endpoint_accepts_topic_without_sources_but_rejects_empty_range(monkeypatch):
    project=create_project('按话题出题');captured=[]
    async def worker(job,value):captured.append((job,value))
    monkeypatch.setattr(server,'_generate_job',worker)
    async def run():
        result=await server.generate(server.GenerateIn(project_id=project['id'],source_ids=[],provider='deepseek',
            only_exercises=True,instructions='给我一道基础逻辑题'))
        await asyncio.sleep(0)
        return result
    result=asyncio.run(run());assert captured[0][1].only_exercises and captured[0][1].exercises
    assert server.job(result['job_id'])['payload']['only_exercises']
    with pytest.raises(Exception,match='请选择资料'):
        asyncio.run(server.generate(server.GenerateIn(project_id=project['id'],source_ids=[],provider='deepseek',only_exercises=True)))


def test_codex_cancellation_closes_owned_server_before_releasing_lock(monkeypatch):
    bridge=CodexBridge();calls=[]
    async def run():
        entered=asyncio.Event()
        async def start():pass
        async def request(method,params):
            if method=='thread/start':return {'thread':{'id':'local-ephemeral','ephemeral':True}}
            entered.set();return {}
        async def close():calls.append('closed')
        monkeypatch.setattr(bridge,'start',start);monkeypatch.setattr(bridge,'request',request);monkeypatch.setattr(bridge,'close',close)
        async def consume():
            async for _ in bridge.stream_turn('等待模型'):pass
        task=asyncio.create_task(consume());await entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert calls==['closed'] and not bridge.turn_lock.locked()
    asyncio.run(run())
