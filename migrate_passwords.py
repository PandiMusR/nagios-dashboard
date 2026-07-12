#!/usr/bin/env python3
"""Encrypt plaintext password fields in global_config.json.

Idempotent — skips fields already prefixed with __ENC__.
Backs up original to <input>.migration-backup before modifying.

Usage:
    python3 migrate_passwords.py              # encrypt all password fields
    python3 migrate_passwords.py --dry-run    # show what would change
"""
import json
import os
import sys
import argparse
from datetime import datetime

PROD_CONFIG = '/svr/dashboard-nagios/config/global_config.json'

PASSWORD_FIELDS = [
    'nextcloud_password',
    'uptime_kuma_password',
    'password',
]


def bootstrap_fernet(config_dir: str):
    import base64
    import hashlib
    from cryptography.fernet import Fernet
    secret_key_path = os.path.join(config_dir, 'secret_key')
    with open(secret_key_path, 'r') as f:
        secret_key = f.read().strip()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
    return Fernet(key)


def main():
    parser = argparse.ArgumentParser(description='Encrypt passwords in global_config.json')
    parser.add_argument('--dry-run', action='store_true', help='Show changes without modifying the file')
    args = parser.parse_args()

    # Try prod path first, fall back to dev
    config_path = PROD_CONFIG if os.path.exists(PROD_CONFIG) else 'config/global_config.json'
    if not os.path.exists(config_path):
        print(f'ERROR: {config_path} not found', file=sys.stderr)
        sys.exit(1)

    config_dir = os.path.dirname(os.path.abspath(config_path))
    fernet = bootstrap_fernet(config_dir)
    ENCRYPTED_MARKER = '__ENC__'

    with open(config_path, 'r') as f:
        config = json.load(f)

    changed = []
    for field in PASSWORD_FIELDS:
        value = config.get(field)
        if value and isinstance(value, str) and not value.startswith(ENCRYPTED_MARKER):
            if args.dry_run:
                print(f'  WOULD encrypt: {field} ({value[:4]}... -> __ENC__...)')
            else:
                config[field] = ENCRYPTED_MARKER + fernet.encrypt(value.encode()).decode()
                changed.append(field)
                print(f'  Encrypted: {field} ({value[:4]}... -> {config[field][:14]}...)')

    if not changed and not args.dry_run:
        print('No plaintext passwords found — already migrated.')
        return

    if args.dry_run:
        if not changed and not any(
            config.get(f, '') and isinstance(config.get(f, ''), str) and not str(config.get(f, '')).startswith(ENCRYPTED_MARKER)
            for f in PASSWORD_FIELDS
        ):
            print('No plaintext passwords found — nothing to migrate.')
        return

    if not args.dry_run:
        # Backup
        backup_path = config_path + '.migration-backup'
        with open(backup_path, 'w') as f:
            json.dump(config if not changed else {}, f, indent=2)
        # Reload original for backup since we modified config in-place
        with open(config_path, 'r') as f:
            original = json.load(f)
        # Re-apply encryption to backup too (save encrypted version)
        for field in PASSWORD_FIELDS:
            value = original.get(field)
            if value and isinstance(value, str) and not value.startswith(ENCRYPTED_MARKER):
                original[field] = ENCRYPTED_MARKER + fernet.encrypt(value.encode()).decode()
        with open(backup_path, 'w') as f:
            json.dump(original, f, indent=2)
        print(f'Backup saved to {backup_path}')

        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        print(f'Encrypted {len(changed)} field(s): {", ".join(changed)}')
        print('Migration complete.')


if __name__ == '__main__':
    main()
