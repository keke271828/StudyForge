"""Verify saved isolated evidence and final sources without new AI requests."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from docx import Document

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/lesson-check-review-20261015'


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    identities=set();runs=[]
    for name in ('lesson-check-new.xml','lesson-check-regression.xml','lesson-check-guide.xml'):
        cases=ET.parse(ROOT/'build'/name).findall('.//testcase')
        assert cases and not any(any(case.find(tag) is not None for tag in ('failure','error','skipped')) for case in cases)
        identities.update((case.attrib.get('classname'),case.attrib.get('name')) for case in cases)
        runs.append({'file':name,'checks':len(cases)})
    ui=read(ROOT/'build/lesson-check-ui-20261015-2/ui-report.json')
    assert ui['passed'] and len(ui['checks'])==6 and not ui['console_errors']
    assert ui['controlled_model_calls']==8 and ui['external_model_requests']==0
    static=read(OUT/'页面静态核验.json');page=read(OUT/'页面运行核验.json')
    assert static['passed'] and static['student_samples']==4 and not static['private_solutions_published']
    assert page['passed'] and page['displayed_samples']==4 and page['verbatim_student_outputs']
    assert page['word_links_exist'] and page['desktop_and_phone_no_horizontal_overflow'] and not page['network_requests']
    assert static['html_sha256']==hashlib.sha256((OUT/'补讲后单题理解检查实际对照.html').read_bytes()).hexdigest()
    real=[];calls=0
    for name in ('lesson-check-real-20261015-2','lesson-check-real-20261015-3'):
        folder=ROOT/'build'/name;results=read(folder/'results.json')
        records=read(folder/'private-final-model-records.json')
        assert len(results)==2 and len(records)==sum(row['component_calls'] for row in results)
        assert all(isinstance(record.get('final_response'),str) for record in records)
        for row in results:
            assert row['status']=='completed' and row['synthetic_teaching_records'] and not row['tools']
            text=(folder/row['student_file']).read_text(encoding='utf-8')
            assert hashlib.sha256(text.encode()).hexdigest()==row['student_sha256']
            public=read(folder/(row['case']+'-student.json'))
            assert len(public['questions'])==1 and 'solutions' not in public
            paragraphs=[p.text for p in Document(row['word_file']).paragraphs]
            assert paragraphs and '解析' not in paragraphs and not any(p.startswith('评分标准：') for p in paragraphs)
            assert not any('本题与补讲的关系' in p for p in paragraphs)
            if name.endswith('-3'):
                spec=read(folder/(row['case']+'-context.json'));assert spec['version']==2
                private=read(folder/(row['case']+'-private-quality-review.json'))[0]
                assert isinstance(private['rubric'],list) and sum(p['points'] for p in private['rubric'])==100
            calls+=row['component_calls']
        real.append({'folder':name,'results':results})
    assert calls==24
    manifest=read(ROOT/'build/lesson-check-real-20261015-3/runtime-manifest.json')
    for name,digest in manifest['source_hashes'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest, 'Final real trials must match the shipped task code.'
    assert 'v42' in (ROOT/'web/mobile/sw.js').read_text(encoding='utf-8')
    files=('studyforge/lesson_checks.py','studyforge/exercises.py','studyforge/server.py','studyforge/db.py',
        'studyforge/lesson_feedback.py','studyforge/mobile_access.py','web/lesson_feedback.js',
        'web/mobile/lesson-feedback.js','web/mobile/index.html','web/mobile/sw.js','web/help/guide.html',
        'tests/test_lesson_checks.py','tests/test_workflow_pause.py','scripts/export_teaching_policy.py','docs/AI导师提示词.md',
        'scripts/eval_lesson_checks.py','scripts/smoke_lesson_check_ui.py','scripts/smoke_lesson_check_ui.js')
    result={'passed':True,'unique_related_checks':len(identities),'runs':runs,'full_ui_flows':6,
        'ui_controlled_model_calls':8,'ui_external_model_requests':0,'real_complete_trials':4,
        'real_component_calls':calls,'final_task_code_matches_real_trial':True,'real_trials':real,
        'student_page_samples':4,'private_answers_in_student_page':False,'mobile_shell':'v42','packaged':False,
        'limits':'Synthetic prior lessons; small sequential samples, no blind assessment. Some statistical wording still needs scrutiny. No universal correctness, speed, total RAM, long-video, or actual Android validation.',
        'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}}
    (OUT/'最终核验记录.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in result.items() if key not in ('runs','source_sha256','real_trials')},ensure_ascii=True))


if __name__=='__main__':main()
