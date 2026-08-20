#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any
import base64

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)
os.chdir(APP_ROOT)

from services.intensive_db import insert_ping_result, purge_old_records

CONFIG_PATH = os.path.join(APP_ROOT, 'config', 'intensive_hosts.json')
GLOBAL_CONFIG_PATH = os.path.join(APP_ROOT, 'config', 'global_config.json')
SECRET_KEY_PATH = os.path.join(APP_ROOT, 'config', 'secret_key')
PING_BIN = os.environ.get('PING_BIN', 'ping')
TELEGRAM_API = 'https://api.telegram.org/bot{token}/sendMessage'
ENCRYPTED_MARKER = '__ENC__'
_ping_flavor: str | None = None
_fernet = None

_LOSS_RE = re.compile(r'(\d+(?:\.\d+)?)%\s*packet loss', re.IGNORECASE)
_COUNTS_RE = re.compile(
    r'(\d+)\s+packets transmitted,\s+(\d+)\s+(?:packets\s+)?received',
    re.IGNORECASE,
)
_RTT_RE = re.compile(
    r'(?:rtt|round-trip)\s+min/avg/max(?:/mdev)?\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)',
    re.IGNORECASE,
)
_TIME_LINE_RE = re.compile(r'\btime[=<]([\d.]+)\s*ms', re.IGNORECASE)

_consecutive_down: dict[str, int] = {}
_alert_armed: dict[str, bool] = {}


def log(message: str) -> None:
    print(f'[{datetime.now().isoformat(timespec="seconds")}] {message}', flush=True)


def load_config(path: str = CONFIG_PATH) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def _init_fernet() -> None:
    global _fernet
    if _fernet is not None or not os.path.exists(SECRET_KEY_PATH):
        return
    try:
        from cryptography.fernet import Fernet
        with open(SECRET_KEY_PATH) as f:
            secret_key = f.read().strip()
        key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
        _fernet = Fernet(key)
    except Exception:
        _fernet = None


def _decrypt_maybe(value: str) -> str:
    if not isinstance(value, str) or not value:
        return ''
    if not value.startswith(ENCRYPTED_MARKER):
        return value
    _init_fernet()
    if _fernet is None:
        return ''
    try:
        return _fernet.decrypt(value[len(ENCRYPTED_MARKER):].encode()).decode()
    except Exception:
        return ''


def load_telegram_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Credentials from global_config.json; intensive_hosts.json is fallback only."""
    bot_token = ''
    chat_id = ''
    enabled = False
    try:
        with open(GLOBAL_CONFIG_PATH) as f:
            global_cfg = json.load(f)
        bot_token = _decrypt_maybe(str(global_cfg.get('telegram_bot_token') or ''))
        chat_id = str(global_cfg.get('telegram_chat_id') or '').strip()
        enabled = bool(global_cfg.get('telegram_enabled', False))
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    local = config.get('telegram') or {}
    if not bot_token:
        bot_token = _decrypt_maybe(str(local.get('bot_token') or ''))
    if not chat_id:
        chat_id = str(local.get('chat_id') or '').strip()
    if not enabled:
        enabled = bool(local.get('enabled', False))
    return {'bot_token': bot_token, 'chat_id': chat_id, 'enabled': enabled}


def alerts_are_mocked(config: dict[str, Any]) -> bool:
    return bool(config.get('mock_alerts', True) or config.get('dev_mode', True))


def host_settings(host: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    defaults = config.get('defaults') or {}
    return {
        'id': host['id'],
        'name': host.get('name') or host['id'],
        'address': host['address'],
        'interval_seconds': int(host.get('interval_seconds', defaults.get('interval_seconds', 20))),
        'ping_count': int(host.get('ping_count', defaults.get('ping_count', 4))),
        'timeout_seconds': int(host.get('timeout_seconds', defaults.get('timeout_seconds', 2))),
        'latency_threshold_ms': float(host.get('latency_threshold_ms', defaults.get('latency_threshold_ms', 100))),
        'packet_loss_threshold_pct': float(
            host.get('packet_loss_threshold_pct', defaults.get('packet_loss_threshold_pct', 25))
        ),
        'enabled': bool(host.get('enabled', True)),
    }


def parse_ping_output(stdout: str, stderr: str = '') -> dict[str, Any]:
    """Parse iputils (Dev) and BusyBox (Prod/Alpine) ping summaries."""
    text = f'{stdout}\n{stderr}'

    loss_match = _LOSS_RE.search(text)
    counts_match = _COUNTS_RE.search(text)
    rtt_match = _RTT_RE.search(text)

    packets_sent = int(counts_match.group(1)) if counts_match else None
    packets_received = int(counts_match.group(2)) if counts_match else None
    packet_loss_pct = float(loss_match.group(1)) if loss_match else None

    latency_ms: float | None = None
    if rtt_match:
        latency_ms = float(rtt_match.group(2))
    else:
        samples = [float(m.group(1)) for m in _TIME_LINE_RE.finditer(text)]
        if samples:
            latency_ms = sum(samples) / len(samples)
            if packets_received is None:
                packets_received = len(samples)

    if packet_loss_pct is None and packets_sent and packets_received is not None:
        packet_loss_pct = round((1 - packets_received / packets_sent) * 100, 2)

    if packet_loss_pct is None:
        packet_loss_pct = 100.0 if packets_received in (None, 0) else 0.0

    if packets_received is None and packet_loss_pct >= 100:
        packets_received = 0

    status = 'up' if (packets_received or 0) > 0 else 'down'
    if status == 'down':
        latency_ms = None
        packet_loss_pct = 100.0

    return {
        'status': status,
        'latency_ms': round(latency_ms, 3) if latency_ms is not None else None,
        'packet_loss_pct': round(float(packet_loss_pct), 2),
        'packets_sent': packets_sent,
        'packets_received': packets_received,
        'raw': text.strip(),
    }


async def detect_ping_flavor() -> str:
    """iputils (Dev) vs BusyBox (Prod). Flag meanings differ: do not mix -w/-W."""
    global _ping_flavor
    if _ping_flavor:
        return _ping_flavor
    try:
        proc = await asyncio.create_subprocess_exec(
            PING_BIN,
            '-V',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=3)
        text = (out_b + err_b).decode('utf-8', errors='replace').lower()
        _ping_flavor = 'iputils' if 'iputils' in text else 'busybox'
    except Exception:
        _ping_flavor = 'busybox'
    return _ping_flavor


def build_ping_cmd(address: str, count: int, timeout_seconds: int, flavor: str) -> tuple[list[str], int]:
    deadline = count * (timeout_seconds + 1) + 2
    if flavor == 'iputils':
        cmd = [PING_BIN, '-c', str(count), '-W', str(timeout_seconds), address]
    else:
        cmd = [PING_BIN, '-c', str(count), '-w', str(deadline), address]
    return cmd, deadline


async def ping_address(address: str, count: int, timeout_seconds: int) -> dict[str, Any]:
    """Run system ping with flavor-specific flags (iputils -W vs BusyBox -w)."""
    count = max(1, count)
    timeout_seconds = max(1, timeout_seconds)
    flavor = await detect_ping_flavor()
    cmd, deadline = build_ping_cmd(address, count, timeout_seconds, flavor)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=deadline + 3)
    except FileNotFoundError:
        return {
            'status': 'down',
            'latency_ms': None,
            'packet_loss_pct': 100.0,
            'packets_sent': count,
            'packets_received': 0,
            'raw': f'ping binary not found: {PING_BIN}',
        }
    except TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except (ProcessLookupError, UnboundLocalError):
            pass
        return {
            'status': 'down',
            'latency_ms': None,
            'packet_loss_pct': 100.0,
            'packets_sent': count,
            'packets_received': 0,
            'raw': f'ping timed out after {deadline + 3}s ({address})',
        }
    except OSError as e:
        return {
            'status': 'down',
            'latency_ms': None,
            'packet_loss_pct': 100.0,
            'packets_sent': count,
            'packets_received': 0,
            'raw': f'ping failed to start: {e}',
        }

    stdout = stdout_b.decode('utf-8', errors='replace')
    stderr = stderr_b.decode('utf-8', errors='replace')
    parsed = parse_ping_output(stdout, stderr)
    if parsed['packets_sent'] is None:
        parsed['packets_sent'] = count
    return parsed


def format_alert_text(host: dict[str, Any], result: dict[str, Any], event: str) -> str:
    name = host.get('name') or host.get('id')
    address = host.get('address')
    if event == 'recovered':
        latency = result.get('latency_ms')
        latency_s = f'{latency} ms' if latency is not None else 'n/a'
        return (
            f'RECOVERED: {name} ({address})\n'
            f'latency={latency_s}  loss={result.get("packet_loss_pct")}%'
        )
    return (
        f'DOWN: {name} ({address})\n'
        f'3 consecutive ping failures\n'
        f'loss={result.get("packet_loss_pct")}%  latency=n/a'
    )


def _telegram_post(token: str, chat_id: str, text: str) -> None:
    url = TELEGRAM_API.format(token=token)
    body = urllib.parse.urlencode({
        'chat_id': chat_id,
        'text': text,
        'disable_web_page_preview': 'true',
    }).encode()
    req = urllib.request.Request(url, data=body, method='POST')
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


async def send_telegram_alert(
    host: dict[str, Any],
    result: dict[str, Any],
    config: dict[str, Any],
    event: str,
) -> None:
    payload = {
        'event': event,
        'host_id': host['id'],
        'host_name': host['name'],
        'address': host['address'],
        'status': result.get('status'),
        'latency_ms': result.get('latency_ms'),
        'packet_loss_pct': result.get('packet_loss_pct'),
    }
    if alerts_are_mocked(config):
        log(f'[ALERT mock] {payload}')
        return
    telegram = load_telegram_settings(config)
    if not telegram['enabled']:
        log(f'[ALERT skipped — telegram disabled] {payload}')
        return
    if not telegram['bot_token'] or not telegram['chat_id']:
        log('[ALERT skipped — missing telegram_bot_token or telegram_chat_id in global_config.json]')
        return
    text = format_alert_text(host, result, event)
    try:
        await asyncio.to_thread(_telegram_post, telegram['bot_token'], telegram['chat_id'], text)
        log(f'[ALERT telegram] {event} {host["id"]}')
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as e:
        log(f'[ALERT telegram failed] {type(e).__name__}')


async def apply_consecutive_alert_rule(
    host: dict[str, Any],
    result: dict[str, Any],
    config: dict[str, Any],
) -> None:
    host_id = host['id']
    threshold = int(config.get('consecutive_failures_threshold', 3))
    if result['status'] == 'up':
        was_alerting = _alert_armed.get(host_id, False)
        _consecutive_down[host_id] = 0
        _alert_armed[host_id] = False
        if was_alerting:
            await send_telegram_alert(host, result, config, 'recovered')
        return

    _consecutive_down[host_id] = _consecutive_down.get(host_id, 0) + 1
    if _consecutive_down[host_id] >= threshold and not _alert_armed.get(host_id):
        _alert_armed[host_id] = True
        await send_telegram_alert(host, result, config, 'down')


async def check_host(host: dict[str, Any], config: dict[str, Any], sem: asyncio.Semaphore) -> dict[str, Any]:
    async with sem:
        result = await ping_address(host['address'], host['ping_count'], host['timeout_seconds'])
    insert_ping_result(
        host_id=host['id'],
        host_name=host['name'],
        address=host['address'],
        status=result['status'],
        latency_ms=result['latency_ms'],
        packet_loss_pct=result['packet_loss_pct'],
        packets_sent=result['packets_sent'],
        packets_received=result['packets_received'],
    )
    await apply_consecutive_alert_rule(host, result, config)
    log(
        f'{host["id"]} {host["address"]} {result["status"]} '
        f'latency={result["latency_ms"]}ms loss={result["packet_loss_pct"]}% '
        f'{result["packets_received"]}/{result["packets_sent"]}'
    )
    return result


async def monitor_loop(host_id: str, sem: asyncio.Semaphore) -> None:
    while True:
        try:
            config = load_config()
        except (OSError, json.JSONDecodeError) as e:
            log(f'{host_id} config read failed: {e}')
            await asyncio.sleep(10)
            continue
        raw = next(
            (
                h for h in config.get('hosts', [])
                if isinstance(h, dict) and h.get('id') == host_id and h.get('enabled', True)
            ),
            None,
        )
        if raw is None:
            log(f'{host_id} removed or disabled')
            return
        host = host_settings(raw, config)
        try:
            await check_host(host, config, sem)
        except Exception as e:
            log(f'{host_id} check failed: {e}')
        await asyncio.sleep(max(5, host['interval_seconds']))


async def retention_loop() -> None:
    while True:
        try:
            config = load_config()
            retention_days = int(config.get('retention_days', 14))
            deleted = purge_old_records(retention_days)
            if deleted:
                log(f'retention: deleted {deleted} rows older than {retention_days}d')
        except Exception as e:
            log(f'retention failed: {e}')
        await asyncio.sleep(3600)


async def run_worker() -> None:
    _init_fernet()
    try:
        config = load_config()
    except (OSError, json.JSONDecodeError) as e:
        log(f'cannot read {CONFIG_PATH}: {e}')
        return
    max_concurrent = max(1, int(config.get('max_concurrent_pings', 8)))
    sem = asyncio.Semaphore(max_concurrent)
    mock = alerts_are_mocked(config)
    log(
        f'starting intensive worker: ping={await detect_ping_flavor()}, '
        f'concurrency={max_concurrent}, mock_alerts={mock}'
    )
    try:
        purge_old_records(int(config.get('retention_days', 14)))
    except Exception as e:
        log(f'retention startup failed: {e}')

    tasks: dict[str, asyncio.Task] = {}
    asyncio.create_task(retention_loop())
    while True:
        try:
            config = load_config()
        except (OSError, json.JSONDecodeError) as e:
            log(f'config reload failed: {e}')
            await asyncio.sleep(10)
            continue
        wanted = {
            str(h['id'])
            for h in config.get('hosts', [])
            if isinstance(h, dict) and h.get('enabled', True) and h.get('id') and h.get('address')
        }
        for host_id in list(tasks):
            if host_id not in wanted or tasks[host_id].done():
                task = tasks.pop(host_id)
                if not task.done():
                    task.cancel()
                    log(f'stopped monitor {host_id}')
        for host_id in wanted:
            if host_id not in tasks:
                tasks[host_id] = asyncio.create_task(monitor_loop(host_id, sem))
                log(f'started monitor {host_id}')
        await asyncio.sleep(10)


async def run_once(address: str | None = None) -> None:
    config = load_config()
    if address:
        result = await ping_address(address, count=4, timeout_seconds=2)
        print(json.dumps({'address': address, 'flavor': await detect_ping_flavor(), **{k: v for k, v in result.items() if k != 'raw'}}, indent=2))
        print('--- raw ---')
        print(result['raw'])
        return
    hosts = [host_settings(h, config) for h in config.get('hosts', []) if h.get('enabled', True)]
    sem = asyncio.Semaphore(max(1, int(config.get('max_concurrent_pings', 8))))
    for host in hosts:
        result = await check_host(host, config, sem)
        print(json.dumps({
            'id': host['id'],
            'address': host['address'],
            'status': result['status'],
            'latency_ms': result['latency_ms'],
            'packet_loss_pct': result['packet_loss_pct'],
            'packets_sent': result['packets_sent'],
            'packets_received': result['packets_received'],
        }))


def main() -> None:
    parser = argparse.ArgumentParser(description='Intensive ping worker')
    parser.add_argument('--once', action='store_true', help='Ping all enabled hosts once and exit')
    parser.add_argument('--ping', metavar='ADDRESS', help='Ping one address, print parser output, exit')
    args = parser.parse_args()
    if args.ping:
        asyncio.run(run_once(address=args.ping))
        return
    if args.once:
        asyncio.run(run_once())
        return
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        log('stopped')


if __name__ == '__main__':
    main()
