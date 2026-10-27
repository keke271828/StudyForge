"""Controlled native tool loop through full reading, review and DOCX generation."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import zipfile
from xml.etree import ElementTree

import httpx

ROOT=Path(__file__).resolve().parents[1]


async def main(name):
    folder=ROOT/'build'/name
    if folder.exists() and any(folder.iterdir()):raise SystemExit('Use a fresh output folder.')
    folder.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
    from studyforge import ai,conversations,server
    from studyforge.db import create_job,create_project,execute,j,many,now,one,uid,unj
    from studyforge.review_input import MARKER
    ai.save_settings({'agent_tools_enabled':True,'agent_permission_mode':'read_only','agent_network_enabled':False,
        'background_learning_enabled':False,'model_concurrency':2})
    ai.get_secret=lambda name:'controlled-fixture-only'
    project=create_project('数学工具完整流程验收');chat=conversations.create(project['id'],'deepseek','deepseek-flash')
    original='非零实向量的点积是各对应分量乘积的和。同向要求一个是另一个的正倍数。FULL_SOURCE_END'
    source_path=folder/'向量原资料.txt';source_path.write_text(original,encoding='utf-8');sid=uid()
    execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
        (sid,project['id'],source_path.name,'.txt',str(source_path),j([{'locator':'预览','text':'STALE_PREVIEW_NOT_SOURCE'}]),'ready',now()))
    answer=('# 点积为正与同向的区别\n\n这份受控流程样例用于检查工具和导出，不是模型教学质量样本。\n\n'
        '对 a=(1,0)、b=(1,1)，精确核验得到点积1、Gram差1、不同向，夹角约45度。'
        '本例是“正点积必定同向”的反例。\n\n'
        '一般地，非零实向量点积为正对应0°≤θ<90°，允许同向时的0°；不能一概说夹角一定是锐角。'
        '这个条件来自点积公式，不是单个数例证明的。\n\n'
        '## 系统性总结\n\n点积为正不足以推出同向；核验只确认给定例子的数值关系。')
    calls=[]
    def respond(request):
        body=json.loads(request.content);calls.append(body)
        (folder/'controlled-requests.json').write_text(j(calls),encoding='utf-8')
        assert 'sf_check_math' in j(body.get('tools',[])), 'math tool absent from schema'
        text='\n'.join(str(m.get('content','')) for m in body['messages'])
        assert 'FULL_SOURCE_END' in text and 'STALE_PREVIEW_NOT_SOURCE' not in text, 'original source or preview mismatch'
        if body.get('response_format'):
            assert MARKER in text and '点积为正与同向的区别' in text, 'review inputs missing'
            delta={'content':j({'passed':True,'issues':[],'corrections':[]})};finish='stop'
        elif body['messages'][-1]['role']=='tool':
            value=json.loads(body['messages'][-1]['content'])
            assert value['results']['dot_product']=='1' and value['results']['same_direction'] is False
            delta={'content':answer};finish='stop'
        else:
            delta={'tool_calls':[{'index':0,'id':'vector-case','type':'function','function':{'name':'sf_check_math',
                'arguments':j({'operation':'vectors','left':['1','0'],'right':['1','1']})}}]};finish='tool_calls'
        return httpx.Response(200,text='data: '+j({'choices':[{'delta':delta,'finish_reason':finish}]})+'\n\ndata: [DONE]\n\n')
    def attach(client):
        client._http=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        fork=client.fork
        client.fork=lambda:attach(fork())
        return client
    def factory(provider,**kwargs):
        assert provider=='deepseek'
        return attach(ai.DeepSeekClient(kwargs.get('model'),agent_runtime=kwargs.get('agent_runtime'),
            conversation=copy.deepcopy(kwargs.get('conversation')),effort=kwargs.get('effort')))
    server.client_for=factory
    value=server.GenerateIn(project_id=project['id'],conversation_id=chat['id'],source_ids=[sid],provider='deepseek',
        model='deepseek-flash',reasoning_effort='high',generation_quality='custom',review_mode='fast',
        output_format='docx',instructions='核验原资料对应的向量例子，解释正点积与同向，不出题。')
    job=create_job(project['id'],'generate',value.model_dump());start=time.perf_counter()
    await server._generate_job(job,value)
    saved=one('SELECT status,error FROM jobs WHERE id=?',(job,));assert saved['status']=='completed',saved
    assert len(calls)==3 and sum(bool(c.get('response_format')) for c in calls)==1
    artifacts=many('SELECT * FROM artifacts WHERE project_id=?',(project['id'],));assert len(artifacts)==1
    artifact=artifacts[0];assert artifact['kind']=='explanation'
    metadata=unj(artifact['metadata_json'],{})
    with zipfile.ZipFile(artifact['path']) as z:xml=z.read('word/document.xml').decode()
    visible=''.join(ElementTree.fromstring(xml).itertext())
    assert all(text in visible for text in ['Gram差1','不同向','系统性总结','0°≤θ<90°'])
    assert not any(text in xml for text in ['same_direction','tool_calls','vector-case','explanation_text'])
    events=many('SELECT tool,status,result_json FROM agent_tool_events WHERE job_id=?',(job,))
    assert len(events)==1 and events[0]['status']=='completed' and 'dot_product' not in events[0]['result_json']
    assert not many('SELECT * FROM exercise_sets') and not many('SELECT * FROM mastery')
    output=folder/'数学核验与Word导出流程样例.docx';output.write_bytes(Path(artifact['path']).read_bytes())
    public=[dict(body,messages=[{k:v for k,v in m.items() if k!='reasoning_content'} for m in body['messages']]) for body in calls]
    (folder/'controlled-public-wire.json').write_text(j(public),encoding='utf-8')
    result={'passed':True,'controlled_model_requests':len(calls),'external_model_requests':0,
        'full_original_not_preview':True,'read_only_math_tool':True,'tool_events':events,'fast_review_requests':1,
        'single_requested_docx':True,'no_exercise_or_mastery':True,'source_reading':metadata['source_reading'],
        'docx_file':output.name,'docx_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'seconds':time.perf_counter()-start}
    (folder/'results.json').write_text(j(result),encoding='utf-8');print(j(result),flush=True)


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
