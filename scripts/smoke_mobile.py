"""Real TLS + Electron integration fixture. Uses no external AI or user data."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import socket
import sys

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    case_path = Path(os.environ['STUDYFORGE_MOBILE_CASE'])
    case_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(case_path.parent / 'data')
    os.environ['STUDYFORGE_DESKTOP_TOKEN'] = 'mobile-test-owner'
    from studyforge import ai, server, conversations, coding
    from studyforge.db import create_project, execute, j, now, uid
    from studyforge.config import files_dir
    from studyforge.mobile_access import StartIn
    ai.save_settings({'chat_provider': 'deepseek', 'background_learning_enabled': False,
                      'agent_permission_mode': 'full_access', 'auto_select_imports': True,
                      'agent_tools_enabled': False})
    project, other = create_project('随身学习验收'), create_project('另一个独立项目')
    chat = conversations.create(project['id'], 'deepseek')
    second_chat = conversations.create(project['id'], 'deepseek')
    conversations.activate(chat['id'])
    worksheet, program = uid(), uid()
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
        (worksheet,project['id'],'[]','变量理解与计算练习',
         j([{'index':0,'topic':'变量的含义','question':'解释公式中变量表示什么，为什么需要先说明量的意义。'},
            {'index':1,'topic':'加法计算','question':'计算2+3并说明你的步骤。'}]),
         j([{'index':0,'solution':'PHONE_REFERENCE_VARIABLE：变量表示指定的量，需先明确意义和条件。','rubric':'说明量与符号的区别'},
            {'index':1,'solution':'PHONE_REFERENCE_ADD：2+3=5。','rubric':'逐步计算正确'}]),2,'assigned',now()))
    execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
        (program,project['id'],'[]','JavaScript加法作业',
         j([{'index':0,'topic':'函数加法','question':'用 JavaScript 实现 add(a,b)，返回两数之和。','language':'javascript'}]),
         j([{'index':0,'solution':'function add(a,b){return a+b;}','rubric':'正确相加','test_code':'检查 add(2,3)===5'}]),2,'assigned',now()))
    code_file=case_path.parent/'student-answer.js'
    code_file.write_bytes('// 中文代码说明\nfunction add(a,b){return a-b;}'.encode('utf-16'))
    coding._run_assignment_tests=lambda *args:{'ran':False,'score':0,'reason':'离线验收未运行Docker，保留静态反馈'}
    grade_gate=asyncio.Event()
    feedback_gate=asyncio.Event()
    @server.app.post('/__mobile_test__/release-grade')
    async def release_grade():
        grade_gate.set()
        return {'released':True}
    @server.app.post('/__mobile_test__/release-feedback')
    async def release_feedback():
        feedback_gate.set()
        return {'released':True}
    mount=next(route for route in server.app.router.routes if getattr(route,'name',None)=='web')
    server.app.router.routes.remove(mount)
    server.app.router.routes.append(mount)
    import fitz
    book = case_path.parent / 'four-pages.pdf'
    document = fitz.open()
    for index in range(1, 5):
        page = document.new_page()
        page.insert_text((50, 65), f'PRIVATE_PAGE_{index}: A whole paragraph for page {index}, never read other pages.')
        page.insert_text((50, 100), f'TARGET_PARAGRAPH_{index}: This exact paragraph is enough for this lesson.')
    document.save(book)
    document.close()
    text = ('# 选段讲解\n\n只使用你选择的原文。先明确概念、条件与证据。'
            '\n\n## 为什么这样推理\n\n结论来自已给条件，推理不能悄悄增加前提。'
            '\n\n## 系统性总结\n\n本次只学习选段，未通读其余页面。')
    calls = []
    report = case_path.with_name('requests.json')
    async def respond(request):
        if request.method == 'GET':
            return httpx.Response(200, json={'data': [{'id': 'deepseek-flash'}]})
        body = json.loads(request.content)
        calls.append(body)
        report.write_text(j(calls), encoding='utf-8')
        system = body['messages'][0]['content']
        user = body['messages'][-1]['content']
        if '从学生作答文件中提取' in system:
            answer=j({'answers':['我不知道变量表示的量，写不出具体含义','2+3=4，我从2开始加错了'],
                      'uncertainties':['第二题的手写结果需人工核对']})
        elif '逐题诊断错因并补讲' in system:
            source=json.JSONDecoder().raw_decode(user)[0]
            items=[]
            for index in source['wrong_indices']:
                code=bool(source['questions'][index].get('language'))
                causes=[row for row in source['student_causes'] if row['index']==index]
                unknown=index==0 and not causes and not code
                quote=(causes[0]['text'] or causes[0]['labels'][0]) if causes else source['student_answers'][index]
                explanation=('题目要求返回两个数的和，return a-b 返回的是差。应把运算符改为加法，返回a+b。再代入2和3验证结果是5，逐个核对运算符与题目要求。' if code else
                    '变量首先表示一个明确的量，符号只是这个量的名称。应先说明每个量的意义、单位以及取值条件，再判断公式中各量的关系。把符号当成结果会跳过建模步骤，先逐个写清量的含义再计算。' if index==0 else
                    '你把2+3写成4，计算步骤有误。从2开始连续加三个1，依次得到3、4、5，所以答案是5。用逆运算核对：5减3等于2，而4减3等于1，后一结果不能回到原来的2。')
                items.append({'index':index,'kind':'implementation' if code or index==1 else 'terminology',
                    'confidence':'uncertain' if unknown else 'self_report' if causes else 'supported',
                    'cause':'需要确认变量与量的关系' if unknown else '学生自报变量含义不清楚' if causes else '计算或运算符出错',
                    'evidence':[{'source':'questionnaire' if causes else 'answer','quote':quote}],
                    'clarification':'你当时把变量当成了什么？是不懂量的意义，还是不知道条件？',
                    'explanation':explanation,'check':'逐个核对量的意义，再用简单数值检查。'})
            answer=j({'items':items})
        elif '批改者' in system or '评分复核者' in system:
            await grade_gate.wait()
            answer=j({'scores':[30,50],'feedback':['变量的含义尚未解释','加法步骤出错'],'uncertainties':[]})
        elif '编程教师' in system:
            answer=j({'score':50,'feedback':'把求和写成求差','issues':['return a-b 与题意不符']})
        elif '费曼学习法评审' in system:
            answer=j({'score':75,'passed':False,'feedback':'能区分符号与量，但还需要说明取值条件。',
                      'gaps':['说明取值条件与单位'],'critical_errors':[]})
        elif body.get('response_format', {}).get('type') == 'json_object':
            answer = j({'passed': True, 'issues': []})
        elif '通读理解资料' in system:
            answer = '## 本次选段阅读笔记\n\n仅阅读本次选定范围，不代表通读整本书。'
        elif '教材式讲解' in system:
            answer = text
        elif '本次是讲解后补讲' in system:
            await feedback_gate.wait()
            answer = ('## 先说明条件为什么必要\n\nPHONE_LESSON_SUPPLEMENT：这次只针对你反馈的构造动机与前置知识补讲。'
                      '\n\n量的意义决定符号代表什么，成立条件说明推理什么时候有效。要得到结论，先检查需要哪些前提，'
                      '再说明这一步为什么能从前一步推出，不能把缺失条件当成默认事实。'
                      '\n\n例如 $x>0$ 是一个条件，不是计算结果。\n\n## 小结\n\n先定位目标与条件，再衔接理由。哪一个前置概念仍不清楚？')
        else:
            await asyncio.sleep(2)
            answer = ('## 只看你的选段\n\n这条回复检验电脑后台持久运行。\n\n'
                      '公式可以显示：$E=mc^2$。\n\n$$\\int_0^1 x\\,dx=\\frac{1}{2}$$\n\n'
                      '> 引用：所选原文。\n\n| 范围 | 已读取 |\n| --- | --- |\n| 所选段落 | 是 |\n| 其他页面 | 否 |\n\n'
                      '```python\nprint("only a display example")\n```\n\n'
                      '正文末尾：任务不会因手机离开页面而消失。')
        if body.get('stream'):
            return httpx.Response(200, text='data: ' + j({'choices': [{'delta': {'content': answer}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n')
        return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':answer}}]})
    original_http = httpx.AsyncClient
    httpx.AsyncClient = lambda *args, **kwargs: original_http(transport=httpx.MockTransport(respond))
    ai.get_secret = lambda key: 'fixture-key' if key == 'DEEPSEEK_API_KEY' else None
    server.get_secret = ai.get_secret
    sockets = []
    for _ in range(2):
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        sockets.append(sock)
    main_port, mobile_port = [sock.getsockname()[1] for sock in sockets]
    for sock in sockets:
        sock.close()
    case = {'project_id': project['id'], 'other_project_id': other['id'], 'conversation_id': chat['id'],
            'second_conversation_id':second_chat['id'],'worksheet_id':worksheet,'program_id':program,'code_file':str(code_file),
            'desktop_url': f'http://127.0.0.1:{main_port}', 'mobile_url': f'https://127.0.0.1:{mobile_port}',
            'book': str(book), 'token': 'mobile-test-owner'}
    async def start_mobile():
        while not getattr(server.app.state, 'mobile_manager', None):
            await asyncio.sleep(.05)
        manager = server.app.state.mobile_manager
        await manager.start(StartIn(addresses=['127.0.0.1'], port=mobile_port))
        case['pairing_code'] = manager.code
        case['certificate'] = manager.tls['ca']
        case['fingerprint'] = manager.tls['fingerprint']
        case_path.write_text(j(case), encoding='utf-8')
    async def serve():
        starter = asyncio.create_task(start_mobile())
        await uvicorn.Server(uvicorn.Config(server.app, host='127.0.0.1', port=main_port, log_level='warning')).serve()
        await asyncio.gather(starter, return_exceptions=True)
    asyncio.run(serve())


if __name__ == '__main__':
    main()
