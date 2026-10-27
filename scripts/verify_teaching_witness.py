"""Frozen production hashes and one final relevant regression command."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/algebra-witness-20261021'
FILES=['studyforge/algebra_hints.py','studyforge/ai.py','studyforge/json_math.py','studyforge/teaching_policy.py']
TESTS=['algebra_witness','algebra_hints','json_math_delimiters','review_input','review_math_label_anchors',
    'review_quote_anchors','review_passages','review_correction_groups','review_modes','explanation_review_scope',
    'teaching','teaching_review','teaching_preferences','learning_modes','summary_evidence','summary_cautions',
    'revision_cautions','generation_review_recovery','task_exercise_workflows','mentor_handoff','knowledge',
    'learning_memory','coding','coding_runtime']


def hashes():return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in FILES}


def main():
    xml=OUT/'final-regression-20261022.xml';report=OUT/'final-command-20261022.json'
    if xml.exists() or report.exists():raise SystemExit('Preserve final gate evidence; use a new filename if repeating.')
    before=hashes();command=[sys.executable,'-X','utf8','-m','pytest']+['tests/test_'+name+'.py' for name in TESTS]+['-q','--junitxml='+str(xml)]
    start=time.perf_counter();run=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8')
    (OUT/'final-regression-20261022.log').write_text(run.stdout,encoding='utf-8');after=hashes()
    result={'exit_code':run.returncode,'seconds':round(time.perf_counter()-start,3),'command':command,
        'production_before':before,'production_after':after,'frozen_production_unchanged':before==after}
    if xml.exists():
        rows=ET.parse(xml).getroot().findall('.//testcase')
        result['tests']={key:sum(row.find(key) is not None for row in rows) for key in ('failure','error','skipped')}
        result['tests']['total']=len(rows)
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result['tests'],ensure_ascii=False),flush=True)
    if run.returncode or before!=after:raise SystemExit(1)


if __name__=='__main__':main()
