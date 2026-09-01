from __future__ import annotations

import json
import os
import sqlite3
import threading

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_DIR = os.path.join(_APP_ROOT, 'config')
DEFAULT_DB_PATH = os.path.join(_CONFIG_DIR, 'host_stages.db')
DEFAULT_JSON_PATH = os.path.join(_CONFIG_DIR, 'host_stages.json')

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_conn_path: str | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS host_stages (
    container TEXT NOT NULL,
    hostname TEXT NOT NULL,
    stage TEXT NOT NULL,
    updated_at TEXT,
    updated_by TEXT,
    note TEXT,
    host_up_since TEXT,
    PRIMARY KEY (container, hostname)
);
CREATE INDEX IF NOT EXISTS idx_host_stages_stage ON host_stages (stage);
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS stage_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    container TEXT NOT NULL,
    hostname TEXT NOT NULL,
    user TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    stage TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stage_comments_host ON stage_comments (container, hostname, id);
"""

_UPSERT_SQL = """
INSERT INTO host_stages (
    container, hostname, stage, updated_at, updated_by, note, host_up_since
) VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(container, hostname) DO UPDATE SET
    stage = excluded.stage,
    updated_at = excluded.updated_at,
    updated_by = excluded.updated_by,
    note = excluded.note,
    host_up_since = excluded.host_up_since
"""


def _split_stage_key(stage_key: str) -> tuple[str, str]:
    if '__' not in stage_key:
        return '', stage_key
    container, hostname = stage_key.rsplit('__', 1)
    return container, hostname


def _row_to_info(row: sqlite3.Row) -> dict:
    return {
        'stage': row['stage'],
        'updated_at': row['updated_at'],
        'updated_by': row['updated_by'],
        'note': row['note'] if row['note'] is not None else '',
        'host_up_since': row['host_up_since'],
    }


def _comment_to_dict(row: sqlite3.Row) -> dict:
    return {
        'id': row['id'],
        'user': row['user'] if row['user'] is not None else '',
        'timestamp': row['timestamp'] if row['timestamp'] is not None else '',
        'stage': row['stage'] if row['stage'] is not None else '',
        'text': row['text'] if row['text'] is not None else '',
    }


def _apply_migrations(conn: sqlite3.Connection) -> None:
    conn.execute('INSERT OR IGNORE INTO schema_migrations (version) VALUES (1)')
    conn.commit()
    if conn.execute(
        'SELECT version FROM schema_migrations WHERE version = 2'
    ).fetchone():
        return
    rows = conn.execute(
        'SELECT container, hostname, stage, updated_at, updated_by, note '
        'FROM host_stages '
        'WHERE note IS NOT NULL AND TRIM(note) != \'\''
    ).fetchall()
    for row in rows:
        already = conn.execute(
            'SELECT 1 FROM stage_comments WHERE container = ? AND hostname = ? LIMIT 1',
            (row['container'], row['hostname']),
        ).fetchone()
        if already:
            continue
        conn.execute(
            'INSERT INTO stage_comments '
            '(container, hostname, user, timestamp, stage, text) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (
                row['container'],
                row['hostname'],
                row['updated_by'] or 'unknown',
                row['updated_at'] or '',
                row['stage'] or 'new',
                row['note'],
            ),
        )
    conn.execute('INSERT OR IGNORE INTO schema_migrations (version) VALUES (2)')
    conn.commit()


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.executescript(_SCHEMA)
    conn.commit()
    _apply_migrations(conn)
    return conn


def init_db(db_path: str | None = None) -> sqlite3.Connection:
    """Create host_stages.db if needed, enable WAL, and return a shared connection."""
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


def count_stages(db_path: str | None = None) -> int:
    conn = init_db(db_path)
    with _lock:
        row = conn.execute('SELECT COUNT(*) AS n FROM host_stages').fetchone()
        return int(row['n'] if row else 0)


def list_stage_rows(stage: str | None = None, db_path: str | None = None) -> list[dict]:
    conn = init_db(db_path)
    sql = (
        'SELECT container, hostname, stage, updated_at, updated_by, note, host_up_since '
        'FROM host_stages'
    )
    params: tuple = ()
    if stage:
        sql += ' WHERE stage = ?'
        params = (stage,)
    with _lock:
        rows = conn.execute(sql, params).fetchall()
    result = []
    for row in rows:
        info = _row_to_info(row)
        info['container'] = row['container']
        info['hostname'] = row['hostname']
        result.append(info)
    return result


def select_stage(container: str, hostname: str, db_path: str | None = None) -> dict | None:
    conn = init_db(db_path)
    with _lock:
        row = conn.execute(
            'SELECT container, hostname, stage, updated_at, updated_by, note, host_up_since '
            'FROM host_stages WHERE container = ? AND hostname = ?',
            (container, hostname),
        ).fetchone()
    return _row_to_info(row) if row else None


def upsert_stage(
    container: str,
    hostname: str,
    stage: str,
    updated_at: str | None = None,
    updated_by: str | None = None,
    note: str | None = None,
    host_up_since: str | None = None,
    db_path: str | None = None,
) -> None:
    conn = init_db(db_path)
    with _lock:
        conn.execute(
            _UPSERT_SQL,
            (
                container,
                hostname,
                stage or 'new',
                updated_at,
                updated_by,
                note if note is not None else '',
                host_up_since,
            ),
        )
        conn.commit()


def delete_stage(container: str, hostname: str, db_path: str | None = None) -> None:
    conn = init_db(db_path)
    with _lock:
        conn.execute(
            'DELETE FROM host_stages WHERE container = ? AND hostname = ?',
            (container, hostname),
        )
        conn.commit()


def list_comments(container: str, hostname: str, db_path: str | None = None) -> list[dict]:
    conn = init_db(db_path)
    with _lock:
        rows = conn.execute(
            'SELECT id, user, timestamp, stage, text '
            'FROM stage_comments WHERE container = ? AND hostname = ? '
            'ORDER BY id ASC',
            (container, hostname),
        ).fetchall()
    return [_comment_to_dict(row) for row in rows]


def append_comment(
    container: str,
    hostname: str,
    user: str,
    timestamp: str,
    stage: str,
    text: str,
    db_path: str | None = None,
) -> int:
    conn = init_db(db_path)
    with _lock:
        cursor = conn.execute(
            'INSERT INTO stage_comments '
            '(container, hostname, user, timestamp, stage, text) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (container, hostname, user, timestamp, stage, text),
        )
        conn.execute(
            'UPDATE host_stages SET note = ? WHERE container = ? AND hostname = ?',
            (text, container, hostname),
        )
        conn.commit()
        return int(cursor.lastrowid or 0)


def relocate_comments(
    old_container: str,
    old_hostname: str,
    new_container: str,
    new_hostname: str,
    db_path: str | None = None,
) -> None:
    conn = init_db(db_path)
    with _lock:
        conn.execute(
            'UPDATE stage_comments SET container = ?, hostname = ? '
            'WHERE container = ? AND hostname = ?',
            (new_container, new_hostname, old_container, old_hostname),
        )
        conn.commit()


def insert_stage_if_absent(
    container: str,
    hostname: str,
    stage: str,
    updated_at: str | None = None,
    updated_by: str | None = None,
    note: str | None = None,
    host_up_since: str | None = None,
    db_path: str | None = None,
) -> bool:
    conn = init_db(db_path)
    with _lock:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO host_stages (
                container, hostname, stage, updated_at, updated_by, note, host_up_since
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                container,
                hostname,
                stage or 'new',
                updated_at,
                updated_by,
                note if note is not None else '',
                host_up_since,
            ),
        )
        conn.commit()
        return cursor.rowcount == 1


def set_host_up_since_if_unset(
    container: str,
    hostname: str,
    host_up_since: str,
    db_path: str | None = None,
) -> bool:
    conn = init_db(db_path)
    with _lock:
        cursor = conn.execute(
            """
            UPDATE host_stages
            SET host_up_since = ?
            WHERE container = ? AND hostname = ?
              AND stage = 'watchlist'
              AND (host_up_since IS NULL OR host_up_since = '')
            """,
            (host_up_since, container, hostname),
        )
        conn.commit()
        return cursor.rowcount > 0


def clear_host_up_since(container: str, hostname: str, db_path: str | None = None) -> None:
    conn = init_db(db_path)
    with _lock:
        conn.execute(
            """
            UPDATE host_stages
            SET host_up_since = NULL
            WHERE container = ? AND hostname = ?
            """,
            (container, hostname),
        )
        conn.commit()


def import_from_json(json_path: str | None = None, db_path: str | None = None) -> int:
    """Insert rows from host_stages.json. Returns the number of keys imported."""
    path = json_path or DEFAULT_JSON_PATH
    with open(path, 'r') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError('host_stages.json root must be an object')
    imported = 0
    for key, info in data.items():
        if not isinstance(info, dict):
            continue
        container, hostname = _split_stage_key(str(key))
        upsert_stage(
            container,
            hostname,
            info.get('stage') or 'new',
            updated_at=info.get('updated_at'),
            updated_by=info.get('updated_by'),
            note=info.get('note') if info.get('note') is not None else '',
            host_up_since=info.get('host_up_since'),
            db_path=db_path,
        )
        imported += 1
    return imported


def integrity_ok(db_path: str | None = None) -> bool:
    conn = init_db(db_path)
    with _lock:
        row = conn.execute('PRAGMA integrity_check').fetchone()
    return bool(row) and str(row[0]) == 'ok'
