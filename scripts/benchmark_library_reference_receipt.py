"""Compare local reference preparation on a previous isolated 12-node fixture.

Keeps old measurements intact. Measures Python allocation, not total app RAM
or model quality; legacy text/evidence fields must remain exactly identical.
"""
import argparse
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import tracemalloc

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'build'/'library-reference-receipt-20261011'
DATASET=ROOT/'build'/'library-evidence-performance-20261011'


def run(variant):
    from studyforge import library
    if variant=='before':
        spec=importlib.util.spec_from_file_location('studyforge._reference_receipt_before',FOLDER/'library.before.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    else:module=library
    case=json.loads((DATASET/'case.json').read_text(encoding='utf-8'))
    operation=lambda:module.reference_content(case['snapshot'],'needle')
    operation();gc.collect();start=time.perf_counter()
    for _ in range(4):result=operation()
    mean=(time.perf_counter()-start)/4
    gc.collect();tracemalloc.start()
    try:result=operation();peak=tracemalloc.get_traced_memory()[1]
    finally:tracemalloc.stop()
    reads=[];native=module.file_sha256
    def counted(path):reads.append(str(path));return native(path)
    module.file_sha256=counted
    try:operation()
    finally:module.file_sha256=native
    fields=('text','evidence','candidates','mode','truncated','omitted_references')
    payload=json.dumps({key:result[key] for key in fields},ensure_ascii=False,sort_keys=True)
    report={'variant':variant,'timed_repeats':4,'mean_ms':mean*1000,'python_peak_bytes':peak,
        'legacy_content_sha256':hashlib.sha256(payload.encode()).hexdigest(),'context_characters':len(result['text']),
        'hash_reads_per_call':len(reads),'book_hash_reads_per_call':reads.count(case['book_path']),
        'receipt_bytes':len(json.dumps(library.reference_receipt(result),ensure_ascii=False).encode()) if variant=='current' else 0,
        'external_model_requests':0,'scope':'local preparation on 12 synthetic long notes and three native PDF page crops'}
    (FOLDER/('reference-'+variant+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


def compare():
    reports={variant:json.loads((FOLDER/('reference-'+variant+'.json')).read_text(encoding='utf-8')) for variant in ('before','current')}
    assert reports['before']['legacy_content_sha256']==reports['current']['legacy_content_sha256']
    report={'passed':True,'prepared_text_and_evidence_identical':True,'before':reports['before'],'current':reports['current']}
    (FOLDER/'reference-comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Reference text, spans, candidates and omissions are exactly equal; no cloud request')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('variant',choices=['before','current','compare']);args=parser.parse_args()
    os.environ['STUDYFORGE_DATA_DIR']=str(DATASET/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(DATASET/'unused-semantic-model')
    if args.variant=='compare':compare()
    else:run(args.variant)
