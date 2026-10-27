"""Extend saved-version acceptance with follow-up guards and a failed/retried chat."""
import asyncio

from scripts import smoke_review_versions_ui as base
from studyforge import server,conversations
from studyforge.codex_bridge import CodexBridge


class ControlledBridge(CodexBridge):
    def __init__(self):super().__init__();self.turns=[]
    async def start(self):pass
    async def request(self,method,params):
        if method=='thread/start':return {'thread':{'id':'followup-controlled-codex','ephemeral':True}}
        if method=='turn/start':
            prompt=params['input'][0]['text']
            self.turns.append({'verified_notice':'同题版本已核实' in prompt,'unknown_notice':'同题版本未核实' in prompt})
            if len(self.turns)==1:
                await self.events.put({'method':'turn/completed','params':{'threadId':'followup-controlled-codex',
                    'turn':{'status':'failed','error':{'message':'exceeded retry limit, last status: 429 Too Many Requests',
                        'codexErrorInfo':{'responseTooManyFailedAttempts':{'httpStatusCode':429}}}}}})
            else:
                await self.events.put({'method':'item/completed','params':{'threadId':'followup-controlled-codex',
                    'item':{'type':'agentMessage','text':'受控重试已完成。近期复习需分别核对题目版本与帮助条件，不能只凭间隔判断已经掌握。'}}})
                await self.events.put({'method':'turn/completed','params':{'threadId':'followup-controlled-codex','turn':{'status':'completed'}}})
        return {}


bridge=ControlledBridge();server.bridge_for=lambda _:bridge
chat=conversations.create(base.fixture.p['id'],'codex','fixture-codex')
base.fixture.case['rate_test_chat']=chat['id'];conversations.activate(base.fixture.c['id'])


async def catalog(*args,**kwargs):
    return {'models':[{'id':'fixture-codex','name':'受控 Codex','efforts':['none'],
        'default_effort':'none','is_default':True}],'source':'app_server','warning':None}
server.model_catalog.get_models=catalog


@server.app.get('/__followup_test__/state')
def state():return {'turns':bridge.turns,'active_chats':list(server.active_chat_conversations)}


mount=next(route for route in server.app.routes if getattr(route,'name',None)=='web')
server.app.router.routes.remove(mount);server.app.router.routes.append(mount)
if __name__=='__main__':asyncio.run(base.fixture.main())
