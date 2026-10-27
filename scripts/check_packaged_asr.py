"""Run the frozen GPU silence probe against an already cached model, offline."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from huggingface_hub.constants import HF_HUB_CACHE

root=Path(__file__).resolve().parents[1]
out=root/'build'/('packaged-asr-'+sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
models=Path(HF_HUB_CACHE)/'models--Systran--faster-whisper-small'/'snapshots'
model=next((p for p in models.glob('*') if (p/'model.bin').is_file() and (p/'config.json').is_file()),None)
if model is None:raise SystemExit('No complete cached small model; no model will be downloaded')
exe=root/'dist/win-unpacked/resources/backend/StudyForgeBackend.exe'
env={**os.environ,'STUDYFORGE_DATA_DIR':str(out/'data'),'HF_HUB_OFFLINE':'1','PYTHONUTF8':'1',
     'PATH':str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32')}
for key in ('STUDYFORGE_ASR_CUDA_DIR','PYTHONPATH','PYTHONHOME'):env.pop(key,None)
started=time.perf_counter()
run=subprocess.run([str(exe),'--asr-probe',str(model)],cwd=out,env=env,capture_output=True,
    timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
output=run.stdout.decode('utf-8',errors='replace')
ok=run.returncode==0 and any(line.strip()=='{"ready": true}' for line in output.splitlines())
report={'ok':ok,'gpu_silence_probe':True,'model':str(model),'local_files_only':True,'seconds':round(time.perf_counter()-started,2),
        'exit_code':run.returncode,'stdout':output,'stderr':run.stderr.decode('utf-8',errors='replace')}
(out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False));raise SystemExit(0 if ok else 1)
