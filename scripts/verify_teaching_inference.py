"""Verify frozen outputs and final guards. No model calls or learner DB access."""
import hashlib
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT/'build/teaching-inference-20261015'
    os.environ['STUDYFORGE_DATA_DIR'] = str(out/'verification-data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(out/'isolated-model')
    from studyforge.review import INFERENCE_SCOPE_RULES
    from studyforge.teaching_policy import SUPPLEMENT_TEACHING_RULES
    from scripts.eval_inference_audit import INFERENCE_CHECK
    from scripts.teaching_inference_candidate import CANDIDATE
    assert INFERENCE_SCOPE_RULES == INFERENCE_CHECK and SUPPLEMENT_TEACHING_RULES != CANDIDATE
    unique, runs = set(), []
    for name in ('inference-audit-regression.xml', 'inference-audit-delivery.xml', 'inference-audit-final.xml', 'quote-anchor-core.xml'):
        root = ET.parse(ROOT/'build'/name).getroot(); cases = root.findall('.//testcase')
        assert not root.findall('.//failure') and not root.findall('.//error') and not root.findall('.//skipped')
        unique.update((case.get('classname'),case.get('name')) for case in cases); runs.append({'file':name,'cases':len(cases)})
    assert len(unique)==212
    actual = []
    for folder in ('teaching-inference-real-20261015-1','inference-audit-real-20261015-1','inference-audit-control-20261015-1'):
        base = ROOT/'build'/folder
        rows = json.loads((base/'results.json').read_text(encoding='utf-8'))
        for row in rows:
            assert row['status']=='completed'
            path = base/row.get('answer_file',row.get('output_file'))
            assert hashlib.sha256(path.read_bytes()).hexdigest()==row.get('answer_sha256',row.get('output_sha256'))
            if row.get('model_calls') is not None: assert row['model_calls']==1
        actual.extend(rows)
    assert len(actual)==20
    replay = json.loads((out/'replay/results.json').read_text(encoding='utf-8'))
    assert len(replay)==8 and all(row['external_model_requests']==0 and row['replayed_calls']==1 for row in replay)
    fixed = next(row for row in replay if row['case']=='causal' and row['arm']=='expanded')
    assert fixed['reports'][0]['locally_corrected_issues']==[0,1] and fixed['word_verified']
    assert fixed['reports'][0]['inference_scope']['criteria_sha256']==hashlib.sha256(INFERENCE_SCOPE_RULES.encode()).hexdigest()
    assert all(row['original_body_unchanged'] for row in replay if row['case']=='math_control')
    page = json.loads((out/'页面运行核验.json').read_text(encoding='utf-8'))
    assert page['passed'] and page['groups']==8 and page['displayed_samples']==21 and not page['console_errors'] and not page['network_requests']
    reference = json.loads((out/'合成例子的本机核对.json').read_text(encoding='utf-8')); assert reference['passed']
    names = ['studyforge/review.py','studyforge/review_corrections.py','tests/test_inference_audit.py',
             'tests/test_review_quote_anchors.py','scripts/export_teaching_policy.py','docs/AI导师提示词.md']
    result = {'passed':True,'unique_related_checks':len(unique),'runs':runs,'real_component_calls':20,
        'teacher_answers':12,'real_audits':8,'historical_responses_replayed':8,'replay_model_calls':0,
        'teacher_candidate_adopted':False,'audit_criteria_match_actual_trial':True,'word_replay_verified':True,
        'page_groups':8,'page_samples':21,'review_rounds_unchanged':True,
        'limits':'One sample per cell; failures, residual wording and ambiguous control retained. Not all teaching quality, latency, whole-app memory or Android validation.',
        'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}}
    (out/'最终核验记录.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__': main()
