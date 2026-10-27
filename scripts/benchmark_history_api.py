"""Measure real API response overhead on isolated synthetic messages.

This is not a model-speed, full-application RAM or Android-network benchmark.
No model requests or production database writes are made.
"""
from __future__ import annotations

import gc
import json
import os
from pathlib import Path
import statistics
import sys
import time
import tracemalloc

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
label = sys.argv[1] if len(sys.argv) > 1 else 'history-api-20261011-1'
if Path(label).name != label or label in ('.', '..'):
    raise ValueError('Use a directory name below build')
folder = root / 'build' / label
folder.mkdir(parents=True, exist_ok=True)
if (folder / 'data' / 'studyforge.sqlite3').exists():
    raise ValueError('Use a fresh isolated directory')
os.environ['STUDYFORGE_DATA_DIR'] = str(folder / 'data')
os.environ['STUDYFORGE_DESKTOP_TOKEN'] = 'history-benchmark-owner'

from fastapi.testclient import TestClient
from studyforge import conversations, message_history, server
from studyforge.db import connect, create_project, uid

count = 1500
project = create_project('Synthetic history benchmark')
chat = conversations.create(project['id'], 'deepseek')
with connect() as database:
    for i in range(count):
        text = f'MESSAGE_{i:04}\n' + ('先讲清定义与适用条件，再说明证明目标与构造动机；原文证据必须保留。' * 22)
        database.execute('INSERT INTO messages VALUES (?,?,?,?,?)',
            (uid(),chat['id'],'assistant' if i%2 else 'user',text,'2026-10-11T00:00:00+00:00'))
client = TestClient(server.app, headers={'x-studyforge-desktop-token':'history-benchmark-owner'})
base = f"/api/conversations/{chat['id']}"
scope = f"project_id={project['id']}"
first = message_history.page(chat['id'], project['id'], limit=60)
revision = first['history']['revision']
cases = {
    'full_initial': ('GET',base+'?'+scope,None),
    'paged_initial': ('GET',base+'?'+scope+'&history_limit=60',None),
    'full_unchanged_poll': ('GET',base+'/messages?'+scope,None),
    'revision_unchanged_poll': ('GET',base+'/messages?'+scope+f'&limit=60&since={revision}',None),
    'full_save': ('PUT',base,{'project_id':project['id'],'draft':'保留草稿'}),
    'metadata_save': ('PUT',base+'?include_history=false',{'project_id':project['id'],'draft':'保留草稿'}),
}

def request(case):
    method, url, body = case
    response = client.request(method,url,json=body) if body is not None else client.request(method,url)
    assert response.status_code==200, response.text[:500]
    return response

result = {name:{'timings_ms':[]} for name in cases}
# Warm each route once, then alternate them on every repetition.
for case in cases.values():request(case)
for _ in range(5):
    for name, case in cases.items():
        start = time.perf_counter()
        response = request(case)
        result[name]['timings_ms'].append((time.perf_counter()-start)*1000)
        payload = response.json()
        result[name].update(response_bytes=len(response.content),message_count=len(payload.get('messages',[])))
        if name=='revision_unchanged_poll':assert payload['not_modified'] and 'messages' not in payload
        elif name=='metadata_save':assert payload['history_omitted'] and not payload['messages']
        else:assert len(payload['messages'])==(60 if name=='paged_initial' else count)
        del response,payload
for name, case in cases.items():
    gc.collect()
    tracemalloc.start()
    response=request(case)
    result[name]['python_peak_mib']=round(tracemalloc.get_traced_memory()[1]/1024**2,4)
    tracemalloc.stop()
    result[name]['median_ms']=round(statistics.median(result[name]['timings_ms']),3)
    result[name]['timings_ms']=[round(t,3) for t in result[name]['timings_ms']]
    del response
report={'messages':count,'repetitions':5,'isolated_data':str(folder/'data'),
        'scope':'Real FastAPI/TestClient response bytes, local request time and one-request Python allocation peak. Synthetic text; no model, OCR, Android network or full-app RAM measurement.',
        'cases':result}
(folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
