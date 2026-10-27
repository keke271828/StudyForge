"""Replay the six real JSON responses through the final guard, without AI."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


async def main():
    out = ROOT / 'build/fast-review-20261014'
    os.environ['STUDYFORGE_DATA_DIR'] = str(out / 'replay-data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(out / 'replay-isolated-model')
    from studyforge.review import review_explanation
    rows = []
    for name in ('fast-review-20261014-before', 'fast-review-20261014-after'):
        folder = ROOT / 'build' / name
        inputs = {case['name']: case for case in json.loads((folder / 'inputs.json').read_text(encoding='utf-8'))}
        for record in json.loads((folder / 'results.json').read_text(encoding='utf-8')):
            case = inputs[record['case']]
            responses = json.loads((folder / (record['case'] + '-requests.json')).read_text(encoding='utf-8'))
            class Replay:
                calls = 0
                async def complete(self, *args, **kwargs):
                    self.calls += 1
                    assert self.calls <= len(responses), 'Replay requested an extra model response.'
                    return responses[self.calls-1]['response']
            client = Replay()
            result, reports = await review_explanation(client, case['source'], case['draft'], mode='fast',
                learning_mode='deep', explanation_style='balanced', summary_level=3, requirements=case['requirements'])
            assert result == (folder / record['answer_file']).read_text(encoding='utf-8')
            assert client.calls == 1
            assert reports[0].get('locally_corrected_issues', []) == record['audit_reports'][0].get('locally_corrected_issues', [])
            rows.append({'round': name, 'case': record['case'], 'passed': True,
                'recorded_responses_replayed': client.calls, 'new_model_calls': 0})
    filenames = ['review-corrections-final.xml', 'review-corrections-guide.xml',
        'review-corrections-render-final.xml', 'review-corrections-last.xml']
    unique, suites = set(), []
    for filename in filenames:
        path = ROOT / 'build' / filename
        tree = ET.parse(path)
        failures = list(tree.iter('failure')) + list(tree.iter('error'))
        assert not failures, filename
        cases = list(tree.iter('testcase'))
        unique.update((case.get('classname'), case.get('name')) for case in cases)
        suites.append({'file': filename, 'cases': len(cases), 'failures': len(failures)})
    paths = ['studyforge/review_corrections.py', 'studyforge/review.py', 'studyforge/document_render.py', 'web/help/guide.html']
    result = {'passed': True, 'replayed_actual_reviews': rows, 'new_model_calls': 0,
        'regression_runs': suites, 'unique_regression_cases': len(unique),
        'final_source_sha256': {file: hashlib.sha256((ROOT / file).read_bytes()).hexdigest() for file in paths}}
    (out / '最终核验记录.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'real_responses_replayed': len(rows), 'new_model_calls': 0,
        'unique_regression_cases': len(unique)}, ensure_ascii=False))


if __name__ == '__main__': asyncio.run(main())
