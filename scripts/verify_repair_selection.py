"""Relevant final regression gate, with immutable source fingerprints."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/repair-selection-final-20261022'
FILES=['studyforge/server.py','studyforge/repair_learning.py','studyforge/homework_context.py','studyforge/db.py',
       'studyforge/mobile_access.py','web/repair_picker.js','web/repair_picker.css','web/homework_reader.js',
       'web/homework.js','web/mobile/homework.js','web/practice.js','web/index.html','web/mobile/index.html',
       'web/mobile/sw.js','web/help/guide.html']
TESTS=['repair_selection','repair_learning','homework_reader','homework_context','task_exercise_workflows',
       'practice','assessment_quality','learning_transfer','learning_goals','mobile_access','teaching_review']


def hashes():return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in FILES}


def main():
    if OUT.exists():raise SystemExit('Preserve earlier gate evidence; use a fresh output folder.')
    OUT.mkdir();local=OUT/'local-temp';local.mkdir();env=dict(os.environ)
    env['PYTHONIOENCODING']='utf-8';env['TMP']=env['TEMP']=str(local)
    before=hashes();started=time.perf_counter();xml=OUT/'regression.xml'
    command=[sys.executable,'-X','utf8','-m','pytest']+['tests/test_'+test+'.py' for test in TESTS]+[
        '-q','--basetemp='+str(OUT/'pytest'),'--junitxml='+str(xml)]
    with (OUT/'regression.log').open('w',encoding='utf-8') as log:
        result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    after=hashes();report={'exit_code':result.returncode,'seconds':round(time.perf_counter()-started,3),'command':command,
        'production_before':before,'production_after':after,'source_frozen':before==after}
    if xml.exists():
        cases=ET.parse(xml).getroot().findall('.//testcase')
        report['tests']={'total':len(cases),**{key:sum(case.find(key)is not None for case in cases) for key in ('failure','error','skipped')}}
    (OUT/'command.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report.get('tests')),flush=True)
    if result.returncode or not report['source_frozen']:raise SystemExit(1)


if __name__=='__main__':main()
