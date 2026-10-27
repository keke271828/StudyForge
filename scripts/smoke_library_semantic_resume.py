"""Verify the real pinned downloader by resuming only the final 64 KiB/file."""
import json
import os
from pathlib import Path
import shutil
import sys
import time

base=Path(__file__).resolve().parents[1]
folder=base/'build'/(sys.argv[1] if len(sys.argv)>1 else 'library-semantic-resume-20261010-1')
if folder.exists():raise SystemExit('Use a fresh evidence directory.')
folder.mkdir(parents=True)
os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'model')
sys.path.insert(0,str(base))
from studyforge import library_semantic as semantic

root=semantic.model_root();root.mkdir(parents=True)
for name,(_,size,_) in semantic.FILES.items():
    source=base/'resources/library-semantic-e5'/name
    target=root/(name+'.partial')
    shutil.copyfile(source,target)
    with target.open('r+b') as stream:stream.truncate(size-65536)
started=time.perf_counter()
semantic.download_model()
report={'passed':semantic.model_ready(),'seconds':time.perf_counter()-started,'model':semantic.REPO,
        'resumed_tail_bytes_per_file':65536,'state':semantic.download_state(),'model_calls':0}
(folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False),flush=True)
assert report['passed']
