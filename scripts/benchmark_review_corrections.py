"""Measure the local guard only, with no model calls or learner data."""
import json
from pathlib import Path
import statistics
import time
import tracemalloc

from studyforge.review_corrections import apply_local_corrections


def main():
    out = Path(__file__).resolve().parents[1] / 'build/fast-review-20261014'
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for size in (80000, 1000000):
        chunk = '这是已有的讲解段落，用于测量局部修订开销。\n' * (size // (8 * 25))
        draft = '# 讲解\n' + '\n'.join(chunk + f'唯一错误标记{i}。' for i in range(8))
        patches = [dict(issue_index=i, before=f'唯一错误标记{i}。', after=f'唯一修订标记{i}。') for i in range(8)]
        issues = [{'problem': '测试错误'} for _ in range(8)]
        times = []
        for _ in range(5):
            start = time.perf_counter()
            result, used = apply_local_corrections(draft, patches, issues)
            times.append(time.perf_counter() - start)
            assert used == list(range(8)) and all(f'唯一修订标记{i}。' in result for i in range(8))
        tracemalloc.start()
        result, used = apply_local_corrections(draft, patches, issues)
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        start = time.perf_counter()
        unchanged, used = apply_local_corrections(draft, [], [])
        empty = time.perf_counter() - start
        assert unchanged is draft and used == []
        rows.append({'characters': len(draft), 'patches': 8, 'median_seconds': round(statistics.median(times), 4),
            'peak_python_bytes': peak, 'no_corrections_seconds': round(empty, 7)})
        output = {'scope': 'Local guard only; generated synthetic text, no model requests. Not app RAM or full generation speed.', 'rows': rows}
        (out / 'local-cost.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
        print(json.dumps(rows[-1]), flush=True)


if __name__ == '__main__': main()
