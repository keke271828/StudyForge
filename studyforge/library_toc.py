"""Bounded local discovery of a textbook's contents pages, not book reading."""
from __future__ import annotations

import asyncio
import re
import unicodedata

from . import library
from .db import connect, execute, j, now, one, unj
from .scheduling import run_local

VERSION = 'front-contents-v2'
DEFAULT_SCAN_LIMIT = 32
MAX_SCAN_LIMIT = 64
MAX_TOC_PAGES = 12
APPLIED_STEP = 'toc-outline-applied-v2'


def classify_rows(rows, width, page_count):
    """Require contents-page layout as well as plausible titles/page numbers."""
    entries = library.parse_directory([(0, rows)])
    entries = [n for n in entries if n['printed_page'] <= max(page_count * 2, 50)]
    by_text = {r['text']: r for r in rows}
    layouts = 0
    for entry in entries:
        row = by_text[entry['provenance']['row']]
        leaders = re.search(r'[.．·…•。]{2,}', row['text'])
        column = any(p.get('x', 0) >= width * .6 and
                     re.fullmatch(r'\d{1,4}', p['text'].strip()) for p in row.get('parts', []))
        layouts += bool(leaders or column or row.get('number_column'))
    labels = []
    for row in rows[:8]:
        text = unicodedata.normalize('NFKC', row['text']).lower()
        text = re.sub(r'[\s·.。:：()（）\d-]', '', text)
        text = re.sub(r'^[ivxlcdm|]+(?=目录|目次)', '', text)
        if text in ('目录', '目次', '目录续', '续目录', 'contents', 'tableofcontents', 'contentscontinued'):
            labels.append(row['text'])
    numbers = [n['printed_page'] for n in entries]
    ordered = (len(numbers) < 2 or
               sum(b >= a for a, b in zip(numbers, numbers[1:])) / (len(numbers) - 1) >= .8)
    density = len(entries) / max(1, sum(bool(r['text'].strip()) for r in rows))
    strong = ordered and ((bool(labels) and len(entries) >= 2 and (layouts or density >= .5)) or
                          (len(entries) >= 4 and layouts >= max(3, len(entries) * .6) and density >= .38))
    continuation = ordered and ((len(entries) >= 2 and layouts >= max(1, len(entries) * .4) and density >= .3) or
                                (len(entries) == 1 and layouts >= 1 and density >= .4))
    return {'entries': len(entries), 'layouts': layouts, 'label': labels[:2],
            'strong': bool(strong), 'continuation': bool(continuation), 'ordered': ordered,
            'samples': [n['title'] + ' · ' + str(n['printed_page']) for n in entries[:4]]}


def probe_page(book, page):
    """Cache only layout evidence; temporary OCR images are released per page."""
    import fitz
    folder = library.root() / book['id'] / 'toc-discovery'
    folder.mkdir(exist_ok=True)
    cache = folder / f'{VERSION}-{page}.json'
    if cache.is_file():
        saved = unj(cache.read_text(encoding='utf-8'), {})
        if saved.get('sha256') == book['sha256']:
            return saved
    path = cache.with_suffix('.png')
    try:
        with fitz.open(book['original_path']) as document:
            original = document[page - 1]
            width = original.rect.width
            rows = library.geometric_rows([
                {'x': x0, 'y': (y0 + y1) / 2, 'height': y1 - y0, 'text': word, 'score': None}
                for x0, y0, x1, y1, word, *_ in original.get_text('words')])
            native = len(original.get_text().strip()) > 30
            if not native and rows:
                layout = classify_rows(rows, width, book['page_count'])
                native = layout['strong'] or layout['continuation']
            if not native:
                # Bound a single page even when a scan uses very large coordinates.
                scale = min(1.5, 1800 / max(original.rect.width, original.rect.height))
                image = original.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                width = image.width
                image.save(path)
                del image
        if not native:
            rows = library.ocr_rows(path)
        result = classify_rows(rows, width, book['page_count']) | {
            'page': page, 'method': 'native_pdf' if native else 'local_ocr', 'sha256': book['sha256']}
        # Body-page text is not saved as a reading or added to the knowledge index.
        temporary = cache.with_suffix('.tmp')
        temporary.write_text(j(result), encoding='utf-8')
        temporary.replace(cache)
        return result
    finally:
        path.unlink(missing_ok=True)


async def discover(control, book, scan_limit=DEFAULT_SCAN_LIMIT):
    limit = min(book['page_count'], max(1, min(scan_limit, MAX_SCAN_LIMIT)))
    inspected, found, pending = [], [], []
    misses = 0
    stopped = False
    overflow = False
    for page in range(1, limit + 1):
        control.stage(f'本机查找目录 · PDF 第 {page}/{limit} 页 · 不通读正文',
                      discovery_pages_checked=len(inspected), discovery_scan_limit=limit)
        result = await control.step('toc-probe', [VERSION, book['sha256'], page],
                                    lambda p=page: run_local('image', probe_page, book, p))
        inspected.append(result)
        hit = result['strong'] or (bool(found) and result['continuation'])
        if hit:
            if len(found) >= MAX_TOC_PAGES:
                overflow = True
                break
            if not found and pending and pending[-1]['page'] == page - 1 and pending[-1]['continuation']:
                found.append(pending[-1])
            found.append(result)
            misses = 0
        elif found:
            misses += 1
            if misses >= 2:
                stopped = True
                break
        elif result['entries'] or result['label']:
            pending.append(result)
        execute('UPDATE library_jobs SET progress=?,updated_at=? WHERE id=?',
                (min(40, int(40 * page / limit)), now(), control.job_id))
    warnings = []
    if overflow:
        warnings.append('目录超过一次可识别的 12 页；没有截断后自动建立。请核对原页或拆分目录。')
    truncated = bool(found) and not stopped and not overflow and found[-1]['page'] == limit and limit < book['page_count']
    if truncated:
        warnings.append('查找范围末页仍像目录，可能还有后续页；请扩大查找范围或手动指定。')
    if not found:
        warnings.append(f'前 {limit} 页未找到可靠目录；可扩大查找范围或手动指定目录页。')
    gaps = [p for p in inspected if found and found[0]['page'] < p['page'] < found[-1]['page'] and p not in found]
    if gaps:
        warnings.append('连续目录中有未识别的页面（PDF '+ '、'.join(str(p['page']) for p in gaps)+'），请核对；没有静默跳过后自动建立。')
        found=sorted(found+gaps,key=lambda p:p['page'])
    evidence = found if found else pending[-MAX_TOC_PAGES:]
    return {'version': VERSION, 'status': 'found' if found and not (overflow or truncated or gaps) else 'review',
            'scan_limit': limit, 'inspected_pages': [p['page'] for p in inspected],
            'candidate_pages': [p['page'] for p in evidence],
            'evidence': [{k: p[k] for k in ('page', 'method', 'entries', 'label', 'samples')} for p in evidence],
            'warnings': warnings, 'model_requests': 0}


def commit_outline(book_id, nodes, page_spec, job_id, result):
    """Persist the outline and completion checkpoint in one transaction."""
    with connect() as database:
        database.execute('BEGIN IMMEDIATE')
        saved = database.execute('SELECT response_json FROM library_steps WHERE job_id=? AND step_key=?',
                                 (job_id, APPLIED_STEP)).fetchone()
        if saved:
            return unj(saved['response_json'])
        job = database.execute('SELECT status FROM library_jobs WHERE id=?', (job_id,)).fetchone()
        if not job or job['status'] == 'cancelled':
            raise asyncio.CancelledError()
        library.save_outline(book_id, nodes, database=database)
        database.execute('UPDATE library_books SET toc_pages=? WHERE id=?', (page_spec, book_id))
        database.execute('INSERT INTO library_steps VALUES (?,?,?,?)', (job_id, APPLIED_STEP, j(result), now()))
    return result


def applied_result(job_id):
    saved = one('SELECT response_json FROM library_steps WHERE job_id=? AND step_key=?', (job_id, APPLIED_STEP))
    return unj(saved['response_json']) if saved else None
