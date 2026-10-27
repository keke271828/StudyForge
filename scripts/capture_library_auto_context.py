"""Identical saved corpus and question; capture real chat preparation, no cloud."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'build/library-followup-20261021'
OUT=ROOT/'build/library-auto-context-20261021'/sys.argv[1]
if (OUT/'requests.json').exists():raise SystemExit('Use a fresh phase, do not overwrite evidence.')
(OUT/'data').mkdir(parents=True,exist_ok=True)
with sqlite3.connect(SOURCE/'corpus.sqlite3') as source,sqlite3.connect(OUT/'data/studyforge.sqlite3') as dest:source.backup(dest)
os.environ['STUDYFORGE_DATA_DIR']=str(OUT/'data')
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(OUT/'no-model')
from studyforge import ai,server
from studyforge.db import j


async def main():
    data=json.loads((SOURCE/'case.json').read_text(encoding='utf-8'));rows=[]
    ai.get_secret=lambda *a:'fixture-only'
    server.discussion_completed=lambda *a:None
    server.profile_context=lambda *a,**kw:''
    class Capture:
        model='deepseek-flash';effort='high'
        async def agent_stream(self,messages,**kwargs):self.messages=messages;yield 'delta','受控占位回答。'
        async def close(self):pass
    for sample in data['cases']:
        client=Capture();server.DeepSeekClient=lambda *a,**kw:client
        response=await server._chat_response(server.ChatIn(project_id=sample['project_id'],conversation_id=sample['conversation_id'],
            source_ids=[],text=data['question'],reply_reference=sample['reply_reference'],provider='deepseek',model='deepseek-flash',
            reasoning_effort='high',learning_mode='deep',explanation_style='balanced'))
        text=''.join([chunk.decode() if isinstance(chunk,bytes) else chunk async for chunk in response.body_iterator])
        events=[json.loads(line) for line in text.splitlines() if line];assert not [e for e in events if e['type']=='error'],events
        receipt=next((e['value']['receipt'] for e in events if e['type']=='library'),None);context=''
        if receipt:
            system=client.messages[0]['content'];start=system.index('\n## 全局书库参考');context=system[start:start+receipt['context_characters']]
            assert hashlib.sha256(context.encode()).hexdigest()==receipt['context_sha256']
        rows.append({'name':sample['name'],'question':data['question'],'quote':sample['quote'],'original':sample['original'],
            'messages':client.messages,'receipt':receipt,'context':context,'original_reached_model':sample['original'] in j(client.messages)})
    (OUT/'requests.json').write_text(j(rows),encoding='utf-8')
    print(j({'phase':sys.argv[1],'original_reached':[r['original_reached_model'] for r in rows],
        'source_nodes':[[s['title'] for s in (r['receipt'] or {}).get('sources',[])] for r in rows],
        'context_characters':[len(r['context']) for r in rows],'external_requests':0}),flush=True)


if __name__=='__main__':asyncio.run(main())
