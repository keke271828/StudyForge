"""Measure local excerpt overhead only, excluding model/OCR and app-wide RAM."""
import json
from pathlib import Path
import statistics
import time
import tracemalloc
from unittest.mock import patch

from studyforge.teaching import summary_context
from studyforge.summary_evidence import augment


def main():
    values=[f'# 部分{i+1}\n\n'+('正文背景。'*9000)+f'\n\n## 条件\n\n仅当参数q{i}>0时才讨论此结论，不能推广到零值。\n\n'+
        ('展开说明。'*9000)+f'\n\n## 系统性总结\n本部分{i+1}解释条件与结论的关系。' for i in range(10)]
    with patch('studyforge.summary_evidence.augment',lambda plan,*a,**k:plan):base=summary_context(values)
    assert base['excerpted'] and not base['omitted_chapters']
    durations=[]
    for _ in range(7):
        start=time.perf_counter();result=augment(base,values,48000);durations.append(time.perf_counter()-start)
    tracemalloc.start();augment(base,values,48000);_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    assert result['body_evidence']['included']==10 and len(result['text'])<=48000
    row={'chapters':len(values),'body_characters':sum(map(len,values)),'runs':len(durations),
        'median_seconds':statistics.median(durations),'min_seconds':min(durations),'max_seconds':max(durations),
        'extra_python_allocation_peak_bytes':peak,'input_before':len(base['text']),'input_after':len(result['text']),
        'evidence_characters':result['body_evidence']['characters'],'scope':'local_helper_only_not_total_app_memory_or_model_latency'}
    target=Path(__file__).resolve().parents[1]/'build/summary-evidence-local-overhead-20261016.json'
    target.write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(row),flush=True)


if __name__=='__main__':main()
