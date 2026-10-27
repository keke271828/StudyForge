"""Create a source-only snapshot from Git's upload candidates, never publish."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
DIRECTORIES={'desktop','studyforge','web','scripts','tests','integrations','docs'}
TOP={'.gitignore','README.md','package.json','package-lock.json','pyproject.toml',
     'setup_studyforge.cmd','start_studyforge.cmd','验收最新版.vbs'}
PRIVATE_SUFFIXES={'.db','.sqlite','.sqlite3','.pem','.key','.mp4','.mp3','.pdf','.docx','.apkg','.onnx'}
SECRET_PATTERNS={
    'private_key':re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github_token':re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{60,}'),
    'google_api_key':re.compile(rb'AIza[0-9A-Za-z_-]{35}'),
    'model_api_key':re.compile(rb'sk-(?:proj-|ant-api\d+-)?[A-Za-z0-9_-]{40,}'),
}

def main():
    version=json.loads((ROOT/'package.json').read_text(encoding='utf-8'))['version']
    result=subprocess.run(['git','-c','core.quotepath=false','ls-files','-z','--cached','--others','--exclude-standard'],
        cwd=ROOT,check=True,capture_output=True)
    candidates=sorted(set(Path(name.decode('utf-8')) for name in result.stdout.split(b'\0') if name))
    selected=[];rejected=[];alerts=[]
    for relative in candidates:
        file=(ROOT/relative).resolve()
        if not file.is_relative_to(ROOT) or not file.is_file() or file.is_symlink():
            rejected.append(relative.as_posix());continue
        if relative.as_posix() not in TOP and relative.parts[0] not in DIRECTORIES:
            rejected.append(relative.as_posix());continue
        if file.suffix.lower() in PRIVATE_SUFFIXES or file.name.startswith('.env'):
            rejected.append(relative.as_posix());continue
        if file.stat().st_size>=100*1024**2:raise ValueError('Oversize source candidate: '+relative.as_posix())
        content=file.read_bytes()
        for kind,pattern in SECRET_PATTERNS.items():
            if pattern.search(content):alerts.append({'path':relative.as_posix(),'kind':kind})
        selected.append((relative,content))
    if alerts:
        # Paths/types only: never print a discovered credential value.
        raise ValueError('Review potential credential locations before packaging: '+json.dumps(alerts))
    required={'studyforge/server.py','studyforge/task_recovery.py','web/task_controls.js','web/help/guide.html',
        'desktop/main.js','docs/GitHub上传与发布指南.md','docs/Release-'+version+'.md'}
    names={path.as_posix() for path,content in selected}
    assert required<=names,required-names
    target=ROOT/'dist'/f'StudyForge-source-{version}.zip';target.parent.mkdir(exist_ok=True)
    if target.exists():raise FileExistsError('Preserve the prior snapshot; select a new version or path.')
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for relative,content in selected:archive.writestr(f'StudyForge-source-{version}/'+relative.as_posix(),content)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None and len(archive.namelist())==len(selected)
    digest=hashlib.sha256(target.read_bytes()).hexdigest().upper()
    target.with_name(target.name+'.sha256.txt').write_text(digest+'  '+target.name+'\n',encoding='ascii')
    manifest={'version':version,'files':len(selected),'source_bytes':sum(len(content) for path,content in selected),
        'archive_bytes':target.stat().st_size,'archive_sha256':digest,'published':False,'credential_pattern_alerts':alerts,
        'excluded':rejected,'entries':[{'path':p.as_posix(),'bytes':len(c),'sha256':hashlib.sha256(c).hexdigest()} for p,c in selected]}
    report=ROOT/'build'/f'github-source-{version}-manifest.json'
    report.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k!='entries' and k!='excluded'},ensure_ascii=False))

if __name__=='__main__':main()
