"""Freeze fingerprints while checking error presentation and phone-session boundaries."""
from pathlib import Path
import json
import subprocess
from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/error-help-final-20261026-2'
gate.FILES=['web/operation_errors.js','web/operation_errors.css','web/app.js','web/notifications.js','web/task_controls.js',
    'web/parallel.js','web/library.js','web/mobile/app.js','web/mobile/index.html','web/index.html',
    'web/mobile/sw.js','studyforge/mobile_access.py','web/help/guide.html']
gate.TESTS=['operation_errors','mobile_access','mobile_first_delta','mobile_network','mobile_lesson_feedback',
    'user_guide','teaching_review','source_scope','agent_permissions','task_retry','generation_control',
    'generation_progress','homework_recovery_policy','model_services']


def main():
    gate.main()
    node='C:/Program Files/nodejs/node.exe'
    sources=[p for base in ['web','desktop'] for p in (gate.ROOT/base).rglob('*.js') if 'vendor' not in p.parts]
    for source in sources:subprocess.run([node,'--check',str(source)],check=True,capture_output=True)
    command=[node,'--test','--test-reporter=tap',*[str(p) for p in sorted((gate.ROOT/'tests').glob('*.test.js'))]]
    with (gate.OUT/'javascript.log').open('w',encoding='utf-8') as log:
        result=subprocess.run(command,cwd=gate.ROOT,stdout=log,stderr=subprocess.STDOUT)
    record={'syntax_files':len(sources),'exit_code':result.returncode,'command':command,'production_unchanged':gate.hashes()==json.loads((gate.OUT/'command.json').read_text(encoding='utf-8'))['production_after']}
    (gate.OUT/'javascript.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    assert not result.returncode and record['production_unchanged']
    print(json.dumps({'syntax_files':len(sources),'javascript_exit':result.returncode}))


if __name__=='__main__':main()
