from pathlib import Path
import json
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
datas = [(str(root / 'web'), 'web')]
datas += [(str(root / 'LICENSE'), 'licenses'), (str(root / 'THIRD_PARTY_NOTICES.md'), 'licenses')]
if (root/'resources/asr-cuda/manifest.json').is_file():
    # Optional verified CUDA component. Keep licenses and relative DLL layout;
    # CPU execution remains available if this component is absent.
    datas.append((str(root/'resources/asr-cuda'),'resources/asr-cuda'))
binaries = []
hiddenimports = ['studyforge.server', 'studyforge.mcp_server', 'studyforge.packaging_check',
                 'studyforge.asr_backend',
                 'studyforge.mobile_access', 'studyforge.mobile_context', 'studyforge.mobile_tls', 'studyforge.source_scope',
                 'qrcode.image.svg',
                 'keyring.backends.Windows', 'pyttsx3.drivers.sapi5', 'uvicorn.logging',
                 'uvicorn.loops.asyncio', 'uvicorn.protocols.http.h11_impl',
                 'uvicorn.protocols.http.httptools_impl', 'uvicorn.protocols.websockets.websockets_impl',
                 'uvicorn.lifespan.on', 'win32timezone']
for package in ('rapidocr', 'faster_whisper', 'ctranslate2', 'onnxruntime', 'imageio_ffmpeg',
                'tokenizers', 'av', 'latex2mathml', 'zstandard'):
    data, binary, imports = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += imports
hiddenimports += collect_submodules('yt_dlp')
hiddenimports += collect_submodules('fontTools.ttLib.tables')
hiddenimports += ['fontTools.ttLib.woff2', 'brotli']
datas += collect_data_files('genanki')
datas += copy_metadata('studyforge', recursive=True)

a = Analysis([str(root / 'scripts' / 'backend_entry.py')], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=['pytest', '_pytest', 'tkinter', 'IPython', 'torch', 'tensorflow', 'paddle'],
             noarchive=False)
from scripts.bundle_cuda import deduplicate_cuda
a.binaries,a.datas,removed = deduplicate_cuda(a.binaries,a.datas)
(root/'build/cuda-duplicate-report.json').write_text(json.dumps({
    'removed_files':removed,'saved_bytes':sum(row['bytes'] for row in removed),
    'retained_loader_root':True,'licenses_preserved':True},indent=2),encoding='utf-8')
print(f'CUDA bundle: removed {len(removed)} identical nested copies; saved {sum(row["bytes"] for row in removed)} bytes')
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='StudyForgeBackend',
          debug=False, strip=False, upx=False, console=True,
          icon=str(root / 'desktop' / 'assets' / 'studyforge.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='StudyForgeBackend')
