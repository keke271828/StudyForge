"""Isolated before/after polling: content parity, local time and memory.

Does not measure OCR, model quality, whole application RAM or video speed.
Run after the UI fixture stops changing its jobs.
"""
import argparse
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time
import tracemalloc

ROOT=Path(__file__).resolve().parents[1]


def memory():
    command=f'Get-Process -Id {os.getpid()} | Select-Object WorkingSet64,PeakWorkingSet64,PrivateMemorySize64 | ConvertTo-Json -Compress'
    return json.loads(subprocess.check_output(['powershell.exe','-NoProfile','-Command',command],
        creationflags=subprocess.CREATE_NO_WINDOW,text=True))


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def measure(operation,normalize=lambda value:value):
    before=memory();start=time.perf_counter();result=operation();cold=(time.perf_counter()-start)*1000
    after=memory();gc.collect();start=time.perf_counter()
    for _ in range(4):result=operation()
    elapsed=(time.perf_counter()-start)/4;gc.collect();tracemalloc.start()
    try:result=operation();peak=tracemalloc.get_traced_memory()[1]
    finally:tracemalloc.stop()
    return {'cold_ms':cold,'mean_ms':elapsed*1000,'timed_repeats':4,'python_peak_bytes':peak,
        'process_memory_before':before,'process_memory_after':after,'response_bytes':len(json.dumps(result,ensure_ascii=False).encode()),
        'public_fields_sha256':digest(normalize(result))}


def run(folder,variant):
    from studyforge import server
    # Both processes import both route modules so the historical process peak
    # is not biased by an extra FastAPI/model registry in the baseline alone.
    spec=importlib.util.spec_from_file_location('studyforge._workspace_poll_before',folder/'server.before.py')
    baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
    module=baseline if variant=='before' else server
    case=json.loads((folder/'fixture-case.json').read_text(encoding='utf-8'))
    legacy_keys=('id','kind','status','progress','error','created_at','only_exercises','reading_id','set_id','conversation_id',
        'export_formats','can_pause','stage','request_status','execution','parallel','scheduling_note','waiting_for_causes','homework_attempt_id','retry')
    jobs=lambda rows:[{key:row.get(key) for key in legacy_keys} for row in rows]
    polling=lambda row:{key:row.get(key) for key in ('id','project_id','kind','status','progress','error','can_pause','retry','export_formats')}|{'stage':row['result'].get('stage')}
    operations=[('source_list',lambda:module.sources(case['project_id']),lambda rows:rows),
        ('task_list',lambda:module.jobs(case['project_id']),jobs),
        ('task_poll',lambda:module.job(case['task_ids'][0]) if variant=='before' else module.job(case['task_ids'][0],view='progress'),polling)]
    report={'variant':variant,'external_model_requests':0,'scope':'local polling on 40 synthetic cached sources and isolated tasks'}
    for name,operation,normalize in operations:report[name]=measure(operation,normalize)
    (folder/('polling-'+variant+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


def compare(folder):
    before=json.loads((folder/'polling-before.json').read_text(encoding='utf-8'))
    current=json.loads((folder/'polling-current.json').read_text(encoding='utf-8'))
    for key in ('source_list','task_list','task_poll'):
        assert before[key]['public_fields_sha256']==current[key]['public_fields_sha256'],key
    report={'passed':True,'public_fields_identical':True,'before':before,'current':current}
    (folder/'polling-comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('All original displayed fields match; complete task intent stays in the isolated database')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('variant',choices=['before','current','compare']);args=parser.parse_args()
    folder=ROOT/'build'/'workspace-refresh-20261011'
    case=json.loads((folder/'fixture-case.json').read_text(encoding='utf-8'))
    os.environ['STUDYFORGE_DATA_DIR']=str(Path(case['certificate']).parents[2])
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'unused-semantic-model')
    if args.variant=='compare':compare(folder)
    else:run(folder,args.variant)
