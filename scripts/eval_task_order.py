"""Native teaching-message order comparison; no added policy or reduced input."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    {'id': 'epsilon', 'title': '数学追问：已懂邻域，只问全称命题', 'role': 'tutor', 'style': 'balanced', 'mode': 'deep',
     'source': '极限定义：对任意ε>0，存在N使n>N时|x_n−a|<ε。反证同时趋于a,b且a<b，可取ε=(b−a)/2，统一N后得到矛盾。',
     'previous': '取ε=(b−a)/2时两个开邻域不相交，N=max(N₁,N₂)使两个限制同时成立，得到矛盾。',
     'question': '开区间、最大阈值和矛盾我都懂了。我只不懂“任意ε”怎么允许主动取(b−a)/2，这不是给定义加限制吗？只补这个逻辑，不重新证明唯一性，不出题。',
     'checks': ['已知全称命题可应用合法特例，与证明极限不同', 'a<b保证该值为正', '不重证两个邻域和统一N', '不把半间距当唯一可取值']},
    {'id': 'copy_document', 'title': '文档追问：替换槽位，保留完整静态结果', 'role': 'lecture', 'style': 'clear', 'mode': 'deep',
     'source': '代码未运行：a=[[1],[2]]; b=a.copy(); b[0]=[9]。浅复制得到不同的外层，但初始共享两个内层对象；槽位赋值替换引用，不修改原内层列表。',
     'previous': 'a与b外层不同，内层原来共享；b[0].append(3)会修改共享内层，使a也看到变化。',
     'question': '外层不同、内层共享和append我已经懂了。这次换成b[0]=[9]，为什么a[0]不变？只补这一句操作，给出原代码完整静态结果，不重画整套引用关系，不出题。',
     'instructions': '沿最后这个疑问整理成可独立阅读的简短讲解，保留完整静态结果，最后系统性总结。',
     'checks': ['赋值只换b的第0槽位，未修改旧[1]', 'a=[[1],[2]], b=[[9],[2]]，第二项保留', '静态推演不声称实机执行', '独立可读且总结不引入新内容']},
    {'id': 'causal', 'title': '社会科学追问：研究模式也服从本次比较范围', 'role': 'tutor', 'style': 'clear', 'mode': 'research',
     'source': '假想观察：常记笔记与高分相关。解释甲：自律同时促使记笔记和努力学习；解释乙：原本理解快、成绩好的学生更有余力记笔记。均为未经因果验证的候选解释。',
     'previous': '大样本降低抽样随机误差，不能自动消除混杂或反向因果，相关不直接证明因果。',
     'question': '大样本不能证明因果我已经懂了。只比较原文甲和乙：为什么一个叫混杂，一个叫反向因果？请各用一句箭头关系接回同一例子，说明两者能否并存；不要另设计研究，不出题。',
     'checks': ['甲是共同原因同时影响记笔记和成绩', '乙成绩/原有能力影响记笔记，方向与目标相反', '两者可并存但不能称本次已验证', '不重讲抽样或设计新实验']},
    {'id': 'full_chemistry', 'title': '完整讲解对照：明确展开时不应压缩遗漏', 'role': 'lecture', 'style': 'balanced', 'mode': 'deep',
     'source': '本材料给定反应A+B→C的速率模型v=k[A][B]，浓度单位mol/L，速率单位mol/(L·s)，k单位L/(mol·s)。反应式不能单独推出这个速率律。设k=0.2 L/(mol·s)，[A]=0.5 mol/L，[B]=0.3 mol/L。',
     'previous': 'v是反应速率，[A]、[B]是给定模型中的浓度，不能单由化学计量系数判定速率律。',
     'question': '这次请把整段系统讲透，不是只补一句：解释每个量、为何这样推k的单位、完成给定数值例子，并说明反应方程式与给定速率模型的边界，最后系统总结。可以充分展开必要步骤，不出题。',
     'instructions': '按本次完整展开要求整理讲解，不能用短追问形式代替；末尾系统总结，不出题。',
     'checks': ['四个量的含义、单位完整', 'k单位推导与v=0.03 mol/(L·s)正确', '速率模型不冒充反应式的必然结果', '没有压成只答单点，保留系统总结']},
]


async def main(name, separated=False, capture_only=False):
    out = ROOT / 'build' / name
    if out.exists() and any(out.iterdir()):
        raise SystemExit('Use a fresh folder.')
    out.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(out / 'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(out / 'isolated-model')
    import httpx
    from studyforge import ai, conversations, server
    from studyforge.agent_tools import AgentRuntime
    from studyforge.db import create_project, execute, j, now, uid
    from studyforge.learning import learning_requirements, requirements_without_duplicate_history
    from studyforge.learning_modes import mode_task_reminder
    from studyforge.teaching_policy import TEACHING_TASK_REMINDER
    from studyforge.teaching_styles import style_task_reminder
    from studyforge.deepseek_protocol import Reply
    from studyforge.scheduling import model_slot
    from scripts.diagnose_deepseek_speed import traced_class

    ai.save_settings({'api_connection_mode': 'direct', 'agent_tools_enabled': False, 'agent_network_enabled': False,
                      'background_learning_enabled': False, 'model_concurrency': 2, 'library_reference_mode': 'off'})
    native = ai.DeepSeekClient
    cases = []
    selected_cases = CASES[:2] if separated else CASES
    for case in selected_cases:
        project = create_project('隔离教学顺序对照：' + case['id'])
        chat = conversations.create(project['id'], 'deepseek', 'deepseek-flash', 'high')
        history = [{'id': uid(), 'role': 'user', 'content': '请先讲解这份资料。'},
                   {'id': uid(), 'role': 'assistant', 'content': case['previous']}]
        for row in history:
            execute('INSERT INTO messages VALUES (?,?,?,?,?)', (row['id'], chat['id'], row['role'], row['content'], now()))
        path = out / (case['id'] + '.txt'); path.write_text(case['source'], encoding='utf-8')
        sid = uid()
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
                (sid, project['id'], path.name, '.txt', str(path), 'ready', now()))
        captured = []
        def respond(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, text='data: ' + j({'choices': [{'delta': {'content': '## 系统性总结\n受控捕获，不是实验回答。'}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n')
        def capture_client(*args, **kwargs):
            client = native(*args, **kwargs)
            client._http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            return client
        task_block = ''
        if case['role'] == 'tutor':
            with patch.object(server, 'DeepSeekClient', capture_client):
                response = await server._chat_response(server.ChatIn(project_id=project['id'], conversation_id=chat['id'],
                    provider='deepseek', model='deepseek-flash', reasoning_effort='high', source_ids=[sid],
                    text=case['question'], explanation_style=case['style'], learning_mode=case['mode']))
                packets = [p async for p in response.body_iterator]
                assert not any(b'"error"' in p for p in packets), packets
        else:
            history.append({'id': uid(), 'role': 'user', 'content': case['question']})
            requirements = learning_requirements(history, case['instructions'])
            slim = requirements_without_duplicate_history(requirements, history)
            task_block = f'\n学习对话与讲解要求：\n{slim}\n'
            runtime = AgentRuntime(project['id'], [sid], 'deepseek', 'deepseek-flash', 'high',
                                   conversation_id=chat['id'], job_id=uid(), publishing=False)
            client = capture_client('deepseek-flash', runtime, dict(chat, messages=history, remote_thread_id=None), effort='high')
            try:
                await ai.generate_explanation(client, f'[来源 {path.name}｜行1]\n{case["source"]}', 3, [],
                    style=case['style'], learning_mode=case['mode'], requirements=requirements)
            finally:
                await client.close()
        assert len(captured) == 1
        before = captured[0]['messages']
        if case['role'] == 'tutor' and before[-1]['content'] == case['question']:
            # Current production no longer appends this historical tail. Keep
            # the old-layout comparator explicit for a future replay.
            before = copy.deepcopy(before)
            before[-1]['content'] += (style_task_reminder(case['style']) + TEACHING_TASK_REMINDER
                                      + mode_task_reminder(case['mode']))
        after = copy.deepcopy(before)
        current = after[-1]['content']
        if case['role'] == 'tutor':
            suffix = style_task_reminder(case['style']) + TEACHING_TASK_REMINDER + mode_task_reminder(case['mode'])
            assert current == case['question'] + suffix
            after[-1]['content'] = suffix + ('\n\n' if separated else '') + case['question']
        else:
            assert current.count(task_block) == 1
            after[-1]['content'] = current.replace(task_block, '', 1) + task_block
        assert len(after[-1]['content']) == len(current) + (2 if separated and case['role'] == 'tutor' else 0)
        assert before[:-1] == after[:-1]
        assert all(after[-1]['content'].count(piece) == current.count(piece) for piece in (case['question'], case['source']))
        options = {k: v for k, v in captured[0].items() if k not in ('messages', 'tools', 'tool_choice')}
        cases.append(case | {'requests': {'baseline': before, 'task_last': after}, 'request_options': options})
    (out / 'cases.json').write_text(j({'cases': cases, 'difference': 'same_content_reordered_current_task_last',
        'tutor_separator': '\n\n' if separated else '',
        'controlled_capture_requests': len(cases), 'planned_real_requests': 2 * len(cases),
        'model': 'deepseek-flash', 'effort': 'high'}), encoding='utf-8')
    if capture_only:
        return
    cls = traced_class(); results = []
    for index, case in enumerate(cases):
        async def sample(arm):
            client = cls('deepseek-flash', effort='high'); start = time.perf_counter()
            row = {'case': case['id'], 'arm': arm, 'role': case['role'], 'model': 'deepseek-flash', 'effort': 'high'}
            try:
                body = copy.deepcopy(case['request_options']); body['messages'] = copy.deepcopy(case['requests'][arm])
                reply = Reply(service_name='DeepSeek')
                async with asyncio.timeout(240):
                    async with model_slot('deepseek'):
                        async for packet in client.stream_packets(body):
                            reply.accept(packet)
                    reply.validate(client.model)
                assert not reply.calls and reply.content.strip()
                answer = reply.content
                filename = case['id'] + '-' + arm + '-final.md'
                (out / filename).write_text(answer, encoding='utf-8')
                row.update(status='completed', answer_file=filename, output_characters=len(answer),
                           answer_sha256=hashlib.sha256(answer.encode()).hexdigest())
            except Exception as exc:
                row.update(status='failed', error_type=type(exc).__name__)
            finally:
                await client.close()
            row.update(seconds=time.perf_counter() - start, model_requests=len(client.traces),
                       http_attempts=[t.public() for t in client.traces])
            results.append(row); (out / 'results.json').write_text(j(results), encoding='utf-8')
            print(json.dumps({k: row[k] for k in ('case', 'arm', 'status', 'seconds', 'model_requests')}), flush=True)
        arms = ('baseline', 'task_last') if index % 2 == 0 else ('task_last', 'baseline')
        await asyncio.gather(*(sample(arm) for arm in arms))


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1], '--separated' in sys.argv[2:]))
