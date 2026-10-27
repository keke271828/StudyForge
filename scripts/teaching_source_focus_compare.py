"""Four bounded, real tutor requests, with isolated synthetic long originals.

Requires --live. Only the local original-excerpt selector differs between arms.
Saved requests exclude credentials and private reasoning. No automatic AI judge.
"""
import argparse
import asyncio
from contextlib import aclosing
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.source_focus_cases import CASES


async def main(args):
    output = (ROOT/'build'/args.output).resolve()
    if output.parent != (ROOT/'build').resolve() or output.exists():
        raise SystemExit('Use a fresh direct build directory.')
    output.mkdir()
    os.environ['STUDYFORGE_DATA_DIR'] = str(output/'data')
    from studyforge import ai, conversations, server, source_focus
    from studyforge.db import create_project, execute, j, now, one, uid
    from studyforge.learning import source_fingerprint, reading_context
    from studyforge.materials import read_original_sources
    ai.save_settings({'background_learning_enabled':False,'agent_tools_enabled':False,'agent_network_enabled':False,
                      'library_reference_mode':'off','agent_permission_mode':'read_only'})
    server.discussion_completed = lambda *a:None
    original_client, original_focus = server.DeepSeekClient, source_focus.prepare
    rows=[]
    report={'model':args.model,'effort':args.effort,'synthetic_prepared_reading':True,
            'live':args.live,'private_reasoning_saved':False,'real_user_data_used':False,'results':rows}
    def save():
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if not args.live:
        save(); print(json.dumps({'model_calls':0,'output':str(output)})); return
    for order, (case, material) in enumerate(CASES.items()):
        project=create_project('长资料教学对照：'+case)
        path=output/(case+'-source.txt');path.write_text(material['front']+material['tail'],encoding='utf-8')
        sid,rid=uid(),uid()
        execute('INSERT INTO sources(id,project_id,name,kind,original_path,segments_json,status,created_at) '
                'VALUES (?,?,?,?,?,?,?,?)',(sid,project['id'],material['title']+'.txt','.txt',str(path),'[]','ready',now()))
        records=read_original_sources([dict(id=sid,project_id=project['id'],name=material['title']+'.txt',kind='.txt',original_path=str(path))])
        notes=[{'part':1,'text':'这份人工样本的前半部分为背景，后半部分含当前问题的定义、例子与限制；本笔记不能代替原文。'}]
        execute('INSERT INTO reading_sessions VALUES (?,?,?,?,?,?,?,?,?,?)',(rid,project['id'],j([sid]),source_fingerprint(records),
            'deepseek',args.model,args.effort,j(notes),j([records[0]['read_manifest']]),now()))
        (output/(case+'-question.txt')).write_text(material['question'],encoding='utf-8')
        for arm in (['legacy','focused'] if order==0 else ['focused','legacy']):
            started=time.perf_counter();requests=[];clients=[];first=None;receipt=None;answer=''
            row={'case':case,'arm':arm,'status':'running','criteria':material['criteria']}
            class Observed(ai.DeepSeekClient):
                def __init__(self,*a,**kw):super().__init__(*a,**kw);clients.append(self)
                async def stream_packets(self,body):
                    nonlocal first
                    record={'model':body['model'],'thinking':body.get('thinking'),'reasoning_effort':body.get('reasoning_effort'),
                        'messages':[{k:v for k,v in m.items() if k!='reasoning_content'} for m in body['messages']],
                        'response_models':[],'usage':None}
                    requests.append(record)
                    async for packet in super().stream_packets(body):
                        if packet.get('model') and packet['model'] not in record['response_models']:record['response_models'].append(packet['model'])
                        if packet.get('usage'):record['usage']=packet['usage']
                        if first is None and any(c.get('delta',{}).get('content') for c in packet.get('choices',[])):first=time.perf_counter()-started
                        yield packet
            def selected(digest,query,saved_notes,**kw):
                nonlocal receipt
                if arm=='focused':
                    text,receipt=original_focus(digest,query,saved_notes,**kw)
                else:
                    plain=re.sub(r'(\[来源 [^\n]+\]) \[资料ID:[^\n]+\]\n',r'\1\n',digest)
                    text=('已通读完整原资料；本次对话使用阅读笔记与原文开头片段。涉及未提供的细节时不得声称已核对全文，'
                        '应提示生成完整讲解或核对相应原文。\n'+reading_context(saved_notes)+'\n原文片段（非全文）：\n'+plain[:45000])
                    receipt={'version':'legacy-fixed-prefix','context_characters':len(text),'included':[{'legacy_prefix':True}],'model_calls':0}
                receipt['targets_supplied']={target:target in text for target in material['targets']}
                return text,receipt
            try:
                server.DeepSeekClient=Observed;source_focus.prepare=selected
                chat=conversations.create(project['id'],'deepseek',args.model,args.effort)
                request=server.ChatIn(project_id=project['id'],conversation_id=chat['id'],source_ids=[sid],reading_id=rid,
                    provider='deepseek',model=args.model,reasoning_effort=args.effort,learning_mode='deep',explanation_style='balanced',
                    output_language='zh',text=material['question'])
                async def run():
                    response=await server.chat_stream(request)
                    async with aclosing(response.body_iterator) as stream:
                        async for line in stream:
                            event=json.loads(line)
                            if event['type']=='error':raise RuntimeError(event['value'])
                            if event['type']=='job':raise RuntimeError('Unexpected exercise job')
                    return one("SELECT content FROM messages WHERE conversation_id=? AND role='assistant' ORDER BY rowid DESC LIMIT 1",(chat['id'],))['content']
                answer=await asyncio.wait_for(run(),timeout=300)
                row.update(status='completed',answer_characters=len(answer),answer_sha256=hashlib.sha256(answer.encode()).hexdigest())
                (output/(case+'-'+arm+'.md')).write_text(answer,encoding='utf-8')
            except Exception as exc:
                row.update(status='failed',error=type(exc).__name__+': '+str(exc))
            finally:
                server.DeepSeekClient=original_client;source_focus.prepare=original_focus
                for client in clients:await client.close()
                row.update(seconds=round(time.perf_counter()-started,3),first_visible_seconds=round(first,3) if first is not None else None,
                           input_receipt=receipt,request_count=len(requests),answer_file=case+'-'+arm+'.md')
                (output/(case+'-'+arm+'-requests.json')).write_text(json.dumps(requests,ensure_ascii=False,indent=2),encoding='utf-8')
                rows.append(row);save();print(json.dumps({k:row[k] for k in ('case','arm','status','seconds','request_count')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True);parser.add_argument('--live',action='store_true')
    parser.add_argument('--model',default='deepseek-flash');parser.add_argument('--effort',default='high')
    asyncio.run(main(parser.parse_args()))
