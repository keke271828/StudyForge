"""Capture native tutor/document inputs; compare retrieval priority only."""
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
    {'id': 'gauss_quote', 'title': '引用追问：净通量与局部电场', 'role': 'tutor', 'topic': '高斯定律',
     'style': 'clear', 'quoted': True,
     'source': '',
     'previous': '高斯定律说明闭合曲面的净电通量等于内部净电荷除以ε₀；内部总电荷为零不等于局部电场处处为零。',
     'quote': '高斯定律',
     'question': '这句我还是不明白：等式右边已经为零，为什么左边的电场还能不为零？只讲这个，不出题。',
     'observation': '学生自报已分清场强与电荷，当前仍不懂面积积分中的正负贡献怎样抵消；希望沿匀强场穿过立方体的具体情形解释，尚未经过测验。',
     'checks': ['净通量零不等于电场零', '通量符号随外法线与场方向，正负可抵消', '不把画像自报当测验结果']},
    {'id': 'epsilon_book', 'title': '多知识点资料：取特例的合法性', 'role': 'tutor', 'topic': '极限唯一性',
     'style': 'balanced', 'quoted': False,
     'source': '极限唯一性：反证设x_n同时趋于a,b且a<b。由对任意ε>0成立的极限定义，可取ε=(b-a)/2；两个开邻域不相交，再取N=max(N₁,N₂)得到矛盾。',
     'previous': '证明的关键是利用极限定义选足够小的半径。',
     'question': '关于极限唯一性，我就问：怎么能主动取ε=(b-a)/2？这不是把“任意”限制成一个值了吗？不要布置习题。',
     'observation': '学生自报已理解两个开邻域不相交以及统一N的作用；尚未理清“已知对所有ε成立，可以应用一个正值”与“只验证一个值就证明极限”的区别，尚未测验。',
     'checks': ['a<b保证所取值正', '全称命题可用合法特例，使用假设不同于证明定义', '已懂部分不需从头重证']},
    {'id': 'copy_document', 'title': '文档承接：浅复制与替换槽位', 'role': 'lecture', 'topic': '浅复制',
     'style': 'balanced', 'quoted': False,
     'source': 'Python浅复制示例（未运行）：a=[[1],[2]]; b=a.copy(); b[0]=[9]。不同外层列表最初共享已有内层对象；下标赋值替换当前外层的一个元素引用，不会改旧内层对象。',
     'previous': 'a和b是不同外层；a.copy()不复制已有内层对象。b[0].append(7)会改共享内层，这只是另一种操作。',
     'question': '浅复制时，我问的就是b[0]=[9]为什么不会让a[0]跟着变？请给出原代码完整静态结果，只说明这个操作。',
     'observation': '学生自报已经分清不同外层与共享内层，也理解append修改旧对象；当前困惑是给外层槽位赋新列表和修改共享内层的区别，尚未测验。',
     'checks': ['只替换b的第0槽位，旧[1]不被修改', 'a=[[1],[2]], b=[[9],[2]]，第二项保留', '原代码静态推演不伪称已运行', '文档独立可读且有系统总结，不出题']},
]
NOISE = ['复数运算', '矩阵秩', '向量空间', '线性映射', '函数连续性', '偏导数', '定积分', '概率分布', '回归分析']


async def main(name):
    out = ROOT / 'build' / name
    if out.exists() and any(out.iterdir()):
        raise SystemExit('Use a fresh folder.')
    out.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(out / 'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(out / 'isolated-model')
    import httpx
    from studyforge import ai, conversations, learning_memory as memory, message_focus, server
    from studyforge.agent_tools import AgentRuntime
    from studyforge.db import connect, create_project, execute, j, now, uid
    from studyforge.learning import learning_requirements
    from studyforge.deepseek_protocol import Reply
    from studyforge.scheduling import model_slot
    from scripts.diagnose_deepseek_speed import traced_class

    ai.save_settings({'api_connection_mode': 'direct', 'agent_tools_enabled': False, 'agent_network_enabled': False,
                      'background_learning_enabled': False, 'model_concurrency': 2, 'library_reference_mode': 'off'})
    real_profile_context = memory.profile_context
    cases = []
    for case in CASES:
        p = create_project('隔离画像教学对照：' + case['id'])
        event = memory.record_event('target:' + case['id'], 'chat',
            {'student_text': '我不明白这个概念。PRIVATE_PROFILE_EVIDENCE'}, p['id'], analyzed=True)
        memory._save_insight(event, case['topic'], 'gap', 'concepts', case['observation'],
                            'PRIVATE_PROFILE_EVIDENCE', '自报困难（未测验）', anchors=[case['topic']])
        for topic in NOISE:
            event = memory.record_event('other:' + case['id'] + topic, 'chat',
                {'student_text': '我不理解这个知识点。PRIVATE_OTHER_EVIDENCE'}, p['id'], analyzed=True)
            memory._save_insight(event, topic, 'gap', 'concepts', '学生曾自报需要进一步解释' + topic + '，尚未测验。',
                                'PRIVATE_OTHER_EVIDENCE', '自报困难（未测验）', anchors=[topic])
        chat = conversations.create(p['id'], 'deepseek', 'deepseek-flash', 'high')
        target_id = uid()
        history = [
            {'id': uid(), 'role': 'user', 'content': '以前曾浏览过：' + '、'.join(NOISE) + '。'},
            {'id': target_id, 'role': 'assistant', 'content': case['previous']},
        ]
        for row in history:
            execute('INSERT INTO messages VALUES (?,?,?,?,?)', (row['id'], chat['id'], row['role'], row['content'], now()))
        reference = None
        if case['quoted']:
            start = case['previous'].index(case['quote'])
            reference = message_focus.MessageReference(message_id=target_id,
                content_sha256=hashlib.sha256(case['previous'].encode()).hexdigest(),
                selection={'start': start, 'end': start + len(case['quote']), 'text': case['quote']})
        source_ids = []
        full_source = case['source']
        if full_source:
            full_source = '本资料还列有这些导航主题：' + '、'.join(NOISE) + '。\n' + full_source
            path = out / (case['id'] + '.txt'); path.write_text(full_source, encoding='utf-8')
            sid = uid(); source_ids = [sid]
            execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
                    (sid, p['id'], path.name, '.txt', str(path), 'ready', now()))
        captured, contexts = [], []
        native = ai.DeepSeekClient
        def respond(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, text='data: ' + j({'choices': [{'delta': {'content': '## 系统性总结\n受控输入捕获，不是实验回答。'}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n')
        def capture_client(*args, **kwargs):
            result = native(*args, **kwargs)
            result._http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            return result
        def focused_context(query, *, focus=''):
            before = real_profile_context(query)
            after = real_profile_context(query, focus=focus)
            contexts.append({'before': before, 'after': after, 'focus': focus})
            return after
        with patch.object(server, 'profile_context', focused_context), patch.object(memory, 'profile_context', focused_context):
            if case['role'] == 'tutor':
                with patch.object(server, 'DeepSeekClient', capture_client):
                    response = await server._chat_response(server.ChatIn(
                        project_id=p['id'], conversation_id=chat['id'], provider='deepseek', model='deepseek-flash',
                        reasoning_effort='high', learning_mode='deep', explanation_style=case['style'],
                        source_ids=source_ids, text=case['question'], reply_reference=reference))
                    lines = [line async for line in response.body_iterator]
                    assert not any(b'"error"' in line for line in lines), lines
            else:
                history.append({'id': uid(), 'role': 'user', 'content': case['question']})
                snapshot = dict(chat, messages=history, remote_thread_id=None)
                runtime = AgentRuntime(p['id'], source_ids, 'deepseek', 'deepseek-flash', 'high',
                    conversation_id=chat['id'], job_id=uid(), publishing=False)
                client = capture_client('deepseek-flash', runtime, snapshot, effort='high')
                try:
                    await ai.generate_explanation(client, full_source, 3, [], style=case['style'],
                        requirements=learning_requirements(history, '沿最后的具体疑问整理成简短独立讲解，最后系统性总结，不出题。'))
                finally:
                    await client.close()
        assert len(captured) == len(contexts) == 1
        context = contexts[0]; after = captured[0]['messages']; before = copy.deepcopy(after)
        assert case['observation'] in context['after'] and case['observation'] not in context['before']
        assert sum(row['content'].count(context['after']) for row in before) == 1
        for row in before:
            row['content'] = row['content'].replace(context['after'], context['before'], 1)
        assert 'PRIVATE_' not in j(after) and 'PRIVATE_' not in j(before)
        assert all(a == b for a, b in zip(after[1:-1], before[1:-1]))
        options = {key: value for key, value in captured[0].items() if key not in ('messages', 'tools', 'tool_choice')}
        cases.append(case | {'source': full_source, 'contexts': context, 'requests': {'baseline': before, 'focused': after},
                             'request_options': options})
    (out / 'cases.json').write_text(j({'cases': cases, 'model': 'deepseek-flash', 'effort': 'high',
        'controlled_capture_requests': 3, 'planned_real_requests': 6, 'difference': 'related_profile_selection_and_order_only',
        'replay': 'native_http_messages_no_second_boundary_tools_omitted'}), encoding='utf-8')
    cls = traced_class(); results = []
    for index, case in enumerate(cases):
        async def sample(arm):
            client = cls('deepseek-flash', effort='high'); started = time.perf_counter()
            row = {'case': case['id'], 'arm': arm, 'role': case['role'], 'model': 'deepseek-flash', 'effort': 'high'}
            try:
                answer = ''
                async with asyncio.timeout(240):
                    # The native capture already contains the client's context
                    # boundary. Replaying via agent_stream would append it twice.
                    # Preserve captured messages/options; omit tools in both arms.
                    body = copy.deepcopy(case['request_options'])
                    body['messages'] = copy.deepcopy(case['requests'][arm])
                    reply = Reply(service_name='DeepSeek')
                    async with model_slot('deepseek'):
                        async for packet in client.stream_packets(body):
                            reply.accept(packet)
                    reply.validate(client.model)
                    assert not reply.calls, 'Tool call is not a completed teaching answer.'
                    answer = reply.content
                assert answer.strip()
                filename = case['id'] + '-' + arm + '-final.md'
                (out / filename).write_text(answer, encoding='utf-8')
                row.update(status='completed', answer_file=filename, output_characters=len(answer),
                           answer_sha256=hashlib.sha256(answer.encode()).hexdigest())
            except Exception as exc:
                row.update(status='failed', error_type=type(exc).__name__)
            finally:
                await client.close()
            row.update(seconds=time.perf_counter() - started, model_requests=len(client.traces),
                       http_attempts=[trace.public() for trace in client.traces])
            results.append(row); (out / 'results.json').write_text(j(results), encoding='utf-8')
            print(json.dumps({key: row[key] for key in ('case', 'arm', 'status', 'seconds', 'model_requests')}), flush=True)
        arms = ('baseline', 'focused') if index % 2 == 0 else ('focused', 'baseline')
        await asyncio.gather(*(sample(arm) for arm in arms))


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1]))
