#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import signal
import subprocess
import sys
from datetime import datetime

import aiohttp
from aiohttp import web
from cryptography.fernet import Fernet

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)
os.chdir(APP_ROOT)

from services.proxy_control import load_disabled  # noqa: E402

CONFIG_DIR = os.path.join(APP_ROOT, 'config')
SECRET_KEY_PATH = os.path.join(CONFIG_DIR, 'secret_key')
PID_PATH = os.path.join(CONFIG_DIR, 'nagios-proxy.pid')
ENCRYPTED_MARKER = '__ENC__'
PROXY_PORT_OFFSET = 1000
RELOAD_INTERVAL = 30
UPSTREAM_TIMEOUT = 30
CHUNK_SIZE = 65536
BIND_HOST = os.environ.get('NAGIOS_PROXY_BIND', '0.0.0.0')

SKIP_REQUEST_HEADERS = {
    'host',
    'accept-encoding',
    'x-auth-user',
    'x-auth-pass',
    'authorization',
    'connection',
    'keep-alive',
    'proxy-authenticate',
    'proxy-authorization',
    'te',
    'trailers',
    'upgrade',
    'transfer-encoding',
}
HOP_BY_HOP_HEADERS = {
    'content-encoding',
    'content-length',
    'transfer-encoding',
    'connection',
    'keep-alive',
    'proxy-authenticate',
    'proxy-authorization',
    'te',
    'trailers',
    'upgrade',
}

_fernet: Fernet | None = None
_creds_cache: dict[str, tuple[float, str | None]] = {}
_sites: dict[int, web.TCPSite] = {}
_backends: dict[int, tuple[str, str]] = {}
_runner: web.AppRunner | None = None
_client: aiohttp.ClientSession | None = None
_reload_event: asyncio.Event | None = None
_shutdown_event: asyncio.Event | None = None


def log(message: str) -> None:
    print(f'[{datetime.now().isoformat(timespec="seconds")}] {message}', flush=True)


def _init_fernet() -> Fernet | None:
    global _fernet
    if _fernet is not None:
        return _fernet
    if not os.path.exists(SECRET_KEY_PATH):
        return None
    try:
        with open(SECRET_KEY_PATH) as f:
            secret_key = f.read().strip()
        key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
        _fernet = Fernet(key)
    except Exception:
        _fernet = None
    return _fernet


def _decrypt_maybe(value: object) -> str:
    if not isinstance(value, str) or not value:
        return ''
    if not value.startswith(ENCRYPTED_MARKER):
        return value
    fernet = _init_fernet()
    if fernet is None:
        return ''
    try:
        return fernet.decrypt(value[len(ENCRYPTED_MARKER):].encode()).decode()
    except Exception:
        return ''


def _load_json(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def discover_running_ports() -> dict[str, str]:
    try:
        result = subprocess.run(
            ['docker', 'ps', '--filter', 'ancestor=nagios-ldap:latest',
             '--format', '{{.Names}}:{{.Ports}}'],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    ports: dict[str, str] = {}
    if not result.stdout.strip():
        return ports
    for line in result.stdout.strip().split('\n'):
        if ':' not in line:
            continue
        name, port_info = line.split(':', 1)
        if '->' not in port_info:
            continue
        try:
            ports[name] = port_info.split(':')[1].split('->')[0]
        except IndexError:
            continue
    return ports


def _auth_header_from_file(container: str) -> str | None:
    path = os.path.join(CONFIG_DIR, f'nagios_creds_{container}.json')
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _creds_cache.pop(container, None)
        return None
    cached = _creds_cache.get(container)
    if cached and cached[0] == mtime:
        return cached[1]
    data = _load_json(path)
    header = None
    if isinstance(data, dict):
        username = _decrypt_maybe(data.get('username'))
        password = _decrypt_maybe(data.get('password'))
        if username and password:
            token = base64.b64encode(f'{username}:{password}'.encode()).decode()
            header = f'Basic {token}'
    _creds_cache[container] = (mtime, header)
    return header


def _store_creds(container: str, username: str, password: str) -> None:
    path = os.path.join(CONFIG_DIR, f'nagios_creds_{container}.json')
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        data = {'username': username, 'password': password}
        fernet = _init_fernet()
        if fernet:
            data = {
                k: ENCRYPTED_MARKER + fernet.encrypt(v.encode()).decode()
                for k, v in data.items()
            }
        tmp = path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(data, f)
        os.replace(tmp, path)
        _creds_cache.pop(container, None)
    except (OSError, ValueError):
        pass


def _rewrite_location(value: str, nagios_port: str, public_host: str) -> str:
    prefixes = (
        f'http://127.0.0.1:{nagios_port}',
        f'http://localhost:{nagios_port}',
        f'https://127.0.0.1:{nagios_port}',
        f'https://localhost:{nagios_port}',
    )
    for prefix in prefixes:
        if value.startswith(prefix):
            scheme = 'https' if prefix.startswith('https://') else 'http'
            return f'{scheme}://{public_host}' + value[len(prefix):]
    return value


def build_target_url(path: str, query: str, nagios_port: str) -> str:
    base = f'http://127.0.0.1:{nagios_port}'
    clean = path.lstrip('/')
    if clean.startswith('nagios/'):
        clean = clean[len('nagios/'):]
    if clean.startswith('cgi-bin/'):
        target = f'{base}/{clean}'
    else:
        target = f'{base}/nagios/{clean}'
    if query:
        target += '?' + query
    return target


def _local_port(request: web.Request) -> int | None:
    transport = request.transport
    if transport is None:
        return None
    sockname = transport.get_extra_info('sockname')
    if not sockname or len(sockname) < 2:
        return None
    try:
        return int(sockname[1])
    except (TypeError, ValueError):
        return None


async def handle_proxy(request: web.Request) -> web.StreamResponse:
    port = _local_port(request)
    if port is None:
        return web.Response(status=500, text='Proxy Error')
    backend = _backends.get(port)
    if backend is None:
        return web.Response(status=404, text='Unknown proxy port')
    container, nagios_port = backend

    username = request.headers.get('X-Auth-User')
    password = request.headers.get('X-Auth-Pass')
    if username and password:
        await asyncio.get_running_loop().run_in_executor(
            None, _store_creds, container, username, password,
        )
        token = base64.b64encode(f'{username}:{password}'.encode()).decode()
        auth_header = f'Basic {token}'
    else:
        auth_header = _auth_header_from_file(container)
    if not auth_header:
        return web.Response(status=401, text='No credentials configured for this Nagios server')

    path = request.match_info.get('path', '')
    query = request.query_string or ''
    target_url = build_target_url(path, query, nagios_port)

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in SKIP_REQUEST_HEADERS
    }
    headers['Authorization'] = auth_header
    public_host = request.headers.get('Host') or request.host
    if public_host:
        headers['Host'] = public_host

    client: aiohttp.ClientSession = request.app['client']
    body = request.content if request.method not in ('GET', 'HEAD') else None
    try:
        async with client.request(
            request.method,
            target_url,
            headers=headers,
            data=body,
            allow_redirects=False,
        ) as resp:
            out_headers = []
            for key, value in resp.headers.items():
                if key.lower() in HOP_BY_HOP_HEADERS:
                    continue
                if key.lower() == 'location':
                    value = _rewrite_location(value, nagios_port, public_host)
                out_headers.append((key, value))
            response = web.StreamResponse(status=resp.status, headers=out_headers)
            await response.prepare(request)
            async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                await response.write(chunk)
            await response.write_eof()
            return response
    except asyncio.TimeoutError:
        log(f'Timeout proxying {request.method} {target_url}')
        return web.Response(status=504, text='Proxy Error')
    except aiohttp.ClientError:
        log(f'Upstream error proxying {request.method} {target_url}')
        return web.Response(status=502, text='Proxy Error')
    except Exception:
        log(f'Proxy error for {container} {request.method} {target_url}')
        return web.Response(status=500, text='Proxy Error')


async def reload_sites() -> None:
    if _runner is None:
        return
    loop = asyncio.get_running_loop()
    running = await loop.run_in_executor(None, discover_running_ports)
    disabled = await loop.run_in_executor(None, load_disabled)

    desired: dict[int, tuple[str, str]] = {}
    for name, nagios_port in running.items():
        if name in disabled:
            continue
        try:
            proxy_port = PROXY_PORT_OFFSET + int(nagios_port)
        except ValueError:
            continue
        desired[proxy_port] = (name, nagios_port)

    for port in list(_sites):
        if port in desired and _backends.get(port) == desired[port]:
            continue
        name = _backends.get(port, ('?', ''))[0]
        log(f'Unbinding :{port} ({name})')
        try:
            await _sites[port].stop()
        except Exception as exc:
            log(f'Error unbinding :{port}: {exc}')
        _sites.pop(port, None)
        _backends.pop(port, None)

    for port, info in desired.items():
        if port in _sites:
            continue
        name, nagios_port = info
        site = web.TCPSite(_runner, BIND_HOST, port, reuse_address=True)
        try:
            await site.start()
        except OSError as exc:
            log(f'Failed to bind :{port} for {name}: {exc}')
            continue
        _sites[port] = site
        _backends[port] = info
        log(f'Listening on {BIND_HOST}:{port} -> {name}:{nagios_port}')

    if not desired:
        log('No Nagios proxy ports to bind')


def _write_pid() -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(PID_PATH, 'w') as f:
            f.write(str(os.getpid()))
    except OSError:
        pass


def _clear_pid() -> None:
    try:
        if os.path.exists(PID_PATH):
            with open(PID_PATH) as f:
                stored = f.read().strip()
            if stored == str(os.getpid()):
                os.remove(PID_PATH)
    except OSError:
        pass


async def main() -> None:
    global _runner, _client, _reload_event, _shutdown_event

    _write_pid()
    _reload_event = asyncio.Event()
    _shutdown_event = asyncio.Event()

    timeout = aiohttp.ClientTimeout(total=UPSTREAM_TIMEOUT, sock_connect=5)
    connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=60, force_close=False)
    _client = aiohttp.ClientSession(timeout=timeout, connector=connector)

    app = web.Application()
    app['client'] = _client
    app.router.add_route('*', '/', handle_proxy)
    app.router.add_route('*', '/{path:.*}', handle_proxy)

    _runner = web.AppRunner(app, access_log=None)
    await _runner.setup()

    loop = asyncio.get_running_loop()

    def _sighup() -> None:
        if _reload_event is not None:
            _reload_event.set()

    def _sigterm() -> None:
        if _shutdown_event is not None:
            _shutdown_event.set()
        if _reload_event is not None:
            _reload_event.set()

    for sig, handler in ((signal.SIGHUP, _sighup), (signal.SIGTERM, _sigterm), (signal.SIGINT, _sigterm)):
        try:
            loop.add_signal_handler(sig, handler)
        except NotImplementedError:
            signal.signal(sig, lambda *_args, h=handler: h())

    log(f'Nagios iframe proxy multiplexer starting (pid {os.getpid()})')
    await reload_sites()

    while not _shutdown_event.is_set():
        _reload_event.clear()
        try:
            await asyncio.wait_for(_reload_event.wait(), timeout=RELOAD_INTERVAL)
            if _shutdown_event.is_set():
                break
            log('SIGHUP received — reloading port mappings')
        except asyncio.TimeoutError:
            pass
        if _shutdown_event.is_set():
            break
        await reload_sites()

    log('Shutting down proxy multiplexer')
    for port, site in list(_sites.items()):
        try:
            await site.stop()
        except Exception:
            pass
        _sites.pop(port, None)
        _backends.pop(port, None)
    await _runner.cleanup()
    await _client.close()
    _clear_pid()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
