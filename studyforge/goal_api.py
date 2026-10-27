"""Local learning-route controls; generation uses the existing task pipeline."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import learning_goals as goals
from .db import many, one, unj
from .teaching_styles import ExplanationStyle, OutputLanguage

router=APIRouter()


class GoalIn(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True,extra='forbid')
    name:str=Field(min_length=1,max_length=120)
    domain:str=Field(default='',max_length=80)
    intent:Literal['explore','deep','research']='explore'
    criterion:str=Field(default='',max_length=1200)
    source_ids:list[str]=Field(default_factory=list,max_length=100)
    prerequisite_ids:list[str]=Field(default_factory=list,max_length=20)
    paused:bool=False
    version:int|None=Field(default=None,ge=1)


class FocusIn(BaseModel):
    goal_id:str|None=None


class PauseIn(BaseModel):
    paused:bool
    version:int=Field(ge=1)


class ImportIn(BaseModel):
    map_id:str
    concept_ids:list[str]=Field(min_length=1,max_length=120)


class CheckIn(BaseModel):
    version:int=Field(ge=1)
    conversation_id:str
    provider:str
    model:str|None=Field(default=None,max_length=120)
    reasoning_effort:str|None=Field(default=None,max_length=16)
    explanation_style:ExplanationStyle='clear'
    output_language:OutputLanguage='zh'
    kind:Literal['standard','new_context']='standard'


def fail(exc):
    raise HTTPException(409 if isinstance(exc,goals.GoalConflict) else 400,str(exc)) from exc


@router.get('/api/projects/{project_id}/learning-goals')
def listing(project_id:str,conversation_id:str|None=None):
    try:return goals.list_goals(project_id,conversation_id)
    except ValueError as exc:fail(exc)


@router.post('/api/projects/{project_id}/learning-goals')
def create(project_id:str,value:GoalIn):
    try:return goals.save(project_id,value.model_dump())
    except ValueError as exc:fail(exc)


@router.put('/api/projects/{project_id}/learning-goals/{goal_id}')
def update(project_id:str,goal_id:str,value:GoalIn):
    try:return goals.save(project_id,value.model_dump(),goal_id)
    except ValueError as exc:fail(exc)


@router.delete('/api/projects/{project_id}/learning-goals/{goal_id}')
def remove(project_id:str,goal_id:str,version:int=Query(ge=1)):
    try:return goals.remove(goal_id,project_id,version)
    except ValueError as exc:fail(exc)


@router.patch('/api/projects/{project_id}/learning-goals/{goal_id}')
def pause(project_id:str,goal_id:str,value:PauseIn):
    try:return goals.set_paused(goal_id,project_id,value.paused,value.version)
    except ValueError as exc:fail(exc)


@router.put('/api/conversations/{conversation_id}/learning-goal')
def focus(conversation_id:str,project_id:str,value:FocusIn):
    try:return goals.focus(project_id,conversation_id,value.goal_id)
    except ValueError as exc:fail(exc)


@router.post('/api/projects/{project_id}/learning-goals/import')
def import_nodes(project_id:str,value:ImportIn):
    try:return goals.import_concepts(project_id,value.map_id,value.concept_ids)
    except ValueError as exc:fail(exc)


@router.post('/api/projects/{project_id}/learning-goals/{goal_id}/check')
async def check(project_id:str,goal_id:str,value:CheckIn):
    from .server import GenerateIn,generate
    try:
        row=goals.get(goal_id,project_id)
        if row['version']!=value.version:raise goals.GoalConflict('目标已更新，请刷新后再检查')
        if row['paused']:raise ValueError('请先恢复这项目标')
        public=goals.public_goal(row)
        if not public['sources'] or any(not s['available'] for s in public['sources']):raise ValueError('先为目标关联可读取的原资料，再进行理解检查')
        chat=one('SELECT provider FROM conversations WHERE id=? AND project_id=?',(value.conversation_id,project_id))
        if not chat or chat['provider']!=value.provider:raise ValueError('请选择当前项目的对话及相同AI服务')
        requested_spec=goals.check_spec(row,value.kind)
        # Repeated UI actions open the already-running check, including paused work.
        for job in many("SELECT id,payload_json FROM jobs WHERE project_id=? AND kind='generate' AND status IN ('queued','waiting','running','pausing','paused') ORDER BY created_at DESC",(project_id,)):
            payload=unj(job['payload_json'],{});spec=payload.get('goal_check') or {}
            same_baseline=value.kind!='new_context' or (spec.get('baseline') or {}).get('exercise_set_id')==requested_spec['baseline']['exercise_set_id']
            if spec.get('goal_id')==goal_id and spec.get('fingerprint')==requested_spec['fingerprint'] and spec.get('kind','standard')==value.kind and same_baseline and payload.get('conversation_id')==value.conversation_id:
                return {'job_id':job['id'],'reused':True,'goal_id':goal_id}
        goals.focus(project_id,value.conversation_id,goal_id)
        request=GenerateIn(project_id=project_id,source_ids=public['source_ids'],conversation_id=value.conversation_id,
            provider=value.provider,model=value.model,reasoning_effort=value.reasoning_effort,
            explanation_style=value.explanation_style,output_language=value.output_language,only_exercises=True,
            exercise_format='docx',goal_check=requested_spec,
            instructions='请为学习目标《'+row['name']+'》生成'+goals.CHECK_KINDS[value.kind]+'，仅出题，不同步生成讲解。')
        return await generate(request)
    except ValueError as exc:fail(exc)


@router.post('/api/projects/{project_id}/learning-goals/{goal_id}/review')
def review(project_id:str,goal_id:str,interval_days:int=Query(default=3,ge=1,le=90)):
    from .practice import schedule_review
    try:
        row=goals.get(goal_id,project_id)
        latest=goals.reviewable_check(row)
        if not latest:raise ValueError('请先完整提交并确认当前目标范围的理解检查成绩，再安排复习')
        return schedule_review(latest,interval_days)
    except ValueError as exc:fail(exc)
