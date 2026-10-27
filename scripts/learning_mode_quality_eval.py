"""Compare actual tutor/generation endpoints on the same source and request.

Requires --live, isolates all fixtures and history, and does not grade its own
semantic quality. Read each output and record a separate content review.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

SUBJECTS = {
    'math': ('柯西不等式的平方构造',
        '对实数数组a_i、b_i（i=1,...,n），令A=sum(a_i*b_i)，B=sum(b_i^2)，C=sum(a_i^2)。'
        '目标是A^2<=BC。若B=0，则每个b_i=0，A=0，结论及等号成立。若B>0，'
        '考虑Q(t)=sum((a_i-t*b_i)^2)=C-2tA+t^2B，它对每个实数t都非负。'
        '取t=A/B，得到Q(A/B)=C-A^2/B>=0，从而A^2<=BC。'
        '等号当且仅当a_i=(A/B)*b_i对每个i成立。构造中t用于调节交叉项，'
        '平方非负将目标差值联系到可核对的量；这是一种可行证明，不证明方法唯一。'
        '本资料只讨论有限维实数数组，没有证明复数版本，也没有给出这一构造的历史发现过程。'),
    'social': ('自愿讨论与成绩的因果辨析',
        '某学校观察到自愿参加学习讨论的学生平均成绩较高，这是一条相关描述。'
        '讨论可能改善学习；原有学习动机也可能同时影响参加讨论和成绩。'
        '本资料没有随机分配，也没有给出能排除共同原因的数据，不能仅凭这项相关认定讨论有因果效果。'
        '增大样本能减少一些随机误差，但不会自动消除这类系统偏差。'
        '要解释因果效果，需要明确比较条件及识别假设，并寻找能区分解释的证据。'
        '能否推广到其他学校、人群和实施条件是另一个问题，需要相应证据。'
        '本资料没有测出因果效应的大小，也没有给出任何学者归属。'),
}
MODES = ('overview', 'deep', 'research')
REQUEST = '请按当前学习模式讲解这份资料，正文约400—650汉字，只用给定材料，不布置习题，不写发现史。'


async def evaluate(args):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(output / 'data')
    import httpx
    from studyforge import ai, server
    from studyforge.codex_bridge import CodexBridge, close_chat_bridges, bridge
    from studyforge.db import create_project, execute, j, many, now, one, uid, unj
    from studyforge.teaching import headings
    from docx import Document

    ai.save_settings({'chat_provider': 'codex', 'codex_model': args.model,
        'agent_tools_enabled': False, 'agent_network_enabled': False,
        'agent_web_video_enabled': False, 'background_learning_enabled': False,
        'output_language': 'zh', 'review_mode': 'express'})
    calls, rows = [], []
    real_stream = CodexBridge.stream_turn

    async def measured(self, prompt, *a, **kw):
        record = {'prompt': prompt, 'model': kw.get('model'), 'text': '', 'seconds': None}
        calls.append(record)
        started = time.perf_counter()
        try:
            async for kind, value in real_stream(self, prompt, *a, **kw):
                if kind == 'final': record['text'] = value
                elif kind == 'delta' and not record['text']: record.setdefault('partial', []).append(value)
                yield kind, value
        finally:
            record['seconds'] = round(time.perf_counter() - started, 2)

    CodexBridge.stream_turn = measured
    def write_report():
        report = {'simulated': False, 'real_learning_data_used': False, 'provider': 'codex',
            'model': args.model, 'effort': args.effort, 'same_request': REQUEST,
            'cases': rows, 'model_requests': len(calls), 'calls': calls,
            'notice': '来源匹配、不同标题与篇幅不等于模式适配或教学正确；需逐份审读。'}
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://test') as api:
            for subject in args.subject or SUBJECTS:
                title, original = SUBJECTS[subject]
                project = create_project('模式对照 · ' + title)
                path = output / (title + '.txt')
                path.write_text(original, encoding='utf-8')
                source = uid()
                execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (source, project['id'], path.name, '.txt', str(path), j([{'locator':'旧预览','text':'DO_NOT_USE_PREVIEW'}]), 'ready', now()))
                for role in args.role or ('tutor', 'lecture'):
                    for mode in args.mode or MODES:
                        name = f'{subject}-{role}-{mode}'
                        started, before = time.perf_counter(), len(calls)
                        body = {'project_id': project['id'], 'source_ids': [source], 'provider': 'codex',
                            'model': args.model, 'reasoning_effort': args.effort, 'learning_mode': mode,
                            'explanation_style': 'clear', 'output_language': 'zh'}
                        async def sample():
                            if role == 'tutor':
                                response = await api.post('/api/chat/stream', json=body | {'text': REQUEST})
                                response.raise_for_status()
                                events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
                                errors = [event['value'] for event in events if event['type'] == 'error']
                                if errors: raise RuntimeError(str(errors))
                                chat = next(event['value'] for event in events if event['type'] == 'conversation')
                                reply = one("SELECT content FROM messages WHERE conversation_id=? AND role='assistant' ORDER BY created_at DESC,rowid DESC LIMIT 1", (chat,))
                                if not reply: raise RuntimeError('导师没有保存回答')
                                return reply['content'], {'conversation_id': chat}
                            response = await api.post('/api/generate', json=body | {'instructions': REQUEST,
                                'summary_level': 3, 'exercises': False, 'review_mode': 'express', 'format': 'docx'})
                            response.raise_for_status()
                            job_id = response.json()['job_id']
                            while True:
                                job = one('SELECT * FROM jobs WHERE id=?', (job_id,))
                                if job['status'] in ('completed', 'failed', 'cancelled'):
                                    if job['status'] != 'completed': raise RuntimeError(job['error'] or job['status'])
                                    break
                                await asyncio.sleep(.1)
                            artifact = next(a for a in many('SELECT * FROM artifacts WHERE project_id=?', (project['id'],))
                                if unj(a['metadata_json'], {}).get('generation_job_id') == job_id)
                            metadata = unj(artifact['metadata_json'], {})
                            text = unj(job['payload_json'], {}).get('generated_document')
                            if not text:
                                text = one('SELECT content FROM messages WHERE id=(SELECT message_id FROM generation_dialogue_outputs WHERE job_id=?)', (job_id,))['content'].removeprefix('已生成讲解文档：\n\n')
                            doc = Document(artifact['path'])
                            return text, {'job_id': job_id, 'document': artifact['path'], 'metadata': metadata,
                                'docx_readable': bool(doc.paragraphs), 'exercise_sets': len(many('SELECT id FROM exercise_sets WHERE project_id=?', (project['id'],)))}
                        try:
                            text, details = await asyncio.wait_for(sample(), args.timeout)
                            md = output / (name + '.md'); md.write_text(text, encoding='utf-8')
                            row = {'case': name, 'subject': subject, 'role': role, 'mode': mode, 'status': 'completed',
                                'text': text, 'markdown': str(md), 'headings': [h[2] for h in headings(text)],
                                'semantic_review': None, **details}
                        except Exception as exc:
                            row = {'case': name, 'subject': subject, 'role': role, 'mode': mode,
                                'status': 'failed', 'error': str(exc) or type(exc).__name__, 'semantic_review': None}
                        row.update(seconds=round(time.perf_counter()-started, 2), model_requests=len(calls)-before)
                        rows.append(row); write_report()
                        print(j({key: row.get(key) for key in ('case','status','seconds','model_requests','error')}), flush=True)
    finally:
        CodexBridge.stream_turn = real_stream
        await close_chat_bridges()
        await bridge.close()
    return output / 'report.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--model', required=True)
    parser.add_argument('--effort', default='medium')
    parser.add_argument('--subject', action='append', choices=SUBJECTS)
    parser.add_argument('--role', action='append', choices=('tutor','lecture'))
    parser.add_argument('--mode', action='append', choices=MODES)
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if not args.live: parser.error('只在显式--live时调用真实模型；不存在模拟教学质量分数')
    print(asyncio.run(evaluate(args)), flush=True)


if __name__ == '__main__': main()
