"""One regression gate with source fingerprints, separate from live UI acceptance."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/homework-reader-checked-20261022'
FILES=['studyforge/homework.py','studyforge/homework_context.py','studyforge/server.py','studyforge/mobile_access.py',
       'web/homework_reader.js','web/homework_reader.css','web/homework.js','web/mobile/homework.js',
       'web/index.html','web/mobile/index.html','web/mobile/sw.js','web/help/guide.html']
TESTS=['homework_reader','homework_context','homework','homework_analysis_reuse','mobile_access','teaching_review']


def hashes():return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in FILES}


def main():
    report=OUT/'final-command.json';xml=OUT/'final-regression.xml';temp=OUT/'pytest-final'
    if report.exists() or xml.exists() or temp.exists():raise SystemExit('Preserve existing evidence; use a fresh gate name.')
    OUT.mkdir(parents=True,exist_ok=True);local=OUT/'local-temp';local.mkdir(exist_ok=True)
    env=dict(os.environ);env['PYTHONIOENCODING']='utf-8';env['TMP']=env['TEMP']=str(local)
    before=hashes();started=time.perf_counter()
    command=[sys.executable,'-X','utf8','-m','pytest']+['tests/test_'+test+'.py' for test in TESTS]+[
        '-q','--basetemp='+str(temp),'--junitxml='+str(xml)]
    with (OUT/'final-regression.log').open('w',encoding='utf-8') as log:
        result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    after=hashes();final={'exit_code':result.returncode,'seconds':round(time.perf_counter()-started,3),
        'command':command,'production_before':before,'production_after':after,'source_frozen':before==after}
    if xml.is_file():
        cases=ET.parse(xml).getroot().findall('.//testcase')
        final['tests']={'total':len(cases),**{key:sum(item.find(key)is not None for item in cases) for key in ('failure','error','skipped')}}
    report.write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(final.get('tests')),flush=True)
    if result.returncode or not final['source_frozen']:raise SystemExit(1)


if __name__=='__main__':main()
