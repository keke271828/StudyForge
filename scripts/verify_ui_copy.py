"""Related regression + presentation contract check with immutable source hashes."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from collections import Counter
from scripts import verify_repair_selection as gate
from scripts.audit_ui_copy import js_strings

AUDIT=gate.ROOT/'build/ui-copy-audit-20261026-2'
rows=json.loads((AUDIT/'before.json').read_text(encoding='utf-8'))
gate.OUT=gate.ROOT/'build/ui-copy-final-20261026'
gate.FILES=[r['path'] for r in rows]+['web/library.css']
gate.TESTS=['user_guide','library_models','library_foreground','library_policy','library_outline','source_scope',
    'source_preparation','model_controls','model_services','review_modes','learning_modes','mobile_lesson_feedback',
    'mobile_access','lesson_feedback','message_focus','document_exports','navigation','learning_profile',
    'profile_scoring','task_retry','teaching_review','homework_reader','dialogue_profile_scope']


def skeleton(text):
    for start,value in reversed(list(js_strings(text))):text=text[:start]+'STRING'+text[start+len(value)+2:]
    return re.sub(r'\s+','',text)


def contracts():
    changed=[];logic=[];details=[]
    pattern=r'(?:includes|startsWith|endsWith)\(\s*([\'\"])([^\n]*?)\1'
    attributes=r'\b(?:id|name|data-[a-z-]+|value|href|src|type)=[\"\']([^\"\']*)[\"\']'
    for row in rows:
        name=row['path'];old=(AUDIT/'before'/name).read_text(encoding='utf-8');new=(gate.ROOT/name).read_text(encoding='utf-8')
        if old==new:continue
        changed.append(name)
        assert re.findall(pattern,old)==re.findall(pattern,new),('Saved protocol recognition changed',name)
        before=Counter(re.findall(attributes,old));after=Counter(re.findall(attributes,new))
        added=after-before;removed=before-after
        if name=='web/library.js':assert added==Counter({'bookReadingDetails':1,'bookShowProgress':1,'button':1}) and not removed,(name,added,removed)
        else:assert not added and not removed,(name,added,removed)
        if name.endswith('.js') and skeleton(old)!=skeleton(new):logic.append(name)
        details.append({'path':name,'before_sha256':row['sha256'],'after_sha256':hashlib.sha256(new.encode()).hexdigest()})
    assert set(logic)=={'web/library.js','web/lesson_feedback.js','web/mobile/lesson-feedback.js'},logic
    return {'reviewed_files':len(rows),'files_with_chinese':sum(bool(r['items']) for r in rows),
            'changed_files':changed,'ui_behavior_additions':logic,'protected_control_values_and_recognizers_unchanged':True,'changes':details}


def main():
    report=contracts()
    # The only functional additions are optional reading help/progress navigation
    # and public questionnaire-label aliases; saved difficulty IDs are unchanged.
    recheck='--desktop-only' in sys.argv
    if recheck:
        prior=json.loads((gate.OUT/'command.json').read_text(encoding='utf-8'))
        assert prior['exit_code']==0 and prior['source_frozen'] and prior['production_after']==gate.hashes()
    else:
        gate.main()
        (gate.OUT/'copy-contracts.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    node='C:/Program Files/nodejs/node.exe'
    files=[p for base in ('web','desktop') for p in (gate.ROOT/base).rglob('*.js') if 'vendor' not in p.parts]
    for path in files:subprocess.run([node,'--check',str(path)],check=True,capture_output=True)
    command=[node,'--test','--test-reporter=tap',*[str(p) for p in sorted((gate.ROOT/'tests').glob('*.test.js'))]]
    log_path=gate.OUT/('desktop-tests-rechecked.log' if recheck else 'desktop-tests.log')
    json_path=gate.OUT/('javascript-rechecked.json' if recheck else 'javascript.json')
    assert not log_path.exists() or not recheck, 'Preserve prior recheck output'
    with log_path.open('w',encoding='utf-8') as log:
        result=subprocess.run(command,cwd=gate.ROOT,stdout=log,stderr=subprocess.STDOUT)
    assert json.loads((gate.OUT/'command.json').read_text(encoding='utf-8'))['production_after']==gate.hashes()
    json_path.write_text(json.dumps({'syntax_files':len(files),'command':command,'exit_code':result.returncode,'production_unchanged':True},indent=2),encoding='utf-8')
    if result.returncode:raise SystemExit('Desktop regression failed; see desktop-tests.log')
    print(json.dumps({'reviewed_files':len(rows),'changed_copy_files':len(report['changed_files']),'syntax_files':len(files)}))


if __name__=='__main__':main()
