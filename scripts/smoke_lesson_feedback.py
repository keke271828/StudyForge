"""Seed isolated questionnaires and serve real HTTP routes with mocked cloud replies."""
import asyncio
import ast
import json
import os
import socket
from pathlib import Path

import httpx
import uvicorn

from studyforge import ai, server
from studyforge.db import create_job, create_project, execute, j, now, one, uid, update_mastery


def main():
    result_path = Path(os.environ['STUDYFORGE_FEEDBACK_UI_CASE_PATH'])
    result_path.parent.mkdir(parents=True, exist_ok=True)
    ai.save_settings({'chat_provider': 'deepseek', 'deepseek_model': 'ui-test-model', 'background_learning_enabled': False})
    ai.get_secret = lambda key: 'test-key'
    server.get_secret = lambda key: 'test-key' if key == 'DEEPSEEK_API_KEY' else None
    real_client = httpx.AsyncClient
    requests = []
    def respond(request):
        body = json.loads(request.content); requests.append(body)
        if os.environ.get('STUDYFORGE_PROFILE_UI'):
            result_path.with_name('last_mock_request.json').write_text(j(body), encoding='utf-8')
        assert body['model'] == 'ui-test-model'
        is_feedback = '本次是讲解后补讲' in j(body['messages'])
        is_structure = '【资料知识结构整理】' in body['messages'][0]['content']
        system = body['messages'][0]['content']
        is_grading = '逐题批改' in system or '第二位独立批改者' in system
        is_feynman = '费曼学习法评审' in system
        text = j(structure) if is_structure else ('## 针对你的理解反馈\n先区分概念，再解释论证的构造动机。\n原文和你的补充已经纳入这次讲解。\n\n哪一步仍不清楚？' if is_feedback
                else '# 规训权力与论证\n> 原文：观察、记录与规范化判断。\n\n福柯讨论规训权力。不同实践的相似并不证明机制相同。\n\n## 系统性总结\n区分概念、证据和适用边界。')
        if os.environ.get('STUDYFORGE_QUALITY_UI') or os.environ.get('STUDYFORGE_FORMATS_UI'):
            quote = '福柯讨论规训权力，关注观察、记录与规范化判断。'
            if '请生成界面核对样例' in j(body['messages']): quote = '这里故意使用未出现的测试引句。'
            text = f'# 规训权力与论证\n\n> {quote} [规训权力.txt｜{locator}]\n\n区分观察、记录和规范化判断；不同实践的相似不证明共同机制。\n\n## 系统性总结\n概念、论证与适用边界需要分别核对。'
        if os.environ.get('STUDYFORGE_FORMATS_UI'):
            if '【Anki格式整理】' in system:
                text=j({'cards':[{'question':'这份资料讨论规训权力的哪些日常活动？','answer':'观察、记录与规范化判断。','source':f'[规训权力.txt｜{locator}]'}]})
            elif '【代码包格式整理】' in system:
                text=j({'files':[{'path':'src/model.js','content':'// 未运行的结构样例\nconst labels=["观察","记录"];\nconsole.log(labels);'},
                                {'path':'README.md','content':'node src/model.js；尚未运行，不作为理论证明。'}]})
            elif '实现为可运行的 Python' in system: text='```python\nlabels=["观察","记录"]\nprint(labels)\n```'
        if os.environ.get('STUDYFORGE_PRACTICE_UI') and is_grading:
            user = body['messages'][-1]['content']
            questions = ast.literal_eval(user.split('题目：', 1)[1].split('\n参考', 1)[0])
            score = 80 if '完整论证' in user.split('学生答案：', 1)[1] else 60
            text = j({'scores': [score] * len(questions), 'feedback': ['应明确区分相似与机制，补充论证依据。'] * len(questions),
                      'uncertainties': [], 'diagnostics': [{'index': i, 'kind': 'argumentation', 'quote': '因为相似',
                       'reason': '推断缺少机制证据，暂不能断言学生缺少前置知识。'} for i in range(len(questions))]})
        elif os.environ.get('STUDYFORGE_PRACTICE_UI') and is_feynman:
            text = j({'score': 80, 'feedback': '本次讲解区分了相似、机制和适用边界。', 'gaps': []})
        result_path.with_name('cloud_requests.json').write_text(j({'requests': len(requests),
            'feedback_requests': sum('本次是讲解后补讲' in j(row['messages']) for row in requests),
            'knowledge_requests': sum('【资料知识结构整理】' in row['messages'][0]['content'] for row in requests),
            'grading_requests': sum('逐题批改' in row['messages'][0]['content'] or '第二位独立批改者' in row['messages'][0]['content'] for row in requests),
            'feynman_requests': sum('费曼学习法评审' in row['messages'][0]['content'] for row in requests),
            'last_has_structure': '原资料知识结构，仅作组织线索' in j(body['messages']),
            'last_profile_corrected': '已理解概念，请解释论证的适用边界。' in j(body['messages']),
            'last_profile_old': '旧判断：尚不理解基本概念。' in j(body['messages']),
            'last_mode': next((label for label in ['概览', '精学', '研究'] if f'当前学习模式：{label}' in j(body['messages'])), None)}), encoding='utf-8')
        return httpx.Response(200, text='data: ' + j({'choices': [{'delta': {'content': text}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n')
    httpx.AsyncClient = lambda *args, **kwargs: real_client(transport=httpx.MockTransport(respond))
    project = create_project('知识结构验收' if os.environ.get('STUDYFORGE_KNOWLEDGE_UI') else '理解问卷验收'); source = uid()
    original = result_path.parent / '规训权力.txt'; original.write_text('福柯讨论规训权力，关注观察、记录与规范化判断。', encoding='utf-8')
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
            (source, project['id'], original.name, '.txt', str(original), 'ready', now()))
    from studyforge.parsers import parse_file
    locator = str(parse_file(original)[0]['locator'])
    evidence = {'source_id': source, 'locator': locator, 'quote': '福柯讨论规训权力'}
    structure = {'concepts': [
        {'id': 'observe', 'name': '观察和记录', 'domain': '社会科学', 'description': '先区分观察、记录与评价。',
         'basis': 'source', 'evidence': [dict(evidence, quote='关注观察、记录与规范化判断')]},
        {'id': 'discipline', 'name': '规训权力', 'domain': '哲学与社会科学', 'description': '在原文所属理论语境中理解，不能凭相似实践推断相同机制。',
         'basis': 'source', 'evidence': [evidence], 'attribution': {'name': '福柯', 'role': '讨论', 'evidence': [evidence]}}],
        'relations': [{'from_id': 'observe', 'to_id': 'discipline', 'kind': 'prerequisite', 'reason': '先区分观察和记录，有助于讨论规训如何运作。',
                       'boundary': '这是阅读顺序建议，不是唯一顺序，也不能据此判定学生不会。', 'basis': 'teaching', 'evidence': [evidence]}]}
    async def seed():
        reading = server.ReadIn(project_id=project['id'], source_ids=[source], provider='deepseek', model='ui-test-model')
        read_job = create_job(project['id'], 'read', reading.model_dump()); await server._read_job(read_job, reading)
        read_id = json.loads(one('SELECT result_json FROM jobs WHERE id=?', (read_job,))['result_json'])['reading_id']
        ids = []
        for mode in ['overview', 'deep']:
            conversation = uid()
            execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)',
                    (conversation, project['id'], 'deepseek', None, now(), j([source]), 'ui-test-model', None))
            execute('INSERT INTO messages VALUES (?,?,?,?,?)', (uid(), conversation, 'user', '请解释概念及论证动机，不需要习题。', now()))
            value = server.GenerateIn(project_id=project['id'], source_ids=[source], provider='deepseek', model='ui-test-model',
                                      conversation_id=conversation, reading_id=read_id, exercises=False, learning_mode=mode)
            job = create_job(project['id'], 'generate', value.model_dump()); await server._generate_job(job, value)
            row = one('SELECT * FROM lesson_questionnaires WHERE job_id=?', (job,))
            assert row, one('SELECT error FROM jobs WHERE id=?', (job,))
            ids.append(row['id'])
        return ids
    ids = asyncio.run(seed())
    profile_case = {}
    if os.environ.get('STUDYFORGE_PROFILE_UI'):
        from studyforge import learning_memory as memory
        conversation = one('SELECT conversation_id FROM lesson_questionnaires WHERE id=?', (ids[0],))['conversation_id']
        message = one("SELECT id FROM messages WHERE conversation_id=? AND role='user' LIMIT 1", (conversation,))['id']
        memory.discussion_completed(conversation, message)
        event = one('SELECT id FROM learning_events WHERE event_key=?', ('chat:' + message,))['id']
        memory._save_insight(event, '规训权力', 'gap', 'concepts', '旧判断：尚不理解基本概念。',
                             '请解释概念及论证动机，不需要习题。', '暂定')
        profile_case['insight_id'] = one('SELECT id FROM learning_insights ORDER BY id DESC LIMIT 1')['id']
        for index in range(135):
            memory._save_insight(event, f'无关资料{index}', 'exposure', '', '仅接触，不能证明掌握。', '资料范围', '接触记录')
        for key, score in [('low', 60), ('high', 100)]:
            update_mastery('规训权力', quiz=score)
            memory.assessment_record('quiz:' + key, '规训权力', '做题', score, '我的论证片段。', '原评估反馈。', project['id'])
            profile_case[key + '_id'] = one('SELECT id FROM learning_insights ORDER BY id DESC LIMIT 1')['id']
        server.rate(server.RatingIn(topic='哲学', rating=100, difficulty_rating=20))
        update_mastery('早期电场', quiz=88, self_rating=99)
    practice_case = {}
    if os.environ.get('STUDYFORGE_PRACTICE_UI'):
        from studyforge import practice
        def create_set(pid, title, topics, sources, graded=False):
            set_id = uid()
            public = [{'index': i, 'topic': topic, 'question': '说明两种现象相似是否证明机制相同，并交代论证边界。符号示例 $a=b$。'} for i, topic in enumerate(topics)]
            private = [{'index': i, 'solution': 'PRIVATE_REFERENCE：相似本身不够，还要机制与排除其他解释的证据。', 'rubric': 'PRIVATE_RUBRIC：定义、论据、边界。'} for i in range(len(topics))]
            execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)', (set_id, pid, j(sources), title,
                    j(public), j(private), 3, 'passed' if graded else 'assigned', now()))
            if graded:
                execute('INSERT INTO submissions VALUES (?,?,?,?,?,?,?)', (uid(), set_id, j(['已有完整作答。'] * len(topics)),
                        j({'scores': [90] * len(topics), 'feedback': ['有依据。'] * len(topics)}), 90, '{}', now()))
            return set_id
        practice_case['practice_set_id'] = create_set(project['id'], '论证与适用边界练习', ['论证', '适用边界'], [source])
        other = create_project('跨项目复习验收')
        other_set = create_set(other['id'], '关系与证据练习', ['关系与证据'], [], True)
        practice.schedule_review(other_set, 1)
        repair_requests = []
        async def generate_repair(client, project_id, source_ids, digest, title, difficulty):
            assert '关注观察、记录与规范化判断' in digest and '不因低分加难度' in digest and difficulty == 3
            repair_requests.append({'model': client.model, 'difficulty': difficulty})
            result_path.with_name('repair_requests.json').write_text(j(repair_requests), encoding='utf-8')
            return create_set(project_id, title, ['论证', '适用边界'], source_ids), [{'stage': '隔离模拟审查'}]
        server.generate_set = generate_repair
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
    result_path.write_text(j({'project_id': project['id'], 'submit_id': ids[0], 'skip_id': ids[1],
                              'url': f'http://127.0.0.1:{port}', **profile_case, **practice_case}), encoding='utf-8')
    uvicorn.run(server.app, host='127.0.0.1', port=port, log_level='warning')


if __name__ == '__main__': main()
