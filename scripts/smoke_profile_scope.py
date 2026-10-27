"""Local model fixture for native UI, scope checks and review recovery."""
import json
import os
import socket
from pathlib import Path

import httpx
import uvicorn

from studyforge import ai, conversations, exercises, learning_memory as memory, server
from studyforge.agent_tools import AgentRuntime
from studyforge.config import data_dir
from studyforge.db import create_project, execute, j, many, now, one, uid


def main():
    case_path=Path(os.environ['STUDYFORGE_PROFILE_SCOPE_CASE'])
    if case_path.exists():case=json.loads(case_path.read_text(encoding='utf-8'))
    else:
        projects=[create_project('数学与推理'),create_project('哲学与社会科学')]
        chats=[conversations.create(p['id'],'deepseek','fixture-model') for p in [projects[0],projects[0],projects[1]]]
        original=data_dir()/'files'/'相关与因果.txt';original.parent.mkdir(exist_ok=True)
        original.write_text('相关不等于因果。共同原因可能同时影响两个变量。因果推断应明确干预和观察的区别。',encoding='utf-8')
        source=uid()
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
                (source,projects[0]['id'],original.name,'.txt',str(original),'ready',now()))
        for chat,marker in zip(chats,['CHAT_A1_ONLY','CHAT_A2_ONLY','CHAT_B1_ONLY']):
            execute('INSERT INTO messages VALUES (?,?,?,?,?)',(uid(),chat['id'],'user',marker,now()))
        eid=memory.record_event('study','chat',{'student_text':'为什么构造辅助函数？ RAW_EVIDENCE_ONLY'},projects[0]['id'],chats[0]['id'],analyzed=True)
        memory._save_insight(eid,'柯西不等式','gap','reasoning','需要解释辅助函数的构造动机。','RAW_EVIDENCE_ONLY','暂定',anchors=['柯西不等式'])
        memory.assessment_record('quiz','柯西不等式','做题',79,'PRIVATE_ASSESSMENT_QUOTE','等号条件遗漏。',projects[0]['id'])
        memory.assessment_record('feynman','柯西不等式','费曼讲解',86,'PRIVATE_FEYNMAN_QUOTE','能清楚串联论证。',projects[0]['id'])
        runtime=AgentRuntime(projects[0]['id'],conversation_id=chats[0]['id'])
        foreign=runtime.workspace/'private-notes.txt';foreign.write_text('FOREIGN_WORKSPACE_CONTENT',encoding='utf-8')
        execute('INSERT INTO agent_dialogue_state VALUES (?,?,?,?,1)',(chats[1]['id'],0,j([{'role':'assistant','content':'LEGACY_CROSS_CHAT_CACHE'}]),now()))
        conversations.activate(chats[1]['id'])
        case={'projects':projects,'chats':chats,'source':source,'foreign':str(foreign)}
    ai.save_settings({'chat_provider':'deepseek','deepseek_model':'fixture-model','agent_read_roots':[str(data_dir().parent)],
                      'agent_tools_enabled':True,'background_learning_enabled':False})
    ai.get_secret=lambda key:'fixture-key' if key=='DEEPSEEK_API_KEY' else None
    server.get_secret=ai.get_secret
    native=httpx.AsyncClient
    stats={'requests':[],'quiz_repaired':False,'audit_format_repaired':False}
    question={'question':'在观察数据中，说明共同原因为什么会使两个变量相关。','solution':'PRIVATE_SOLUTION_NOT_PUBLISHED',
              'rubric':'说明共同原因同时影响两个变量。','topic':'因果推断','source_url':''}
    def respond(request):
        if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'fixture-model'}]})
        body=json.loads(request.content);messages=body['messages'];system=messages[0]['content'];last=messages[-1]
        packet=j(body)
        stats['requests'].append({'count':len(messages),'json_mode':bool(body.get('response_format')),
            'has_profile': '柯西不等式' in system,'a1':'CHAT_A1_ONLY' in packet,'a2':'CHAT_A2_ONLY' in packet,
            'b1':'CHAT_B1_ONLY' in packet,'raw_quote':'RAW_EVIDENCE_ONLY' in packet or 'PRIVATE_ASSESSMENT_QUOTE' in packet,
            'legacy':'LEGACY_CROSS_CHAT_CACHE' in packet,'foreign_content':'FOREIGN_WORKSPACE_CONTENT' in packet,
            'profile_tool':any(t['function']['name']=='sf_read_learning_profile' for t in body.get('tools',[]))})
        if '正在修订当前题单' in system:
            stats['quiz_repaired']=True;content=j({'questions':[question]})
        elif '习题设计者' in system:content=j({'questions':[dict(question,question='说明共同原因为何会相关。')]})
        elif '独立解题员' in system:content=j({'answers':[{'index':0,'solution':'PRIVATE_SOLUTION_NOT_PUBLISHED','issues':[]}]})
        elif '习题审查员' in system:
            passed=stats['quiz_repaired']
            content=j({'passed':passed,'issues':[] if passed else [{'index':0,'category':'statement','problem':'题意缺少两个变量这一条件。'}],
                       'corrected_questions':[] if passed else [question]})
        elif '综合核查' in str(last.get('content','')) and 'passed' in system:
            if not stats['audit_format_repaired']:stats['audit_format_repaired']=True;content='核查已结束但未返回JSON'
            else:content=j({'passed':True,'issues':[]})
        elif last['role']=='tool':
            result=json.loads(last['content'])
            if result.get('scope')=='global_learning_profile':
                assert 'RAW_EVIDENCE_ONLY' not in last['content']
                content='已读取学习画像摘要：柯西不等式做题79分，费曼讲解86分；需要补充辅助函数的构造动机。'
            else:content='访问被拒绝：其他对话文件隔离。'
        elif '我的用户画像' in str(last.get('content','')) or '查看我的学习画像' in str(last.get('content','')):
            call={'id':'profile-call','type':'function','function':{'name':'sf_read_learning_profile','arguments':'{}'}}
            return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'tool_calls':[dict(call,index=0)]},'finish_reason':'tool_calls'}]})+'\n\ndata: [DONE]\n\n')
        elif '读取别的对话文件' in str(last.get('content','')):
            call={'id':'foreign-call','type':'function','function':{'name':'sf_read_file','arguments':j({'path':case['foreign']})}}
            return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'tool_calls':[dict(call,index=0)]},'finish_reason':'tool_calls'}]})+'\n\ndata: [DONE]\n\n')
        elif '删除按钮' in str(last.get('content','')):content='这是软件操作反馈。'
        else:content='# 相关与因果\n\n相关描述共同变化；因果关注干预改变结果。\n\n> 相关不等于因果。[来源：相关与因果.txt｜段落 1]\n\n共同原因可能同时改变两个变量。\n\n## 系统性总结\n先区分观察与干预，再核对共同原因，避免从相关直接推断因果。'
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':content},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    httpx.AsyncClient=lambda *a,**kw:native(transport=httpx.MockTransport(respond))
    async def no_network(topic):return []
    exercises.search_exercises=no_network

    @server.app.get('/__profile_scope/stats')
    def get_stats():
        return {**stats,'events':one('SELECT COUNT(*) AS n FROM learning_events')['n']}

    @server.app.get('/__profile_scope/files')
    def inspect_files():
        from docx import Document
        rows=many('SELECT path,kind FROM artifacts')
        return [{'kind':row['kind'],'opens':True,'answer_hidden':'PRIVATE_SOLUTION_NOT_PUBLISHED' not in '\n'.join(p.text for p in Document(row['path']).paragraphs)} for row in rows]

    for route in list(server.app.routes):
        if getattr(route,'path','').startswith('/__profile_scope/'):
            server.app.routes.remove(route);server.app.routes.insert(0,route)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    case['url']=f'http://127.0.0.1:{port}'
    case_path.write_text(j(case),encoding='utf-8')
    uvicorn.run(server.app,host='127.0.0.1',port=port,log_level='warning')


if __name__=='__main__':main()
