#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)
os.chdir(APP_ROOT)

from services.poller_db import (  # noqa: E402
    commit_successful_fetch,
    get_container_health,
    record_fetch_error,
)
from services.stage_db import (  # noqa: E402
    clear_host_up_since,
    delete_stage,
    insert_stage_if_absent,
    select_stage,
    set_host_up_since_if_unset,
)
from services.stage_history import append_stage_history  # noqa: E402

CONFIG_DIR = os.path.join(APP_ROOT, 'config')
MAPPINGS_PATH = os.path.join(CONFIG_DIR, 'monitoring_server_mappings.json')
MONITORING_CONFIG_PATH = os.path.join(CONFIG_DIR, 'monitoring_config.json')
SECRET_KEY_PATH = os.path.join(CONFIG_DIR, 'secret_key')
ENCRYPTED_MARKER = '__ENC__'

STAGE_NEW = 'new'
STAGE_WATCHLIST = 'watchlist'
STAGE_RETAIN_MINUTES = 30
CGI_TIMEOUT = float(os.environ.get('MONITORING_CGI_TIMEOUT', '15'))
DEFAULT_INTERVAL = 30
MAX_WORKERS = 10
CIRCUIT_FAILURES = 3

_fernet = None
_thread_local = threading.local()
_ip_cache: dict[str, dict[str, str]] = {}
_ip_cache_hash: dict[str, str] = {}


def log(message: str) -> None:
    print(f'[{datetime.now().isoformat(timespec="seconds")}] {message}', flush=True)


def _init_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    if not os.path.exists(SECRET_KEY_PATH):
        return None
    try:
        from cryptography.fernet import Fernet
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


def _session() -> requests.Session:
    sess = getattr(_thread_local, 'session', None)
    if sess is None:
        sess = requests.Session()
        _thread_local.session = sess
    return sess


def load_stored_creds(container: str) -> tuple[str, str] | None:
    path = os.path.join(CONFIG_DIR, f'nagios_creds_{container}.json')
    data = _load_json(path)
    if not isinstance(data, dict):
        return None
    username = _decrypt_maybe(data.get('username'))
    password = _decrypt_maybe(data.get('password'))
    if not username or not password:
        return None
    return username, password


def auth_header_for(container: str) -> str | None:
    creds = load_stored_creds(container)
    if not creds:
        return None
    token = base64.b64encode(f'{creds[0]}:{creds[1]}'.encode()).decode()
    return f'Basic {token}'


def poll_interval() -> int:
    data = _load_json(MONITORING_CONFIG_PATH)
    if isinstance(data, dict):
        try:
            value = int(data.get('refresh_interval') or DEFAULT_INTERVAL)
            return max(5, value)
        except (TypeError, ValueError):
            pass
    return DEFAULT_INTERVAL


def load_mapped_containers() -> list[str]:
    data = _load_json(MAPPINGS_PATH)
    names: list[str] = []
    seen: set[str] = set()
    if not isinstance(data, dict):
        return names
    for servers in data.values():
        if not isinstance(servers, list):
            continue
        for name in servers:
            if isinstance(name, str) and name and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def containers_needing_services() -> set[str]:
    mappings = _load_json(MAPPINGS_PATH)
    config = _load_json(MONITORING_CONFIG_PATH)
    needed: set[str] = set()
    if not isinstance(mappings, dict) or not isinstance(config, dict):
        return needed
    settings = config.get('category_settings') or {}
    if not isinstance(settings, dict):
        return needed
    for category, servers in mappings.items():
        if not isinstance(servers, list):
            continue
        cat_cfg = settings.get(category) or {}
        if isinstance(cat_cfg, dict) and cat_cfg.get('use_service_plugin'):
            needed.update(s for s in servers if isinstance(s, str))
    return needed


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


def _fetch_error(container: str, reason: str) -> str:
    return f'Failed to fetch data from container {container} ({reason})'


def _circuit_open(container: str) -> bool:
    health = get_container_health(container)
    if not health:
        return False
    failures = health['consecutive_failures']
    if failures < CIRCUIT_FAILURES:
        return False
    last_attempt = health.get('last_attempt_at')
    if not last_attempt:
        return False
    try:
        attempted = datetime.fromisoformat(last_attempt)
    except (ValueError, TypeError):
        return False
    backoff = min(60, 15 * failures)
    return (datetime.now() - attempted).total_seconds() < backoff


def _parse_ip_mapping(object_data: dict) -> dict[str, str]:
    object_hostlist = object_data.get('data', {}).get('hostlist', {})
    if not isinstance(object_hostlist, dict):
        return {}
    return {
        hostname: details.get('address', 'N/A')
        for hostname, details in object_hostlist.items()
        if isinstance(details, dict)
    }


def fetch_container(
    container: str,
    port: str,
    auth_header: str,
    fetch_services: bool,
) -> tuple[list[dict], dict[str, int] | None, str | None]:
    headers = {'Authorization': auth_header}
    sess = _session()
    status_url = f'http://localhost:{port}/nagios/cgi-bin/statusjson.cgi?query=hostlist&details=true'
    object_url = f'http://localhost:{port}/nagios/cgi-bin/objectjson.cgi?details=true&query=hostlist'
    try:
        status_resp = sess.get(status_url, headers=headers, timeout=CGI_TIMEOUT)
        if status_resp.status_code != 200:
            return [], None, _fetch_error(container, f'HTTP {status_resp.status_code} from statusjson.cgi')
        try:
            status_data = status_resp.json()
        except json.JSONDecodeError:
            return [], None, _fetch_error(container, 'invalid JSON from Nagios CGI')
        hostlist = status_data.get('data', {}).get('hostlist', {})
        if not isinstance(hostlist, dict):
            return [], None, _fetch_error(container, 'malformed hostlist')

        ip_mapping = _ip_cache.get(container, {})
        try:
            object_resp = sess.get(object_url, headers=headers, timeout=CGI_TIMEOUT)
            if object_resp.status_code == 200:
                digest = hashlib.sha256(object_resp.content).hexdigest()
                if _ip_cache_hash.get(container) != digest:
                    object_data = object_resp.json()
                    parsed = _parse_ip_mapping(object_data)
                    if parsed:
                        ip_mapping = parsed
                        _ip_cache[container] = parsed
                        _ip_cache_hash[container] = digest
            elif not ip_mapping:
                log(f'{container}: objectjson HTTP {object_resp.status_code}; addresses unknown')
        except (requests.RequestException, json.JSONDecodeError, ValueError):
            if not ip_mapping:
                log(f'{container}: objectjson failed; continuing without addresses')

        service_data: dict[str, str] = {}
        service_counts: dict[str, int] | None = None
        try:
            service_url = f'http://localhost:{port}/nagios/cgi-bin/statusjson.cgi?query=servicelist&details=true'
            service_resp = sess.get(service_url, headers=headers, timeout=CGI_TIMEOUT)
            if service_resp.status_code == 200:
                services = service_resp.json().get('data', {}).get('servicelist', {})
                if isinstance(services, dict):
                    counts = {'ok': 0, 'warning': 0, 'critical': 0, 'unknown': 0}
                    for hostname, host_services in services.items():
                        if not isinstance(host_services, dict):
                            continue
                        for service_info in host_services.values():
                            if not isinstance(service_info, dict):
                                continue
                            status_code = int(service_info.get('status') or 0)
                            if status_code == 2:
                                counts['ok'] += 1
                            elif status_code == 4:
                                counts['warning'] += 1
                            elif status_code == 16:
                                counts['critical'] += 1
                            else:
                                counts['unknown'] += 1
                            if fetch_services and hostname not in service_data:
                                service_data[hostname] = service_info.get('plugin_output', '') or ''
                    service_counts = counts
        except (requests.RequestException, json.JSONDecodeError, ValueError, TypeError):
            log(f'{container}: servicelist fetch failed; continuing with host data')

        hosts = []
        for hostname, host in hostlist.items():
            if not isinstance(host, dict):
                continue
            hosts.append({
                'hostname': hostname,
                'name': host.get('name', hostname),
                'status_code': int(host.get('status') or 0),
                'plugin_output': host.get('plugin_output', '') or '',
                'service_plugin_output': service_data.get(hostname, ''),
                'last_check_ms': int(host.get('last_check') or 0),
                'last_state_change_ms': int(host.get('last_state_change') or 0),
                'acknowledged': bool(host.get('problem_has_been_acknowledged', False)),
                'address': ip_mapping.get(hostname, 'N/A'),
                'port': port,
            })
        return hosts, service_counts, None
    except requests.Timeout:
        log(f'CGI timeout after {CGI_TIMEOUT:g}s for {container}')
        return [], None, _fetch_error(container, f'timeout after {CGI_TIMEOUT:g}s')
    except requests.RequestException:
        log(f'CGI connection error for {container}')
        return [], None, _fetch_error(container, 'connection error')
    except (ValueError, KeyError, TypeError):
        log(f'CGI parse error for {container}')
        return [], None, _fetch_error(container, 'unexpected CGI response')


def reconcile_container(container: str, hosts: list[dict]) -> None:
    now = datetime.now()
    for host in hosts:
        hostname = host['hostname']
        status_code = host['status_code']
        host_is_down = status_code in (4, 8)
        host_is_up = status_code == 2
        try:
            stage_info = select_stage(container, hostname)
        except Exception:
            stage_info = None

        if host_is_up and stage_info:
            current_stage = stage_info.get('stage', STAGE_NEW)
            if current_stage == STAGE_WATCHLIST:
                if not stage_info.get('host_up_since'):
                    if set_host_up_since_if_unset(container, hostname, now.isoformat()):
                        append_stage_history(
                            hostname, container, current_stage, 'up',
                            'system (auto-detect)',
                            'Host recovered (flapping — watching for 30min)',
                        )
                else:
                    try:
                        up_since = datetime.fromisoformat(stage_info['host_up_since'])
                        if (now - up_since).total_seconds() > STAGE_RETAIN_MINUTES * 60:
                            delete_stage(container, hostname)
                            append_stage_history(
                                hostname, container, current_stage, 'up',
                                'system (auto-detect)',
                                'Host recovered (watchlist — 30min flapping window expired)',
                            )
                    except (ValueError, TypeError):
                        delete_stage(container, hostname)
                        append_stage_history(
                            hostname, container, current_stage, 'up',
                            'system (auto-detect)',
                            'Host recovered (watchlist — parse error, removed)',
                        )
            else:
                delete_stage(container, hostname)
                append_stage_history(
                    hostname, container, current_stage, 'up',
                    'system (auto-detect)', 'Host recovered',
                )
            continue

        if not host_is_down:
            continue

        if host.get('acknowledged'):
            if stage_info:
                delete_stage(container, hostname)
            continue

        if stage_info and stage_info.get('host_up_since'):
            clear_host_up_since(container, hostname)
            append_stage_history(
                hostname, container, 'up', stage_info.get('stage', STAGE_NEW),
                'system (auto-detect)', 'Host went DOWN again (flapping)',
            )
            try:
                stage_info = select_stage(container, hostname)
            except Exception:
                stage_info = None

        if not stage_info:
            inserted = insert_stage_if_absent(
                container,
                hostname,
                STAGE_NEW,
                updated_at=now.isoformat(),
                updated_by='system',
                host_up_since=None,
            )
            if inserted:
                append_stage_history(
                    hostname, container, 'up', STAGE_NEW,
                    'system (auto-detect)', 'Host went DOWN',
                )


def process_container(
    container: str,
    port: str | None,
    fetch_services: bool,
) -> None:
    started = time.monotonic()
    if not port:
        record_fetch_error(container, 'not running or port unavailable')
        log(f'{container}: not running or port unavailable')
        return
    if _circuit_open(container):
        log(f'{container}: circuit open, serving stale snapshot')
        return
    header = auth_header_for(container)
    if not header:
        record_fetch_error(container, 'no stored credentials', port=port)
        log(f'{container}: no stored credentials')
        return
    hosts, service_counts, error = fetch_container(container, port, header, fetch_services)
    duration_ms = int((time.monotonic() - started) * 1000)
    if error:
        reason = error.split('(', 1)[-1].rstrip(')') if '(' in error else error
        record_fetch_error(container, reason, port=port)
        log(f'{container}: {reason}')
        return
    commit_successful_fetch(container, hosts, duration_ms, port, services=service_counts)
    reconcile_container(container, hosts)
    log(f'{container}: {len(hosts)} host(s) in {duration_ms}ms')


def run_cycle() -> None:
    mapped = load_mapped_containers()
    running = discover_running_ports()
    names: list[str] = []
    seen: set[str] = set()
    for name in [*mapped, *running.keys()]:
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    if not names:
        log('no containers to poll')
        return
    need_services = containers_needing_services()
    with ThreadPoolExecutor(max_workers=min(len(names), MAX_WORKERS)) as executor:
        futures = {
            executor.submit(
                process_container,
                name,
                running.get(name),
                name in need_services,
            ): name
            for name in names
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
            except Exception:
                record_fetch_error(name, 'internal error', port=running.get(name))
                log(f'{name}: internal error')


def run_loop() -> None:
    log(f'nagios-poller started (cgi_timeout={CGI_TIMEOUT:g}s)')
    while True:
        cycle_start = time.monotonic()
        try:
            run_cycle()
        except Exception as exc:
            log(f'cycle failed: {exc}')
        interval = poll_interval()
        elapsed = time.monotonic() - cycle_start
        sleep_for = max(0.0, interval - elapsed)
        log(f'cycle done in {elapsed:.1f}s, next in {sleep_for:.1f}s')
        time.sleep(sleep_for)


def main() -> None:
    parser = argparse.ArgumentParser(description='Nagios CGI snapshot poller')
    parser.add_argument('--once', action='store_true', help='Run one fetch cycle and exit')
    args = parser.parse_args()
    if args.once:
        run_cycle()
        return
    try:
        run_loop()
    except KeyboardInterrupt:
        log('stopped')


if __name__ == '__main__':
    main()
