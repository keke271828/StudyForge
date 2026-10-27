"""Saved pre-change/current evidence preparation on isolated synthetic data.

Measures local Python allocation and lookup time, never model quality, OCR,
total app RAM or video generation. Baseline source must exist before preparing.
"""
import argparse
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import sys
import time
import tracemalloc

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def previous(folder):
    spec=importlib.util.spec_from_file_location('studyforge._library_evidence_before',folder/'library.before.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def prepare(folder):
    import fitz
    from studyforge import library
    from studyforge.db import connect,j,now,uid
    if (folder/'data'/'studyforge.sqlite3').exists():raise ValueError('Fixture already exists; preserve its measurements')
    if not (folder/'library.before.py').exists():raise ValueError('Pre-change source snapshot is required')
    source=folder/'fixture.pdf'
    with fitz.open() as document:
        for number in range(3):
            page=document.new_page()
            page.insert_text((40,60),f'needle: a definition requires its conditions. Page {number+1}.')
        document.save(source)
    book=library.import_book(source,'Isolated source fixture.pdf')['book']
    references=[];original_pages=None
    note=('阅读导航应区分主张、条件、构造与疑点。'*40000)[:600000]+'\nneedle: retain the original conditions.'
    with connect() as db:
        for ordinal in range(12):
            node={'id':uid(),'start_page':1,'end_page':3,'start_y':0.0,'end_y':1.0}
            stamp=now();reading=uid()
            db.execute('INSERT INTO library_nodes(id,book_id,position,title,kind,start_page,end_page,start_y,end_y,confirmed,updated_at) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?)',(node['id'],book['id'],ordinal,f'范围 {ordinal+1}','section',1,3,0,1,1,stamp))
            db.execute('INSERT INTO library_readings(id,node_id,signature,provider,model,effort,status,notes,warnings_json,created_at,updated_at) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?)',(reading,node['id'],library.reading_signature(book,node,'fixture','reader','none'),
                'fixture','reader','none','completed',note,'[]',stamp,stamp))
            if original_pages is None:original_pages=[library.extract_page(book,node,number,ocr=False) for number in range(1,4)]
            for page in original_pages:
                db.execute('INSERT INTO library_chunks VALUES (?,?,?,?,?,?,?)',
                    (reading,page['page'],page['locator'],page['original_text'],'图像核对记录：原页条件。',page['image_path'],page['image_sha256']))
            references.append({'node_id':node['id'],'purpose':'primary','source_version':library.version(book,node),
                'note_annotation':{'reading_id':reading,'reading_updated_at':stamp,'suspect':False,'comment':'','revision':0}})
    value={'snapshot':{'references':references,'candidates':[],'mode':'manual'},'nodes':12,'characters_per_navigation_note':len(note),
        'original_pages_per_node':3,'book_path':book['original_path'],'source_kind':'synthetic stored navigation notes and real native PDF page crops'}
    (folder/'case.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Prepared 12 nodes; no cloud requests or user learning data')


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def measure(operation,repeats=4):
    result=operation();gc.collect()
    start=time.perf_counter()
    for _ in range(repeats):result=operation()
    elapsed=(time.perf_counter()-start)/repeats
    gc.collect();tracemalloc.start()
    try:result=operation();peak=tracemalloc.get_traced_memory()[1]
    finally:tracemalloc.stop()
    return result,{'mean_ms':elapsed*1000,'python_peak_bytes':peak,'timed_repeats':repeats}


def run(folder,variant):
    from studyforge import library
    module=previous(folder) if variant=='before' else library
    case=json.loads((folder/'case.json').read_text(encoding='utf-8'))
    dense='alpha_beta '*30000
    window,window_metrics=measure(lambda:module.text_window(dense,{'alpha_beta'},450))
    context,context_metrics=measure(lambda:module.reference_content(case['snapshot'],'needle'))
    reads=[];native=module.file_sha256
    def counted(path):reads.append(str(path));return native(path)
    module.file_sha256=counted
    try:records,generation_metrics=measure(lambda:module.generation_records(case['snapshot']))
    finally:module.file_sha256=native
    generation_calls=generation_metrics['timed_repeats']+2
    report={'variant':variant,'dense_window':{**window_metrics,'result_sha256':digest(window)},
        'reference_context':{**context_metrics,'result_sha256':digest(context),'output_chars':len(context['text'])},
        'generation_records':{**generation_metrics,
            'segment_sha256':digest([record['segments'] for record in records]),
            'content_fingerprints': [record['read_manifest']['content_sha256'] for record in records],
            'book_hash_reads_per_call':reads.count(case['book_path'])//generation_calls,
            'all_hash_reads_per_call':len(reads)//generation_calls},
        'external_model_requests':0,'scope':'local evidence preparation; synthetic notes, native PDF page images; not total app RAM'}
    (folder/(variant+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


def compare(folder):
    from studyforge import library
    baseline=previous(folder)
    rng=random.Random(92110);cases=[]
    for index in range(40):
        words=['数学定义','必要条件','alpha_beta','needle','ε','🙂','\n','$x_n-a$',' ']
        text=''.join(rng.choice(words) for _ in range(800+index*11))
        terms=library.terms(['必要条件 needle','alpha_beta 数学定义','missing_word',''][index%4])
        limit=[0,80,100,320,450,900,12000][index%7]
        anchor=None if index%3 else rng.randrange(len(text))
        expected=baseline.text_window(text,terms,limit,anchor)
        actual=library.text_window(text,terms,limit,anchor)
        if expected!=actual:raise AssertionError(f'Window differs at case {index}')
        cases.append({'case':index,'characters':len(text),'limit':limit,'anchor':anchor})
    before=json.loads((folder/'before.json').read_text(encoding='utf-8'))
    after=json.loads((folder/'current.json').read_text(encoding='utf-8'))
    assert before['dense_window']['result_sha256']==after['dense_window']['result_sha256']
    assert before['reference_context']['result_sha256']==after['reference_context']['result_sha256']
    assert before['generation_records']['segment_sha256']==after['generation_records']['segment_sha256']
    assert before['generation_records']['content_fingerprints']==after['generation_records']['content_fingerprints']
    report={'passed':True,'exact_window_cases':cases,'old_and_new_context_identical':True,
        'complete_original_segments_identical':True,'unchanged_source_hashes_compatible':True,'external_model_requests':0}
    (folder/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('40 exact excerpt comparisons, full original segments, context and content hashes match')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder');parser.add_argument('command',choices=['prepare','run','compare']);parser.add_argument('--variant',choices=['before','current'],default='current')
    args=parser.parse_args();folder=(ROOT/'build'/args.folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'unused-semantic-model')
    if args.command=='prepare':prepare(folder)
    elif args.command=='run':run(folder,args.variant)
    else:compare(folder)
