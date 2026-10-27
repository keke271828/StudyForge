"""Offline HTTP model fixture for native homework acceptance; isolated app data."""
import asyncio
import json
import os
import socket
import time
from pathlib import Path

import httpx
import uvicorn
from docx import Document

from studyforge import ai, coding, conversations, learning_memory, server
from studyforge.db import create_project, execute, j, many, now, one, uid, unj
from studyforge.scheduling import execution_context


def main():
    case_path=Path(os.environ['STUDYFORGE_HOMEWORK_CASE']);root=case_path.parent
    phase=int(os.environ.get('STUDYFORGE_HOMEWORK_PHASE','1'))
    if phase==1:
        ai.save_settings({'chat_provider':'deepseek','deepseek_model':'homework-model','agent_tools_enabled':False,
                          'background_learning_enabled':True,'auto_select_imports':False,'model_concurrency':2})
        project=create_project('错因教学验收');other=create_project('独立项目乙')
        chat=conversations.create(project['id'],'deepseek','homework-model');conversations.activate(chat['id'])
        second=conversations.create(project['id'],'deepseek','homework-model')
        message=uid();execute('INSERT INTO messages VALUES (?,?,?,?,?)',(message,chat['id'],'user','高斯定律是什么？',now()))
        learning_memory.discussion_completed(chat['id'],message)
        ai.save_settings({'background_learning_enabled':False})
        worksheet,program=uid(),uid()
        questions=[{'index':0,'topic':'高斯定律','question':r'解释 $\oint_S\mathbf E\cdot d\mathbf S=Q_{\mathrm{in}}/\epsilon_0$，说明各个量的意义。'},
                   {'index':1,'topic':'加法','question':'计算2+3，并写出计算步骤。'}]
        solutions=[{'index':0,'solution':'REFERENCE_GAUSS：封闭面电通量等于面内电荷除以真空介电常数。电场来自所有电荷；Q只包括面内电荷。','rubric':'区分电场、封闭面通量与内电荷'},
                   {'index':1,'solution':'REFERENCE_ADD：2+3=5。','rubric':'加法计算正确'}]
        execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(worksheet,project['id'],'[]','高斯定律与计算练习',j(questions),j(solutions),2,'assigned',now()))
        execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',(program,project['id'],'[]','JavaScript函数练习',
                j([{'index':0,'topic':'函数加法','question':'用 JavaScript 实现 add(a,b)，返回两数之和。','language':'javascript'}]),
                j([{'index':0,'solution':'function add(a,b){return a+b;}','rubric':'正确相加','test_code':'检查 add(2,3)===5'}]),2,'assigned',now()))
        case={'project':project['id'],'other':other['id'],'chat':chat['id'],'second':second['id'],'worksheet':worksheet,'program':program}
    else:case=json.loads(case_path.read_text(encoding='utf-8'))
    requests_path=root/'requests.json'
    calls=json.loads(requests_path.read_text(encoding='utf-8')) if requests_path.exists() else []
    gate=asyncio.Event();released={'value':phase!=1};pending_review={'value':True}
    ai.get_secret=lambda name:'fixture-key' if name=='DEEPSEEK_API_KEY' else None
    server.get_secret=ai.get_secret;server.shutil.which=lambda name:None
    coding._run_assignment_tests=lambda *a:{'ran':False,'score':0,'reason':'离线验收：Docker未启动，保留静态审查'}
    native=httpx.AsyncClient
    async def reply(request):
        if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'homework-model'}]})
        body=json.loads(request.content);system=body['messages'][0]['content'];user=body['messages'][-1]['content']
        kind=('analysis' if '逐题诊断错因并补讲' in system else 'grade' if '批改者' in system or '评分复核者' in system else
              'code' if '编程教师' in system else 'chat')
        call={'kind':kind,'start':time.time(),'end':None,'job':execution_context.get().get('job_id')}
        calls.append(call);requests_path.write_text(j(calls),encoding='utf-8')
        try:
            if kind=='grade' and not released['value']:await gate.wait()
            await asyncio.sleep(.35)
            if kind=='analysis':
                data=unj(user);items=[]
                for index in data['wrong_indices']:
                    is_code=bool(data['questions'][index].get('language'))
                    causes=[x for x in data['student_causes'] if x['index']==index]
                    unknown=index==0 and not causes and not is_code
                    quote=causes[0]['text'] or causes[0]['labels'][0] if causes else data['student_answers'][index]
                    explanation=('return a-b 得到的是差，题目要的是和，因此应 return a+b。逐个核对运算符，再代入2和3：正确结果应为5。' if is_code else
                        '高斯定律中的通量是把封闭面各小块上的电场法向分量乘面积后相加。电场与外法向决定每小块的贡献；Q是面内总电荷。外部电荷可以影响电场，但不进入Q。先逐个解释量的意义，再代入公式，不能把通量直接当作电场。' if index==0 else
                        '2+3=4 的错误在加法计算。由2开始连续加三个1，依次得到3、4、5，所以结果应为5。用逆运算核对：5−3=2，而4−3=1。')
                    items.append({'index':index,'kind':'implementation' if index==1 or is_code else 'terminology',
                        'confidence':'uncertain' if unknown else 'self_report' if causes else 'supported',
                        'cause':'仅凭最终作答不能确定概念卡点' if unknown else '学生自报混淆电通量与电场' if causes else '作答中的运算步骤错误',
                        'evidence':[{'source':'questionnaire' if causes else 'answer','quote':quote}],
                        'clarification':'你当时如何理解电通量？是哪个符号不清楚，还是不知道为何要对封闭面积分？',
                        'explanation':explanation,'check':'核对量的意义、适用条件，再用简单数值或逆运算检查。'})
                text=j({'items':items})
            elif kind=='grade':
                if 'SMOKE_SCORE_RECHECK' in user:
                    text=j({'scores':[20 if pending_review['value'] else 100],'feedback':['评分依据待核实' if pending_review['value'] else '逐个加1得到5，满足全部评分点'],
                            'uncertainties':['第1题的参考评分依据有实质疑点'] if pending_review['value'] else []})
                else:text=j({'scores':[30,50],'feedback':[r'**封闭面通量**概念尚未说明；需要区分 $\Phi_E$ 与 $\mathbf E$。','加法计算错误'],'uncertainties':[]})
            elif kind=='code':text=j({'score':50,'feedback':'把求和写成求差','issues':['return a-b 与求和要求不符']})
            else:text='导师：我们可以继续讨论变量的含义，独立作业批改在后台运行。'
            if body.get('stream'):
                return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':text},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
            return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':text}}]})
        finally:call['end']=time.time();requests_path.write_text(j(calls),encoding='utf-8')
    class Offline(native):
        def __init__(self,*args,**kwargs):kwargs['transport']=httpx.MockTransport(reply);super().__init__(*args,**kwargs)
    httpx.AsyncClient=Offline
    @server.app.post('/__homework_test__/release')
    def release():released['value']=True;gate.set();return {'ok':True}
    @server.app.post('/__homework_test__/review-worksheet')
    def review_worksheet():
        ident=uid();execute('INSERT INTO exercise_sets VALUES (?,?,?,?,?,?,?,?,?)',
            (ident,case['project'],'[]','评分疑点复核',j([{'index':0,'topic':'SMOKE_SCORE_RECHECK','question':'计算2+3并说明步骤。'}]),
             j([{'index':0,'solution':'2+3=5','rubric':'逐步计算正确100分'}]),1,'assigned',now()))
        return {'id':ident}
    @server.app.post('/__homework_test__/clear-review-doubt')
    def clear_review_doubt():pending_review['value']=False;return {'ok':True}
    @server.app.get('/__homework_test__/state')
    def inspect():
        artifacts=many('SELECT * FROM artifacts')
        for artifact in artifacts:
            artifact['paragraphs']='\n'.join(p.text for p in Document(artifact['path']).paragraphs)
        return {'calls':calls,'attempts':server.project_homework(case['project']),'artifacts':artifacts,
                'submissions':many('SELECT * FROM submissions'),'insights':many('SELECT * FROM learning_insights')}
    mount=next(route for route in server.app.router.routes if getattr(route,'name',None)=='web')
    server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    case.update(url=f'http://127.0.0.1:{port}',phase=phase);case_path.write_text(j(case),encoding='utf-8')
    uvicorn.run(server.app,host='127.0.0.1',port=port,log_level='warning')


if __name__=='__main__':main()
