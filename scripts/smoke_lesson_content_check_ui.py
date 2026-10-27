"""Isolated real UI fixture: content doubts are not learner weaknesses."""
import asyncio
import json
import os
from pathlib import Path
import sys

folder=Path(__file__).resolve().parents[1]/'build'/sys.argv[1]
os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
from scripts import smoke_library_ui as fixture
from scripts.lesson_check_fixture import seed
from studyforge import conversations
from studyforge.db import execute,j,many,one

fixture.enable_semantic(False)
pc=seed(folder/'pc','math',fixture.p['id'],fixture.c['id'])
second=conversations.create(fixture.p['id'],'deepseek','deepseek-flash')
phone=seed(folder/'phone','causal',fixture.p['id'],second['id'])
# Discard only these synthetic pre-completed feedback records in this isolated DB.
for item in (pc,phone):
    row=one('SELECT reply_message_id FROM lesson_questionnaires WHERE id=?',(item['questionnaire_id'],))
    execute("UPDATE lesson_questionnaires SET status='pending',difficulties_json='[]',other_text='',focus_json='{}',reply_status='pending',reply_message_id=NULL WHERE id=?",(item['questionnaire_id'],))
    execute('DELETE FROM messages WHERE id=?',(row['reply_message_id'],))
execute('DELETE FROM learning_insights');execute('DELETE FROM learning_events')
conversations.update(fixture.c['id'],fixture.p['id'],{'source_ids':[phone['source_id']]})
conversations.activate(fixture.c['id'])
fixture.case.update(pc=pc,phone=phone,process_id=os.getpid())


@fixture.server.app.get('/__content_check__/state')
def state():
    return {'events':many('SELECT kind,payload_json FROM learning_events'),
            'insights':many('SELECT kind,dimension,observation FROM learning_insights'),
            'scores':many('SELECT * FROM mastery'),
            'exercises':many('SELECT id FROM exercise_sets')}


mount=next(route for route in fixture.server.app.routes if getattr(route,'name',None)=='web')
fixture.server.app.router.routes.remove(mount);fixture.server.app.router.routes.append(mount)


async def respond(request):
    if request.method=='GET':return await fixture.respond(request)
    body=json.loads(request.content);fixture.calls.append(body)
    text=j(body['messages'])
    assert '先处理内容疑点' in text and '不默认学生的指正必定成立' in text
    assert 'CONTENT_CRITIQUE' in text and body['model']=='deepseek-flash'
    answer=('UI_CONTENT_CHECK_DONE：旧讲解“需要严格小于，所以取等号”前后矛盾。正确条件是正半径不大于距离的一半，因为开区间不含共同中点。取一半只是方便，更小正半径也可。'
            if 'PC_CONTENT_CRITIQUE' in text else
            'UI_CONTENT_CHECK_DONE：旧讲解错误。大样本降低抽样不确定性，不会自动排除混杂或反向因果。你另选的构造动机困难会针对解释，内容质疑本身不算知识薄弱。')
    if body.get('stream'):return fixture.httpx.Response(200,text='data: '+j({'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
    return fixture.httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':answer},'finish_reason':'stop'}]})


fixture.httpx.AsyncClient=lambda *a,**kw:fixture.original(transport=fixture.httpx.MockTransport(respond))
if __name__=='__main__':asyncio.run(fixture.main())
