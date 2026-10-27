"""One resumable library job, with small sequential execution batches.

Selections are normalized before batching. Only the active batch holds page
geometry or chapter workers; completed batches live in SQLite, not in the UI.
"""
from __future__ import annotations

import hashlib
import math

from .db import connect, j, many, now, one, unj

SELECTION_LIMIT = 2000
BATCH_THRESHOLD = 200
BATCH_SIZE = 100
AI_BUDGET_STEP = 'ranges-ai-budget-v1'


def batch_plan(ids):
    if len(ids) <= BATCH_THRESHOLD:
        return {}
    return {'batch_size': BATCH_SIZE, 'batches_total': math.ceil(len(ids) / BATCH_SIZE)}


def chunks(ids, size):
    for start in range(0, len(ids), size):
        yield ids[start:start + size]


def saved_step(job_id, key):
    row = one('SELECT response_json FROM library_steps WHERE job_id=? AND step_key=?', (job_id, key))
    return unj(row['response_json']) if row else None


def reserve_ai_choice(job_id, signature, limit):
    """Cap unique ambiguous-heading choices for the entire job, including retries."""
    ident = hashlib.sha256(j(signature).encode()).hexdigest()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT response_json FROM library_steps WHERE job_id=? AND step_key=?',
                         (job_id, AI_BUDGET_STEP)).fetchone()
        choices = unj(row['response_json'], []) if row else []
        if ident in choices:
            return True
        if len(choices) >= limit:
            return False
        choices.append(ident)
        db.execute('INSERT OR REPLACE INTO library_steps VALUES (?,?,?,?)',
                   (job_id, AI_BUDGET_STEP, j(choices), now()))
        return True


class BatchControl:
    def __init__(self, root, kind, index, total, nodes_before, nodes_total, node_count):
        self.root, self.job_id = root, root.job_id
        self.kind, self.index, self.total = kind, index, total
        self.nodes_before, self.nodes_total, self.node_count = nodes_before, nodes_total, node_count
        self.page_totals, self.processed_pages = {}, {}

    async def checkpoint(self):
        await self.root.checkpoint()

    async def step(self, key, signature, operation):
        # Source and model steps remain reusable after a crash within a batch.
        # Heading-page steps are shared across batches via their source keys.
        prefix = key if self.kind == 'ranges' else ['read-batch-v1', self.index, key]
        return await self.root.step(prefix, signature, operation)

    def progress(self, percent):
        self.root.progress(95 * (self.index + max(0, min(100, percent)) / 100) / self.total)

    def stage(self, label, **values):
        completed = len(values.get('ranges', values.get('nodes_completed', [])))
        values.update(batch_index=self.index + 1, batches_total=self.total,
                      batches_completed=self.index, batch_node_count=self.node_count,
                      nodes_total=self.nodes_total)
        if 'ranges' in values or 'nodes_completed' in values:
            values.update(batch_nodes_completed=completed,
                          nodes_completed_count=self.nodes_before + completed)
        self.root.stage(f'第 {self.index + 1}/{self.total} 批 · ' + label, **values)

    def record_pages(self, node_id, count):
        self.processed_pages[node_id] = max(count, self.processed_pages.get(node_id, 0))
        self.root.processed_pages[node_id] = max(count, self.root.processed_pages.get(node_id, 0))
        total = sum(self.root.page_totals.values())
        done = sum(self.root.processed_pages.values())
        self.stage('已保存分页整理', pages_processed=done, total_pages=total)
        if total:
            self.root.progress(min(90, 90 * done / total))


async def run_read_batches(control, book, payload, client_factory):
    from . import library
    from .library_worker import run_read

    ids = payload['node_ids']
    plan = list(chunks(ids, payload['batch_size']))
    completed = 0
    last = {}
    for index, batch in enumerate(plan):
        await control.checkpoint()
        # A saved batch cannot bless later edits to the authorized page scopes.
        nodes = {n['id']: n for n in many('SELECT * FROM library_nodes WHERE book_id=?', (book['id'],))}
        if any(ident not in nodes or not nodes[ident]['confirmed']
               or library.version(book, nodes[ident]) != payload['scopes'][ident] for ident in ids):
            raise ValueError('阅读范围已改变，请核对后重新安排；已完成笔记保留，没有覆盖你的修改')
        control.page_totals = {ident: nodes[ident]['end_page'] - nodes[ident]['start_page'] + 1 for ident in ids}
        key = f'read-batch-result-v1:{index}'
        last = saved_step(control.job_id, key)
        if last is None:
            batch_control = BatchControl(control, 'read', index, len(plan), completed, len(ids), len(batch))
            batch_control.stage('开始处理本批节点', nodes_completed=[], failures=[])
            last = await run_read(batch_control, book, payload | {'node_ids': batch}, client_factory)
            await control.checkpoint()
            with connect() as db:
                db.execute('INSERT OR REPLACE INTO library_steps VALUES (?,?,?,?)',
                           (control.job_id, key, j(last), now()))
        for ident in batch:
            control.processed_pages[ident] = control.page_totals[ident]
        completed += len(batch)
        control.progress(95 * (index + 1) / len(plan))
        control.stage(f'已保存第 {index + 1}/{len(plan)} 批；完成 {completed}/{len(ids)} 个节点',
                      batches_completed=index + 1, batches_total=len(plan), batch_index=index + 1,
                      batch_node_count=len(batch), batch_nodes_completed=len(batch),
                      nodes_completed_count=completed, nodes_total=len(ids),
                      nodes_completed=last['nodes_completed'], failures=[],
                      pages_processed=sum(control.processed_pages.values()), total_pages=sum(control.page_totals.values()))
    return last | {'stage':'所选节点分批整理完成 · 不代表学生已掌握',
                   'batches_completed':len(plan), 'batches_total':len(plan), 'batch_index':len(plan),
                   'nodes_completed_count':completed, 'nodes_total':len(ids), 'result_preview_only':True,
                   'pages_processed':sum(control.processed_pages.values()), 'total_pages':sum(control.page_totals.values())}


async def run_range_batches(control, book, payload, client_factory):
    from . import library
    from .library_ranges import APPLIED_STEP, MAX_AI_CHOICES, finish_ranges, outline_signature, run_ranges

    final = saved_step(control.job_id, APPLIED_STEP)
    if final is not None:
        return finish_ranges(control, book, payload, final)
    ids = payload['batch_node_ids']
    plan = list(chunks(ids, payload['batch_size']))
    expected = payload['outline_signature']
    pending, inspected, warnings = [], set(), []
    completed = rechecks = checks = 0
    last = {}
    for index, batch in enumerate(plan):
        await control.checkpoint()
        key = f'ranges-batch-applied-v1:{index}'
        saved = saved_step(control.job_id, key)
        if saved is None:
            batch_control = BatchControl(control, 'ranges', index, len(plan), completed, len(ids), len(batch))
            batch_control.stage('开始检查本批边界', ranges=[])
            await run_ranges(batch_control, book, payload | {'node_ids':batch, 'outline_signature':expected,
                             'read_after':False, '_applied_step':key}, client_factory)
            saved = saved_step(control.job_id, key)
        expected = saved['outline_signature_after']
        last = saved['output']
        pending.extend(last['pending_node_ids'])
        inspected.update(last['boundary_page_numbers'])
        checks += last['boundary_pages']
        rechecks += last['heading_rechecks']
        warnings.extend(w for w in last['warnings'] if w not in warnings)
        warnings = warnings[:40]
        completed += len(batch)
        control.progress(95 * (index + 1) / len(plan))
        control.stage(f'已保存第 {index + 1}/{len(plan)} 批；核对 {completed}/{len(ids)} 个节点',
                      batches_completed=index + 1, batches_total=len(plan), batch_index=index + 1,
                      batch_node_count=len(batch), batch_nodes_completed=len(batch),
                      nodes_completed_count=completed, nodes_total=len(ids), ranges=last['ranges'],
                      pending_node_ids=list(pending), boundary_pages=len(inspected))
    await control.checkpoint()
    output = last | {'stage':f'分批定位完成：{completed - len(pending)} 个可用，{len(pending)} 个待核对；未通读正文',
                     'batches_completed':len(plan), 'batches_total':len(plan), 'batch_index':len(plan),
                     'nodes_completed_count':completed, 'nodes_total':len(ids), 'result_preview_only':True,
                     'pending_node_ids':pending, 'boundary_pages':len(inspected), 'boundary_checks':checks,
                     'boundary_page_numbers':sorted(inspected), 'heading_rechecks':rechecks, 'warnings':warnings,
                     'ai_choices':len(saved_step(control.job_id, AI_BUDGET_STEP) or [])}
    assert output['ai_choices'] <= MAX_AI_CHOICES
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        nodes = [dict(n) for n in db.execute('SELECT * FROM library_nodes WHERE book_id=? ORDER BY position,id', (book['id'],))]
        if outline_signature(nodes) != expected:
            raise ValueError('分批定位后目录或范围已改变，请重新安排；没有覆盖手动修改')
        selected = set(payload['node_ids'])
        final = {'output':output, 'outline_signature_after':expected,
                 'versions':{n['id']:library.version(book, n) for n in nodes if n['id'] in selected}}
        db.execute('INSERT INTO library_steps VALUES (?,?,?,?)', (control.job_id, APPLIED_STEP, j(final), now()))
    return finish_ranges(control, book, payload, final)
