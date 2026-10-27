"""Read only isolated A/B evidence; no models, parsing or user database access."""
from __future__ import annotations
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def inspect(work, variant):
    database=work/variant/'data/studyforge.sqlite3'
    if not database.is_file(): return {'variant':variant,'status':'not_started'}
    with sqlite3.connect('file:'+database.as_posix()+'?mode=ro',uri=True) as connection:
        connection.row_factory=sqlite3.Row
        jobs=[dict(row) for row in connection.execute('SELECT id,kind,status,progress,error,result_json FROM jobs')]
        for job in jobs:job['result']=json.loads(job.pop('result_json') or '{}')
        source=connection.execute('SELECT name,status,segments_json FROM sources LIMIT 1').fetchone()
        parts=json.loads(source['segments_json'] or '[]') if source else []
        transcript=[(p['locator'],p['text']) for p in parts if p['kind']=='transcript']
        result={'variant':variant,'jobs':jobs,'segments':len(parts),
                'source_name':source['name'] if source else None,
                'sampling':next((p['meta']['video_sampling'] for p in parts if p.get('meta',{}).get('video_sampling')),{}),
                'transcript_sha256':hashlib.sha256(json.dumps(transcript,ensure_ascii=False).encode()).hexdigest(),
                'transcript_segments':len(transcript),
                'vision_readings':connection.execute('SELECT COUNT(*) FROM source_vision_cache').fetchone()[0]}
        result['artifacts']=[dict(row) for row in connection.execute('SELECT kind,title,path FROM artifacts')]
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('work',type=Path);args=parser.parse_args()
    work=args.work.resolve();root=Path(__file__).resolve().parents[1]/'build'
    if not work.is_relative_to(root):raise ValueError('只检查当前工作区 build 下的隔离测试目录')
    print(json.dumps([inspect(work,v) for v in ('A','B')],ensure_ascii=False,indent=2))


if __name__=='__main__':main()
