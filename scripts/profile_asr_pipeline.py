"""One real application-path CUDA speech run, isolated from the user DB."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import argparse

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'build/asr-quality-performance-20261012'
os.environ['STUDYFORGE_DATA_DIR']=str(FOLDER/'pipeline-data')
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(FOLDER/'unused-semantic-model')
sys.stdout.reconfigure(encoding='utf-8')


async def main(device):
    from studyforge import ai,media,task_timing
    from studyforge.db import create_job,create_project,update_job
    from studyforge.scheduling import execution_scope,run_local
    ai.save_settings({'whisper_model':'small','whisper_device':device})
    project=create_project('real speech pipeline');job=create_job(project['id'],'import',{})
    path=FOLDER/'audio-samples/course-0300.wav'
    start=time.perf_counter()
    async with execution_scope(job_id=job,project_id=project['id']):
        parts=await run_local('media',media.transcribe,path,label='actual complete speech')
    elapsed_ms=(time.perf_counter()-start)*1000
    update_job(job,'completed',100,{'test_finished':True})
    info=task_timing.detail(job)
    result=dict(passed=True,whole_call_ms=elapsed_ms,audio_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                actual_execution=info['asr_execution'],resources=info['resources'],segments=parts,
                external_model_requests=0,scope='complete application transcription on one real 60s WAV; includes extraction, isolated GPU preflight and initial model load')
    expected='cpu' if device=='cpu' else 'cuda'
    if info['asr_execution']['actual_device']!=expected:raise RuntimeError('Application device mismatch: '+info['asr_execution'].get('fallback_reason',''))
    (FOLDER/f'pipeline-{expected}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:result[key] for key in ('passed','whole_call_ms','actual_execution')},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('device',nargs='?',default='auto',choices=['auto','cpu']);args=parser.parse_args()
    asyncio.run(main(args.device))
