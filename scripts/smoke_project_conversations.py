"""Persistent restart fixture using only a simulated DeepSeek transport."""
import json
import asyncio
import os
import socket
from pathlib import Path

import httpx
import uvicorn

from studyforge import ai, server, conversations
from studyforge.db import create_project, execute, j, now, uid


def main():
    case_path = Path(os.environ['STUDYFORGE_WORKSPACE_UI_CASE'])
    case_path.parent.mkdir(parents=True, exist_ok=True)
    ai.save_settings({'chat_provider':'deepseek', 'agent_tools_enabled':False,
                      'background_learning_enabled':False, 'auto_select_imports':False})
    if case_path.exists():
        case = json.loads(case_path.read_text(encoding='utf-8'))
    else:
        project, other = create_project('跨学科学习项目'), create_project('另一个项目')
        ids = []
        for label in ['A', 'B', 'C']:
            path = case_path.parent / (label + '原文.txt')
            path.write_text(label + '原文完整内容。\n原文末尾：保留适用条件。', encoding='utf-8')
            sid = uid(); ids.append(sid)
            execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (sid, project['id'], path.name, '.txt', str(path), j([{'locator':'预览','text':'旧摘要不能替代原文件'}]), 'ready', now()))
        legacy = uid()
        execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)', (legacy, project['id'], 'deepseek', None, now(), '[]', 'deepseek-flash', None))
        execute('INSERT INTO messages VALUES (?,?,?,?,?)', (uid(), legacy, 'user', '保留升级前的聊天记录', now()))
        conversations.activate(legacy)
        case = {'project_id':project['id'], 'other_project_id':other['id'], 'sources':ids, 'legacy_id':legacy}
    report_path = case_path.with_name('requests.json')
    calls = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else []
    ai.get_secret = lambda key:'fixture-key' if key == 'DEEPSEEK_API_KEY' else None
    server.get_secret = ai.get_secret
    original_http = httpx.AsyncClient

    async def respond(request):
        if request.method == 'GET':
            return httpx.Response(200, json={'data':[{'id':'deepseek-flash'},{'id':'deepseek-v4-pro'}]})
        body = json.loads(request.content)
        system = body['messages'][0]['content']; user = body['messages'][-1]['content']
        kind = 'reading' if '通读理解资料' in system else 'knowledge' if '【资料知识结构整理】' in system else 'generation' if '教材式讲解' in system else 'chat'
        calls.append({'kind':kind, 'model':body['model'], 'messages':body['messages']})
        report_path.write_text(j(calls), encoding='utf-8')
        if kind == 'generation': await asyncio.sleep(1.2)
        if body.get('response_format', {}).get('type') == 'json_object' and kind != 'knowledge':
            text = j({'passed':True, 'issues':[]})
        elif kind == 'knowledge':
            text = j({'concepts':[{'id':'a','name':'概念A','domain':'跨学科','description':'先辨认概念与适用条件。',
                     'basis':'source','evidence':[{'source_id':case['sources'][0], 'locator':'行 1-2','quote':'A原文完整内容'}]}], 'relations':[]})
        elif kind == 'reading':
            labels = ''.join(label for label in ['A', 'B', 'C'] if label + '原文完整内容' in user) or '成果'
            text = ('## 阅读笔记\n\n笔记范围：' + labels + '\n\n'
                    '完整读取原文，保留适用条件。[来源：所选原文 · 行 1-2]\n\n'
                    '### 公式排版示例\n\n行内公式 $E=mc^2$。\n\n$$\\frac{d}{dt}x(t)=v(t)$$\n\n'
                    '| 内容 | 位置 |\n| --- | --- |\n| 原文条件 | 行 1-2 |\n\n'
                    '> 原文末尾：保留适用条件。\n\n'
                    '```python\n# 仅为代码排版验收，不执行\nx = 1\n```\n\n' +
                    '\n\n'.join(f'### 阅读段落 {i}\n\n第 {i} 段用于长笔记滚动验收。辨认概念、条件和论证依据，回到原文核对重要结论。' for i in range(1, 25)))
        elif kind == 'generation': text = '# 原资料讲解\n\n先解释概念和依据。\n\n成果末尾唯一证据：独立引用无需重新导入。\n\n## 系统性总结\n保留适用条件和关键动机。'
        else: text = '导师回应：' + user[:100] + '\n\n此回复用于离线功能验收。'
        return httpx.Response(200, text='data: '+j({'choices':[{'delta':{'content':text},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    httpx.AsyncClient = lambda *a, **kw: original_http(transport=httpx.MockTransport(respond))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    case['url'] = f'http://127.0.0.1:{port}'
    case_path.write_text(j(case), encoding='utf-8')
    uvicorn.run(server.app, host='127.0.0.1', port=port, log_level='warning')


if __name__ == '__main__': main()
