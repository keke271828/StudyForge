import asyncio
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from studyforge import server, mobile_network
from studyforge.db import execute, one
from studyforge.mobile_access import MobileManager, StartIn, ConnectionPreferences, COOKIE
from test_mobile_access import mobile_client, pair


def ready():
    return {'BackendState': 'Running', 'Self': {'Online': True,
            'TailscaleIPs': ['100.83.42.9', 'fd7a:115c:a1e0::1']}, 'Health': []}


def test_status_uses_only_connected_local_node_not_peers_or_public_addresses():
    raw = ready() | {'Peer': {'other': {'TailscaleIPs': ['100.100.1.1']}}, 'CurrentTailnet': {'Name': 'private-account'}}
    value = mobile_network.normalize_status(raw)
    assert value['connected'] and value['addresses'] == ['100.83.42.9']
    assert 'private-account' not in json.dumps(value) and '100.100.1.1' not in json.dumps(value)
    for changes in ({'BackendState': 'NeedsLogin'}, {'Self': {'Online': False, 'TailscaleIPs': ['100.83.42.9']}},
                    {'Self': {'Online': True, 'Expired': True, 'TailscaleIPs': ['100.83.42.9']}},
                    {'Self': {'Online': True, 'TailscaleIPs': ['8.8.8.8']}}):
        assert not mobile_network.normalize_status(raw | changes)['connected']
    assert not mobile_network.tailnet_address('100.63.255.255')
    assert mobile_network.tailnet_address('100.127.255.255')
    assert not mobile_network.tailnet_address('100.128.0.0')


def test_cli_is_read_only_bounded_and_handles_unavailable_state(monkeypatch):
    monkeypatch.setattr(mobile_network, 'executable', lambda: None)
    assert mobile_network.read_status()['state'] == 'NotInstalled'
    monkeypatch.setattr(mobile_network, 'executable', lambda: 'C:/Program Files/Tailscale/tailscale.exe')
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=json.dumps(ready()), returncode=0)
    monkeypatch.setattr(mobile_network.subprocess, 'run', run)
    assert mobile_network.read_status()['addresses'] == ['100.83.42.9']
    assert calls[0][0][1:] == ['status', '--json'] and calls[0][1]['timeout'] == 4
    monkeypatch.setattr(mobile_network.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout='[]'))
    assert mobile_network.read_status()['state'] == 'Unavailable'


def test_cgn_peer_requires_enabled_overlay_and_cannot_spoof_another_host():
    manager = MobileManager(server.app)
    manager.addresses = ['100.83.42.9']
    manager.tailnet = mobile_network.normalize_status(ready())
    client = TestClient(manager.gateway, base_url='https://100.83.42.9', client=('100.100.1.1', 15000))
    with client:
        assert client.get('/').status_code == 403
        manager.enable_tailscale = True
        assert client.get('/').status_code == 200
        assert client.get('/api/projects').status_code == 401
        pair(manager, client)
        assert client.get('/api/projects').status_code == 200
        assert client.post('/api/mobile/network-refresh').status_code == 403
        assert client.put('/api/mobile/preferences', json={'auto_start': True, 'remember_days': 365}).status_code == 403
        assert client.get('https://100.83.42.10/').status_code == 403
        manager.tailnet = {'addresses': []}
        assert client.get('/api/projects').status_code == 403
    with TestClient(manager.gateway, base_url='https://100.83.42.9', client=('8.8.8.8', 15000)) as outsider:
        manager.tailnet = mobile_network.normalize_status(ready())
        assert outsider.get('/').status_code == 403


def test_unverified_overlay_address_is_rejected_before_opening_a_listener(monkeypatch):
    monkeypatch.setattr(mobile_network, 'read_status', lambda: mobile_network.normalize_status(ready()))
    manager = MobileManager(server.app)
    with pytest.raises(ValueError):
        asyncio.run(manager.start(StartIn(addresses=['100.90.1.1'], enable_tailscale=True)))
    with pytest.raises(ValueError):
        asyncio.run(manager.start(StartIn(addresses=['100.83.42.9'], enable_tailscale=False)))
    assert manager.server is None


def test_remembered_device_renews_cookie_and_survives_server_restart():
    manager, client = mobile_client()
    with client:
        ident = pair(manager, client)
        token = client.cookies.get(COOKIE)
        expiry = datetime.fromisoformat(one('SELECT * FROM mobile_devices WHERE id=?', (ident,))['expires_at'])
        assert expiry > datetime.now(timezone.utc) + timedelta(days=364)
        execute('UPDATE mobile_devices SET expires_at=? WHERE id=?',
                ((datetime.now(timezone.utc) + timedelta(days=5)).isoformat(), ident))
        renewed = client.get('/mobile/session')
        assert renewed.status_code == 200 and 'Max-Age=31536000' in renewed.headers['set-cookie']
        assert client.cookies.get(COOKIE) == token
        assert 'set-cookie' not in client.get('/mobile/session').headers
        other, reopened = mobile_client()
        with reopened:
            reopened.cookies.update(client.cookies)
            assert reopened.get('/mobile/session').json()['device']['id'] == ident
            assert len(other.status()['devices']) == 1
            asyncio.run(other.revoke(ident))
        assert client.get('/mobile/session').status_code == 401


def test_shorter_remember_setting_takes_effect_and_expired_device_is_not_revived():
    manager, client = mobile_client()
    with client:
        ident = pair(manager, client)
        manager.save_preferences(ConnectionPreferences(auto_start=True, remember_days=30))
        response = client.get('/mobile/session')
        assert 'Max-Age=2592000' in response.headers['set-cookie']
        value = datetime.fromisoformat(response.json()['device']['expires_at'])
        assert datetime.now(timezone.utc) + timedelta(days=29) < value < datetime.now(timezone.utc) + timedelta(days=31)
        assert manager.config()['auto_start'] is True
        execute('UPDATE mobile_devices SET expires_at=? WHERE id=?',
                ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), ident))
        assert client.get('/mobile/session').status_code == 401
