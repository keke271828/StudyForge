import httpx
import pytest
from fastapi.testclient import TestClient

from studyforge import server, update_transfer


@pytest.mark.parametrize('kind,asset,range_value', [
    ('https://evil.test', None, None), ('asset', 0, None), ('asset', -1, None),
    ('asset', True, None), ('latest', 123, None), ('latest', None, 'bytes=0-2'),
    ('asset', 123, 'bytes=0-9999999'), ('asset', 123, 'bytes=10-20')])
def test_only_fixed_public_release_endpoints_and_bounded_probe_ranges(kind, asset, range_value):
    with pytest.raises(ValueError):
        update_transfer.transfer_target(kind, asset, range_value)


def test_desktop_auth_is_required_before_update_network_access(monkeypatch):
    monkeypatch.setenv('STUDYFORGE_DESKTOP_TOKEN', 'owner')
    with TestClient(server.app) as client:
        response = client.get('/api/desktop/update-transfer?kind=latest')
    assert response.status_code == 403


def test_public_metadata_is_streamed_without_forwarding_local_credentials(monkeypatch):
    monkeypatch.setenv('STUDYFORGE_DESKTOP_TOKEN', 'owner')
    seen = []
    def transport(request):
        seen.append(request)
        assert request.url == update_transfer.BASE + '/latest'
        assert 'authorization' not in request.headers and 'x-studyforge-desktop-token' not in request.headers
        return httpx.Response(200, json={'tag_name': 'v0.0.1'}, request=request)
    original = httpx.AsyncClient
    def factory(**kwargs):
        kwargs.pop('proxy', None)
        kwargs['transport'] = httpx.MockTransport(transport)
        return original(**kwargs)
    monkeypatch.setattr(update_transfer.httpx, 'AsyncClient', factory)
    with TestClient(server.app) as client:
        response = client.get('/api/desktop/update-transfer?kind=latest', headers={'X-StudyForge-Desktop-Token': 'owner'})
    assert response.status_code == 200 and response.json()['tag_name'] == 'v0.0.1'
    assert len(seen) == 1 and response.headers['cache-control'] == 'no-store'


def test_asset_ranges_and_rate_limit_headers_survive_the_local_stream(monkeypatch):
    monkeypatch.setenv('STUDYFORGE_DESKTOP_TOKEN', 'owner')
    original = httpx.AsyncClient
    def transport(request):
        assert request.url == update_transfer.BASE + '/assets/123'
        assert request.headers['accept'] == 'application/octet-stream'
        assert request.headers['range'] == 'bytes=0-65535'
        return httpx.Response(206, content=b'MZ'+b'0'*65534, headers={'content-range': 'bytes 0-65535/1000000'}, request=request)
    def factory(**kwargs):
        kwargs.pop('proxy', None)
        kwargs['transport'] = httpx.MockTransport(transport)
        return original(**kwargs)
    monkeypatch.setattr(update_transfer.httpx, 'AsyncClient', factory)
    with TestClient(server.app) as client:
        response = client.get('/api/desktop/update-transfer?kind=asset&asset_id=123',
                              headers={'X-StudyForge-Desktop-Token': 'owner', 'Range': 'bytes=0-65535'})
    assert response.status_code == 206 and len(response.content) == 65536 and response.content[:2] == b'MZ'
    assert response.headers['content-range'] == 'bytes 0-65535/1000000'


def test_public_network_errors_are_recoverable_and_do_not_expose_environment(monkeypatch):
    monkeypatch.setenv('STUDYFORGE_DESKTOP_TOKEN', 'owner')
    original = httpx.AsyncClient
    def transport(request):
        raise httpx.ConnectError('private proxy details', request=request)
    def factory(**kwargs):
        kwargs.pop('proxy', None)
        kwargs['transport'] = httpx.MockTransport(transport)
        return original(**kwargs)
    monkeypatch.setattr(update_transfer.httpx, 'AsyncClient', factory)
    with TestClient(server.app) as client:
        response = client.get('/api/desktop/update-transfer?kind=latest', headers={'X-StudyForge-Desktop-Token': 'owner'})
    assert response.status_code == 502 and 'private proxy details' not in response.text


def test_transient_tls_errors_retry_with_fresh_clients_and_normal_certificate_checks(monkeypatch):
    import ssl
    monkeypatch.setenv('STUDYFORGE_DESKTOP_TOKEN', 'owner')
    original = httpx.AsyncClient
    attempts, clients = [], []
    def transport(request):
        attempts.append(request)
        if len(attempts) < 3:
            raise ssl.SSLError('temporary handshake failure')
        return httpx.Response(200, json={'tag_name': 'v0.0.1'}, request=request)
    def factory(**kwargs):
        assert kwargs.get('verify', True) is not False
        kwargs.pop('proxy', None)
        kwargs['transport'] = httpx.MockTransport(transport)
        client = original(**kwargs)
        clients.append(client)
        return client
    monkeypatch.setattr(update_transfer.httpx, 'AsyncClient', factory)
    with TestClient(server.app) as client:
        response = client.get('/api/desktop/update-transfer?kind=latest', headers={'X-StudyForge-Desktop-Token': 'owner'})
    assert response.status_code == 200 and len(attempts) == 3
    assert all(client.is_closed for client in clients)
