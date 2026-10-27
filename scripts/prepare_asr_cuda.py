"""Stage official NVIDIA Windows runtime wheels privately, verifying PyPI SHA.

No global installation, registry/driver change or user database mutation. This
developer preparation tool uses direct HTTPS for these fixed public PyPI hosts
because the system proxy may stall large wheels; certificate checks remain on.
"""
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile
import subprocess
from concurrent.futures import ThreadPoolExecutor


def download_ranges(opener,url,target,size):
    # Bound memory and use short, verified ranges when a CDN full-file transfer
    # stalls. Only these public runtime wheels use direct HTTPS.
    chunk_size=4*1024*1024
    folder=target.parent/(target.stem+'-chunks');folder.mkdir(exist_ok=True)
    def fetch(index):
        start=index*chunk_size;end=min(size-1,start+chunk_size-1);path=folder/f'{index:05}.part'
        if path.exists() and path.stat().st_size==end-start+1:return path
        for attempt in range(3):
            try:
                headers=path.with_suffix('.headers')
                result=subprocess.run(['curl.exe','--noproxy','*','--fail','--silent','--show-error','--max-time','45',
                    '--range',f'{start}-{end}','--dump-header',str(headers),'--output',str(path),url],capture_output=True,timeout=50)
                if result.returncode:raise RuntimeError('Runtime range transfer failed')
                if f'content-range: bytes {start}-{end}/{size}' not in headers.read_text(encoding='utf-8').lower():raise RuntimeError('Unexpected runtime range')
                if path.stat().st_size!=end-start+1:raise RuntimeError('Incomplete runtime range')
                return path
            except Exception:
                if attempt==2:raise
    indices=range((size+chunk_size-1)//chunk_size)
    with ThreadPoolExecutor(max_workers=8) as executor:paths=list(executor.map(fetch,indices))
    digest=hashlib.sha256()
    with target.open('wb') as output:
        for path in paths:
            with path.open('rb') as source:
                while chunk:=source.read(1024*1024):output.write(chunk);digest.update(chunk)
    return digest.hexdigest()

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'build/asr-quality-performance-20261012'
TARGET=FOLDER/'cuda-runtime'
PACKAGES=('nvidia-cublas-cu12','nvidia-cudnn-cu12','nvidia-cuda-runtime-cu12')


def main():
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    wheels=FOLDER/'wheels';wheels.mkdir(exist_ok=True);TARGET.mkdir(exist_ok=True)
    manifest=[]
    for package in PACKAGES:
        result=subprocess.run(['curl.exe','--noproxy','*','--fail','--silent','--show-error','--max-time','30',
             'https://pypi.org/pypi/'+package+'/json'],capture_output=True,timeout=35)
        if result.returncode:raise RuntimeError('Official runtime metadata unavailable')
        data=json.loads(result.stdout)
        value=next(item for item in data['urls'] if item['filename'].endswith('py3-none-win_amd64.whl'))
        path=wheels/value['filename'];digest=hashlib.sha256()
        if path.is_file():
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256')
        if not path.is_file() or digest.hexdigest()!=value['digests']['sha256']:
            print('Downloading '+value['filename']+' ('+str(round(value['size']/1024**2))+' MiB)',flush=True)
            partial=path.with_suffix('.part')
            actual=download_ranges(opener,value['url'],partial,value['size'])
            if actual!=value['digests']['sha256']:raise RuntimeError('NVIDIA runtime checksum mismatch')
            partial.replace(path)
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                destination=(TARGET/item.filename).resolve()
                if not destination.is_relative_to(TARGET.resolve()):raise RuntimeError('Wheel extraction escaped runtime directory')
            archive.extractall(TARGET)
        manifest.append(dict(package=package,version=data['info']['version'],file=value['filename'],size=value['size'],sha256=value['digests']['sha256']))
        print('Verified and staged '+package,flush=True)
    (TARGET/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(str(TARGET),flush=True)


if __name__=='__main__':main()
