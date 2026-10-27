"""Compare the saved real query implementation on an isolated ten-book fixture.

The stored notes/pages are synthetic: this measures database/query overhead,
not OCR, textbook understanding, model speed, or total application memory.
Prepare once, then run each mode in a separate Python process.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmark_video_ab import peak_ram_mb


def load_previous(folder):
    name = 'studyforge._library_scale_before'
    spec = importlib.util.spec_from_file_location(name, folder / 'library.before.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(folder, books, pages, nodes, note_chars):
    from studyforge import library
    from studyforge.db import connect, j
    db_path = folder / 'data' / 'studyforge.sqlite3'
    if db_path.exists(): raise ValueError('Fixture already exists; use a new isolated folder')
    folder.mkdir(parents=True, exist_ok=True)
    # Preserve a baseline only when preparing before a source change. Refuse
    # measurement without the explicit source snapshot.
    if not (folder / 'library.before.py').is_file(): raise ValueError('Missing pre-change library snapshot')
    timestamp = '2026-10-10T08:00:00+00:00'
    book_ids = []
    current_ids = []
    note_rows = 0
    original_rows = 0
    with connect() as db:
        for bi in range(books):
            book_id = f'scale-book-{bi:02}'
            b = {'id': book_id, 'sha256': f'{bi+1:064x}'}
            book_ids.append(book_id)
            db.execute('INSERT INTO library_books(id,title,filename,original_path,sha256,page_count,created_at,updated_at) '
                       'VALUES (?,?,?,?,?,?,?,?)',
                       (book_id, f'数理教材负载样例 {bi+1}', f'fixture-{bi}.pdf', str(folder/f'fixture-{bi}.pdf'),
                        b['sha256'], pages, timestamp, timestamp))
            for ni in range(nodes):
                begin = ni * pages // nodes + 1
                end = (ni+1) * pages // nodes
                n = {'id': f'{book_id}-node-{ni:03}', 'start_page': begin, 'end_page': end,
                     'start_y': 0.0, 'end_y': 1.0}
                # The final node retains historical rows but has an unconfirmed
                # current scope. No search/status operation may expose its notes.
                confirmed = ni != nodes-1
                db.execute('INSERT INTO library_nodes(id,book_id,position,title,kind,start_page,end_page,confirmed,updated_at) '
                           'VALUES (?,?,?,?,?,?,?,?,?)',
                           (n['id'], book_id, ni, f'第 {ni+1} 节：条件与论证', 'section', begin, end, int(confirmed), timestamp))
                for version in range(3):
                    ident = n['id'] + f'-reading-{version}'
                    model = f'fixture-model-{version}'
                    signature = (library.reading_signature(b, n, 'fixture', model, 'none')
                                 if version != 2 else 'obsolete-range-' + ident)
                    marker = ('old_only_marker' if version == 0 else 'latest_marker' if version == 1 else 'stale_only_marker')
                    body = ('定义、条件和构造动机应当区分；方法适用性需要检查，笔记不能代替原文。\n' * (note_chars//36+1))[:note_chars]
                    body += f'\n{marker}: book={bi}, node={ni}. 完整末尾信息。'
                    db.execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,warnings_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                               (ident, n['id'], signature, 'fixture', model, 'none', 'completed', body,
                                j(['模型读取记录，不代表学生掌握'] if ni % 7 == 0 else []), timestamp,
                                f'2026-10-10T{8+version:02}:00:00+00:00'))
                    note_rows += 1
                    if version == 1:
                        if confirmed: current_ids.append(ident)
                        for page in range(begin, end+1):
                            text = ('数域的定义要求对四则运算封闭，除数不为零。条件缺失不能仅凭名称补全。\n'*50)
                            if bi == books-1 and ni == nodes-2 and page == end:
                                text += 'epsilon_selection: choose half the distance; open neighbourhoods do not intersect.\n'
                            visual = '图像核对记录：保留条件与原文定位。' if page % 5 == 0 else ''
                            db.execute('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',
                                       (ident, page, f'PDF 第 {page} 页', text, visual, None, None))
                            original_rows += 1
    case = {'books': books, 'pages_per_book': pages, 'nodes_per_book': nodes,
            'versions_per_node': 3, 'characters_per_note': note_chars,
            'book_ids': book_ids, 'stored_notes': note_rows, 'stored_pages': original_rows,
            'valid_readings': len(current_ids), 'fixture_kind': 'synthetic stored notes and extracted page text'}
    (folder/'case.json').write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(case, ensure_ascii=False), flush=True)


def measure(folder, mode, rounds):
    from studyforge import library, library_semantic as semantic
    from studyforge.db import j
    native = load_previous(folder) if mode == 'baseline' else library
    # Status should be measurable without loading an embedding model. Both
    # modes receive precisely the same model-availability metadata.
    semantic.model_ready = lambda: False
    semantic.eligible = (lambda: native.eligible_readings()[2]) if mode == 'baseline' else semantic.eligible
    case = json.loads((folder/'case.json').read_text(encoding='utf-8'))
    queries = ['epsilon_selection', '构造动机', 'latest_marker', 'old_only_marker', 'stale_only_marker']
    actions = {
        'shelf_details': lambda: [native.details(ident) for ident in case['book_ids']],
        'semantic_status': lambda: semantic.status(),
        'keyword_search': lambda: {query: native.search(query, limit=12, mode='keyword') for query in queries},
    }
    metrics = {}
    outputs = {}
    for name, operation in actions.items():
        elapsed = []
        for _ in range(rounds):
            gc.collect()
            started = time.perf_counter()
            value = operation()
            elapsed.append(time.perf_counter()-started)
            digest = hashlib.sha256(j(value).encode()).hexdigest()
            if name in outputs and outputs[name] != digest: raise AssertionError('Non-deterministic fixture result')
            outputs[name] = digest
            del value
        gc.collect()
        tracemalloc.start()
        value = operation()
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        del value
        metrics[name] = {'elapsed_seconds': elapsed, 'mean_seconds': sum(elapsed)/len(elapsed),
                         'python_allocation_peak_mib': peak/1024**2}
        print(json.dumps({'mode': mode, 'action': name, **metrics[name]}), flush=True)
    result = {'mode': mode, 'case': case, 'metrics': metrics, 'output_sha256': outputs,
              'process_peak_working_set_mib': peak_ram_mb(),
              'scope': 'Isolated stored-text query workload; no actual scanned-book reading, model, OCR or app UI.'}
    (folder/(mode+'.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['prepare', 'baseline', 'optimized'], required=True)
    parser.add_argument('--folder', default='library-scale-20261010-1')
    parser.add_argument('--books', type=int, default=10)
    parser.add_argument('--pages', type=int, default=350)
    parser.add_argument('--nodes', type=int, default=50)
    parser.add_argument('--note-chars', type=int, default=12000)
    parser.add_argument('--rounds', type=int, default=2)
    args = parser.parse_args()
    folder = (ROOT/'build'/args.folder).resolve()
    if not folder.is_relative_to(ROOT/'build'): raise ValueError('Benchmark outside build')
    if not 1 <= args.books <= 30 or not 1 <= args.nodes <= args.pages <= 500 or not 100 <= args.note_chars <= 20000 or not 1 <= args.rounds <= 5:
        raise ValueError('Fixture parameters outside bounded test range')
    os.environ['STUDYFORGE_DATA_DIR'] = str(folder/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(folder/'absent-model')
    if args.mode == 'prepare': prepare(folder, args.books, args.pages, args.nodes, args.note_chars)
    else: measure(folder, args.mode, args.rounds)


if __name__ == '__main__': main()
