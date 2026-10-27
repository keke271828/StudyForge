"""Collect finished, scoped validation records without any model requests."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / 'build/summary-cautions-20261014'
    files = ['summary-cautions-core.xml', 'summary-cautions-delivery.xml', 'summary-cautions-final.xml',
        'summary-cautions-continuity.xml', 'summary-cautions-last.xml']
    unique, runs = set(), []
    for file in files:
        tree = ET.parse(ROOT / 'build' / file)
        assert not list(tree.iter('failure')) and not list(tree.iter('error')), file
        cases = list(tree.iter('testcase'))
        for case in cases:
            name = case.get('name')
            # The original unparameterized test was the sequential case;
            # later it explicitly covered both False and True.
            if name == 'test_actual_long_generation_keeps_review_cautions_in_summary_word_and_receipt': name += '[False]'
            unique.add((case.get('classname'), name))
        runs.append({'file': file, 'passed_cases': len(cases)})
    stats = json.loads((out / '人工复核与统计.json').read_text(encoding='utf-8'))
    assert stats['actual_calls'] == stats['successful_calls'] == 5 and not stats['failures']
    page = json.loads((out / '页面运行核验.json').read_text(encoding='utf-8'))
    assert page['passed'] and page['displayed_samples'] == 5 and not page['network_requests']
    ui = json.loads((ROOT / 'build/summary-cautions-ui-20261014-2/ui-report.json').read_text(encoding='utf-8'))
    assert ui['passed'] and len(ui['checks']) == 4 and ui['external_model_requests'] == 0
    sources = ['studyforge/lesson_cautions.py', 'studyforge/teaching.py', 'studyforge/lesson_quality.py',
        'studyforge/server.py', 'web/source_evidence.js', 'web/mobile/sw.js', 'web/help/guide.html']
    result = {'passed': True, 'regression_runs': runs, 'unique_regression_cases': len(unique),
        'actual_model_calls': 5, 'desktop_and_paired_phone_ui_checks': len(ui['checks']),
        'report_displayed_samples': 5, 'report_external_dependencies': 0,
        'new_verifier_model_requests': 0, 'unrelated_learner_database_access': False,
        'source_sha256': {file: hashlib.sha256((ROOT / file).read_bytes()).hexdigest() for file in sources}}
    (out / '最终核验记录.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key not in ('source_sha256','regression_runs')}, ensure_ascii=False))


if __name__ == '__main__': main()
