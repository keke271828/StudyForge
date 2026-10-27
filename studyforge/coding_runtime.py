"""Language adapters for tests run only inside Docker, never on the host."""
from pathlib import Path
import re
import subprocess
import tempfile
from uuid import uuid4

from .runtime import background_process_options

IMAGES = {'python': 'python:3.12-alpine', 'javascript': 'node:22-alpine',
          'typescript': 'mcr.microsoft.com/devcontainers/typescript-node:22-bookworm',
          'cpp': 'gcc:14-bookworm'}

TEST_RULES = {
    'python': 'test_code 导入 solution.py，至少 3 个 unittest 测试方法。',
    'javascript': 'reference_code 与 starter_code 使用 CommonJS module.exports 导出同一接口。'
                  'test_code 使用 node:test 的 test 与 node:assert/strict，require("./solution") 导入实现，至少 3 个独立 test 调用。',
    'typescript': 'reference_code 与 starter_code 使用 export 导出同一接口，能通过 tsc --strict --target ES2022 --module commonjs。'
                  'test_code 是 JavaScript（不是 TypeScript），使用 node:test 的 test 与 node:assert/strict，'
                  'require("./solution") 导入编译后的实现，至少 3 个独立 test 调用。',
    'cpp': '代码为 C++17，仅定义函数或类，不含 main。test_code 是完整 C++17 测试文件，'
           '#include "solution.cpp"，定义 void sf_tests()，至少 3 个 sf_check("测试名称", [](){ return 布尔判定; }); 调用。'
           'sf_check 由运行器提供，无需定义，不定义 main，不使用 exit 或打印测试总分。',
}

CPP_HARNESS = r'''
#include <iostream>
#include <exception>
#include <utility>
static int sf_total = 0, sf_errors = 0;
template<class F> void sf_check(const char* name, F check) {
    ++sf_total;
    bool ok = false;
    try { ok = bool(check()); } catch (...) {}
    if (!ok) { ++sf_errors; std::cerr << "FAIL: " << name << '\n'; }
}
'''
CPP_FOOTER = r'''
int main() {
    try { sf_tests(); } catch (...) { ++sf_errors; }
    std::cout << "\nSTUDYFORGE_RESULT " << sf_total << " " << sf_errors << "\n";
    return sf_total > 0 && sf_errors == 0 ? 0 : 1;
}
'''


def test_count(tests, language):
    pattern = r'\b(?:test|it)\s*\(' if language in ('javascript', 'typescript') else r'\bsf_check\s*\('
    return len(re.findall(pattern, tests))


def _prepare(root, language, code, tests):
    extension = {'python': 'py', 'javascript': 'js', 'typescript': 'ts', 'cpp': 'cpp'}[language]
    (root / f'solution.{extension}').write_text(code, encoding='utf-8')
    if language == 'python':
        (root / 'test_solution.py').write_text(tests, encoding='utf-8')
        return ['python', '-m', 'unittest', 'discover', '-v']
    if language in ('javascript', 'typescript'):
        (root / 'test_solution.js').write_text(tests, encoding='utf-8')
        if language == 'javascript':
            return ['node', '--test', '--test-reporter=tap', 'test_solution.js']
        # This shell string is fixed application code; submitted code is in files.
        return ['sh', '-c', 'tsc --strict --target ES2022 --module commonjs --outDir /tmp/compiled /work/solution.ts '
                '&& cp /work/test_solution.js /tmp/compiled/test_solution.js '
                '&& node --test --test-reporter=tap /tmp/compiled/test_solution.js']
    (root / 'test_solution.cpp').write_text(CPP_HARNESS + '\n' + tests + '\n' + CPP_FOOTER, encoding='utf-8')
    return ['sh', '-c', 'g++ -std=c++17 -O0 /work/test_solution.cpp -o /tmp/suite && /tmp/suite']


def _result(language, exit_code, output):
    if language == 'python':
        match = re.search(r'Ran (\d+) tests?', output)
        total = int(match[1]) if match else 0
        errors = sum(int(v) for v in re.findall(r'(?:failures|errors)=(\d+)', output))
    elif language in ('javascript', 'typescript'):
        match = re.search(r'^# tests (\d+)\s*$', output, re.M)
        failure = re.search(r'^# fail (\d+)\s*$', output, re.M)
        skipped = re.search(r'^# skipped (\d+)\s*$', output, re.M)
        cancelled = re.search(r'^# cancelled (\d+)\s*$', output, re.M)
        total = int(match[1]) if match else 0
        # A skipped or cancelled case has not established correctness.
        errors = sum(int(m[1]) for m in (failure, skipped, cancelled) if m)
    else:
        match = re.search(r'^STUDYFORGE_RESULT (\d+) (\d+)\s*$', output, re.M)
        total, errors = (int(match[1]), int(match[2])) if match else (0, 0)
    passed = exit_code == 0 and total > 0 and errors == 0
    # No report with a successful exit is not evidence of passed tests.
    if exit_code == 0 and not total:
        return {'ran': False, 'reason': '测试没有产生有效结果，请检查私有测试；仅保留静态审查', 'output': output}
    score = round(100 * max(0, total - errors) / total, 1) if total else 0
    if exit_code != 0 and errors == 0: score = 0
    return {'ran': True, 'passed': passed, 'score': score, 'tests': total, 'output': output}


def run_tests(language, code, tests, docker_available):
    if language not in IMAGES:
        return {'ran': False, 'reason': '此语言尚无原生隔离运行器；仅完成静态审查'}
    if not tests.strip():
        return {'ran': False, 'reason': '这份旧作业没有私有运行测试；仅完成静态审查，请重新布置作业'}
    if not docker_available():
        return {'ran': False, 'reason': 'Docker Desktop 未安装或未启动；仅完成静态审查'}
    image = IMAGES[language]
    options = dict(capture_output=True, text=True, encoding='utf-8', errors='replace', **background_process_options())
    try:
        inspected = subprocess.run(['docker', 'image', 'inspect', image], timeout=10, **options)
    except (OSError, subprocess.TimeoutExpired):
        return {'ran': False, 'reason': '无法检查 Docker 镜像；仅完成静态审查'}
    if inspected.returncode:
        return {'ran': False, 'reason': f'判题镜像尚未准备，请先执行 docker pull {image}；仅完成静态审查'}
    with tempfile.TemporaryDirectory(prefix='studyforge-code-') as folder:
        root = Path(folder)
        program = _prepare(root, language, code, tests)
        container = 'studyforge-grade-' + uuid4().hex
        command = ['docker', 'run', '--rm', '--name', container, '--pull', 'never', '--network', 'none',
                   '--memory', '512m', '--cpus', '1', '--pids-limit', '64', '--read-only',
                   '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                   '--tmpfs', '/tmp:rw,nosuid,size=64m',
                   '--mount', f'type=bind,source={root.resolve()},target=/work,readonly',
                   '-w', '/work', image, *program]
        try:
            result = subprocess.run(command, timeout=90, **options)
        except subprocess.TimeoutExpired:
            # Killing the CLI does not kill its container. Remove our UUID name only.
            try:
                subprocess.run(['docker', 'rm', '-f', container], timeout=10, **options)
            except (OSError, subprocess.TimeoutExpired):
                return {'ran': True, 'passed': False, 'score': 0, 'output': '测试超时（90 秒）；容器清理失败',
                        'cleanup_container': container}
            return {'ran': True, 'passed': False, 'score': 0, 'output': '测试超时（90 秒），已清理本次判题容器'}
        except OSError:
            return {'ran': False, 'reason': 'Docker 进程无法启动；仅完成静态审查'}
        output = (result.stdout + '\n' + result.stderr)[-10000:]
        if result.returncode in (125, 126, 127):
            return {'ran': False, 'reason': 'Docker 或语言运行环境启动失败；仅完成静态审查', 'output': output}
        return _result(language, result.returncode, output)
