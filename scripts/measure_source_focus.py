"""Local Python allocation probe of the selector, not whole-app RAM testing."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import time
import tracemalloc

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'build'/(sys.argv[1] if len(sys.argv)>1 else 'source-focus-allocation-20261026')


def main():
    if OUT.resolve().parent != (ROOT/'build').resolve() or OUT.exists():raise SystemExit('Use a fresh evidence directory.')
    OUT.mkdir();os.environ['STUDYFORGE_DATA_DIR']=str(OUT/'data')
    from studyforge.source_focus import prepare
    # Load lexical helpers before allocation measurement; inputs are also
    # created before tracing, like already prepared material in the tutor.
    prepare('\n[来源 预热｜p1] [资料ID:warm]\n可逆元。','可逆元')
    original=''.join(f'\n[来源 合成教材｜第 {p+1} 页] [资料ID:synthetic]\n'+
        (('本页讨论矩阵记号及其合法的代数运算。\n\n'*40) if p!=1750 else
         '定义：本页讨论商环可逆元。\n\n限制：非零不能代替存在逆元的条件。\n\n') for p in range(2600))
    rows=[]
    for concurrent in (1,2):
        tracemalloc.start();started=time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrent) as pool:
            results=list(pool.map(lambda _:prepare(original,'商环可逆元'),range(concurrent)))
        current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        assert all('非零不能代替存在逆元' in text for text,_ in results)
        rows.append({'concurrent':concurrent,'input_characters_each':len(original),
            'seconds':round(time.perf_counter()-started,3),'python_traced_peak_bytes':peak,
            'context_characters':[len(text) for text,_ in results],'model_calls':0})
    value={'meaning':'selector_only_python_allocations_excluding_existing_inputs_not_whole_app_ram',
           'results':rows}
    (OUT/'result.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(value,ensure_ascii=False))


if __name__=='__main__':main()
