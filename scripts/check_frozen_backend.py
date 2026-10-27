"""Exercise the shipped runtime in isolated data, without external Python/Node."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid


def main() -> None:
    repo = Path(__file__).resolve().parent.parent
    root = repo / 'build' / ('frozen-backend-check-' + uuid.uuid4().hex)
    root.mkdir(parents=True)
    executable = repo / 'dist' / 'win-unpacked' / 'resources' / 'backend' / 'StudyForgeBackend.exe'
    assert executable.is_file(), executable
    environment = {**os.environ, 'STUDYFORGE_DATA_DIR': str(root / 'data'),
        'PATH': str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32'),
        'PYTHONUTF8': '1'}
    environment.pop('PYTHONPATH', None)
    environment.pop('PYTHONHOME', None)
    report = {'ok': False, 'root': str(root), 'checks': []}
    try:
        completed = subprocess.run([str(executable), '--self-check'], cwd=root, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW)
        output = completed.stdout.decode('utf-8', errors='replace')
        (root / 'backend.log').write_text(output, encoding='utf-8')
        assert completed.returncode == 0, f'Frozen self-check failed ({completed.returncode}); see {root / "backend.log"}'
        result = next((json.loads(line) for line in reversed(output.splitlines())
            if line.startswith('{') and '"exports"' in line), None)
        assert result and result['ok'] and len(result['exports']) == 13
        assert result.get('api_network') == {'environment_mode': True, 'direct_mode': True, 'certificate_verification': True}
        report['runtime'] = result
        report['checks'].append('13 native export formats generate and reparse; OCR, bundled FFmpeg, voice and credential dependencies load')
        resources = Path(result['web'])
        hashes = {}
        for source in sorted((repo / 'web').rglob('*')):
            if not source.is_file():
                continue
            relative = source.relative_to(repo / 'web').as_posix()
            shipped = resources / relative
            assert shipped.is_file(), f'Missing packaged asset: {relative}'
            assert shipped.read_bytes() == source.read_bytes(), f'Stale packaged asset: {relative}'
            hashes[relative] = hashlib.sha256(shipped.read_bytes()).hexdigest()
        report['asset_sha256'] = hashes
        report['checks'].append('API routing, learning checks, source evidence, reading, phone, history and guide assets exactly match the accepted source')
        report['ok'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        (root / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
