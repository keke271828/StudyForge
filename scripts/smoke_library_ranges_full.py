"""Check the entire directory of a supplied scan, without cloud calls.

Run with an existing isolated acceptance data folder. This never uses the
installed app's database; it keeps the original PDF and page-row evidence.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = (root / 'build' / sys.argv[1]).resolve()
if not target.is_relative_to((root / 'build').resolve()):
    raise ValueError('Acceptance data must stay under build')
os.environ['STUDYFORGE_DATA_DIR'] = str(target / 'data')

from studyforge import library, library_ranges, library_worker
from studyforge.db import j, many, one, unj


async def main():
    book = many('SELECT * FROM library_books')[0]
    nodes = many('SELECT * FROM library_nodes WHERE book_id=? ORDER BY position', (book['id'],))
    job = library_ranges.range_job(book['id'], [n['id'] for n in nodes],
                                   foreground=True, allow_ai=False)
    worker = library_worker.LibraryWorker(
        lambda p: (_ for _ in ()).throw(AssertionError('No cloud call for scope acceptance')))
    started = time.perf_counter()
    worker.launch(job['id'])
    task = worker.tasks[job['id']]
    previous = None
    while not task.done():
        row = one('SELECT * FROM library_jobs WHERE id=?', (job['id'],))
        stage = unj(row['result_json'], {}).get('stage', row['status'])
        if stage != previous:
            print(stage, flush=True)
            previous = stage
        await asyncio.sleep(1)
    await task
    result = library.public_job(one('SELECT * FROM library_jobs WHERE id=?', (job['id'],)))
    current = library.details(book['id'])['nodes']
    report = {'version': library_ranges.VERSION, 'elapsed_seconds': round(time.perf_counter()-started, 3),
              'total_nodes': len(nodes), 'confirmed_before': sum(n['confirmed'] for n in nodes),
              'confirmed_after': sum(n['confirmed'] for n in current), 'job': result, 'cloud_calls': 0}
    name = sys.argv[2] if len(sys.argv) > 2 else 'full-report.json'
    (target/name).write_text(j(report), encoding='utf-8')
    print(j({k: v for k, v in report.items() if k != 'job'}), flush=True)
    for n in result['result'].get('ranges', []):
        if not n['reliable']:
            print('PENDING', n['title'], n['reason'],
                  None if not n['start'] else (n['start']['page'], n['start']['text'], round(n['start']['score'],3)),
                  None if not n['next_heading'] else (n['next_heading']['page'], n['next_heading']['text'], round(n['next_heading']['score'],3)), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
