"""Optional live programming-assignment check using isolated local source data."""
import asyncio
import json
import os
import sys
import tempfile
import time

os.environ['STUDYFORGE_DATA_DIR'] = tempfile.mkdtemp(prefix='studyforge-coding-smoke-')

from studyforge import server
from studyforge.ai import CodexClient
from studyforge.codex_bridge import CodexBridge
from studyforge.config import files_dir
from studyforge.db import create_project, execute, j, now, one, uid


class LoggingClient(CodexClient):
    async def complete(self, system, user, json_mode=False):
        print('Stage:', system[:32], flush=True)
        return await super().complete(system, user, json_mode)


async def main():
    model = next((arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--model=')), 'gpt-6.1-sol')
    client = LoggingClient(CodexBridge(), model=model, effort='medium')
    project = create_project('编程出题验收')
    source_id = uid()
    original = files_dir() / 'keyword-rules.txt'
    original.write_text(
        '字符串扫描练习：统计独立关键词 key 的出现次数。输入为长度不超过 10000 的 str；'
        '仅把 ASCII 英文字母 A-Z/a-z、ASCII 数字 0-9 和下划线作为词内字符，其他字符视为分隔符。'
        '关键词匹配仅忽略 ASCII 大小写；中文相邻的 key 可以计数，_key 和 monkey 中的 key 不计数。'
        '匹配不重叠。返回非负整数。合法输入之外的类型及超限长度不需要处理。期望线性时间，不需进一步优化。',
        encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,error,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
            (source_id, project['id'], original.name, '.txt', str(original), j([{'locator': '旧预览', 'text': '不完整旧概括'}]), 'ready', None, now()))
    server.client_for = lambda provider: client
    started = time.perf_counter()
    print('Model:', model, 'medium', flush=True)
    try:
        assignment = await server.coding_generate(server.CodingIn(project_id=project['id'], source_ids=[source_id], provider='codex', language='python'))
        row = one('SELECT * FROM exercise_sets WHERE id=?', (assignment['id'],))
        private = json.loads(row['solutions_json'])[0]
        reports = private['generation_reviews']
        assert assignment['status'] == 'assigned' and 'solutions' not in assignment
        assert not private['solution'] in json.dumps(assignment, ensure_ascii=False)
        print('Assignment:', assignment['id'], assignment['title'])
        print('Review stages:', [(report['stage'], report.get('attempt')) for report in reports])
        print('Advisories:', sum(len(report.get('result', report).get('notes', [])) for report in reports))
        print('Reference runtime:', reports[-1].get('reference_tests'))
        print('Elapsed seconds:', round(time.perf_counter()-started, 1))
        print('Temporary data:', os.environ['STUDYFORGE_DATA_DIR'])
    finally:
        await client.close()


if __name__ == '__main__':
    asyncio.run(main())
