"""Verify saved evidence only. No model requests, app launch or learner DB access."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def main():
    folders = ROOT/'build/homework-followup-real-20261014-1', ROOT/'build/homework-followup-20261014'
    actual, report = folders
    cases = set(); runs = []
    for name in ('homework-context-regression.xml', 'homework-context-adapters.xml', 'homework-context-final.xml'):
        root = ET.parse(ROOT/'build'/name).getroot(); items = root.findall('.//testcase')
        assert not root.findall('.//failure') and not root.findall('.//error')
        assert not root.findall('.//skipped')
        cases.update((item.get('classname'), item.get('name')) for item in items)
        runs.append({'file': name, 'cases': len(items)})
    rows = json.loads((actual/'results.json').read_text(encoding='utf-8')); reads = 0
    for row in rows:
        assert row['status'] == 'completed'
        text = (actual/row['answer_file']).read_bytes().decode('utf-8')
        assert hashlib.sha256(text.encode()).hexdigest() == row['answer_sha256']
        requests = json.loads((actual/(row['case']+'-'+row['arm']+'-requests.json')).read_text(encoding='utf-8'))
        assert len(requests) == row['model_requests']
        tool_calls = {}
        for request in requests:
            for message in request['messages']:
                assert 'reasoning_content' not in message
                for call in message.get('tool_calls', []): tool_calls[call['id']] = call['function']['name']
        count = sum(name == 'sf_read_homework_feedback' for name in tool_calls.values())
        assert count == (1 if row['arm']=='read_feedback' else 0)
        reads += count
    ui = json.loads((ROOT/'build/homework-followup-ui-20261014-1/ui-report.json').read_text(encoding='utf-8'))
    page = json.loads((report/'页面运行核验.json').read_text(encoding='utf-8'))
    assert ui['passed'] and len(ui['checks']) == 5 and not ui['console_errors']
    assert page['passed'] and page['displayed_samples'] == 4 and not page['console_errors'] and not page['network_requests']
    assert len(cases) == 242 and len(rows) == 4 and sum(row['model_requests'] for row in rows) == 7 and reads == 2
    files = ['studyforge/homework_context.py', 'studyforge/homework.py', 'studyforge/agent_tools.py',
             'studyforge/ai.py', 'studyforge/codex_bridge.py', 'tests/test_homework_context.py',
             'web/help/guide.html', 'web/mobile/sw.js']
    result = {'passed': True, 'unique_regression_cases': len(cases), 'runs': runs, 'ui_checks': len(ui['checks']),
        'complete_real_answers': len(rows), 'actual_model_requests': sum(row['model_requests'] for row in rows),
        'actual_feedback_reads': reads, 'report_samples': page['displayed_samples'], 'private_reasoning_published': False,
        'scope': 'Functional access and saved evidence verification; remaining content errors are retained in manual notes. Not all-model teaching quality, whole-app memory or generation-speed validation.',
        'source_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}}
    (report/'最终核验记录.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__': main()
