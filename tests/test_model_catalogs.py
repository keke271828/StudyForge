import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from studyforge import ai, server, model_catalog, deepseek_catalog
from studyforge.codex_bridge import CodexBridge


@pytest.fixture(autouse=True)
def reset_catalogs(monkeypatch):
    monkeypatch.setattr(model_catalog, '_cache', None)
    monkeypatch.setattr(model_catalog, '_cache_scope', None)
    monkeypatch.setattr(deepseek_catalog, '_cache', None)


def test_codex_paginates_all_visible_models_and_uses_callable_model_ids(monkeypatch):
    calls = []
    async def start(self): pass
    async def request(self, method, params):
        calls.append((method, params))
        if 'cursor' not in params:
            return {'data': [{'id':'picker-id', 'model':'gpt-6.1-sol', 'displayName':'Sol',
                'supportedReasoningEfforts':[{'reasoningEffort':'low'}, {'reasoningEffort':'ultra'}]}], 'nextCursor':'page2'}
        return {'data':[{'id':'gpt-6-astra', 'supportedReasoningEfforts':['high', 'max']}], 'nextCursor':None}
    monkeypatch.setattr(CodexBridge, 'start', start)
    monkeypatch.setattr(CodexBridge, 'request', request)
    raw = asyncio.run(CodexBridge().list_models())
    models = model_catalog._normalize(raw)
    assert [row['id'] for row in models] == ['gpt-6.1-sol', 'gpt-6-astra']
    assert models[0]['efforts'] == ['low','ultra'] and models[1]['efforts'] == ['high','max']
    assert calls == [('model/list', {'limit':50,'includeHidden':False}),
                     ('model/list', {'limit':50,'includeHidden':False,'cursor':'page2'})]


@pytest.mark.parametrize('reply', [{'data':{},'nextCursor':None}, {'data':[], 'nextCursor':'loop'}])
def test_invalid_or_repeated_codex_pages_fail_instead_of_silently_truncating(monkeypatch, reply):
    async def start(self): pass
    async def request(self, method, params): return reply
    monkeypatch.setattr(CodexBridge, 'start', start)
    monkeypatch.setattr(CodexBridge, 'request', request)
    with pytest.raises(RuntimeError, match='目录|分页'):
        asyncio.run(CodexBridge().list_models())


def test_codex_normalization_keeps_capabilities_and_filters_hidden_duplicates():
    raw = [None, {'model':'hidden', 'hidden':True}, {'model':'private', 'visibility':'hide'},
           {'model':'one','supportedReasoningEfforts':['minimal','high','high','made-up',{}], 'isDefault':True},
           {'id':'another-picker-id','model':'one'}, {'slug':'two','supported_reasoning_levels':[{'effort':'none'}]}]
    result = model_catalog._normalize(raw)
    assert [row['id'] for row in result] == ['one','two']
    assert result[0]['efforts'] == ['minimal','high'] and result[0]['is_default']
    assert result[1]['efforts'] == ['none']


def test_codex_refresh_failure_preserves_previous_live_catalog(monkeypatch):
    calls = []
    async def listed(self):
        calls.append(1)
        if len(calls)>1: raise RuntimeError('offline')
        return [{'id':'gpt-6.1-sol','supportedReasoningEfforts':[{'reasoningEffort':'high'}]}]
    async def bundled(): pytest.fail('Do not replace live list with a reduced bundled list')
    monkeypatch.setattr(CodexBridge, 'list_models', listed)
    monkeypatch.setattr(model_catalog, '_bundled_models', bundled)
    first = asyncio.run(model_catalog.get_models(True))
    second = asyncio.run(model_catalog.get_models(True))
    assert second['models'] == first['models'] and second['source'] == 'cached'
    assert '上次' in second['warning']


def test_codex_cache_is_invalidated_when_local_configuration_changes(monkeypatch, tmp_path):
    home = tmp_path/'codex'; home.mkdir(); monkeypatch.setenv('CODEX_HOME', str(home))
    calls = []
    async def listed(self): calls.append(1); return [{'id':f'model-{len(calls)}'}]
    monkeypatch.setattr(CodexBridge, 'list_models', listed)
    assert asyncio.run(model_catalog.get_models())['models'][0]['id'] == 'model-1'
    assert asyncio.run(model_catalog.get_models())['models'][0]['id'] == 'model-1'
    (home/'config.toml').write_text('model_provider="custom"', encoding='utf-8')
    assert asyncio.run(model_catalog.get_models())['models'][0]['id'] == 'model-2'


def test_bundled_probe_uses_resolved_windows_binary(monkeypatch):
    monkeypatch.setattr(model_catalog, 'codex_executable', lambda:r'C:\codex\codex.exe')
    calls = []
    def run(args, **kwargs):
        calls.append((args,kwargs)); return SimpleNamespace(returncode=0, stdout=b'{"models":[{"slug":"one"}]}', stderr=b'')
    monkeypatch.setattr(model_catalog.subprocess, 'run', run)
    assert asyncio.run(model_catalog._bundled_models()) == [{'slug':'one'}]
    assert calls[0][0] == [r'C:\codex\codex.exe','debug','models','--bundled']


def mock_http(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(deepseek_catalog.httpx, 'AsyncClient', lambda *a,**kw:real(transport=httpx.MockTransport(handler)))


def test_deepseek_without_refresh_or_key_uses_documented_choices_without_network(monkeypatch):
    mock_http(monkeypatch, lambda req:pytest.fail('Automatic initialization must not contact API'))
    for force, key in [(False,None), (False,'test-key'), (True,None)]:
        result = asyncio.run(deepseek_catalog.get_models(force, api_key=key))
        assert result['source']=='documented' and result['inference_verified'] is False
        assert [row['id'] for row in result['models']] == ['deepseek-flash','deepseek-v4-pro','deepseek-v4-flash']
        assert '→ V4.1 Flash' in result['models'][2]['name']


def test_deepseek_refresh_only_requests_metadata_and_keeps_unknown_returned_models(monkeypatch):
    calls = []
    def reply(req):
        calls.append(req)
        return httpx.Response(200,json={'data':[{'id':'deepseek-flash'},{'id':'deepseek-v4-pro'},
                                                {'id':'private-deployment'},{'id':'private-deployment'},None]})
    mock_http(monkeypatch,reply)
    first = asyncio.run(deepseek_catalog.get_models(True, api_key='test-secret'))
    cached = asyncio.run(deepseek_catalog.get_models(False, api_key='test-secret'))
    assert cached == first and len(calls)==1 and calls[0].method=='GET'
    assert str(calls[0].url)=='https://api.deepseek.com/models' and not calls[0].content
    assert first['source']=='api' and first['listed_count']==3 and not first['inference_verified']
    assert first['models'][-1]['id']=='private-deployment' and first['models'][-1]['listed']
    assert 'test-secret' not in json.dumps(first) + repr(deepseek_catalog._cache)


@pytest.mark.parametrize('failure', ['401','403','timeout','connect','read','invalid','empty'])
def test_deepseek_failed_refresh_returns_clear_status_and_preserves_choices(monkeypatch,failure):
    def reply(req):
        if failure in ('401','403'): return httpx.Response(int(failure), json={'error':'secret must not leak'})
        if failure=='timeout': raise httpx.ReadTimeout('secret must not leak')
        if failure=='connect': raise httpx.ConnectError('secret must not leak')
        if failure=='read': raise httpx.ReadError('secret must not leak')
        return httpx.Response(200,json={'data':[]} if failure=='empty' else {'bad':123})
    mock_http(monkeypatch,reply)
    result = asyncio.run(deepseek_catalog.get_models(True, api_key='test-key'))
    assert result['source']=='documented' and result['warning'] and len(result['models'])==3
    assert 'secret must not leak' not in json.dumps(result) and 'test-key' not in json.dumps(result)


def test_deepseek_cached_catalog_is_not_shared_after_key_change(monkeypatch):
    calls=[]
    def reply(req):
        calls.append(req)
        if len(calls)>1: raise httpx.ConnectError('offline')
        return httpx.Response(200,json={'data':[{'id':'account-only-model'}]})
    mock_http(monkeypatch,reply)
    first=asyncio.run(deepseek_catalog.get_models(True,api_key='key-a'))
    same=asyncio.run(deepseek_catalog.get_models(True,api_key='key-a'))
    changed=asyncio.run(deepseek_catalog.get_models(True,api_key='key-b'))
    assert same['models']==first['models'] and same['source']=='cached'
    assert changed['source']=='documented' and all(row['id']!='account-only-model' for row in changed['models'])


def test_deepseek_route_does_not_require_or_probe_codex(monkeypatch):
    monkeypatch.setattr(server, 'get_secret', lambda name:None)
    async def forbidden(*a,**kw): pytest.fail('DeepSeek catalog must not require Codex')
    monkeypatch.setattr(model_catalog,'get_models',forbidden)
    result=TestClient(server.app).get('/api/deepseek/models?refresh=true')
    assert result.status_code==200 and result.json()['source']=='documented'


def test_model_preferences_survive_restart_and_default_upgrade_preserves_explicit_choice():
    assert ai.settings()['deepseek_model']=='deepseek-flash'
    ai.save_settings({'deepseek_model':'deepseek-v4-pro', 'chat_model_deepseek':'deepseek-flash',
                      'chat_model_codex':'gpt-6.1-sol','chat_effort_codex':'ultra'})
    config=TestClient(server.app).get('/api/settings').json()
    assert config['deepseek_model']=='deepseek-v4-pro' and config['chat_model_deepseek']=='deepseek-flash'
    assert config['chat_model_codex']=='gpt-6.1-sol' and config['chat_effort_codex']=='ultra'
    ai.save_settings({'chat_model_codex':'','chat_effort_codex':''})
    assert ai.settings()['chat_model_codex']=='' and ai.settings()['chat_effort_codex']==''


@pytest.mark.parametrize('value', [{'chat_model_codex':42}, {'chat_model_deepseek':'bad\nmodel'},
                                 {'chat_model_codex':'x'*121},{'chat_effort_codex':[]}, {'chat_effort_codex':'impossible'}])
def test_invalid_model_preferences_fail_without_overwriting_saved_settings(value):
    ai.save_settings({'deepseek_model':'chosen-model'})
    result=TestClient(server.app).put('/api/settings',json=value)
    assert result.status_code==400 and ai.settings()['deepseek_model']=='chosen-model'
