"""Error help is a public static asset; it must not expand phone API access."""
from pathlib import Path
import asyncio
from fastapi.testclient import TestClient
from studyforge import server
from studyforge.mobile_access import MobileManager
from fastapi import FastAPI,HTTPException
from tests.test_mobile_access import pair


def test_error_help_loads_before_pairing_but_no_new_data_endpoint_is_opened():
    manager=MobileManager(server.app);manager.addresses=['127.0.0.1']
    with TestClient(manager.gateway,base_url='https://127.0.0.1',client=('127.0.0.1',14000)) as client:
        for name in ['operation_errors.js','operation_errors.css']:
            response=client.get('/'+name);assert response.status_code==200
            assert len(response.content)>500
        response=client.get('/api/projects')
        assert response.status_code==401 and response.headers['X-StudyForge-Mobile-Session']=='required'
        for path in ['/operation_errors.py','/desktop/operation_errors.js','/../studyforge/server.py']:
            assert client.get(path).status_code==404


def test_desktop_and_mobile_share_error_explanations_and_phone_updates_shell():
    root=Path(__file__).resolve().parents[1]
    for name in ['web/index.html','web/mobile/index.html']:
        source=(root/name).read_text(encoding='utf-8')
        assert '/operation_errors.js' in source and '/operation_errors.css' in source
    worker=(root/'web/mobile/sw.js').read_text(encoding='utf-8')
    assert 'studyforge-mobile-shell-v90' in worker
    assert "'/operation_errors.js'" in worker and "'/operation_errors.css'" in worker
    assert '/api/jobs' not in worker


def test_provider_401_is_not_reported_as_phone_session_expiry():
    desktop=FastAPI()
    model_path='/api/providers/svc_'+'e'*32+'/models'
    @desktop.get(model_path)
    def rejected_model():raise HTTPException(401,'invalid_api_key')
    manager=MobileManager(desktop);manager.addresses=['127.0.0.1']
    with TestClient(manager.gateway,base_url='https://127.0.0.1',client=('127.0.0.1',14000)) as client:
        assert client.get(model_path).headers['X-StudyForge-Mobile-Session']=='required'
        pair(manager,client)
        response=client.get(model_path)
        assert response.status_code==401 and response.json()['detail']=='invalid_api_key'
        assert 'X-StudyForge-Mobile-Session' not in response.headers
        assert client.get('/mobile/session').status_code==200


def test_a_revoked_phone_still_gets_explicit_repairing_instructions():
    manager=MobileManager(server.app);manager.addresses=['127.0.0.1']
    with TestClient(manager.gateway,base_url='https://127.0.0.1',client=('127.0.0.1',14000)) as client:
        device_id=pair(manager,client);asyncio.run(manager.revoke(device_id))
        response=client.get('/mobile/session')
        assert response.status_code==401 and response.headers['X-StudyForge-Mobile-Session']=='expired'
        assert '重新配对' in response.json()['detail']
