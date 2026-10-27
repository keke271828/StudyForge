"""Actual desktop/paired HTTPS speech controls; explicit fixture device checks."""
import asyncio
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(ROOT/'build'/sys.argv[1]/'unused-semantic-model')
from scripts import smoke_task_timing_ui as parent
from studyforge import asr_backend,task_timing
from studyforge.db import execute,now,uid
from studyforge.scheduling import execution_scope

fixture=parent.fixture.fixture
checks=[]
asr_backend.gpu_count=lambda:1
def choose(model,device):
    checks.append(dict(model=model,device=device))
    return ('cuda','') if device=='cuda' else ('cpu','测试回退说明：GPU 自检未通过，保留同一 small 模型')
asr_backend.choose_device=choose


@fixture.server.app.get('/__asr_test__/checks')
def called():return dict(checks=checks)


mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)


async def main():
    job=parent.fixture.tasks[0]
    async with execution_scope(job_id=job,project_id=fixture.p['id']):
        task_timing.record_info('asr_execution',dict(selected_model='small',actual_model='small',preferred_device='auto',
            actual_device='cpu',compute_type='int8_float32',beam_size=5,audio_seconds=60,language='auto',
            fallback_reason='测试回退说明：GPU 自检未通过，保留同一 small 模型'))
    for resource in ('speech_wait','speech_load','speech_decode'):
        stamp=now()
        execute('INSERT INTO execution_spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (uid(),0,job,fixture.p['id'],fixture.c['id'],resource,None,'Synthetic speech phase',0,'completed',stamp,stamp,stamp,1000))
    fixture.case.update(expected_timing_cards=13,expected_resources=12,asr_execution=True,
        timing_fixture='Synthetic speech phases/metadata; actual settings, current-form validation and paired HTTPS UI; fixture GPU result')
    await fixture.main()


if __name__=='__main__':asyncio.run(main())
