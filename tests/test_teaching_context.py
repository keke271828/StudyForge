import asyncio
import json

import httpx
import pytest

from studyforge import ai
from studyforge.agent_tools import AgentRuntime
from studyforge.codex_bridge import CodexBridge
from studyforge.db import create_project, execute, j, now, uid
from studyforge.learning import learning_requirements, requirements_without_duplicate_history


def test_exact_transcript_removed_without_dropping_late_instruction_or_goal():
    history = [{'role': 'user', 'content': '旧要求：推导每个关键步骤。' * 1000},
               {'role': 'assistant', 'content': '旧解释与它的局限。'},
               {'role': 'user', 'content': '最后追问：为什么取最大阈值？'}]
    requirements = learning_requirements(history, '最新要求：用数轴解释。') + '\n学习目标：能解释构造动机。'
    original = requirements
    result = requirements_without_duplicate_history(requirements, history)
    assert '最新要求：用数轴解释。' in result and '学习目标：能解释构造动机。' in result
    assert history[-1]['content'] not in result  # Still provided as its own message.
    assert requirements == original and len(result) < len(requirements) / 10


@pytest.mark.parametrize('history,requirements', [
    ([], '用户自己的要求全文'),
    ([{'role': 'user', 'content': '完整问题'}], '本资料的学习对话（部分）：完整问'),
    ([{'role': 'user', 'content': '别人的问题'}], '不能因为看起来像历史就删掉我的要求'),
])
def test_unmatched_or_absent_independent_history_is_never_trimmed(history, requirements):
    assert requirements_without_duplicate_history(requirements, history) == requirements


@pytest.mark.parametrize('provider', ['deepseek', 'codex'])
def test_real_client_receives_history_once_full_original_and_current_task(tmp_path, monkeypatch, provider):
    project = create_project('上下文去重验收')
    cid = uid()
    execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)',
            (cid, project['id'], provider, None, now(), '[]', 'fixture-model', 'high'))
    history = [{'role': 'user', 'content': '历史理解哨兵：我会计算但不知道为什么这样构造。'},
               {'role': 'assistant', 'content': '旧解释哨兵：这个回答仍可能有误。'},
               {'role': 'user', 'content': '末尾追问哨兵：最大阈值怎样合并条件？'}]
    requirements = learning_requirements(history, '最新要求哨兵：请用具体数轴解释。')
    snapshot = {'id': cid, 'project_id': project['id'], 'provider': provider, 'model': 'fixture-model',
                'remote_thread_id': None, 'messages': history}
    runtime = AgentRuntime(project['id'], [], provider, 'fixture-model', 'high',
                           conversation_id=cid, job_id=uid(), publishing=False)
    ai.save_settings({'agent_tools_enabled': False, 'background_learning_enabled': False})
    captured = []
    memory_queries = []
    memory_focuses = []
    def memory_lookup(query, *, focus=''):
        memory_queries.append(query)
        memory_focuses.append(focus)
        return '相关学习画像：此知识点仍需核对理解。'
    monkeypatch.setattr('studyforge.learning_memory.profile_context', memory_lookup)
    original = '[来源 哨兵原文件｜第1段]\n原文首部哨兵。\n完整中部条件。\n原文末尾哨兵。'
    answer = '# 可独立阅读的讲解\n已解释。\n\n## 系统性总结\n条件明确。'
    if provider == 'deepseek':
        monkeypatch.setenv('DEEPSEEK_API_KEY', 'fixture-only')
        def response(request):
            captured.append(json.loads(request.content))
            packet = {'choices': [{'delta': {'content': answer}, 'finish_reason': 'stop'}]}
            return httpx.Response(200, text='data: ' + j(packet) + '\n\ndata: [DONE]\n\n',
                                  headers={'content-type': 'text/event-stream'})
        client = ai.DeepSeekClient('fixture-model', runtime, snapshot, effort='high')
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(response))
    else:
        async def stream(self, prompt, **kwargs):
            captured.append({'prompt': prompt, 'history': json.loads(kwargs['fallback_history'])})
            yield 'thread', 'isolated-task-thread'
            yield 'final', answer
        monkeypatch.setattr(CodexBridge, 'stream_turn', stream)
        client = ai.CodexClient(model='fixture-model', effort='high', agent_runtime=runtime, conversation=snapshot)
    async def run():
        try:
            return await ai.generate_explanation(client, original, 3, [], style='balanced', requirements=requirements)
        finally:
            await client.close()
    assert asyncio.run(run()) == answer
    assert len(captured) == 1
    request = captured[0]
    serialized = j(request)
    for message in history:
        assert serialized.count(message['content']) == 1
    assert '原文首部哨兵' in serialized and '完整中部条件' in serialized and '原文末尾哨兵' in serialized
    assert serialized.count('最新要求哨兵') == 1
    assert '相关学习画像：此知识点仍需核对理解。' in serialized
    assert memory_queries == [original + '\n' + requirements]
    assert len(memory_focuses) == 1
    focused = '\n'.join(memory_focuses[0])
    assert '最新要求哨兵' in focused and '末尾追问哨兵' in focused
    assert '历史理解哨兵' not in focused and '旧解释哨兵' not in focused
    assert snapshot['messages'] == history and requirements == learning_requirements(history, '最新要求哨兵：请用具体数轴解释。')


def test_standalone_generation_keeps_history_inside_requirements():
    history = [{'role': 'user', 'content': '仍需传入的历史理解哨兵。'}]
    requirements = learning_requirements(history, '本次需要图形。')
    calls = []
    class Standalone:
        async def complete(self, system, user):
            calls.append(user)
            return '讲解。'
    assert asyncio.run(ai.generate_explanation(Standalone(), '原文件全文', 3, [], requirements=requirements)) == '讲解。'
    assert '仍需传入的历史理解哨兵。' in calls[0] and '本次需要图形。' in calls[0]
