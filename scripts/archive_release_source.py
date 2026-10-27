"""Create a source-only release snapshot from explicit public-development paths."""
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ('studyforge','web','desktop','scripts','tests','docs')
ROOT_FILES = ('.gitignore','README.md','package.json','package-lock.json','pyproject.toml',
    'setup_studyforge.cmd','start_studyforge.cmd','验收最新版.vbs')
EXCLUDE_PARTS = {'__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','.git',
    'node_modules','data','cache','logs'}
EXCLUDE_SUFFIXES = {'.pyc','.pyo','.log','.sqlite','.sqlite3','.db','.pem','.key','.pfx','.p12'}


def main():
    version = json.loads((ROOT/'package.json').read_text(encoding='utf-8'))['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+',version): raise ValueError('Invalid release version')
    target = ROOT/'dist'/f'StudyForge-source-{version}.zip'
    if target.exists(): raise FileExistsError('Preserve the existing release snapshot.')
    sources = [ROOT/name for name in ROOT_FILES]
    for folder in DIRECTORIES:
        for path in (ROOT/folder).rglob('*'):
            relative = path.relative_to(ROOT)
            if (not path.is_file() or path.is_symlink() or any(p in EXCLUDE_PARTS for p in relative.parts)
                    or path.suffix.lower() in EXCLUDE_SUFFIXES or path.name.startswith('.env')):
                continue
            sources.append(path)
    manifest = {'version':version,'source_only':True,'files':{},'limited_credential_pattern_alerts':[],
        'not_included':['user study data','model weights','build output','dependencies','Git history']}
    credential = re.compile(rb'(?:sk-(?:proj-)?[A-Za-z0-9_-]{32,}|AIza[0-9A-Za-z_-]{35}|gh[pousr]_[A-Za-z0-9]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
    for path in sorted(set(sources)):
        data = path.read_bytes()
        relative = path.relative_to(ROOT).as_posix()
        if len(data)>25*1024*1024: raise ValueError('Unexpected large source: '+relative)
        # Regexes and fixtures sometimes contain literal markers. A hit stops
        # packaging for manual inspection; it is never silently excluded.
        if credential.search(data): manifest['limited_credential_pattern_alerts'].append(relative)
        manifest['files'][relative] = hashlib.sha256(data).hexdigest()
    if manifest['limited_credential_pattern_alerts']:
        raise ValueError('Inspect potential credentials in '+repr(manifest['limited_credential_pattern_alerts']))
    with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for relative in manifest['files']: archive.write(ROOT/relative,'StudyForge/'+relative)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        for relative,expected in manifest['files'].items():
            assert hashlib.sha256(archive.read('StudyForge/'+relative)).hexdigest()==expected
    manifest.update(path=str(target),bytes=target.stat().st_size,
        sha256=hashlib.sha256(target.read_bytes()).hexdigest().upper(),file_count=len(manifest['files']))
    (target.with_suffix(target.suffix+'.sha256.txt')).write_text(
        manifest['sha256']+'  '+target.name+'\r\n',encoding='ascii')
    (ROOT/'build'/f'release-{version}-source.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k!='files'},ensure_ascii=False))


if __name__=='__main__': main()
