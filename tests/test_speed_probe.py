"""Check diagnostic arithmetic, privacy, and identical native/raw requests."""
import asyncio
import json

import httpx
import pytest

from scripts.diagnose_deepseek_speed import PacketMetrics,direct,native,traced_class
from studyforge import ai


def body():return {'model':'probe-model','messages':[{'role':'user','content':'PRIVATE_INPUT_DO_NOT_SAVE'}],'stream':True}


def packet(delta,**more):return {'choices':[{'delta':delta,**more}]}


def test_usage_and_observed_windows_are_separate_from_total_latency():
    metrics=PacketMetrics(body());metrics.headers_s=.1
    metrics.observe(packet({'reasoning_content':'PRIVATE_REASONING_DO_NOT_SAVE'}),.2)
    metrics.observe(packet({'content':'a'}),.5)
    metrics.observe(packet({'content':'b'},finish_reason='stop'),1.5)
    metrics.observe({'choices':[],'usage':{'prompt_tokens':10,'completion_tokens':100,
        'completion_tokens_details':{'reasoning_tokens':60}}},1.6)
    metrics.end_s=1.7;result=metrics.public()
    assert result['visible_tokens_from_provider']==40 and result['visible_window_s']==1
    assert result['visible_receive_tokens_per_second']==40
    assert result['all_output_receive_tokens_per_second']==pytest.approx(100/1.3)
    assert result['first_reasoning_s']==.2 and result['first_content_s']==.5 and result['end_s']==1.7
    assert 'PRIVATE_' not in json.dumps(result)


def test_missing_reasoning_usage_is_unknown_and_not_silently_zero():
    metrics=PacketMetrics(body());metrics.observe(packet({'content':'a'}),1);metrics.observe(packet({'content':'b'}),2)
    metrics.observe({'choices':[],'usage':{'completion_tokens':2}},2.1)
    result=metrics.public()
    assert result['visible_tokens_from_provider'] is None and result['visible_receive_tokens_per_second'] is None
    assert result['all_output_receive_tokens_per_second']==2


def test_single_chunk_does_not_produce_an_infinite_throughput():
    metrics=PacketMetrics(body());metrics.observe(packet({'content':'entire answer'},finish_reason='stop'),5)
    metrics.observe({'choices':[],'usage':{'completion_tokens':10,'completion_tokens_details':{'reasoning_tokens':0}}},5)
    assert metrics.public()['visible_window_s'] is None
    assert metrics.public()['visible_receive_tokens_per_second'] is None
    assert metrics.public()['all_output_receive_tokens_per_second'] is None


@pytest.mark.parametrize('invalid',[True,-1,'10'])
def test_invalid_token_numbers_are_not_used_in_diagnostic_rates(invalid):
    metrics=PacketMetrics(body());metrics.observe({'choices':[],'usage':{'completion_tokens':invalid,
        'completion_tokens_details':{'reasoning_tokens':invalid}}},1)
    assert metrics.public()['usage']=={}


def test_native_and_raw_paths_send_identical_bodies_and_never_store_reasoning(monkeypatch):
    requests=[]
    def respond(request):
        requests.append(json.loads(request.content))
        packets=[packet({'reasoning_content':'PRIVATE_REASONING_DO_NOT_SAVE'}),packet({'content':'答案'},finish_reason='stop'),
            {'choices':[],'usage':{'prompt_tokens':3,'completion_tokens':10,'completion_tokens_details':{'reasoning_tokens':6}}}]
        return httpx.Response(200,text=''.join('data: '+json.dumps(value,ensure_ascii=False)+'\n\n' for value in packets)+'data: [DONE]\n\n',headers={'content-type':'text/event-stream'})
    monkeypatch.setattr(ai,'get_secret',lambda key:'PRIVATE_KEY_DO_NOT_SAVE')
    async def run():
        client=traced_class()('probe-model',effort='high')
        client._http=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            first=await native(client,'规则','PRIVATE_INPUT_DO_NOT_SAVE')
            second=await direct(client,client.request_bodies[0])
            assert first==second and requests[0]==requests[1]
            assert requests[0]['thinking']['type']=='enabled' and requests[0]['reasoning_effort']=='high'
            assert requests[0]['stream_options']=={'include_usage':True}
            traces=[value.public() for value in client.traces]
            assert len(traces)==2 and traces[0]['body_sha256']==traces[1]['body_sha256']
            assert all(value['usage']['reasoning_tokens']==6 and value['finish']=='stop' for value in traces)
            assert 'PRIVATE_' not in json.dumps(traces)
        finally:await client.close()
    asyncio.run(run())


def test_failed_http_request_is_preserved_as_failed_timing_without_credential_text(monkeypatch):
    monkeypatch.setattr(ai,'get_secret',lambda key:'PRIVATE_KEY_DO_NOT_SAVE')
    async def run():
        client=traced_class()('probe-model',effort='none')
        client._http=httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(401,json={'error':'PRIVATE_ERROR'})))
        try:
            with pytest.raises(httpx.HTTPStatusError):await direct(client,body())
            record=client.traces[0].public()
            assert record['error']=='HTTPStatusError' and record['status']==401 and record['end_s'] is not None
            assert record['usage']=={} and 'PRIVATE_' not in json.dumps(record)
        finally:await client.close()
    asyncio.run(run())
