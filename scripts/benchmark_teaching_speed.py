"""Real model acceptance using production jobs and isolated StudyForge data.

No credentials, user databases, or source videos are modified. The video case
reuses all previously extracted original segments to measure the changed AI
pipeline separately from unchanged transcription and OCR time.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--case', choices=['proof', 'video'], required=True)
parser.add_argument('--output', required=True)
parser.add_argument('--reuse-video-data', help='Use the same isolated video sources and verified image cache; no new video reads.')
parser.add_argument('--resume-job', help='Resume a saved job in the specified isolated video data after an interrupted acceptance run.')
args = parser.parse_args()
target = (ROOT / args.output).resolve()
if (not target.is_relative_to(ROOT / 'build') or
        target.exists() and not args.resume_job or
        args.resume_job and (not target.is_dir() or (target / 'result.json').exists())):
    raise ValueError('验收必须使用工作区 build 内尚不存在的新目录')
target.mkdir(parents=True, exist_ok=bool(args.resume_job))
reuse = Path(args.reuse_video_data).resolve() if args.reuse_video_data else None
if reuse and (args.case != 'video' or not reuse.is_relative_to(ROOT / 'build') or not (reuse / 'studyforge.sqlite3').is_file()):
    raise ValueError('缓存复用只允许工作区内的已有视频验收数据库')
os.environ['STUDYFORGE_DATA_DIR'] = str(reuse or target / 'data')

from docx import Document
from studyforge import server, conversations
from studyforge.ai import DeepSeekClient, save_settings
from studyforge.db import create_job, create_project, execute, j, many, now, one, uid
from studyforge.video_records import read_record, write_record

PROOF = r'''参考证明片段：收敛数列的极限唯一性。
数列 x_n 收敛于 a 的定义为：对任意 epsilon>0，存在正整数 N，
使 n>N 时 |x_n-a|<epsilon。
为证唯一，假设同时有 x_n -> a 及 x_n -> b，且 a<b。
取 epsilon=(b-a)/2。由两处极限定义，分别有正整数 N_1、N_2，
使 n>N_1 时 |x_n-a|<(b-a)/2，
使 n>N_2 时 |x_n-b|<(b-a)/2。
取 N=max{N_1,N_2}，则当 n>N 时，上述两式同时成立。
第一式推出 x_n<(a+b)/2，第二式推出 x_n>(a+b)/2，矛盾。
因此极限唯一。
这是根据用户给出的证明片段整理的测试资料，不是原教材逐字转录。
'''


def add_source(project, name, path, kind, segments=None):
    source_id = uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
            (source_id, project['id'], name, kind, str(path), j(segments or []), 'ready', now()))
    return source_id


async def generate(value, resume_job=None):
    job = resume_job or create_job(value.project_id, 'generate', value.model_dump())
    started = time.perf_counter()
    trace = []
    finished = asyncio.Event()
    async def monitor():
        previous = None
        while not finished.is_set():
            row = one('SELECT status,progress,result_json FROM jobs WHERE id=?', (job,))
            result = json.loads(row['result_json'])
            status = (row['status'], row['progress'], result.get('stage'), result.get('request_status'))
            if status != previous:
                item = {'seconds': round(time.perf_counter() - started, 2), 'status': status}
                trace.append(item)
                print(j(item), flush=True)
                previous = status
            try: await asyncio.wait_for(finished.wait(), timeout=.75)
            except asyncio.TimeoutError: pass
    watcher = asyncio.create_task(monitor())
    try:
        await server._generate_job(job, value)
    finally:
        finished.set()
        await watcher
        (target / 'generation-progress.json').write_text(j(trace), encoding='utf-8')
    row = one('SELECT * FROM jobs WHERE id=?', (job,))
    if row['status'] != 'completed': raise RuntimeError(row['error'])
    artifacts = many("SELECT * FROM artifacts WHERE project_id=? AND kind='explanation' "
                     "AND json_extract(metadata_json,'$.generation_job_id')=? ORDER BY created_at", (value.project_id, job))
    messages = many('SELECT m.content FROM generation_dialogue_outputs g JOIN messages m ON m.id=g.message_id WHERE g.job_id=?', (job,))
    text = '\n\n'.join(item['content'] for item in messages)
    (target / 'model-lecture.md').write_text(text, encoding='utf-8')
    copies = []
    for index, artifact in enumerate(artifacts):
        name = ('极限唯一性：为什么取半个间距.docx' if args.case == 'proof' else
                f'LaTeX表格课程：改进版讲解{index + 1}.docx')
        final = target / name
        shutil.copyfile(artifact['path'], final)
        document = Document(final)
        copies.append({'path': str(final), 'equations': len(document.element.xpath('//m:oMath')),
                       'characters': len('\n'.join(p.text for p in document.paragraphs)),
                       'metadata': json.loads(artifact['metadata_json'])})
    return {'job_id': job, 'generation_seconds': round(time.perf_counter() - started, 2),
            'outputs': copies, 'execution_spans': many('SELECT label,status,duration_ms FROM execution_spans WHERE job_id=?', (job,))}


async def main():
    save_settings({'chat_provider': 'deepseek', 'deepseek_model': 'deepseek-flash',
                   'deepseek_vision_model': 'deepseek-flash', 'review_mode': 'fast',
                   'explanation_style': 'balanced', 'background_learning_enabled': False,
                   'agent_network_enabled': False, 'agent_image_generation_enabled': False})
    if args.resume_job:
        if args.case != 'video' or not reuse:
            raise ValueError('仅恢复显式指定的工作区视频验收数据')
        saved = one("SELECT * FROM jobs WHERE id=? AND kind='generate'", (args.resume_job,))
        if not saved or saved['status'] not in {'running', 'queued'}:
            raise ValueError('未找到可恢复的独立验收任务')
        evidence = json.loads((target / 'source-evidence.json').read_text(encoding='utf-8'))
        if json.loads(saved['payload_json']) != evidence['parameters']:
            raise ValueError('任务与本目录的验收参数不一致')
        report = await generate(server.GenerateIn(**evidence['parameters']), args.resume_job)
        report.update(model='deepseek-flash', case='video', interrupted_run_resumed=True,
                      timing_note='generation_seconds 仅包含本次恢复后的运行；完整请求耗时见 execution_spans，不用于冷启动速度比较。')
        (target / 'result.json').write_text(j(report), encoding='utf-8')
        print(j({'result': str(target / 'result.json'), 'resumed_seconds': report['generation_seconds']}), flush=True)
        return
    existing = one("SELECT * FROM sources WHERE kind='.sfvideo' LIMIT 1") if reuse else None
    if reuse and not existing: raise ValueError('未找到可复用的视频原资料')
    project = {'id': existing['project_id']} if existing else create_project('直观与专业和速度验收')
    conversation = conversations.create(project['id'], 'deepseek', 'deepseek-flash')
    common = dict(project_id=project['id'], conversation_id=conversation['id'], provider='deepseek',
                  model='deepseek-flash', format='docx', summary_level=3, exercises=False,
                  generation_quality='custom', learning_mode='deep')
    if args.case == 'proof':
        path = target / '极限唯一性参考证明.txt'
        path.write_text(PROOF, encoding='utf-8')
        source = add_source(project, path.name, path, '.txt')
        value = server.GenerateIn(**common, source_ids=[source], explanation_style='balanced', review_mode='fast',
            instructions='请讲清楚这份证明以及怎么想到这样证，尤其是为什么取这个 epsilon。我刚学数列极限，不布置习题。')
    else:
        baseline_dir = ROOT / 'build/video-ab-BV1gv421k7FF-p6/B/data'
        baseline_path = next((baseline_dir / 'files').glob('*.sfvideo'))
        baseline_db = sqlite3.connect('file:' + str(baseline_dir / 'studyforge.sqlite3') + '?mode=ro', uri=True)
        try:
            original = json.loads(baseline_db.execute("SELECT payload_json FROM jobs WHERE kind='generate' LIMIT 1").fetchone()[0])
        finally: baseline_db.close()
        parts = read_record(Path(existing['original_path']) if existing else baseline_path)
        source_hash = hashlib.sha256(j([(p['locator'], p['text']) for p in parts]).encode()).hexdigest()
        if existing:
            path, source = Path(existing['original_path']), existing['id']
        else:
            path = target / 'data/files/course.sfvideo'
            path.parent.mkdir(parents=True, exist_ok=True)
            write_record(path, parts, title='LaTeX 表格课程完整原资料', metadata={'benchmark_original_sha256': source_hash})
            source = add_source(project, 'LaTeX 正文区：插入表格（同一视频）', path, '.sfvideo', parts)
        value = server.GenerateIn(**common, source_ids=[source], explanation_style=original.get('explanation_style', 'clear'),
            review_mode=original.get('review_mode', 'express'), instructions=original.get('instructions', ''))
        (target / 'source-evidence.json').write_text(j({'baseline': str(baseline_path), 'text_locator_sha256': source_hash,
            'segments': len(parts), 'frames': sum(bool(p.get('meta', {}).get('image_path')) for p in parts),
            'original_text_characters': sum(len(p['text']) for p in parts),
            'verified_image_cache_reused': bool(reuse),
            'transcription_ocr_included_in_current_timing': False, 'parameters': value.model_dump()}), encoding='utf-8')
    report = await generate(value)
    if args.case == 'proof':
        began = time.perf_counter()
        response = await server.chat_stream(server.ChatIn(project_id=project['id'], conversation_id=conversation['id'],
            source_ids=[source], provider='deepseek', model='deepseek-flash', explanation_style='balanced', learning_mode='deep',
            text=r'既然要求 $\varepsilon<\frac{b-a}{2}$，为什么还可以直接取临界值 $\varepsilon=\frac{b-a}{2}$？'))
        events = [json.loads(item) async for item in response.body_iterator]
        errors = [event['value'] for event in events if event['type'] == 'error']
        if errors: raise RuntimeError(str(errors))
        reply = next(event['value'] for event in reversed(events) if event['type'] == 'replace')
        (target / 'model-followup.md').write_text(reply, encoding='utf-8')
        report['followup_seconds'] = round(time.perf_counter() - began, 2)
    report['model'] = 'deepseek-flash'
    report['case'] = args.case
    (target / 'result.json').write_text(j(report), encoding='utf-8')
    print(j({'result': str(target / 'result.json'), 'seconds': report['generation_seconds'],
             'documents': [item['path'] for item in report['outputs']]}), flush=True)


if __name__ == '__main__': asyncio.run(main())
