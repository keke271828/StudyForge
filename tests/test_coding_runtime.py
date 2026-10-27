import asyncio
import json
from pathlib import Path
import subprocess

import pytest

from studyforge import coding, coding_runtime
from studyforge.db import create_project, many


@pytest.mark.parametrize('language,output,score', [
    ('python', 'Ran 4 tests in 0.01s\nFAILED (failures=1)', 75),
    ('javascript', '# tests 4\n# fail 1\n# skipped 0\n# cancelled 0', 75),
    ('typescript', '# tests 4\n# fail 0\n# skipped 1\n# cancelled 1', 50),
    ('cpp', 'STUDYFORGE_RESULT 4 1', 75),
])
def test_partial_case_scores(language, output, score):
    result = coding_runtime._result(language, 1, output)
    assert result['ran'] and not result['passed'] and result['score'] == score


@pytest.mark.parametrize('language', ['python', 'javascript', 'typescript', 'cpp'])
def test_compile_failure_and_missing_report_are_not_passes(language):
    failed = coding_runtime._result(language, 1, 'compile error')
    missing = coding_runtime._result(language, 0, '')
    assert failed['ran'] and failed['score'] == 0 and not failed['passed']
    assert not missing['ran']


@pytest.mark.parametrize('exit_code', [125, 126, 127])
def test_runtime_launch_failures_are_provisional(monkeypatch, exit_code):
    def run(command, **options):
        return subprocess.CompletedProcess(command, exit_code if command[1] == 'run' else 0, '', 'runtime error')
    monkeypatch.setattr(coding_runtime.subprocess, 'run', run)
    result = coding_runtime.run_tests('javascript', 'module.exports={};', 'test()', lambda: True)
    assert not result['ran'] and '启动失败' in result['reason']


@pytest.mark.parametrize('language,expected', [
    ('python', 'Ran 3 tests in 0.01s\nOK'),
    ('javascript', '# tests 3\n# fail 0\n# skipped 0\n# cancelled 0'),
    ('typescript', '# tests 3\n# fail 0\n# skipped 0\n# cancelled 0'),
    ('cpp', 'STUDYFORGE_RESULT 3 0'),
])
def test_isolated_language_commands_keep_unicode_and_never_interpolate_code(monkeypatch, language, expected):
    calls = []
    payload = '// 中文; $(danger) `danger`'

    def run(command, **options):
        calls.append(command)
        if command[1] == 'run':
            assert command[command.index('--network')+1] == 'none'
            assert command[command.index('--pull')+1] == 'never'
            assert '--read-only' in command and '--cpus' in command
            mount = command[command.index('--mount') + 1]
            assert mount.endswith(',target=/work,readonly')
            root = Path(mount.removeprefix('type=bind,source=').split(',target=')[0])
            solution = next(root.glob('solution.*'))
            assert solution.read_text(encoding='utf-8') == payload
            assert payload not in ' '.join(command)
            assert coding_runtime.IMAGES[language] in command
        return subprocess.CompletedProcess(command, 0, expected if command[1] == 'run' else '', '')

    monkeypatch.setattr(coding_runtime.subprocess, 'run', run)
    result = coding_runtime.run_tests(language, payload, 'private tests', lambda: True)
    assert result['passed'] and result['score'] == 100 and result['tests'] == 3
    assert calls[0] == ['docker', 'image', 'inspect', coding_runtime.IMAGES[language]]


def test_old_nonpython_assignment_without_tests_stays_provisional(monkeypatch):
    monkeypatch.setattr(coding_runtime.subprocess, 'run', lambda *a, **k: pytest.fail('No Docker or code should run'))
    result = coding_runtime.run_tests('javascript', 'pass', '', lambda: True)
    assert not result['ran'] and '旧作业' in result['reason']


@pytest.mark.parametrize('language', ['javascript', 'typescript', 'cpp'])
def test_new_languages_generate_review_and_run_reference_without_leaking_tests(monkeypatch, language):
    tests = ('void sf_tests(){sf_check("a",[]{return true;});sf_check("b",[]{return true;});sf_check("c",[]{return true;});}'
             if language == 'cpp' else 'test("a",()=>{});test("b",()=>{});test("c",()=>{});')
    generated = {'title':'审计题', 'problem':'合法输入：两个有限整数，相乘返回', 'topic':'乘法',
                 'starter_code':'// TODO', 'reference_code':'// solution', 'test_code':tests}
    reviews = iter([generated, {'passed':True,'blocking_issues':[],'notes':[],'approach':'乘法'},
                    {'passed':True,'blocking_issues':[],'notes':[]}, {'passed':True,'blocking_issues':[],'notes':[]}])
    seen = []

    class Client:
        async def complete(self, *args, **options):
            seen.append(args)
            return json.dumps(next(reviews))

    calls = []
    def reference(selected, code, private_tests):
        calls.append((selected, private_tests))
        return {'ran':True, 'passed':True, 'score':100, 'tests':3}

    monkeypatch.setattr(coding, '_run_assignment_tests', reference)
    project = create_project('多语言测试')
    assignment, reports = asyncio.run(coding.create_assignment(Client(), project['id'], [], '乘法', language=language))
    from studyforge.exercises import public_set
    public = public_set(assignment, reveal=True)
    assert calls == [(language, tests)] and reports[-1]['reference_tests']['passed']
    assert '单元测试 80%' not in json.dumps(public,ensure_ascii=False) and 'test_code' not in public
    assert tests not in json.dumps(public,ensure_ascii=False)
    assert coding_runtime.TEST_RULES[language] in seen[0][0]
