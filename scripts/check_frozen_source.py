"""Compare the actual shipped Python code with current local sources.

Read PyInstaller's archive without importing or executing its modules. Ignore
debug filename/line metadata; compare executable bytecode and constants.
"""
import hashlib
import json
from pathlib import Path
import types

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]


def normalized(value):
    if isinstance(value, types.CodeType):
        fields = ('co_argcount','co_posonlyargcount','co_kwonlyargcount','co_nlocals',
            'co_stacksize','co_flags','co_code','co_consts','co_names','co_varnames',
            'co_name','co_qualname','co_freevars','co_cellvars','co_exceptiontable')
        return {'code':{key:normalized(getattr(value,key)) for key in fields}}
    if isinstance(value, bytes): return {'bytes':value.hex()}
    if isinstance(value, tuple): return {'tuple':[normalized(x) for x in value]}
    if isinstance(value, frozenset):
        return {'frozenset':sorted((normalized(x) for x in value),key=lambda x:json.dumps(x,sort_keys=True))}
    if value is Ellipsis: return {'ellipsis':True}
    if isinstance(value, complex): return {'complex':[value.real,value.imag]}
    return value


def main():
    version = json.loads((ROOT/'package.json').read_text(encoding='utf-8'))['version']
    exe = ROOT/'dist/win-unpacked/resources/backend/StudyForgeBackend.exe'
    archive = CArchiveReader(str(exe))
    pyz = archive.open_embedded_archive(next(name for name in archive.toc if name.endswith('.pyz')))
    # This predecessor is retained only for old handoff-format tests. Current
    # tutor/writer tasks share their dialogue instead; no production import
    # refers to this retired module. Do not silently exempt any other module.
    retired = {'studyforge.mentor_handoff'}
    report = {'ok':False,'version':version,'modules':{},'uncollected_retired_modules':[],
        'executed_model_requests':0}
    for source in sorted((ROOT/'studyforge').rglob('*.py')):
        relative = source.relative_to(ROOT).as_posix()
        parts = source.relative_to(ROOT).with_suffix('').parts
        module = '.'.join(parts[:-1] if parts[-1]=='__init__' else parts)
        if module not in pyz.toc:
            assert module in retired, 'Unexpected missing frozen module: '+module
            report['uncollected_retired_modules'].append(module)
            continue
        expected = normalized(compile(source.read_bytes(),str(source),'exec',dont_inherit=True,optimize=0))
        actual = normalized(pyz.extract(module))
        assert actual == expected, 'Frozen Python differs: '+relative
        report['modules'][module] = {'source':relative,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'executable_sha256':hashlib.sha256(json.dumps(actual,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
    assert 'studyforge.teaching_policy' in report['modules'] and 'studyforge.review' in report['modules']
    report.update(ok=True,module_count=len(report['modules']))
    target = ROOT/'build'/f'release-{version}-frozen-source.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='modules'},ensure_ascii=False))


if __name__=='__main__':main()
