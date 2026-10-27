import asyncio
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket

import certifi
import httpx
import pytest

from studyforge import ai, providers, deepseek_catalog, provider_clients
from studyforge.api_network import http_options
from studyforge.provider_clients import service_client


def test_default_preserves_environment_and_invalid_modes_do_not_save():
    assert ai.settings()['api_connection_mode']=='system'
    assert http_options()=={'trust_env':True}
    for bad in ('auto',None,True,[],{}):
        with pytest.raises(ValueError): ai.save_settings({'api_connection_mode':bad})
        assert ai.settings()['api_connection_mode']=='system'
    for bad in ('auto',True,[],{}):
        with pytest.raises(ValueError): http_options(bad)


def test_direct_route_reaches_local_service_when_environment_proxy_is_unreachable(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(b'local-model-service')
        def log_message(self,*args):pass
    service=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=service.serve_forever,daemon=True);thread.start()
    with socket.socket() as unused:
        unused.bind(('127.0.0.1',0));proxy_port=unused.getsockname()[1]
    monkeypatch.setenv('HTTP_PROXY',f'http://127.0.0.1:{proxy_port}')
    monkeypatch.setenv('NO_PROXY','')
    monkeypatch.delenv('SSL_CERT_FILE',raising=False);monkeypatch.delenv('SSL_CERT_DIR',raising=False)
    async def run():
        url=f'http://127.0.0.1:{service.server_port}/models'
        async with httpx.AsyncClient(**http_options('system'),timeout=2) as client:
            with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):await client.get(url)
        async with httpx.AsyncClient(**http_options('direct'),timeout=2) as client:
            response=await client.get(url)
            assert response.status_code==200 and response.text=='local-model-service'
    try:asyncio.run(run())
    finally:service.shutdown();service.server_close();thread.join(2)


def test_direct_retains_explicit_ca_verification(monkeypatch):
    monkeypatch.setenv('SSL_CERT_FILE',certifi.where());monkeypatch.delenv('SSL_CERT_DIR',raising=False)
    options=http_options('direct')
    assert options['trust_env'] is False
    assert options['verify'].verify_mode==ssl.CERT_REQUIRED and options['verify'].check_hostname


@pytest.mark.parametrize('mode',['system','direct'])
def test_all_native_api_transports_and_catalogs_use_selected_route(monkeypatch,mode):
    ai.save_settings({'api_connection_mode':mode,'agent_tools_enabled':False})
    monkeypatch.setattr(ai,'get_secret',lambda key:'test-key')
    monkeypatch.setattr(provider_clients,'get_secret',lambda key:'test-key')
    monkeypatch.setattr(providers,'get_secret',lambda key:'test-key')
    for key in ('SSL_CERT_FILE','SSL_CERT_DIR'):monkeypatch.delenv(key,raising=False)
    calls=[];native=httpx.AsyncClient
    def respond(request):
        if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'deepseek-flash'}]})
        body=json.loads(request.content)
        if ':generateContent' in request.url.path:
            return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'完成'}]},'finishReason':'STOP'}]})
        if ':streamGenerateContent' in request.url.path:
            packet={'candidates':[{'content':{'parts':[{'text':'完成'}]},'finishReason':'STOP'}]}
            return httpx.Response(200,text='data: '+json.dumps(packet)+'\n\n')
        if body.get('stream'):
            return httpx.Response(200,text='data: '+json.dumps({'choices':[{'delta':{'content':'完成'},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
        return httpx.Response(200,json={'choices':[{'message':{'content':'完成'},'finish_reason':'stop'}]})
    def factory(*args,**kwargs):
        calls.append(kwargs.copy());return native(*args,**(kwargs|{'transport':httpx.MockTransport(respond)}))
    monkeypatch.setattr(httpx,'AsyncClient',factory)
    async def run():
        deep=ai.DeepSeekClient('deepseek-flash',effort='high')
        assert await deep.complete('要求','资料')=='完成'
        async for _ in deep.stream_packets({'model':deep.model,'messages':[],'stream':True}):pass
        await deep.close()
        for protocol in ('openai','gemini'):
            service=providers.save_service({'name':'route fixture','protocol':protocol,'base_url':'https://models.example/v1',
                'default_model':'fixture','models':['fixture'],'requires_key':False})
            client=service_client(service['id'],'fixture')
            assert await client.complete('要求','资料')=='完成'
            async for _ in client.stream_packets({'model':'fixture','messages':[],'stream':True}):pass
            await client.close()
        await deepseek_catalog.get_models(force=True,api_key='fixture-key')
        await providers.model_catalog(service['id'])
    asyncio.run(run())
    assert len(calls)>=7
    assert all(options.get('trust_env')==(mode=='system') for options in calls)
    if mode=='direct':assert all(options.get('verify') is True for options in calls)
