"""Explicit API routing choice; never silently bypass a user's proxy."""
from __future__ import annotations

import os
import ssl

MODES = {'system', 'direct'}


def connection_mode() -> str:
    from .ai import settings
    mode = settings().get('api_connection_mode', 'system')
    if not isinstance(mode,str) or mode not in MODES: raise ValueError('API连接方式须为沿用环境配置或直接连接')
    return mode


def http_options(mode: str | None = None) -> dict:
    mode = connection_mode() if mode is None else mode
    if not isinstance(mode,str) or mode not in MODES: raise ValueError('API连接方式须为沿用环境配置或直接连接')
    if mode == 'system': return {'trust_env': True}
    # Disabling environment proxy discovery must not disable TLS validation or
    # discard explicitly configured CA files/directories.
    cafile, capath = os.environ.get('SSL_CERT_FILE'), os.environ.get('SSL_CERT_DIR')
    verify = ssl.create_default_context(cafile=cafile or None, capath=capath or None) if cafile or capath else True
    return {'trust_env': False, 'verify': verify}
