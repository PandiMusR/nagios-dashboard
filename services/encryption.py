from __future__ import annotations

import os
import json
import base64
import secrets
import hashlib
from cryptography.fernet import Fernet

from services.config import CONFIG_DIR

SECRET_KEY_PATH = os.path.join(CONFIG_DIR, 'secret_key')


def load_or_create_secret_key() -> str:
    """Load the secret key from disk or generate and persist a new one."""
    if os.path.exists(SECRET_KEY_PATH):
        with open(SECRET_KEY_PATH, 'r') as f:
            key = f.read().strip()
            if len(key) >= 32:
                return key
    key = secrets.token_hex(32)
    os.makedirs(os.path.dirname(SECRET_KEY_PATH), exist_ok=True)
    with open(SECRET_KEY_PATH, 'w') as f:
        f.write(key)
    return key


_fernet: Fernet | None = None


def init_encryption(secret_key: str) -> None:
    """Initialize the global Fernet instance from the given secret key."""
    global _fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
    _fernet = Fernet(key)


def encrypt_session_value(value: str | None) -> str | None:
    """Encrypt a session value, returning None if the input is None."""
    if value is None:
        return None
    return _fernet.encrypt(value.encode()).decode()


def decrypt_session_value(token: str | None) -> str | None:
    """Decrypt a session token, returning None on failure or None input."""
    if token is None:
        return None
    try:
        return _fernet.decrypt(token.encode()).decode()
    except Exception:
        return None


ENCRYPTED_MARKER = '__ENC__'


def encrypt_value(value: str) -> str:
    """Encrypt a single value and prefix with __ENC__ marker."""
    return ENCRYPTED_MARKER + _fernet.encrypt(value.encode()).decode()


def decrypt_value(value: str) -> str:
    """Decrypt a single value, falling back to plaintext if not encrypted.

    Safe to call on both encrypted and plaintext values — if the value
    doesn't have the __ENC__ marker, it's returned as-is with a warning.
    """
    if not isinstance(value, str):
        return value
    if not value.startswith(ENCRYPTED_MARKER):
        import logging
        logging.getLogger('nagiosDashboard').warning(
            'Value is not encrypted (missing __ENC__ prefix). '
            'Run migrate_passwords.py to encrypt.'
        )
        return value
    try:
        return _fernet.decrypt(value[len(ENCRYPTED_MARKER):].encode()).decode()
    except Exception:
        return value


def save_encrypted_json(filepath: str, data: dict) -> None:
    """Save a dict to JSON, encrypting all string values at rest."""
    encrypted_data = {}
    for key, value in data.items():
        if isinstance(value, str):
            encrypted_data[key] = ENCRYPTED_MARKER + _fernet.encrypt(value.encode()).decode()
        else:
            encrypted_data[key] = value
    with open(filepath, 'w') as f:
        json.dump(encrypted_data, f)


def load_encrypted_json(filepath: str) -> dict:
    """Load a JSON file, decrypting any encrypted string values."""
    with open(filepath, 'r') as f:
        data = json.load(f)
    decrypted = {}
    for key, value in data.items():
        if isinstance(value, str) and value.startswith(ENCRYPTED_MARKER):
            try:
                decrypted[key] = _fernet.decrypt(value[len(ENCRYPTED_MARKER):].encode()).decode()
            except Exception:
                decrypted[key] = value
        else:
            decrypted[key] = value
    return decrypted
