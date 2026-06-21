from __future__ import annotations

import os
import json

from flask import session

from services.config import CONFIG_DIR, USER_PERMISSIONS_PATH
from services.encryption import save_encrypted_json, load_encrypted_json


def load_user_permissions(username: str) -> dict:
    """Load user permissions from file"""
    try:
        if os.path.exists(USER_PERMISSIONS_PATH):
            with open(USER_PERMISSIONS_PATH, 'r') as f:
                all_perms = json.load(f)
                return all_perms.get(username, get_default_permissions())
    except (json.JSONDecodeError, OSError):
        pass
    return get_default_permissions()


def get_default_permissions() -> dict:
    """Default permissions for regular users"""
    return {
        'dashboard': True,
        'monitoring': True,
        'nagios': False,
        'servers': False,
        'users': False,
        'host_manager': False,
        'monitoring_settings': False,
        'global_settings': False,
        'user_permissions': False,
        'cr_view_only': False
    }


def save_user_permissions(username: str, permissions: dict) -> bool:
    """Save user permissions to file"""
    try:
        all_perms = {}
        if os.path.exists(USER_PERMISSIONS_PATH):
            with open(USER_PERMISSIONS_PATH, 'r') as f:
                all_perms = json.load(f)
        
        all_perms[username] = permissions
        
        with open(USER_PERMISSIONS_PATH, 'w') as f:
            json.dump(all_perms, f)
        return True
    except (OSError, ValueError):
        return False


def save_user_password(username: str, password: str) -> bool:
    """Save user password for htpasswd sync (encrypted at rest)"""
    try:
        pwd_file = f'{CONFIG_DIR}/user_passwords.json'
        passwords = {}
        if os.path.exists(pwd_file):
            passwords = load_encrypted_json(pwd_file)
        passwords[username] = password
        save_encrypted_json(pwd_file, passwords)
        return True
    except (OSError, ValueError):
        return False


def get_user_password(username: str) -> str | None:
    """Get user password for htpasswd sync (decrypted)"""
    try:
        pwd_file = f'{CONFIG_DIR}/user_passwords.json'
        if os.path.exists(pwd_file):
            passwords = load_encrypted_json(pwd_file)
            return passwords.get(username)
    except (json.JSONDecodeError, OSError):
        pass
    return None


def check_permission(permission: str) -> bool:
    """Check if user has permission"""
    if session.get('role') == 'admin':
        return True
    return session.get('permissions', {}).get(permission, False)
