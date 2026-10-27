"""Read saved isolated evidence and source fingerprints; no model/user DB use."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/teaching-alignment-20261015'


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    identities=set();runs=[]
    for filename in ('lesson-passage-existing.xml','lesson-passage-new.xml','lesson-passage-regression.xml','lesson-passage-guide.xml','lesson-passage-final.xml'):
        cases=ET.parse(ROOT/'build'/filename).findall('.//testcase')
        assert cases and not any(item.find('failure') is not None or item.find('error') is not None or item.find('skipped') is not None for item in cases)
        identities.update((item.attrib.get('classname'),item.attrib.get('name')) for item in cases)
        runs.append({'file':filename,'checks':len(cases)})
    ui=read(ROOT/'build/lesson-passage-ui-20261015-2/ui-report.json')
    widget=read(ROOT/'build/lesson-passage-ui-20261015-2/widget-report.json')
    assert ui['passed'] and len(ui['checks'])==7 and not ui['console_errors']
    assert ui['model_requests']==2 and ui['external_model_requests']==0
    assert widget['passed'] and len(widget['checks'])==3 and not widget['console_errors']
    static=read(OUT/'页面静态核验.json');page=read(OUT/'页面运行核验.json')
    assert static['ok'] and static['samples']==12 and static['groups']==4 and static['verbatim_outputs']
    assert page['passed'] and page['displayed_samples']==12 and not page['network_requests']
    calls=0
    for name in ('teaching-alignment-real-20261015-1','teaching-alignment-pairs-real-20261015-1'):
        folder=ROOT/'build'/name;inputs=read(folder/'inputs.json');rows=read(folder/'results.json')
        for row in rows:
            assert row['status']=='completed'
            text=(folder/row['output_file']).read_bytes().decode('utf-8')
            assert hashlib.sha256(text.encode()).hexdigest()==row['output_sha256']
            entry=inputs[row['case']]
            assert hashlib.sha256(entry['draft'].encode()).hexdigest()==entry['draft_sha256']
            records=read(folder/(row['case']+'-'+row['arm']+'-requests.json'))
            assert len(records)==row['model_calls']==1
            for record in records:
                public={key:record[key] for key in ('system','user','json_mode')}
                assert hashlib.sha256(json.dumps(public,sort_keys=True,ensure_ascii=False).encode()).hexdigest()==record['request_sha256']
                assert isinstance(json.loads(record['response'])['issues'],list)
            calls+=row['model_calls']
    assert calls==12
    previous=read(ROOT/'build/teaching-inference-20261015/最终核验记录.json')['source_sha256']
    for file in ('studyforge/review.py','studyforge/review_corrections.py'):
        assert hashlib.sha256((ROOT/file).read_bytes()).hexdigest()==previous[file], 'Unsuccessful audit candidate must not change production rules or edits.'
    files=('studyforge/lesson_focus.py','studyforge/lesson_feedback.py','studyforge/server.py',
        'studyforge/mobile_access.py','studyforge/packaging_check.py','web/lesson_passage.js','web/lesson_passage.css',
        'web/lesson_feedback.js','web/index.html','web/mobile/lesson-feedback.js','web/mobile/index.html','web/mobile/sw.js',
        'web/help/guide.html','scripts/export_teaching_policy.py','docs/AI导师提示词.md',
        'tests/test_lesson_passage.py','scripts/smoke_lesson_passage_ui.js','scripts/check_lesson_passage_widget.js')
    result={'passed':True,'unique_related_checks':len(identities),'runs':runs,'complete_ui_flows':7,'supplementary_widget_checks':3,
        'controlled_followup_requests':2,'ui_external_model_requests':0,'real_audit_component_calls':calls,
        'audit_candidates_adopted':False,'production_review_unchanged':True,'page_groups':4,'page_samples':12,
        'mobile_shell':'v41','packaged':False,
        'limits':'Native requests and UI followups use controlled responses. Twelve real audits are separate trials. No whole-app RAM, long-video timing, universal learning-quality or actual Android validation.',
        'source_sha256':{file:hashlib.sha256((ROOT/file).read_bytes()).hexdigest() for file in files}}
    (OUT/'最终核验记录.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in result.items() if key not in ('runs','source_sha256')},ensure_ascii=True))


if __name__=='__main__':main()
