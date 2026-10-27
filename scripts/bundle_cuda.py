"""Keep loader-root CUDA DLLs and remove only byte-identical nested copies."""
import hashlib
from pathlib import Path


def deduplicate_cuda(binaries, datas):
    roots={};digests={};removed=[]
    def destination(row):return str(row[0]).replace('\\','/')
    for row in [*binaries,*datas]:
        name=destination(row)
        if '/' not in name and name.lower().endswith('.dll'):
            roots.setdefault(name.casefold(),[]).append(row)
    def digest(path):
        path=Path(path)
        if path not in digests:
            with path.open('rb') as stream:digests[path]=hashlib.file_digest(stream,'sha256').hexdigest()
        return digests[path]
    def keep(row):
        name=destination(row)
        if not name.casefold().startswith('resources/asr-cuda/') or not name.lower().endswith('.dll'):return True
        matches=roots.get(name.rsplit('/',1)[-1].casefold(),[])
        if len(matches)!=1:return True
        retained=matches[0];source,other=Path(row[1]),Path(retained[1])
        if not source.is_file() or not other.is_file() or source.stat().st_size!=other.stat().st_size:return True
        if digest(source)!=digest(other):return True
        removed.append({'removed':name,'retained':destination(retained),'bytes':source.stat().st_size,'sha256':digest(source)})
        return False
    return [row for row in binaries if keep(row)],[row for row in datas if keep(row)],removed
