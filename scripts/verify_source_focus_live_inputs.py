"""Recheck final selector against the saved real model inputs, no cloud call."""
import asyncio
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/source-focus-live-20261026'


async def main():
    os.environ['STUDYFORGE_DATA_DIR']=str(OUT/'data')
    from studyforge import ai,source_focus
    from studyforge.db import one,unj
    from studyforge.materials import read_original_sources
    from scripts.source_focus_cases import CASES
    report=json.loads((OUT/'report.json').read_text(encoding='utf-8'))
    checks=[]
    for row in report['results']:
        if row['arm']!='focused':continue
        saved=row['input_receipt'];sid=saved['included'][0]['source_id']
        records=read_original_sources([one('SELECT * FROM sources WHERE id=?',(sid,))])
        original,_=await ai.source_digest(object(),records,include_source_ids=True)
        reading=one('SELECT notes_json FROM reading_sessions WHERE project_id=?',(records[0]['project_id'],))
        text,current=source_focus.prepare(original,CASES[row['case']]['question'],unj(reading['notes_json'],[]))
        requests=json.loads((OUT/(row['case']+'-focused-requests.json')).read_text(encoding='utf-8'))
        assert current['context_sha256']==saved['context_sha256']
        assert current['input_sha256']==saved['input_sha256']
        assert text in requests[0]['messages'][0]['content']
        checks.append({'case':row['case'],'exact_final_input':True,'context_sha256':current['context_sha256']})
    assert len(checks)==2
    (OUT/'final-input-recheck.json').write_text(json.dumps({'passed':True,'model_calls':0,'checks':checks},indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'cases':len(checks),'model_calls':0}))


if __name__=='__main__':asyncio.run(main())
