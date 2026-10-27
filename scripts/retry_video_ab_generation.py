"""Recover one isolated A/B generation without repeating media parsing.

The failed attempt and its time stay in the report. The frozen application
snapshot, settings, original source, and project-scoped visual cache are reused.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import time


def save(path: Path, value: dict) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


async def recover(work: Path, variant: str, direct: bool = False) -> int:
    from studyforge import server
    from studyforge.db import one, unj
    from studyforge.job_control import active_jobs

    report_path = work / variant / 'report.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if report['status'] != 'failed':
        raise ValueError('只恢复已失败的隔离试验，不重启进行中的任务')
    previous_attempts = report.get('recovery_attempts', 0)
    if previous_attempts and not (direct and previous_attempts == 1 and
                                  not report.get('direct_recovery_attempt')):
        raise ValueError('只允许一次普通恢复，以及连接已验证后的单次直连恢复')
    original_job = one('SELECT * FROM jobs WHERE id=?', (report['generation_job_id'],))
    if not original_job or original_job['status'] != 'failed':
        raise ValueError('试验记录与失败任务不符')
    archive = work / variant / ('report.initial-failed.json' if not previous_attempts
                               else f'report.failed-recovery-{previous_attempts}.json')
    save(archive, report)
    request = server.GenerateIn.model_validate(unj(original_job['payload_json'], {}))
    first_seconds = report['elapsed_seconds']
    started = time.perf_counter()
    failure = report.pop('error')
    report.setdefault('initial_failure', failure)
    report.setdefault('failed_attempts', []).append({'job_id': original_job['id'],
                                                    'error': failure,
                                                    'processing_seconds_so_far': first_seconds})
    report.update(status='running', recovery_attempts=previous_attempts + 1,
                  failed_generation_job_id=original_job['id'],
                  recovery_note='复用同一软件源码快照及原资料；已成功核对的画面使用原缓存，失败请求重试耗时计入总耗时。')
    if direct:
        report.update(direct_recovery_attempt=True, network_route='direct_https_for_final_recovery',
                      network_comparison_note='前两次尝试使用原环境代理；极短直连请求验证成功后，最后一次恢复仅在测试进程中使用官方 HTTPS 直连。系统与软件代理配置未修改，A/B 总耗时不再视为相同网络条件的严格对比。')
    launched = await server.generate(request)
    job_id = launched['job_id']
    report['generation_job_id'] = job_id
    save(report_path, report)
    try:
        while True:
            row = one('SELECT * FROM jobs WHERE id=?', (job_id,))
            report['current_stage'] = unj(row['result_json'], {}).get('stage')
            report['recovery_seconds'] = round(time.perf_counter() - started, 3)
            report['elapsed_seconds'] = round(first_seconds + report['recovery_seconds'], 3)
            save(report_path, report)
            print(variant, '恢复', report['current_stage'], f"{report['recovery_seconds']:.0f}s", flush=True)
            if row['status'] not in ('queued', 'running', 'pausing'):
                break
            await asyncio.sleep(15)
        if job_id in active_jobs:
            await active_jobs[job_id]
        row = one('SELECT * FROM jobs WHERE id=?', (job_id,))
        if row['status'] != 'completed':
            raise RuntimeError(row['error'] or row['status'])
        report['artifacts'] = []
        for item in unj(row['result_json'], {}).get('artifacts', []):
            artifact = one('SELECT * FROM artifacts WHERE id=?', (item['id'],))
            destination = work / 'outputs' / f"{variant}方案 {server.artifact_download_name(artifact)}"
            shutil.copyfile(artifact['path'], destination)
            report['artifacts'].append(str(destination))
        report['status'] = 'completed'
    except Exception as error:
        report.update(status='failed', error=f'{type(error).__name__}: {error}')
    report['recovery_seconds'] = round(time.perf_counter() - started, 3)
    report['elapsed_seconds'] = round(first_seconds + report['recovery_seconds'], 3)
    report['generation_seconds'] = round(report['elapsed_seconds'] - report['parsing_seconds'], 3)
    save(report_path, report)
    print(json.dumps({key: value for key, value in report.items()
                     if key not in ('frame_times', 'common_preparation')}, ensure_ascii=False), flush=True)
    return 0 if report['status'] == 'completed' else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('work', type=Path)
    parser.add_argument('--variant', choices=('A', 'B'), default='B')
    parser.add_argument('--direct', action='store_true')
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[1]
    work = args.work.resolve()
    if not work.is_relative_to(workspace / 'build'):
        raise ValueError('仅恢复工作区 build 下的隔离试验')
    snapshot = work / 'baseline-source'
    if not (snapshot / 'studyforge/server.py').is_file():
        raise ValueError('原试验源码快照不存在，停止恢复以避免改变比较条件')
    os.environ['STUDYFORGE_DATA_DIR'] = str(work / args.variant / 'data')
    if args.direct:
        # Process-local route change; TLS verification and stored settings stay intact.
        for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
                     'http_proxy', 'https_proxy', 'all_proxy'):
            os.environ.pop(name, None)
    sys.path.insert(0, str(snapshot))
    return asyncio.run(recover(work, args.variant, args.direct))


if __name__ == '__main__':
    raise SystemExit(main())
