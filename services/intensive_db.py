from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_DIR = os.path.join(_APP_ROOT, 'config')
DEFAULT_DB_PATH = os.path.join(_CONFIG_DIR, 'ping_history.db')
DEFAULT_HOSTS_PATH = os.path.join(_CONFIG_DIR, 'intensive_hosts.json')

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_conn_path: str | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ping_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    host_id TEXT NOT NULL,
    host_name TEXT NOT NULL,
    address TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms REAL,
    packet_loss_pct REAL NOT NULL,
    packets_sent INTEGER,
    packets_received INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ping_results_host_ts ON ping_results (host_id, ts);
CREATE INDEX IF NOT EXISTS idx_ping_results_ts ON ping_results (ts);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.executescript(_SCHEMA)
    return conn


def init_db(db_path: str | None = None) -> sqlite3.Connection:
    """Create ping_history.db if needed, enable WAL, and return a shared connection."""
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


def insert_ping_result(
    host_id: str,
    host_name: str,
    address: str,
    status: str,
    latency_ms: float | None,
    packet_loss_pct: float,
    packets_sent: int | None = None,
    packets_received: int | None = None,
    ts: str | None = None,
    db_path: str | None = None,
) -> None:
    """Insert one ping check row."""
    conn = init_db(db_path)
    row_ts = ts or datetime.now().isoformat(timespec='seconds')
    with _lock:
        conn.execute(
            """
            INSERT INTO ping_results (
                ts, host_id, host_name, address, status,
                latency_ms, packet_loss_pct, packets_sent, packets_received
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_ts,
                host_id,
                host_name,
                address,
                status,
                latency_ms,
                packet_loss_pct,
                packets_sent,
                packets_received,
            ),
        )
        conn.commit()


def purge_old_records(retention_days: int, db_path: str | None = None) -> int:
    """Delete ping rows older than retention_days. Returns deleted row count."""
    if retention_days < 1:
        return 0
    conn = init_db(db_path)
    cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat(timespec='seconds')
    with _lock:
        cursor = conn.execute('DELETE FROM ping_results WHERE ts < ?', (cutoff,))
        conn.commit()
        return cursor.rowcount


def load_configured_hosts() -> list[dict]:
    """Return host definitions from intensive_hosts.json (empty list if missing)."""
    try:
        with open(DEFAULT_HOSTS_PATH) as f:
            data = json.load(f)
        hosts: list[dict] = []
        for raw in data.get('hosts', []):
            host_id = raw.get('id')
            address = raw.get('address')
            if not host_id or not address:
                continue
            hosts.append({
                'id': str(host_id),
                'name': raw.get('name') or str(host_id),
                'address': str(address),
                'interval_seconds': int(raw.get('interval_seconds') or 20),
                'enabled': bool(raw.get('enabled', True)),
            })
        return hosts
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []


def _empty_intensive_config() -> dict:
    return {
        'dev_mode': True,
        'mock_alerts': True,
        'retention_days': 14,
        'max_concurrent_pings': 8,
        'consecutive_failures_threshold': 3,
        'defaults': {
            'interval_seconds': 20,
            'ping_count': 4,
            'timeout_seconds': 2,
            'latency_threshold_ms': 100,
            'packet_loss_threshold_pct': 25,
        },
        'hosts': [],
    }


def load_intensive_config() -> dict:
    """Load the full intensive_hosts.json document."""
    with _lock:
        try:
            with open(DEFAULT_HOSTS_PATH) as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return _empty_intensive_config()
            if not isinstance(data.get('hosts'), list):
                data['hosts'] = []
            return data
        except FileNotFoundError:
            return _empty_intensive_config()
        except (json.JSONDecodeError, OSError):
            return _empty_intensive_config()


def save_intensive_config(data: dict) -> None:
    """Atomically write intensive_hosts.json."""
    os.makedirs(os.path.dirname(DEFAULT_HOSTS_PATH), exist_ok=True)
    tmp_path = DEFAULT_HOSTS_PATH + '.tmp'
    with _lock:
        with open(tmp_path, 'w') as f:
            json.dump(data, f, indent=2)
            f.write('\n')
        os.replace(tmp_path, DEFAULT_HOSTS_PATH)


def make_host_id(name: str, existing_ids: set[str]) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', (name or '').strip().lower()).strip('-') or 'host'
    slug = slug[:40]
    candidate = slug
    n = 2
    while candidate in existing_ids:
        candidate = f'{slug[:36]}-{n}'
        n += 1
    return candidate


def add_configured_host(name: str, address: str, interval_seconds: int) -> dict:
    """Append a host to intensive_hosts.json and return the new record."""
    config = load_intensive_config()
    hosts = config.setdefault('hosts', [])
    existing = {str(h.get('id')) for h in hosts if isinstance(h, dict)}
    host_id = make_host_id(name, existing)
    defaults = config.get('defaults') or {}
    record = {
        'id': host_id,
        'name': name,
        'address': address,
        'interval_seconds': interval_seconds,
        'ping_count': int(defaults.get('ping_count', 4)),
        'timeout_seconds': int(defaults.get('timeout_seconds', 2)),
        'latency_threshold_ms': float(defaults.get('latency_threshold_ms', 100)),
        'packet_loss_threshold_pct': float(defaults.get('packet_loss_threshold_pct', 25)),
        'enabled': True,
    }
    hosts.append(record)
    save_intensive_config(config)
    return record


def delete_configured_host(host_id: str) -> bool:
    """Remove a host from intensive_hosts.json. Returns True if it existed."""
    config = load_intensive_config()
    hosts = config.get('hosts') or []
    kept = [h for h in hosts if not (isinstance(h, dict) and str(h.get('id')) == host_id)]
    if len(kept) == len(hosts):
        return False
    config['hosts'] = kept
    save_intensive_config(config)
    return True


def fetch_history(host_id: str, since_iso: str, db_path: str | None = None) -> list[dict]:
    """Return ping rows for host_id at or after since_iso, oldest first."""
    conn = init_db(db_path)
    with _lock:
        rows = conn.execute(
            """
            SELECT ts, host_id, host_name, address, status, latency_ms, packet_loss_pct,
                   packets_sent, packets_received
            FROM ping_results
            WHERE host_id = ? AND ts >= ?
            ORDER BY ts ASC
            """,
            (host_id, since_iso),
        ).fetchall()
    return [dict(row) for row in rows]


def fetch_latest_by_host(db_path: str | None = None) -> dict[str, dict]:
    """Return the newest ping row per host_id."""
    conn = init_db(db_path)
    with _lock:
        rows = conn.execute(
            """
            SELECT p.ts, p.host_id, p.host_name, p.address, p.status, p.latency_ms, p.packet_loss_pct
            FROM ping_results p
            INNER JOIN (
                SELECT host_id, MAX(ts) AS max_ts
                FROM ping_results
                GROUP BY host_id
            ) latest ON p.host_id = latest.host_id AND p.ts = latest.max_ts
            """
        ).fetchall()
    return {row['host_id']: dict(row) for row in rows}


def fetch_hosts_from_db(db_path: str | None = None) -> list[dict]:
    """Distinct hosts that have at least one ping row."""
    conn = init_db(db_path)
    with _lock:
        rows = conn.execute(
            """
            SELECT host_id, host_name, address
            FROM ping_results
            GROUP BY host_id
            ORDER BY host_name ASC
            """
        ).fetchall()
    return [
        {
            'id': row['host_id'],
            'name': row['host_name'] or row['host_id'],
            'address': row['address'],
            'enabled': True,
        }
        for row in rows
    ]
