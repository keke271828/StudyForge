"""Natural-question teaching comparison through the real tutor entry point.

Requires --live to call the model. Uses an isolated database and existing
keyring credentials. Never exports keys, headers or private reasoning.
Website answers must come from the user; no website result is fabricated.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from contextlib import aclosing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

QUESTIONS = {
    'cauchy': (
        '我在学实数向量的柯西－施瓦茨不等式：\n\n'
        '(∑_{i=1}^n a_i b_i)^2 ≤ (∑_{i=1}^n a_i^2)(∑_{i=1}^n b_i^2)。\n\n'
        '书上为了证明它，构造 f(t)=∑_{i=1}^n(a_i t+b_i)^2，'
        '然后用二次函数的判别式不大于0。我能跟着展开和计算，却不知道为什么会想到引入t、'
        '构造这个f(t)。你能把这个思路讲明白吗？\n\n这次只讲解，不布置习题。'
    ),
    'gauss': (
        '我看到高斯定律\n∮_S E·dS=Q内/ε0。\n'
        '如果一个闭合曲面里的总电荷是0，右边就等于0，那里面的电场应该处处为0吧？'
        '我这样理解哪里不对？\n\n这次只讲解，不布置习题。'
    ),
    'notes_causality': (
        '我看到一种说法：调查两万名学生发现，经常记笔记的学生平均成绩更好，差异在统计上很显著。'
        '样本这么大，应该能证明“多记笔记会让成绩变好”了吧？'
        '如果还不能，究竟缺少什么？\n\n这次只讲解，不布置习题。'
    ),
}

# Evaluator notes are stored separately and NEVER enter either model request.
EVALUATOR_NOTES = {
    'cauchy': [
        '解释待证明式的平方范数与混合项如何提示构造；不只展开多项式。',
        '区分引入参数后的所有 t 约束与一个 t 的约束，并说明怎样选择消去或最小化。',
        '判别式方法要求二次项正，零向量情况必须单独处理。',
        '等号条件须覆盖零向量和线性相关，不把非零比值写成普遍条件。',
        '具体例子支持原结论；不把该方法说成唯一证明。',
        '后续追问再测试理解；首题不能提前泄露以上评分点。',
    ],
    'gauss': [
        '零净通量不等于电场在曲面上或内部逐点为零。',
        '净电荷为零不等于没有电荷；外部电荷仍可造成内部非零场。',
        '反例须真实说明正负通量与法向，不把电场大小解释为负数。',
        '直觉与面积积分准确衔接，不强加无关跨学科比喻。',
    ],
    'notes_causality': [
        '区分统计关联和改变记笔记行为的因果效应，不假装核实未提供的研究。',
        '大样本不能自动消除混杂、选择偏差；统计显著不保证因果或实际效果大。',
        '具体解释已有差异怎样产生关联，并说明什么比较或设计可帮助区分。',
        '证据仍取决于条件与研究设计，不把随机试验说成唯一可行方法。',
        '不额外数学化，不强行关联物理；自拟例子不冒充真实研究结果。',
    ],
}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


async def main(args):
    output = Path(args.output).resolve()
    if args.live and (output / 'report.json').exists():
        raise SystemExit('已有测试结果，请使用新的输出目录，避免覆盖原始回答。')
    output.mkdir(parents=True, exist_ok=True)
    cases = args.case or list(QUESTIONS)
    questions = dict(QUESTIONS)
    if args.question_file:
        if len(cases) != 1:
            raise SystemExit('自定义追问只允许选择一个案例。')
        questions[cases[0]] = Path(args.question_file).read_text(encoding='utf-8').strip()
        if not questions[cases[0]]:
            raise SystemExit('追问不能为空。')
    for case in cases:
        (output / f'{case}-question.txt').write_text(questions[case], encoding='utf-8')
    write_json(output / 'evaluator-notes.json', {case: EVALUATOR_NOTES[case] for case in cases})
    if not args.live:
        print(json.dumps({'questions': cases, 'output': str(output), 'model_calls': 0}, ensure_ascii=False))
        return

    # Set before importing application modules: synthetic misconceptions cannot
    # enter the student's real profile, history, tasks or desktop notifications.
    previous = Path(args.continue_from).resolve() if args.continue_from else None
    if previous and (len(cases) != 1 or args.arm != ['software'] or not args.question_file):
        raise SystemExit('延续测试需指定一个案例、--arm software 和 --question-file。')
    previous_report = json.loads((previous / 'report.json').read_text(encoding='utf-8')) if previous else None
    os.environ['STUDYFORGE_DATA_DIR'] = str((previous or output) / 'isolated-data')
    from studyforge import ai, conversations, server
    from studyforge.db import create_project, many, one
    from studyforge.teaching_policy import POLICY_VERSION

    # Change only the shared teaching policy in this isolated experiment. Keep
    # the actual server, model, modes, styles, tools and context handling intact.
    policy_override = None
    if args.policy_file:
        path = Path(args.policy_file).resolve()
        policy_override = json.loads(path.read_text(encoding='utf-8'))
        allowed = {'TEACHER_PERSONA', 'CHAT_RULES', 'TEACHING_TASK_REMINDER'}
        if not policy_override or set(policy_override) - allowed or any(
                not isinstance(text, str) or not text.strip() for text in policy_override.values()):
            raise SystemExit('实验策略只接受非空的共同导师、对话规则或任务提醒。')
        for name, text in policy_override.items():
            setattr(server, name, text)

    ai.save_settings({'chat_provider': 'deepseek', 'agent_tools_enabled': False,
                      'background_learning_enabled': False, 'agent_permission_mode': 'read_only'})
    previous_chat = None
    if previous:
        prior = next((row for row in previous_report['results'] if row['case'] == cases[0]
                      and row['arm'] == 'software' and row['status'] == 'completed'), None)
        if not prior:
            raise SystemExit('没有可延续的已完成软件对话。')
        previous_chat = one('SELECT * FROM conversations WHERE id=?', (prior['conversation_id'],))
        if not previous_chat:
            raise SystemExit('隔离数据库中没有找到该对话。')
        project = {'id': previous_chat['project_id']}
    else:
        project = create_project('教学质量自然问题对照（隔离测试）')
    common = {'model': args.model, 'effort': args.effort, 'policy_version': POLICY_VERSION,
              'policy_sha256': hashlib.sha256((ROOT / 'studyforge/teaching_policy.py').read_bytes()).hexdigest(),
              'policy_files_sha256': {name: hashlib.sha256((ROOT / 'studyforge' / name).read_bytes()).hexdigest()
                                       for name in ('teaching_policy.py', 'teaching_styles.py', 'learning_modes.py')},
              'software_style': 'balanced', 'software_mode': 'deep', 'language': 'zh',
              'continued_from': str(previous) if previous else None,
              'experimental_policy_file': str(Path(args.policy_file).resolve()) if args.policy_file else None,
              'experimental_policy_sha256': hashlib.sha256(Path(args.policy_file).read_bytes()).hexdigest() if args.policy_file else None,
              'web_configuration_user_report': 'V4.1 Flash；深度思考开启；用户最近明确报告未联网搜索，未核验网站内部配置',
              'limitations': [
                  '软件使用真实聊天处理函数和真实 API，未测试桌面绘制性能。',
                  'API 返回的模型 ID 不证明其与网站的显示名称完全等价。',
                  '简短提示词组仍保留同一客户端的对话边界规则；不是严格零 system 提示。',
                  '软件组保留真实代理环境和画像读取工具；只能比较整体回答，不能单独归因提示词。',
                  '一轮每组一个样本，不推断稳定胜率或普遍提速。',
              ]}
    rows = []

    async def sample(case, arm):
        start = time.perf_counter()
        first = None
        requests = []
        tools_used = []
        clients = []
        response_text = ''
        row = {'case': case, 'arm': arm, 'status': 'running', 'requests': requests}

        class ObservedClient(ai.DeepSeekClient):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                clients.append(self)

            async def stream_packets(self, body):
                nonlocal first
                record = {
                    'model': body['model'], 'thinking': body.get('thinking'),
                    'reasoning_effort': body.get('reasoning_effort'),
                    'tools': [tool['function']['name'] for tool in body.get('tools', [])],
                    'messages': [{k: v for k, v in message.items() if k != 'reasoning_content'}
                                 for message in body['messages']],
                    'response_models': [], 'usage': None,
                }
                requests.append(record)
                async for packet in super().stream_packets(body):
                    model = packet.get('model')
                    if model and model not in record['response_models']:
                        record['response_models'].append(model)
                    if packet.get('usage'):
                        record['usage'] = packet['usage']
                    for choice in packet.get('choices', []):
                        if choice.get('delta', {}).get('content') and first is None:
                            first = time.perf_counter() - start
                    yield packet

        original = server.DeepSeekClient
        try:
            if arm == 'software':
                server.DeepSeekClient = ObservedClient
                chat = previous_chat or conversations.create(project['id'], 'deepseek', args.model)
                row['conversation_id'] = chat['id']
                response = await server.chat_stream(server.ChatIn(
                    project_id=project['id'], conversation_id=chat['id'], text=questions[case],
                    source_ids=[], provider='deepseek', model=args.model, reasoning_effort=args.effort,
                    learning_mode='deep', explanation_style='balanced', output_language='zh'))
                done = False
                # Close a suspended iterator in the same task/context when an
                # error event ends a sample, rather than at asyncio shutdown.
                async with aclosing(response.body_iterator) as stream:
                    async for data in stream:
                        event = json.loads(data)
                        if event['type'] == 'error':
                            raise RuntimeError(event['value'])
                        if event['type'] == 'job':
                            raise RuntimeError('讲解问题被错误识别为出题请求')
                        if event['type'] == 'tool':
                            tools_used.append(event['value'])
                        if event['type'] == 'done':
                            done = True
                messages = many("SELECT content FROM messages WHERE conversation_id=? AND role='assistant' ORDER BY created_at,rowid", (chat['id'],))
                if not done or not messages:
                    raise RuntimeError('真实聊天入口未完成或未保存回答')
                response_text = messages[-1]['content']
            else:
                client = ObservedClient(args.model, effort=args.effort)
                async for kind, value in client.agent_stream([
                    {'role': 'system', 'content': '请用中文回答。'},
                    {'role': 'user', 'content': questions[case]},
                ]):
                    if kind == 'final':
                        response_text = value
            if not response_text.strip():
                raise RuntimeError('没有有效最终回答')
            row['status'] = 'completed'
            row['answer_chars'] = len(response_text)
            name = f'{case}-{arm}.md'
            (output / name).write_text(response_text, encoding='utf-8')
            row['answer_file'] = name
            row['answer_sha256'] = hashlib.sha256(response_text.encode('utf-8')).hexdigest()
        except Exception as exc:
            row['status'] = 'failed'
            row['error'] = f'{type(exc).__name__}: {exc}'
        finally:
            server.DeepSeekClient = original
            for client in clients:
                await client.close()
            row['elapsed_seconds'] = round(time.perf_counter() - start, 2)
            row['first_visible_seconds'] = round(first, 2) if first is not None else None
            row['tools_used'] = tools_used
            request_file = f'{case}-{arm}-requests.json'
            write_json(output / request_file, requests)
            row['request_file'] = request_file
            row.pop('requests')
            rows.append(row)
            write_json(output / 'report.json', {'configuration': common, 'results': rows})
            print(json.dumps(row, ensure_ascii=False), flush=True)

    # Sequential arms avoid shared monkeypatches and same-process scheduling
    # interference. Later rounds can reverse order and repeat independently.
    for case in cases:
        for arm in args.arm or ['software', 'minimal']:
            await asyncio.wait_for(sample(case, arm), timeout=420)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--case', choices=list(QUESTIONS), action='append')
    parser.add_argument('--arm', choices=['software', 'minimal'], action='append')
    parser.add_argument('--model', default='deepseek-flash')
    parser.add_argument('--effort', default='high')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--continue-from', help='延续一个已完成软件案例的隔离对话')
    parser.add_argument('--question-file', help='可核对的原始追问文本，不附评分标准')
    parser.add_argument('--policy-file', help='仅在隔离实验覆盖共同教学规则的 JSON，保留其他实际请求条件')
    asyncio.run(main(parser.parse_args()))
