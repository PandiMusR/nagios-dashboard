from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timezone
from functools import wraps

from flask import session, request, abort as flask_abort

from services.config import CONFIG_DIR, USER_PERMISSIONS_PATH, MONITORING_CONFIG_PATH
from services.encryption import save_encrypted_json, load_encrypted_json

logger = logging.getLogger('nagiosDashboard')

AUDIT_LOG_PATH = os.path.join(CONFIG_DIR, 'permission_audit.log')


def _get_permission_check_mode() -> str:
    try:
        if os.path.exists(MONITORING_CONFIG_PATH):
            with open(MONITORING_CONFIG_PATH, 'r') as f:
                config = json.load(f)
                return config.get('permission_check_mode', 'audit')
    except (json.JSONDecodeError, OSError):
        pass
    return 'audit'


def _log_permission_denial(permission: str, username: str) -> None:
    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'username': username,
        'permission': permission,
        'route': request.path,
        'method': request.method,
        'remote_addr': request.remote_addr,
    }
    try:
        with open(AUDIT_LOG_PATH, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except OSError:
        pass


def load_user_permissions(username: str) -> dict:
    try:
        if os.path.exists(USER_PERMISSIONS_PATH):
            with open(USER_PERMISSIONS_PATH, 'r') as f:
                all_perms = json.load(f)
                return all_perms.get(username, get_default_permissions())
    except (json.JSONDecodeError, OSError):
        pass
    return get_default_permissions()


def get_default_permissions() -> dict:
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
    try:
        pwd_file = f'{CONFIG_DIR}/user_passwords.json'
        if os.path.exists(pwd_file):
            passwords = load_encrypted_json(pwd_file)
            return passwords.get(username)
    except (json.JSONDecodeError, OSError):
        pass
    return None


def check_permission(permission: str) -> bool:
    if session.get('role') == 'admin':
        return True

    has_permission = session.get('permissions', {}).get(permission, False)

    if not has_permission:
        mode = _get_permission_check_mode()
        username = session.get('username', 'unknown')
        _log_permission_denial(permission, username)

        if mode == 'enforce':
            logger.warning(
                'Permission denied: %s -> %s (%s %s)',
                username, permission, request.method, request.path
            )
            return False

        logger.info(
            'AUDIT: would deny %s -> %s (%s %s)',
            username, permission, request.method, request.path
        )
        return True

    return True


def permission_required(permission: str):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'username' not in session:
                flask_abort(401)
            if not check_permission(permission):
                flask_abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator
