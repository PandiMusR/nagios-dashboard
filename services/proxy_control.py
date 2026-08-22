#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(APP_ROOT, 'config')
DISABLED_PATH = os.path.join(CONFIG_DIR, 'proxy_disabled.json')
PID_PATH = os.path.join(CONFIG_DIR, 'nagios-proxy.pid')
SCRIPT_PATH = os.path.join(APP_ROOT, 'services', 'async_proxy.py')
LOG_PATH = os.environ.get('NAGIOS_PROXY_LOG', '/tmp/nagios-proxy.log')
OPENRC_INIT = '/etc/init.d/nagios-proxy'
OPENRC_PID = '/run/nagios-proxy.pid'


def load_disabled() -> set[str]:
    try:
        with open(DISABLED_PATH) as f:
            data = json.load(f)
        if isinstance(data, list):
            return {name for name in data if isinstance(name, str) and name}
    except (OSError, json.JSONDecodeError):
        pass
    return set()


def save_disabled(names: set[str]) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = DISABLED_PATH + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(sorted(names), f)
    os.replace(tmp, DISABLED_PATH)


def enable_container(name: str) -> None:
    disabled = load_disabled()
    if name in disabled:
        disabled.discard(name)
        save_disabled(disabled)


def disable_container(name: str) -> None:
    disabled = load_disabled()
    disabled.add(name)
    save_disabled(disabled)


def enable_all() -> None:
    save_disabled(set())


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _pid_is_proxy(pid: int) -> bool:
    if pid <= 0 or not _pid_is_alive(pid):
        return False
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            cmd = f.read().replace(b'\x00', b' ').decode(errors='replace')
        return 'async_proxy.py' in cmd
    except OSError:
        return False


def _read_pidfile(path: str) -> int | None:
    try:
        with open(path) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    if _pid_is_proxy(pid):
        return pid
    return None


def find_pid() -> int | None:
    for path in (OPENRC_PID, '/var/run/nagios-proxy.pid', PID_PATH):
        pid = _read_pidfile(path)
        if pid is not None:
            return pid
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'async_proxy.py'],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in result.stdout.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if _pid_is_proxy(pid):
            return pid
    return None


def is_running() -> bool:
    return find_pid() is not None


def _openrc_available() -> bool:
    return os.path.isfile(OPENRC_INIT) and bool(_which('rc-service'))


def _which(name: str) -> str | None:
    for directory in os.environ.get('PATH', '').split(os.pathsep):
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _rc_service(action: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ['rc-service', 'nagios-proxy', action],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, result.stdout.strip() or result.stderr.strip() or action
    return False, (result.stderr or result.stdout or action).strip()


def kill_legacy_proxies() -> int:
    try:
        result = subprocess.run(
            ['pgrep', '-af', 'proxy.py'],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    killed = 0
    for line in result.stdout.splitlines():
        if 'async_proxy.py' in line or 'pgrep' in line:
            continue
        if 'proxy.py' not in line:
            continue
        try:
            pid = int(line.split(None, 1)[0])
        except ValueError:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
        except OSError:
            continue
    if killed:
        time.sleep(0.6)
        for line in result.stdout.splitlines():
            if 'async_proxy.py' in line or 'pgrep' in line or 'proxy.py' not in line:
                continue
            try:
                pid = int(line.split(None, 1)[0])
            except ValueError:
                continue
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                continue
    return killed


def _python() -> str:
    venv = os.path.join(APP_ROOT, 'venv', 'bin', 'python3')
    if os.path.isfile(venv) and os.access(venv, os.X_OK):
        return venv
    return sys.executable


def _write_pidfile(pid: int) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(PID_PATH, 'w') as f:
        f.write(str(pid))


def _daemonize() -> tuple[bool, str]:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    log_file = open(LOG_PATH, 'a')
    proc = subprocess.Popen(
        [_python(), SCRIPT_PATH],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=APP_ROOT,
    )
    log_file.close()
    _write_pidfile(proc.pid)
    time.sleep(0.8)
    if not _pid_is_proxy(proc.pid):
        return False, f'async_proxy.py exited immediately (see {LOG_PATH})'
    return True, f'Proxy multiplexer started (PID {proc.pid})'


def start() -> tuple[bool, str]:
    kill_legacy_proxies()
    if is_running():
        return True, f'Proxy multiplexer already running (PID {find_pid()})'
    if _openrc_available():
        ok, msg = _rc_service('start')
        if ok or is_running():
            return True, msg or 'Proxy multiplexer started via OpenRC'
        return False, msg
    return _daemonize()


def reload() -> tuple[bool, str]:
    pid = find_pid()
    if pid is None:
        return start()
    if _openrc_available():
        ok, msg = _rc_service('reload')
        if ok:
            return True, msg or 'Proxy multiplexer reloaded'
    try:
        os.kill(pid, signal.SIGHUP)
    except OSError as exc:
        return False, f'Failed to signal proxy multiplexer: {exc}'
    return True, f'Proxy multiplexer reload signaled (PID {pid})'


def ensure_running_and_reload() -> tuple[bool, str]:
    kill_legacy_proxies()
    if not is_running():
        return start()
    return reload()


def restart() -> tuple[bool, str]:
    kill_legacy_proxies()
    if _openrc_available():
        ok, msg = _rc_service('restart')
        if ok or is_running():
            return True, msg or 'Proxy multiplexer restarted via OpenRC'
        _rc_service('zap')
        ok, msg = _rc_service('start')
        if ok or is_running():
            return True, msg or 'Proxy multiplexer started via OpenRC after failed restart'
        return False, msg
    pid = find_pid()
    if pid is not None:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(20):
            if not _pid_is_alive(pid):
                break
            time.sleep(0.1)
        if _pid_is_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            time.sleep(0.2)
    return _daemonize()
