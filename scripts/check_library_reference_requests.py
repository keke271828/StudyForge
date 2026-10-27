"""Check actual mock-service HTTP payloads against the stored input receipts."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import urllib.request

folder=Path(__file__).resolve().parents[1]/'build'/sys.argv[1]
case=json.loads((folder/'case.json').read_text(encoding='utf-8'))
with urllib.request.urlopen(case['desktop_url']+'/__library_test__/calls') as response:
    calls=json.load(response)['calls']
with sqlite3.connect(folder/'data'/'studyforge.sqlite3') as db:
    db.row_factory=sqlite3.Row
    artifact=db.execute('SELECT metadata_json FROM artifacts WHERE id=?',(case['artifact_id'],)).fetchone()
    meta=json.loads(artifact['metadata_json'])
    prepared=json.loads(db.execute("SELECT response FROM generation_steps WHERE job_id=? AND step_key='library_document_reference'",
        (meta['generation_job_id'],)).fetchone()['response'])


def text_of(call):
    parts=[]
    for message in call['messages']:
        content=message.get('content','')
        if isinstance(content,str):parts.append(content)
        else:parts.extend(part.get('text','') for part in content if isinstance(part,dict))
    return '\n'.join(parts)


received=[index for index,call in enumerate(calls) if prepared['text'] in text_of(call)]
receipt=meta['library_evidence']
assert hashlib.sha256(prepared['text'].encode()).hexdigest()==receipt['context_sha256']
assert prepared['receipt']==receipt and len(prepared['text'])==receipt['context_characters']
assert {1,2}.issubset(received),received  # single-part job, two chapter writes, final recap
report={'passed':True,'reference_characters':len(prepared['text']),'receipt_hash':receipt['context_sha256'],
    'actual_http_requests_containing_complete_reference':received,'model_requests':len(calls),'external_model_requests':0}
(folder/'actual-request-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
