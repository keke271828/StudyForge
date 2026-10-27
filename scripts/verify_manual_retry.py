"""Final related recovery regression with frozen production source fingerprints."""
import json
import subprocess
from scripts import verify_repair_selection as gate

gate.OUT=gate.ROOT/'build/manual-retry-final-20261026'
gate.FILES=['studyforge/db.py','studyforge/task_recovery.py','studyforge/server.py','studyforge/mobile_access.py',
    'web/task_retry.js','web/task_controls.js','web/app.js','web/mobile/app.js','web/mobile/sw.js','web/help/guide.html']
gate.TESTS=['manual_task_retry','generation_control','task_retry','task_context_memory','chapter_continuity',
    'document_exports','task_scheduling','mobile_access','mobile_first_delta','homework_recovery_policy',
    'homework_checkpoint','user_guide','teaching_review','library_generation_evidence','source_preparation',
    'task_exercise_workflows','operation_errors']


def main():
    gate.main()
    node='C:/Program Files/nodejs/node.exe'
    sources=[p for base in ['web','desktop'] for p in (gate.ROOT/base).rglob('*.js') if 'vendor' not in p.parts]
    for source in sources:subprocess.run([node,'--check',str(source)],check=True,capture_output=True)
    command=[node,'--test','--test-reporter=tap',*[str(p) for p in sorted((gate.ROOT/'tests').glob('*.test.js'))]]
    with (gate.OUT/'javascript.log').open('w',encoding='utf-8') as log:
        result=subprocess.run(command,cwd=gate.ROOT,stdout=log,stderr=subprocess.STDOUT)
    record={'syntax_files':len(sources),'exit_code':result.returncode,'command':command,
        'production_unchanged':gate.hashes()==json.loads((gate.OUT/'command.json').read_text(encoding='utf-8'))['production_after']}
    (gate.OUT/'javascript.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    assert result.returncode==0 and record['production_unchanged']
    print(json.dumps({'syntax_files':len(sources),'javascript_exit':result.returncode}))


if __name__=='__main__':main()
