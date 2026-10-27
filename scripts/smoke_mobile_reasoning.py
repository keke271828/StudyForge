"""Paired phone -> durable requests -> actual provider body, with offline replies."""
import asyncio
import json
from scripts import smoke_library_ui as fixture
from studyforge import ai, conversations, providers
from studyforge.codex_bridge import CodexBridge
from studyforge.db import execute, j, now, uid

ai.save_settings({'chat_effort_deepseek':'high','library_semantic_enabled':False})
conversations.update(fixture.c['id'],fixture.p['id'],{'reasoning_effort':'high'})
source=uid();original=fixture.case_path.parent/'封闭性.txt'
original.write_text('数域是包含0与1的复数集合，对加、减、乘和非零除数的除法封闭。\n已包含1且对减法封闭时，1-1=0 已保证包含0。',encoding='utf-8')
execute('INSERT INTO sources(id,project_id,name,kind,original_path,status,created_at) VALUES (?,?,?,?,?,?,?)',
        (source,fixture.p['id'],original.name,'.txt',str(original),'ready',now()))
service=providers.save_service({'name':'离线兼容服务','protocol':'openai','base_url':'https://fixture.invalid/v1',
    'models':['vendor-basic'],'default_model':'vendor-basic','requires_key':False,'supports_tools':False,'supports_vision':False})
fixture.case.update(source_id=source,custom_provider=service['id'])
original_response=fixture.respond
async def respond(request):
    if request.method=='POST':
        body=json.loads(request.content);system=body['messages'][0]['content']
        if isinstance(system,str) and '只整理交接' in system:
            fixture.calls.append(body)
            packet={'learning_goal':'理解本次材料','instructions':[],'understanding':[],
                    'teaching_strategy':[],'unresolved_questions':[]}
            import httpx
            return httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':j(packet)},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    return await original_response(request)
fixture.respond=respond
async def start(self):pass
async def directory(self,method,params):
    assert method=='model/list'
    return {'data':[{'id':'gpt-fixture-wide','model':'gpt-fixture-wide','displayName':'Fixture Wide','isDefault':True,
                    'supportedReasoningEfforts':[{'reasoningEffort':x} for x in ['low','high','max']]},
                    {'id':'gpt-fixture-narrow','model':'gpt-fixture-narrow','displayName':'Fixture Narrow',
                     'supportedReasoningEfforts':[{'reasoningEffort':'low'}]}]}
CodexBridge.start=start;CodexBridge.request=directory
if __name__=='__main__':asyncio.run(fixture.main())
