#!/usr/bin/env python3
"""
Migration script: Encrypt plaintext creds JSON files.

Run ONCE after deploying the encrypted app code.
The app must be stopped before running this script.

Usage:
    rc-service dashboard-nagios stop
    python3 migrate_encrypt_creds.py
    rc-service dashboard-nagios start
"""

import os
import sys
import json
import glob
import shutil
from datetime import datetime

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config')
SECRET_KEY_PATH = os.path.join(CONFIG_DIR, 'secret_key')
BACKUP_DIR = os.path.join(CONFIG_DIR, 'backups', f'creds_migration_{datetime.now().strftime("%Y%m%d_%H%M%S")}')

ENCRYPTED_MARKER = '__ENC__'

def load_fernet():
    from cryptography.fernet import Fernet
    import hashlib
    import base64

    if not os.path.exists(SECRET_KEY_PATH):
        print(f"ERROR: Secret key not found at {SECRET_KEY_PATH}")
        print("Start the app once to generate it, then stop and run this script.")
        sys.exit(1)

    with open(SECRET_KEY_PATH, 'r') as f:
        secret_key = f.read().strip()

    key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
    return Fernet(key)


def is_already_encrypted(data):
    for value in data.values():
        if isinstance(value, str) and value.startswith(ENCRYPTED_MARKER):
            return True
    return False


def encrypt_dict(fernet, data):
    encrypted = {}
    for key, value in data.items():
        if isinstance(value, str):
            encrypted[key] = ENCRYPTED_MARKER + fernet.encrypt(value.encode()).decode()
        else:
            encrypted[key] = value
    return encrypted


def migrate_file(fernet, filepath):
    filename = os.path.basename(filepath)
    print(f"  Processing: {filename}")

    with open(filepath, 'r') as f:
        data = json.load(f)

    if is_already_encrypted(data):
        print(f"    SKIP (already encrypted)")
        return False

    # Backup
    backup_path = os.path.join(BACKUP_DIR, filename)
    shutil.copy2(filepath, backup_path)
    print(f"    Backup: {backup_path}")

    # Encrypt
    encrypted_data = encrypt_dict(fernet, data)
    with open(filepath, 'w') as f:
        json.dump(encrypted_data, f)

    print(f"    DONE — encrypted {len(encrypted_data)} field(s)")
    return True


def main():
    print("=" * 50)
    print("  Creds Migration — Encrypt Plaintext JSON")
    print("=" * 50)
    print()

    fernet = load_fernet()
    print(f"Secret key loaded from: {SECRET_KEY_PATH}")
    print()

    # Create backup directory
    os.makedirs(BACKUP_DIR, exist_ok=True)
    print(f"Backup directory: {BACKUP_DIR}")
    print()

    migrated = 0
    skipped = 0

    # 1. nagios_creds_*.json
    creds_files = glob.glob(os.path.join(CONFIG_DIR, 'nagios_creds_*.json'))
    print(f"Found {len(creds_files)} nagios_creds file(s):")
    for filepath in sorted(creds_files):
        if migrate_file(fernet, filepath):
            migrated += 1
        else:
            skipped += 1
    print()

    # 2. user_passwords.json
    pwd_file = os.path.join(CONFIG_DIR, 'user_passwords.json')
    if os.path.exists(pwd_file):
        print("Found user_passwords.json:")
        if migrate_file(fernet, pwd_file):
            migrated += 1
        else:
            skipped += 1
    else:
        print("No user_passwords.json found (skipping)")
    print()

    print("=" * 50)
    print(f"  Migration complete!")
    print(f"  Migrated: {migrated} file(s)")
    print(f"  Skipped:  {skipped} file(s)")
    print(f"  Backups:  {BACKUP_DIR}")
    print("=" * 50)
    print()
    print("You can now start the app:")
    print("  rc-service dashboard-nagios start")


if __name__ == '__main__':
    main()
