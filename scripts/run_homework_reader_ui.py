"""Run only our isolated localhost fixture and hidden Electron in one environment."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def main(fixture_module='scripts.smoke_homework_reader_ui',ui_script='scripts/smoke_homework_reader_ui.js'):
    name=sys.argv[1]
    folder=(ROOT/'build'/name).resolve()
    if folder.parent != (ROOT/'build').resolve() or folder.exists():
        raise SystemExit('Use a fresh direct build subfolder.')
    folder.mkdir()
    env=dict(os.environ);env['PYTHONIOENCODING']='utf-8';env.pop('ELECTRON_RUN_AS_NODE',None)
    local=folder/'local-temp';local.mkdir();env['TMP']=env['TEMP']=str(local)
    info=None
    if os.name=='nt':
        info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=0
    started=time.perf_counter()
    with (folder/'server.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen([sys.executable,'-X','utf8','-m',fixture_module,name],
            cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,startupinfo=info)
        try:
            for _ in range(900):
                if (folder/'case.json').is_file():break
                if process.poll() is not None:raise RuntimeError('Fixture exited; see server.log')
                time.sleep(.1)
            else:raise TimeoutError('Fixture did not become ready')
            with (folder/'electron.log').open('w',encoding='utf-8') as output:
                result=subprocess.run([str(ROOT/'node_modules/electron/dist/electron.exe'),
                    ui_script,name],cwd=ROOT,env=env,stdout=output,
                    stderr=subprocess.STDOUT,startupinfo=info,timeout=240)
            print(json.dumps({'electron_exit':result.returncode,'seconds':round(time.perf_counter()-started,2),
                              'report':str(folder/'ui-report.json')}),flush=True)
            if result.returncode:raise SystemExit(1)
        finally:
            process.terminate()
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':main()
