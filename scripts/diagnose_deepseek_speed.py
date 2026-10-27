"""Bounded real probes: software client vs identical direct HTTP requests.

Stores timings, provider usage and hashes. Never stores credentials, request
text, model reasoning, or answer text. User data/settings remain untouched.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[1]


def number(value):
    return value if type(value) is int and value>=0 else None


class PacketMetrics:
    def __init__(self,body):
        self.body_sha256=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        self.input_characters=sum(len(str(message.get('content',''))) for message in body.get('messages',[]))
        self.requested_model=body['model'];self.thinking=copy.deepcopy(body.get('thinking'))
        self.effort=body.get('reasoning_effort');self.headers_s=None;self.end_s=None
        self.first_packet_s=None;self.first_reasoning_s=None;self.first_content_s=None;self.last_content_s=None
        self.last_generated_s=None;self.packet_count=0;self.reasoning_characters=0;self.content_characters=0
        self.content_packets=0;self.usage={};self.returned_model=None;self.finish=None;self.consumer_seconds=0
        self.status=None;self.error=None

    def observe(self,packet,elapsed):
        self.packet_count+=1
        if self.first_packet_s is None:self.first_packet_s=elapsed
        if isinstance(packet.get('model'),str):self.returned_model=packet['model']
        usage=packet.get('usage')
        if isinstance(usage,dict):
            for key in ('prompt_tokens','completion_tokens','total_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens'):
                if number(usage.get(key)) is not None:self.usage[key]=usage[key]
            detail=usage.get('completion_tokens_details')
            if isinstance(detail,dict) and number(detail.get('reasoning_tokens')) is not None:
                self.usage['reasoning_tokens']=detail['reasoning_tokens']
        for choice in packet.get('choices') or []:
            if choice.get('finish_reason'):self.finish=choice['finish_reason']
            delta=choice.get('delta') or choice.get('message') or {}
            reasoning=delta.get('reasoning_content');content=delta.get('content')
            if isinstance(reasoning,str) and reasoning:
                if self.first_reasoning_s is None:self.first_reasoning_s=elapsed
                self.reasoning_characters+=len(reasoning);self.last_generated_s=elapsed
            if isinstance(content,str) and content:
                if self.first_content_s is None:self.first_content_s=elapsed
                self.last_content_s=elapsed;self.last_generated_s=elapsed
                self.content_packets+=1;self.content_characters+=len(content)

    def public(self):
        result=dict(vars(self));completion=self.usage.get('completion_tokens');reasoning=self.usage.get('reasoning_tokens')
        visible=completion-reasoning if completion is not None and reasoning is not None and 0<=reasoning<=completion else None
        result['visible_tokens_from_provider']=visible
        result['visible_window_s']=(self.last_content_s-self.first_content_s
            if self.content_packets>1 and self.last_content_s>self.first_content_s else None)
        result['visible_receive_tokens_per_second']=(visible/result['visible_window_s']
            if visible is not None and result['visible_window_s'] else None)
        start=self.first_reasoning_s if self.first_reasoning_s is not None else self.first_content_s
        window=self.last_generated_s-start if start is not None and self.last_generated_s>start else None
        result['all_output_receive_tokens_per_second']=completion/window if completion is not None and window else None
        return result


def traced_class():
    from studyforge.ai import DeepSeekClient
    from studyforge.deepseek_protocol import response_packets

    class TracedClient(DeepSeekClient):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);self.traces=[];self.request_bodies=[]

        async def stream_packets(self,body):
            # Include provider usage for diagnostics; does not cap generation or
            # alter the selected model/thinking strength.
            body=copy.deepcopy(body);body['stream_options']={'include_usage':True}
            self.request_bodies.append(body)
            metrics=PacketMetrics(body);self.traces.append(metrics);start=time.perf_counter()
            try:
                async with self.http_client().stream('POST','https://api.deepseek.com/chat/completions',json=body,
                        headers={'Authorization':'Bearer '+self.key},timeout=240) as response:
                    metrics.headers_s=time.perf_counter()-start;metrics.status=response.status_code
                    response.raise_for_status()
                    async for packet in response_packets(response):
                        metrics.observe(packet,time.perf_counter()-start)
                        consumer_start=time.perf_counter()
                        try:yield packet
                        finally:metrics.consumer_seconds+=time.perf_counter()-consumer_start
            except BaseException as exc:
                metrics.error=type(exc).__name__;raise
            finally:metrics.end_s=time.perf_counter()-start

    return TracedClient


async def native(client,system,user,json_mode=False):
    final=''
    async for kind,value in client.agent_stream([{'role':'system','content':system},{'role':'user','content':user}],json_mode=json_mode):
        if kind=='final':final=value
    if not final:raise RuntimeError('No final answer')
    return {'answer_characters':len(final),'answer_sha256':hashlib.sha256(final.encode()).hexdigest()}


async def direct(client,body):
    from studyforge.scheduling import model_slot
    from studyforge.deepseek_protocol import Reply
    reply=Reply();digest=hashlib.sha256();size=0
    async with model_slot('deepseek'):
        async for packet in client.stream_packets(body):
            # Same validation and final assembly, bypass the agent state loop.
            text=reply.accept(packet)
            if text:digest.update(text.encode());size+=len(text)
    reply.validate(client.model)
    return {'answer_characters':size,'answer_sha256':digest.hexdigest()}


async def main(name,mode):
    folder=ROOT/'build'/name
    if (folder/'results.json').exists():raise SystemExit('Use a new folder; preserve earlier observations.')
    folder.mkdir(parents=True,exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
    from studyforge import ai
    from studyforge.db import create_project,create_job,update_job,many
    from studyforge.scheduling import execution_scope
    from studyforge.dialogue_scope import CONTEXT_BOUNDARY
    ai.save_settings({'api_connection_mode':mode,'background_learning_enabled':False,'agent_tools_enabled':False,
        'agent_network_enabled':False,'model_concurrency':2})
    cls=traced_class();project=create_project('隔离模型速度诊断')
    simple_system='你是一位清晰、严谨的数学老师。只回答当前疑问，不出题。'
    simple_user='为什么证明收敛数列极限唯一时，可以取ε=(b-a)/2？请先指出取值的合法性，再用两个开区间解释，最后说明更小正数是否也可用。请控制在350个汉字以内。'
    previous=json.loads((ROOT/'build/lesson-check-real-20261015-3/private-final-model-records.json').read_text(encoding='utf-8'))
    audit=previous[3]
    cases=[('short_off','none',simple_system,simple_user,False,('software','direct')),
           ('short_high','high',simple_system,simple_user,False,('direct','software')),
           ('audit_high','high',audit['system'],audit['user'],True,('software','direct'))]
    results=[]
    config={'model':'deepseek-flash','mode':mode,'paired_requests':True,'same_body_within_pair':True,
        'sequential':True,'tools':False,'history':False,'provider_usage_requested':True,
        'production_data_modified':False,'attempt_timeout_s':240,'planned_requests':6,
        'proxy_environment_present':any(os.environ.get(key) for key in ('HTTPS_PROXY','HTTP_PROXY','ALL_PROXY')),
        'source_hashes':{path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in (
            'studyforge/ai.py','studyforge/deepseek_protocol.py','studyforge/scheduling.py')}}
    (folder/'configuration.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    for case,effort,system,user,json_mode,arms in cases:
        base=cls('deepseek-flash',effort=effort)
        body=base.prepare_body({'model':base.model,'messages':[{'role':'system','content':system+CONTEXT_BOUNDARY},
            {'role':'user','content':user}],'stream':True})
        if json_mode:body['response_format']={'type':'json_object'}
        expected=None
        try:
            for arm in arms:
                job=create_job(project['id'],'speed_probe',{'case':case,'arm':arm})
                row={'case':case,'arm':arm,'job_id':job,'effort':effort};before=len(base.traces);start=time.perf_counter()
                try:
                    async with execution_scope(job_id=job,project_id=project['id'],label='模型速度诊断'):
                        value=await asyncio.wait_for(native(base,system,user,json_mode) if arm=='software' else direct(base,body),240)
                    row.update(status='completed',**value);update_job(job,'completed',100,{})
                except BaseException as exc:
                    row.update(status='failed',error_type=type(exc).__name__);update_job(job,'failed',0,{},error=type(exc).__name__)
                    if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
                row['wall_s']=time.perf_counter()-start
                row['http_attempts']=[metrics.public() for metrics in base.traces[before:]]
                row['scheduler_spans']=many('SELECT resource,duration_ms,queued_at,started_at,status FROM execution_spans WHERE job_id=?',(job,))
                if row['http_attempts']:
                    hashes={value['body_sha256'] for value in row['http_attempts']}
                    if expected is None:expected=hashes
                    row['same_body_as_paired_request']=hashes==expected
                results.append(row)
                (folder/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({'case':case,'arm':arm,'status':row['status'],'wall_s':round(row['wall_s'],3),
                    'attempts':len(row['http_attempts']),
                    'first_content_s':row['http_attempts'][-1]['first_content_s'] if row['http_attempts'] else None,
                    'usage':row['http_attempts'][-1]['usage'] if row['http_attempts'] else {}},ensure_ascii=True),flush=True)
        finally:await base.close()


async def connection_probe(name):
    """Four fresh connections, counterbalanced order, one identical short body."""
    folder=ROOT/'build'/name
    if (folder/'results.json').exists():raise SystemExit('Use a new folder; preserve earlier observations.')
    folder.mkdir(parents=True,exist_ok=True)
    os.environ['STUDYFORGE_DATA_DIR']=str(folder/'data')
    os.environ['STUDYFORGE_SEMANTIC_MODEL_DIR']=str(folder/'isolated-model')
    from studyforge import ai
    from studyforge.db import create_project,create_job,update_job,many
    from studyforge.scheduling import execution_scope
    from studyforge.dialogue_scope import CONTEXT_BOUNDARY
    cls=traced_class();project=create_project('隔离连接速度对照');results=[]
    system='你是一位清晰、严谨的数学老师。只回答当前疑问，不出题。'
    user='为什么证明收敛数列极限唯一时，可以取ε=(b-a)/2？请先指出取值的合法性，再用两个开区间解释，最后说明更小正数是否也可用。请控制在350个汉字以内。'
    modes=('system','direct','direct','system')
    (folder/'configuration.json').write_text(json.dumps({'model':'deepseek-flash','effort':'none',
        'fresh_connection_every_sample':True,'order':modes,'planned_requests':4,'production_data_modified':False,
        'proxy_environment_present':any(os.environ.get(key) for key in ('HTTPS_PROXY','HTTP_PROXY','ALL_PROXY'))},indent=2),encoding='utf-8')
    expected=None
    for index,mode in enumerate(modes):
        ai.save_settings({'api_connection_mode':mode,'background_learning_enabled':False,'agent_tools_enabled':False,'model_concurrency':2})
        client=cls('deepseek-flash',effort='none');body=client.prepare_body({'model':client.model,
            'messages':[{'role':'system','content':system+CONTEXT_BOUNDARY},{'role':'user','content':user}],'stream':True})
        job=create_job(project['id'],'speed_probe',{'mode':mode});row={'sample':index+1,'mode':mode,'job_id':job}
        start=time.perf_counter()
        try:
            async with execution_scope(job_id=job,project_id=project['id'],label='连接方式对照'):
                row.update(await asyncio.wait_for(direct(client,body),90))
            row['status']='completed';update_job(job,'completed',100,{})
        except BaseException as exc:
            row.update(status='failed',error_type=type(exc).__name__);update_job(job,'failed',0,{},error=type(exc).__name__)
            if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
        finally:await client.close()
        row['wall_s']=time.perf_counter()-start;row['http_attempts']=[value.public() for value in client.traces]
        row['scheduler_spans']=many('SELECT resource,duration_ms,queued_at,started_at,status FROM execution_spans WHERE job_id=?',(job,))
        if row['http_attempts']:
            hashes={value['body_sha256'] for value in row['http_attempts']}
            if expected is None:expected=hashes
            row['same_body_as_other_samples']=hashes==expected
        results.append(row);(folder/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'sample':index+1,'mode':mode,'status':row['status'],'wall_s':round(row['wall_s'],3),
            'headers_s':row['http_attempts'][-1]['headers_s'] if row['http_attempts'] else None},ensure_ascii=True),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder');parser.add_argument('--mode',choices=('system','direct'),default='system')
    parser.add_argument('--connection-probe',action='store_true')
    args=parser.parse_args();asyncio.run(connection_probe(args.folder) if args.connection_probe else main(args.folder,args.mode))
