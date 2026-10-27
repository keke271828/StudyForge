"""Actual link-only versus per-question feedback retrieval, synthetic work only."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
CASES = {
    'epsilon': {
        'title': '极限唯一性中开邻域的边界',
        'question': '设数列有两个极限a<b。用开邻域证明唯一性，并解释为什么可以取ε=(b-a)/2。',
        'answer': '为了让两个邻域不相交，ε必须严格小于(b-a)/2，因此取等号不合法。',
        'solution': '开邻域不相交要求2ε≤b−a。取ε=(b−a)/2>0时，中点(a+b)/2是两个区间的端点，因区间开而不属于任一区间；同一尾项不能同时在两边。取N=max(N1,N2)使两项条件同时成立。',
        'cause': '作答中把开邻域不相交的条件误写为严格小于，排除了可行的等号。',
        'explanation': '两个开区间的右、左端点可以相同而没有共同元素。取a=0、b=2、ε=1时，区间为(-1,1)与(1,3)，数1不属于两边。一般地中点(a+b)/2同样被严格不等式排除。更小的正ε也可以，取一半只是对称且方便，并非唯一选择。',
        'check': '先把区间写出来，再检查端点是否包含；闭区间的边界情形不同。',
        'followup': '第一题批改说取等号可以，我不懂：两个区间碰头不算重叠吗？只补这一点，不要重讲全部证明，也不出题。',
        'expectation': 'Anchor the exact epsilon choice and open endpoints; touching closures are not an intersection of open intervals. No invented new task.'},
    'causal': {
        'title': '随机提醒的效应与实际记笔记的效应',
        'question': '学生随机分配到记笔记提醒组和无提醒组，提醒组平均分更高。部分人不遵从；提醒也可能改变学习投入。这个设计能直接证明实际记笔记本身提高成绩吗？',
        'answer': '分组是随机的，所以两组差异就是实际记笔记本身的因果效应。',
        'solution': '随机分配的是提醒，组间差异在随机分配有效、无严重失访等条件下支持提醒分配的因果效应。实际行为未被随机化；不遵从及其他路径未排除，不能直接归为记笔记行为本身的效应。还须报告不确定性与效应量。',
        'cause': '作答中把随机分配提醒等同于随机分配实际记笔记行为。',
        'explanation': '提醒组可能有人不记笔记，对照组也可能有人记笔记。两组由抽签改变的是是否收到提醒，实际行为并不完全随之改变。提醒还可能让人更加认真，因此分数变化不能只归给记笔记。随机化有价值：在随机过程有效、随访和比较可靠等条件下，可以研究分配提醒的效应；不能因此说整个实验只有关联。',
        'check': '把“抽签分配了什么”与“真正想估计什么效应”各写出来，核对中间是否还需要假设。',
        'followup': '第1题里我把随机分配对象搞混在哪里？我看完批改，担心最后什么结论都不能保留了。只针对我那道题解释，不要泛讲整个因果推断，也不出题。',
        'expectation': 'Correct assignment-versus-behaviour confusion, while retaining conditional causal value of random assignment; do not reduce the entire experiment to correlation.'},
}


def fixture(case, arm, out):
    from studyforge import conversations, homework, server
    from studyforge.db import create_job, create_project, execute, j, now, one, uid
    from studyforge.exporters import export_document
    project = create_project('错题追问对照 '+case['title']+' '+arm)
    chat = conversations.create(project['id'], 'deepseek', 'deepseek-flash', 'high')
    set_id, attempt = uid(), uid()
    questions = [{'index': 0, 'topic': case['title'], 'question': case['question']}]
    reference = [{'index': 0, 'solution': case['solution'], 'rubric': '区分对象、条件与可支持的结论'}]
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
        (set_id, project['id'], '[]', case['title'], j(questions), j(reference), 2, 'graded', now()))
    worksheet = one('SELECT * FROM exercise_sets WHERE id=?', (set_id,))
    grade = {'score': 70, 'scores': [70], 'feedback': ['存在题目对应的推理错误，保留可核对的步骤。']}
    analysis = {'items': [{'index': 0, 'kind': 'argumentation', 'confidence': 'supported', 'cause': case['cause'],
        'evidence': [{'source': 'answer', 'quote': case['answer']}], 'explanation': case['explanation'], 'check': case['check']}]}
    job = create_job(project['id'], 'homework_grade', {'conversation_id': chat['id']})
    execute("UPDATE jobs SET status='completed' WHERE id=?", (job,))
    execute('INSERT INTO homework_attempts(id,exercise_set_id,project_id,conversation_id,job_id,source_version,'
        'answers_json,options_json,status,grade_json,analysis_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (attempt, set_id, project['id'], chat['id'], job, homework.version(worksheet), j([case['answer']]), '{}', 'completed', j(grade), j(analysis), now(), now()))
    row = homework.get_attempt(attempt)
    content = homework.report_document(row, worksheet, grade, analysis)
    path = export_document(content, 'docx', case['title'], attempt+'-feedback.docx')
    artifact = server.add_artifact(project['id'], [], 'grading', 'docx', case['title'], path,
        {'homework_attempt_id': attempt, 'exercise_set_id': set_id, 'conversation_id': chat['id']})
    execute('UPDATE homework_attempts SET feedback_artifact_id=? WHERE id=?', (artifact['id'], attempt))
    public = '《'+case['title']+'》批改与错题讲解已完成。\n\n[下载逐题批改、错因分析与针对性讲解]('+artifact['download_url']+')'
    return project, chat, attempt, public


async def main(name):
    out = ROOT / 'build' / name
    if (out/'results.json').exists(): raise SystemExit('Use a new output folder.')
    out.mkdir(parents=True, exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(out/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR'] = str(out/'isolated-model')
    from studyforge import ai
    from studyforge.agent_tools import AgentRuntime
    from studyforge.teaching import TEACHER_PERSONA, CHAT_RULES, TEACHING_TASK_REMINDER
    from studyforge.teaching_styles import style_policy, style_task_reminder, language_policy
    from studyforge.learning_modes import mode_policy, mode_task_reminder
    ai.save_settings({'api_connection_mode': 'direct', 'agent_tools_enabled': False, 'background_learning_enabled': False,
                      'agent_network_enabled': False, 'model_concurrency': 2})
    tasks, rows, gate = [], [], asyncio.Semaphore(2)
    for key, case in CASES.items():
        for arm in ('link_only', 'read_feedback'):
            project, chat, attempt, public = fixture(case, arm, out)
            runtime = AgentRuntime(project['id'], conversation_id=chat['id'], provider='deepseek', model='deepseek-flash', effort='high')
            if arm == 'link_only':
                original_context = runtime.context
                def context(previous=original_context):
                    value = json.loads(previous()); value.pop('homework_feedback', None)
                    return json.dumps(value, ensure_ascii=False)
                runtime.context = context
            system = TEACHER_PERSONA+CHAT_RULES+mode_policy('deep')+style_policy('balanced')+language_policy('zh')
            messages = [{'role': 'system', 'content': system}, {'role': 'assistant', 'content': public},
                        {'role': 'user', 'content': case['followup']+style_task_reminder('balanced')+TEACHING_TASK_REMINDER+mode_task_reminder('deep')}]
            tasks.append((key, arm, case, runtime, messages))
    async def sample(key, arm, case, runtime, messages):
        async with gate:
            client = ai.DeepSeekClient('deepseek-flash', effort='high', agent_runtime=runtime)
            packets = client.stream_packets; captured = []
            async def stream(body):
                if arm == 'link_only': body = dict(body, tools=[tool for tool in body.get('tools', []) if tool['function']['name'] != 'sf_read_homework_feedback'])
                # Preserve public inputs and tool results; do not publish private reasoning.
                saved = {k:v for k,v in body.items() if k != 'messages'}
                saved['messages'] = [{k:v for k,v in message.items() if k != 'reasoning_content'} for message in body['messages']]
                captured.append(saved)
                async for packet in packets(body): yield packet
            client.stream_packets = stream
            start = time.perf_counter(); answer = ''
            row = {'case': key, 'arm': arm, 'model': 'deepseek-flash', 'effort': 'high', 'network_tools': False,
                   'expectation': case['expectation'], 'scope': 'Synthetic submitted work and supplied diagnoses; tests follow-up access, not actual grading accuracy. Link-only ablation removes the new index and tool.'}
            try:
                async with asyncio.timeout(300):
                    async for kind, value in client.agent_stream(messages):
                        if kind == 'final': answer = value
                file = key+'-'+arm+'.md'; (out/file).write_text(answer, encoding='utf-8', newline='')
                row.update(status='completed', answer_file=file, characters=len(answer), answer_sha256=hashlib.sha256(answer.encode()).hexdigest())
            except Exception as exc: row.update(status='failed', error=type(exc).__name__+': '+str(exc))
            finally:
                await client.close()
                row.update(seconds=round(time.perf_counter()-start, 2), model_requests=len(captured),
                           tool_results=len({message.get('tool_call_id') for request in captured for message in request['messages'] if message['role']=='tool'}))
                (out/(key+'-'+arm+'-requests.json')).write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding='utf-8')
                rows.append(row); (out/'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(row, ensure_ascii=True), flush=True)
    await asyncio.gather(*(sample(*task) for task in tasks))


if __name__ == '__main__': asyncio.run(main(sys.argv[1]))
