"""Run only the generated offline report in a hidden, isolated Electron."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT/'build/teaching-data-scope-acceptance-20261026'


def main():
    env = dict(os.environ)
    env.pop('ELECTRON_RUN_AS_NODE', None)
    local = FOLDER/'local-temp'
    local.mkdir(exist_ok=True)
    env['TMP'] = env['TEMP'] = str(local)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    with (FOLDER/'electron-preview.log').open('w', encoding='utf-8') as log:
        result = subprocess.run([str(ROOT/'node_modules/electron/dist/electron.exe'),
            str(ROOT/'scripts/preview_teaching_scope_report.js'), str(FOLDER/'教学条件保留与真实讲解对照.html')],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, startupinfo=startup, timeout=120)
    report = json.loads((FOLDER/'页面运行核验.json').read_text(encoding='utf-8'))
    assert result.returncode == 0 and report['passed'], report
    assert report['displayed_samples'] == 16 and not report['network_requests']
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()
