"""Read the installed Tailscale client's own address; never change its account."""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess


def tailnet_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        return address.version == 4 and address in ipaddress.ip_network('100.64.0.0/10')
    except (ValueError, TypeError):
        return False


def executable() -> str | None:
    if os.name != 'nt':
        return shutil.which('tailscale')
    # Do not execute a lookalike in the working directory or on an arbitrary PATH.
    for name in ('ProgramW6432', 'ProgramFiles', 'ProgramFiles(x86)'):
        root = Path(os.environ.get(name, 'C:/Program Files'))
        if root.is_absolute():
            candidate = root / 'Tailscale' / 'tailscale.exe'
            if candidate.is_file():
                return str(candidate)
    return None


def normalize_status(raw: dict) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get('Self') or {}, dict):
        raise ValueError('连接状态格式无效')
    state = raw.get('BackendState', 'Unknown')
    node = raw.get('Self') or {}
    addresses = [value for value in node.get('TailscaleIPs', []) if tailnet_address(value)]
    expired = bool(node.get('Expired') or node.get('KeyExpired'))
    connected = state == 'Running' and node.get('Online') is True and not expired and bool(addresses)
    labels = {'NeedsLogin': '请在 Tailscale 中登录', 'NeedsMachineAuth': '请在 Tailscale 账户中批准这台电脑',
              'Stopped': '请打开 Tailscale 连接', 'NoState': 'Tailscale 尚未完成设置'}
    return {'installed': True, 'connected': connected, 'state': state, 'addresses': addresses if connected else [],
            'message': '固定私人地址已就绪' if connected else ('Tailscale 设备登录已过期，请重新登录' if expired else labels.get(state, 'Tailscale 暂未连接')),
            'key_expires': node.get('KeyExpiry'),
            'health': [str(value)[:500] for value in raw.get('Health') or [] if isinstance(value, str)][:4]}


def read_status() -> dict:
    command = executable()
    if not command:
        return {'installed': False, 'connected': False, 'state': 'NotInstalled', 'addresses': [],
                'message': '电脑尚未安装 Tailscale'}
    try:
        result = subprocess.run([command, 'status', '--json'], capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=4,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if not result.stdout.strip():
            raise ValueError('没有返回连接状态')
        return normalize_status(json.loads(result.stdout))
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return {'installed': True, 'connected': False, 'state': 'Unavailable', 'addresses': [],
                'message': '无法读取 Tailscale 状态，请确认它已启动并登录'}
