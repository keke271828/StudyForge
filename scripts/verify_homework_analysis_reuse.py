"""Run the relevant final gate against frozen source, using workspace temp files."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/homework-analysis-reuse-20261022'
FILES=['studyforge/homework.py','studyforge/homework_analysis.py','studyforge/teaching_policy.py',
       'web/help/guide.html','web/mobile/sw.js']
TESTS=['homework_analysis_reuse','homework','homework_context','repair_learning','assessment_quality',
       'assessment_isolation','profile_focus','profile_scoring','workflow_pause','task_exercise_workflows',
       'mobile_access','teaching_review','json_math_delimiters','practice']


def hashes():return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in FILES}


def main():
    report=OUT/'final-command.json';xml=OUT/'final-regression.xml';temp=OUT/'pytest-final-1'
    if report.exists() or xml.exists() or temp.exists():raise SystemExit('Preserve earlier gate evidence; choose a fresh gate name.')
    before=hashes();env=dict(os.environ);env['PYTHONIOENCODING']='utf-8'
    local_temp=OUT/'local-temp';local_temp.mkdir(exist_ok=True)
    env['TMP']=env['TEMP']=str(local_temp)
    command=[sys.executable,'-X','utf8','-m','pytest']+['tests/test_'+name+'.py' for name in TESTS]+[
        '-q','--basetemp='+str(temp),'--junitxml='+str(xml)]
    started=time.perf_counter()
    result=subprocess.run(command,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8')
    (OUT/'final-regression.log').write_text(result.stdout,encoding='utf-8')
    final={'exit_code':result.returncode,'seconds':round(time.perf_counter()-started,3),'command':command,
           'production_before':before,'production_after':hashes(),'source_frozen':before==hashes()}
    if xml.exists():
        cases=ET.parse(xml).getroot().findall('.//testcase')
        final['tests']={'total':len(cases),**{key:sum(case.find(key) is not None for case in cases) for key in ('failure','error','skipped')}}
    report.write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(final.get('tests'),ensure_ascii=False),flush=True)
    if result.returncode or not final['source_frozen']:raise SystemExit(1)


if __name__=='__main__':main()
