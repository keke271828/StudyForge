"""Exercise the installed Tailscale address using isolated data and a spare port.

The production app, port, account and learning files are not changed.
"""
import asyncio
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import urllib.error
import urllib.request
import uuid


def main():
    root = Path(__file__).resolve().parent.parent
    run = root / 'build' / ('private-connection-' + uuid.uuid4().hex)
    run.mkdir(parents=True)
    os.environ['STUDYFORGE_DATA_DIR'] = str(run / 'data')
    sys.path.insert(0, str(root))
    from studyforge import server
    from studyforge.mobile_access import MobileManager, StartIn
    from studyforge import mobile_network
    read_status = mobile_network.read_status
    status = read_status()
    if not status['connected']:
        raise RuntimeError('This check needs the computer Tailscale client to be connected')
    address = status['addresses'][0]
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    report = {'address': address, 'isolated_data': str(run / 'data'), 'checks': []}

    async def check():
        manager = MobileManager(server.app)
        try:
            mobile_network.read_status = lambda: {'installed': True, 'connected': False, 'addresses': [], 'state': 'Stopped', 'message': 'fixture delayed connection'}
            try:
                result = await manager.start(StartIn(addresses=['127.0.0.1'], port=port,
                    enable_tailscale=True, auto_start=True, remember_days=365))
            finally:
                mobile_network.read_status = read_status
            assert result['preferred_address'] is None
            await manager.refresh_network(force=True)
            result = manager.status()
            assert result['preferred_address'] == address and address in result['addresses']
            report['checks'].append('late Tailscale connection adds its address without stopping the server')
            context = ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(Path(manager.tls['ca']).read_bytes()))
            cookies = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                urllib.request.HTTPSHandler(context=context), urllib.request.HTTPCookieProcessor(cookies))
            url = f'https://{address}:{port}'
            def request(path, payload=None, headers=None):
                headers = dict(headers or {})
                if payload is not None:
                    headers['Content-Type'] = 'application/json'
                value = urllib.request.Request(url + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
                with opener.open(value, timeout=8) as response:
                    body = response.read()
                    return response.status, body
            code, page = await asyncio.to_thread(request, '/')
            assert code == 200 and b'StudyForge' in page
            report['checks'].append('real Tailscale IP HTTPS with CA verification')
            _, data = await asyncio.to_thread(request, '/mobile/pair', {'code': manager.code, 'name': 'isolated-private-network-check'})
            device = json.loads(data)
            manager.decide(device['device_id'], True)
            _, data = await asyncio.to_thread(request, '/mobile/pair/' + device['device_id'],
                                            headers={'X-Mobile-Pair-Ticket': device['ticket']})
            assert json.loads(data)['status'] == 'active'
            code, data = await asyncio.to_thread(request, '/mobile/session')
            assert code == 200 and json.loads(data)['remember_days'] == 365
            report['checks'].append('one pairing, authenticated HTTPS without scanning again')
            original_ca = Path(manager.tls['ca']).read_bytes()
            from datetime import datetime, timedelta, timezone
            manager.tls['expires_at'] = (datetime.now(timezone.utc) + timedelta(days=6)).isoformat()
            await manager.refresh_certificate()
            assert Path(manager.tls['ca']).read_bytes() == original_ca
            code, data = await asyncio.to_thread(request, '/mobile/session')
            assert code == 200 and json.loads(data)['device']['id'] == device['device_id']
            report['checks'].append('leaf certificate renews without replacing the CA or losing pairing')
            await manager.stop(shutdown=True)
            replacement = MobileManager(server.app)
            manager = replacement
            await manager.restore()
            assert manager.status()['preferred_address'] == address
            code, data = await asyncio.to_thread(request, '/mobile/session')
            assert code == 200 and json.loads(data)['device']['id'] == device['device_id']
            report['checks'].append('automatic startup and same device cookie after full server restart')
            await manager.revoke(device['device_id'])
            try:
                await asyncio.to_thread(request, '/mobile/session')
            except urllib.error.HTTPError as error:
                assert error.code == 401
            else:
                raise AssertionError('Revoked device was accepted')
            report['checks'].append('revocation immediately blocks the remembered device')
            report['passed'] = True
        finally:
            await manager.stop(shutdown=True)
            (run / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    asyncio.run(check())
    print('PRIVATE_CONNECTION_PASS ' + str(run))


if __name__ == '__main__':
    main()
