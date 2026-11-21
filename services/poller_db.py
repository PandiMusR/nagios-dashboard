from __future__ import annotations

from contextlib import closing
import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_DIR = os.path.join(_APP_ROOT, 'config')
DEFAULT_DB_PATH = os.path.join(_CONFIG_DIR, 'nagios_snapshot.db')

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_conn_path: str | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS container_health (
    container TEXT PRIMARY KEY,
    last_attempt_at TEXT,
    last_success_at TEXT,
    last_error TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    host_count INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    port TEXT,
    services_ok INTEGER NOT NULL DEFAULT 0,
    services_warning INTEGER NOT NULL DEFAULT 0,
    services_critical INTEGER NOT NULL DEFAULT 0,
    services_unknown INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS host_snapshot (
    container TEXT NOT NULL,
    hostname TEXT NOT NULL,
    name TEXT,
    status_code INTEGER,
    plugin_output TEXT,
    service_plugin_output TEXT,
    last_check_ms INTEGER,
    last_state_change_ms INTEGER,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    address TEXT,
    port TEXT,
    updated_at TEXT,
    PRIMARY KEY (container, hostname)
);
CREATE INDEX IF NOT EXISTS idx_host_snapshot_status
    ON host_snapshot (container, status_code);
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY
);
"""

_HOST_UPSERT_SQL = """
INSERT INTO host_snapshot (
    container, hostname, name, status_code, plugin_output, service_plugin_output,
    last_check_ms, last_state_change_ms, acknowledged, address, port, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(container, hostname) DO UPDATE SET
    name = excluded.name,
    status_code = excluded.status_code,
    plugin_output = excluded.plugin_output,
    service_plugin_output = excluded.service_plugin_output,
    last_check_ms = excluded.last_check_ms,
    last_state_change_ms = excluded.last_state_change_ms,
    acknowledged = excluded.acknowledged,
    address = excluded.address,
    port = excluded.port,
    updated_at = excluded.updated_at
"""

_SUCCESS_SQL = """
INSERT INTO container_health (
    container, last_attempt_at, last_success_at, last_error,
    consecutive_failures, host_count, duration_ms, port,
    services_ok, services_warning, services_critical, services_unknown
) VALUES (?, ?, ?, NULL, 0, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(container) DO UPDATE SET
    last_attempt_at = excluded.last_attempt_at,
    last_success_at = excluded.last_success_at,
    last_error = NULL,
    consecutive_failures = 0,
    host_count = excluded.host_count,
    duration_ms = excluded.duration_ms,
    port = excluded.port,
    services_ok = COALESCE(excluded.services_ok, container_health.services_ok),
    services_warning = COALESCE(excluded.services_warning, container_health.services_warning),
    services_critical = COALESCE(excluded.services_critical, container_health.services_critical),
    services_unknown = COALESCE(excluded.services_unknown, container_health.services_unknown)
"""

_SERVICE_COLUMNS = (
    ('services_ok', 'INTEGER NOT NULL DEFAULT 0'),
    ('services_warning', 'INTEGER NOT NULL DEFAULT 0'),
    ('services_critical', 'INTEGER NOT NULL DEFAULT 0'),
    ('services_unknown', 'INTEGER NOT NULL DEFAULT 0'),
)

_ERROR_SQL = """
INSERT INTO container_health (
    container, last_attempt_at, last_success_at, last_error,
    consecutive_failures, host_count, duration_ms, port
) VALUES (?, ?, NULL, ?, 1, 0, NULL, ?)
ON CONFLICT(container) DO UPDATE SET
    last_attempt_at = excluded.last_attempt_at,
    last_error = excluded.last_error,
    consecutive_failures = container_health.consecutive_failures + 1,
    port = COALESCE(excluded.port, container_health.port)
"""

_DOWN_STATUS_CODES = (4, 8)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute('PRAGMA table_info(container_health)')}
    for name, typedef in _SERVICE_COLUMNS:
        if name not in cols:
            conn.execute(f'ALTER TABLE container_health ADD COLUMN {name} {typedef}')


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.executescript(_SCHEMA)
    _ensure_schema(conn)
    conn.execute('INSERT OR IGNORE INTO schema_migrations (version) VALUES (1)')
    conn.commit()
    return conn


def init_db(db_path: str | None = None) -> sqlite3.Connection:
    global _conn, _conn_path
    path = db_path or DEFAULT_DB_PATH
    with _lock:
        if _conn is not None and _conn_path == path:
            return _conn
        if _conn is not None:
            _conn.close()
        _conn = _connect(path)
        _conn_path = path
        return _conn


def _row_to_host(row: sqlite3.Row) -> dict:
    return {
        'container': row['container'],
        'hostname': row['hostname'],
        'name': row['name'] or row['hostname'],
        'status_code': row['status_code'],
        'plugin_output': row['plugin_output'] or '',
        'service_plugin_output': row['service_plugin_output'] or '',
        'last_check_ms': row['last_check_ms'] or 0,
        'last_state_change_ms': row['last_state_change_ms'] or 0,
        'acknowledged': bool(row['acknowledged']),
        'address': row['address'] or 'N/A',
        'port': row['port'] or '',
        'updated_at': row['updated_at'],
    }


def _row_to_health(row: sqlite3.Row) -> dict:
    return {
        'container': row['container'],
        'last_attempt_at': row['last_attempt_at'],
        'last_success_at': row['last_success_at'],
        'last_error': row['last_error'],
        'consecutive_failures': int(row['consecutive_failures'] or 0),
        'host_count': int(row['host_count'] or 0),
        'duration_ms': row['duration_ms'],
        'port': row['port'] or '',
        'services_ok': int(row['services_ok'] or 0) if 'services_ok' in row.keys() else 0,
        'services_warning': int(row['services_warning'] or 0) if 'services_warning' in row.keys() else 0,
        'services_critical': int(row['services_critical'] or 0) if 'services_critical' in row.keys() else 0,
        'services_unknown': int(row['services_unknown'] or 0) if 'services_unknown' in row.keys() else 0,
    }


def get_container_health(container: str, db_path: str | None = None) -> dict | None:
    conn = init_db(db_path)
    with _lock:
        row = conn.execute(
            'SELECT * FROM container_health WHERE container = ?',
            (container,),
        ).fetchone()
    return _row_to_health(row) if row else None


def list_container_health(
    containers: list[str] | None = None,
    db_path: str | None = None,
) -> dict[str, dict]:
    conn = init_db(db_path)
    sql = 'SELECT * FROM container_health'
    params: tuple = ()
    if containers:
        placeholders = ','.join('?' * len(containers))
        sql += f' WHERE container IN ({placeholders})'
        params = tuple(containers)
    with _lock:
        rows = conn.execute(sql, params).fetchall()
    return {row['container']: _row_to_health(row) for row in rows}


def list_snapshot_hosts(
    containers: list[str],
    down_only: bool = True,
    include_acked: bool = False,
    db_path: str | None = None,
) -> list[dict]:
    if not containers:
        return []
    conn = init_db(db_path)
    placeholders = ','.join('?' * len(containers))
    sql = f'SELECT * FROM host_snapshot WHERE container IN ({placeholders})'
    params: list = list(containers)
    if down_only:
        status_ph = ','.join('?' * len(_DOWN_STATUS_CODES))
        sql += f' AND status_code IN ({status_ph})'
        params.extend(_DOWN_STATUS_CODES)
    if not include_acked:
        sql += ' AND acknowledged = 0'
    with _lock:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_host(row) for row in rows]


def topology_snapshot(container: str, limit: int, db_path: str | None = None):
    path = Path(db_path or DEFAULT_DB_PATH).absolute()
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0.5)) as conn:
        conn.execute('BEGIN')
        health = conn.execute(
            'SELECT last_success_at, last_error IS NOT NULL FROM container_health WHERE container = ?',
            (container,),
        ).fetchone()
        hosts = conn.execute(
            'SELECT hostname, status_code FROM host_snapshot WHERE container = ? ORDER BY hostname LIMIT ?',
            (container, limit),
        ).fetchall()
    return hosts, health


def commit_successful_fetch(
    container: str,
    hosts: list[dict],
    duration_ms: int,
    port: str,
    services: dict | None = None,
    db_path: str | None = None,
) -> None:
    """Replace one container's host rows and clear its fetch error in one transaction.

    Failed fetches must call record_fetch_error instead so stale hosts stay put.
    Pass services=None to keep the previous service counters.
    """
    conn = init_db(db_path)
    now = datetime.now().isoformat()
    if services is None:
        svc_ok = svc_warn = svc_crit = svc_unk = None
    else:
        svc_ok = int(services.get('ok') or 0)
        svc_warn = int(services.get('warning') or 0)
        svc_crit = int(services.get('critical') or 0)
        svc_unk = int(services.get('unknown') or 0)
    with _lock:
        seen: list[str] = []
        for host in hosts:
            hostname = host['hostname']
            seen.append(hostname)
            conn.execute(
                _HOST_UPSERT_SQL,
                (
                    container,
                    hostname,
                    host.get('name') or hostname,
                    int(host.get('status_code') or 0),
                    host.get('plugin_output') or '',
                    host.get('service_plugin_output') or '',
                    int(host.get('last_check_ms') or 0),
                    int(host.get('last_state_change_ms') or 0),
                    1 if host.get('acknowledged') else 0,
                    host.get('address') or 'N/A',
                    host.get('port') or port,
                    now,
                ),
            )
        if seen:
            placeholders = ','.join('?' * len(seen))
            conn.execute(
                f'DELETE FROM host_snapshot WHERE container = ? AND hostname NOT IN ({placeholders})',
                [container, *seen],
            )
        else:
            conn.execute('DELETE FROM host_snapshot WHERE container = ?', (container,))
        conn.execute(
            _SUCCESS_SQL,
            (
                container, now, now, len(hosts), int(duration_ms), port,
                svc_ok, svc_warn, svc_crit, svc_unk,
            ),
        )
        conn.commit()


def record_fetch_error(
    container: str,
    error: str,
    port: str | None = None,
    db_path: str | None = None,
) -> None:
    """Record a CGI/timeout failure. Does not touch host_snapshot rows."""
    conn = init_db(db_path)
    now = datetime.now().isoformat()
    with _lock:
        conn.execute(_ERROR_SQL, (container, now, error, port))
        conn.commit()


def set_host_acknowledged(
    container: str,
    hostname: str,
    acknowledged: bool = True,
    db_path: str | None = None,
) -> None:
    conn = init_db(db_path)
    with _lock:
        conn.execute(
            """
            UPDATE host_snapshot
            SET acknowledged = ?
            WHERE container = ? AND hostname = ?
            """,
            (1 if acknowledged else 0, container, hostname),
        )
        conn.commit()


def count_hosts(db_path: str | None = None) -> int:
    conn = init_db(db_path)
    with _lock:
        row = conn.execute('SELECT COUNT(*) AS n FROM host_snapshot').fetchone()
        return int(row['n'] if row else 0)


def integrity_ok(db_path: str | None = None) -> bool:
    conn = init_db(db_path)
    with _lock:
        row = conn.execute('PRAGMA integrity_check').fetchone()
    return bool(row) and str(row[0]) == 'ok'


def list_snapshot_containers(db_path: str | None = None) -> list[str]:
    conn = init_db(db_path)
    with _lock:
        rows = conn.execute(
            'SELECT container FROM container_health ORDER BY container'
        ).fetchall()
    return [row['container'] for row in rows]


def count_hosts_by_container(
    containers: list[str] | None = None,
    db_path: str | None = None,
) -> dict[str, dict]:
    conn = init_db(db_path)
    sql = """
        SELECT container,
               SUM(CASE WHEN status_code = 2 THEN 1 ELSE 0 END) AS up,
               SUM(CASE WHEN status_code = 4 THEN 1 ELSE 0 END) AS down,
               SUM(CASE WHEN status_code = 8 THEN 1 ELSE 0 END) AS unreachable,
               COUNT(*) AS total
        FROM host_snapshot
    """
    params: tuple = ()
    if containers is not None:
        if not containers:
            return {}
        placeholders = ','.join('?' * len(containers))
        sql += f' WHERE container IN ({placeholders})'
        params = tuple(containers)
    sql += ' GROUP BY container'
    with _lock:
        rows = conn.execute(sql, params).fetchall()
    return {
        row['container']: {
            'up': int(row['up'] or 0),
            'down': int(row['down'] or 0),
            'unreachable': int(row['unreachable'] or 0),
            'total': int(row['total'] or 0),
        }
        for row in rows
    }


def fetch_error_message(container: str, reason: str) -> str:
    return f'Failed to fetch data from container {container} ({reason})'


def snapshot_stale_after_seconds() -> int:
    path = os.path.join(_CONFIG_DIR, 'monitoring_config.json')
    interval = 30
    try:
        with open(path) as f:
            interval = int(json.load(f).get('refresh_interval') or 30)
            interval = max(5, interval)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return interval * 2


def container_fetch_error_map(
    containers: list[str],
    stale_after_seconds: int | None = None,
    db_path: str | None = None,
) -> dict[str, str]:
    if not containers:
        return {}
    stale_after = snapshot_stale_after_seconds() if stale_after_seconds is None else stale_after_seconds
    health_map = list_container_health(containers, db_path=db_path)
    now = datetime.now()
    errors: dict[str, str] = {}
    for name in containers:
        health = health_map.get(name)
        if not health:
            errors[name] = fetch_error_message(name, 'poller has not fetched yet')
            continue
        if health.get('last_error'):
            errors[name] = fetch_error_message(name, health['last_error'])
            continue
        success_at = health.get('last_success_at')
        if not success_at:
            errors[name] = fetch_error_message(name, 'poller has not succeeded yet')
            continue
        try:
            age = (now - datetime.fromisoformat(success_at)).total_seconds()
        except (ValueError, TypeError):
            errors[name] = fetch_error_message(name, 'snapshot timestamp unreadable')
            continue
        if age > stale_after:
            errors[name] = fetch_error_message(name, f'snapshot stale, last success {int(age)}s ago')
    return errors


def container_fetch_errors(
    containers: list[str],
    stale_after_seconds: int | None = None,
    db_path: str | None = None,
) -> list[str]:
    return list(container_fetch_error_map(containers, stale_after_seconds, db_path).values())
