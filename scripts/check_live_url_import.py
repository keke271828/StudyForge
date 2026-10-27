"""Optional live URL diagnosis in an isolated project, without model calls."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument('url')
args = parser.parse_args()
root = ROOT / 'build' / ('live-url-' + uuid.uuid4().hex)
root.mkdir(parents=True)
os.environ['STUDYFORGE_DATA_DIR'] = str(root / 'data')
from studyforge import server
from studyforge.db import create_project, create_job, execute, now, one, uid, unj
project = create_project('Live source check')
ident = uid()
execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
        (ident, project['id'], args.url, 'url', args.url, 'pending', now()))
job = create_job(project['id'], 'import_url', {'source_id': ident, 'url': args.url})
asyncio.run(server._url_job(job, ident, args.url))
source = one('SELECT * FROM sources WHERE id=?', (ident,))
task = one('SELECT * FROM jobs WHERE id=?', (job,))
result = {'url': args.url, 'status': task['status'], 'error': task['error'],
          'requires_browser': unj(task['result_json'], {}).get('requires_browser', False),
          'segments': len(unj(source['segments_json'], [])), 'origin_url': source['origin_url']}
(root / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'report': str(root / 'report.json'), 'result': result}, ensure_ascii=False))
