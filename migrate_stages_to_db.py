#!/usr/bin/env python3
"""
One-off migration: copy config/host_stages.json into config/host_stages.db.

Run on Dev (or Prod later) before relying on SQLite-backed stage_service.
Does not import services.config (avoids LDAP_ADMIN_PASSWORD).

Usage:
    python3 migrate_stages_to_db.py
"""

from __future__ import annotations

import os
import sys

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from services.stage_db import (  # noqa: E402
    DEFAULT_DB_PATH,
    DEFAULT_JSON_PATH,
    count_stages,
    import_from_json,
    init_db,
    integrity_ok,
    list_stage_rows,
)

MIGRATED_SUFFIX = '.migrated'


def main() -> int:
    json_path = DEFAULT_JSON_PATH
    db_path = DEFAULT_DB_PATH
    migrated_path = json_path + MIGRATED_SUFFIX

    print('==================================================')
    print('  Stage Migration — JSON to SQLite (WAL)')
    print('==================================================')
    print()
    print(f'  JSON: {json_path}')
    print(f'  DB:   {db_path}')
    print()

    if not os.path.exists(json_path):
        if os.path.exists(migrated_path):
            print(f'{json_path} not found (already renamed to {migrated_path}).')
            print('SQLite is the source of truth. Re-run is a no-op.')
            init_db(db_path)
            print(f'  DB rows: {count_stages(db_path)}')
            return 0
        print(f'ERROR: {json_path} not found. Nothing to migrate.')
        return 1

    init_db(db_path)
    existing = count_stages(db_path)
    if existing:
        print(f'SKIP: database already has {existing} row(s). JSON was not imported.')
        print('Delete host_stages.db first if you need to re-import.')
        return 0

    try:
        imported = import_from_json(json_path=json_path, db_path=db_path)
    except (OSError, ValueError) as e:
        print(f'ERROR: failed to import JSON: {e}')
        return 1

    if not integrity_ok(db_path):
        print('ERROR: PRAGMA integrity_check failed after import.')
        return 1

    db_rows = list_stage_rows(db_path=db_path)
    if len(db_rows) != imported:
        print(f'ERROR: imported {imported} JSON key(s) but DB has {len(db_rows)} row(s).')
        return 1

    os.replace(json_path, migrated_path)
    print(f'Imported {imported} stage(s).')
    print(f'Renamed JSON to: {migrated_path}')
    print()
    print('==================================================')
    print('  Migration complete')
    print('==================================================')
    return 0


if __name__ == '__main__':
    sys.exit(main())
