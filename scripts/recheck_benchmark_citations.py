"""Re-export a saved real-model sample with current mechanical source checks.

No model prose is rewritten and no extra AI request is made. Only the exact
old software-generated warning block is replaced by the new check result.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('directory')
parser.add_argument('--data-root', help='Explicit isolated data reused by this sample.')
args = parser.parse_args()
target = Path(args.directory).resolve()
if target.parent != root / 'build' or not target.name.startswith('teaching-speed-'):
    raise ValueError('仅复核工作区内的教学速度验收目录')
data_root = Path(args.data_root).resolve() if args.data_root else target / 'data'
if not data_root.is_relative_to(root / 'build') or not (data_root / 'studyforge.sqlite3').is_file():
    raise ValueError('仅读取工作区内的已有验收数据库')
os.environ['STUDYFORGE_DATA_DIR'] = str(data_root)

from studyforge.db import many, one
from studyforge.materials import read_original_sources
from studyforge.lesson_quality import citation_checks, mark_source_warnings, expand_single_source_labels
from studyforge.exporters import export_docx

report = json.loads((target / 'result.json').read_text(encoding='utf-8'))
if len(report['outputs']) != 1: raise ValueError('此脚本只复核完整的单篇 DOCX 样例')
output = report['outputs'][0]
old = output['metadata']['lesson_quality']
document = (target / 'model-lecture.md').read_text(encoding='utf-8')
prefix = '已生成讲解文档：'
if document.startswith(prefix): document = document[len(prefix):].lstrip()
if old['warning_count']:
    notes = mark_source_warnings('', old).strip()
    if document.count(notes) != 1: raise ValueError('无法唯一识别旧的程序核对记录，未改写文档')
    document = document.replace(notes, '', 1)
job = one('SELECT payload_json FROM jobs WHERE id=?', (report['job_id'],))
ids = json.loads(job['payload_json'])['source_ids']
sources = read_original_sources(many('SELECT * FROM sources WHERE id IN (' + ','.join('?' for _ in ids) + ')', ids))
document, expanded = expand_single_source_labels(document, sources)
checks = citation_checks(document, sources)
checks['source_labels_expanded'] = expanded
document = mark_source_warnings(document, checks)
export_docx(document, Path(output['path']).stem, Path(output['path']))
(target / 'verified-lecture.md').write_text(document, encoding='utf-8')
result = {'old_warning_count': old['warning_count'], 'new_checks': checks,
          'model_prose_changed': False, 'source_labels_expanded': expanded, 'additional_model_requests': 0,
          'docx': output['path']}
(target / 'citation-recheck.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({key: value for key, value in result.items() if key != 'new_checks'} |
                 {'new_warning_count': checks['warning_count'], 'citations': checks['citation_count'],
                  'matched_citations': checks['matched_citations'], 'quotes': checks['quote_count'],
                  'matched_quotes': checks['matched_quotes']}, ensure_ascii=False))
