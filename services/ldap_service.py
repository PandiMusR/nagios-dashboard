from __future__ import annotations

import os
import subprocess
import json
from datetime import datetime

from flask import session, request
from ldap3 import Server, Connection, ALL

from services.config import LDAP_SERVER, LDAP_BASE_DN, LDAP_ADMIN_DN, LDAP_ADMIN_PASSWORD, CONFIG_DIR, ACTIVITY_LOG_PATH
from utils.permissions import load_user_permissions, get_default_permissions

ACTIVITY_LOG_DIR = f'{CONFIG_DIR}/activity_logs'


def get_ldap_admin_connection() -> Connection:
    """Return an authenticated LDAP connection using the admin service account."""
    server = Server(LDAP_SERVER, get_info=ALL)
    return Connection(server, LDAP_ADMIN_DN, LDAP_ADMIN_PASSWORD, auto_bind=True)


def check_ldap_server() -> str:
    """Check the LDAP Docker container status, creating or starting it if needed."""
    try:
        result = subprocess.run(['docker', 'ps', '-a', '--filter', 'name=ldap-server', '--format', '{{.Names}}'],
                                capture_output=True, text=True)

        if not result.stdout.strip():
            print("LDAP container not found. Creating LDAP server...")
            subprocess.run([
                'docker', 'run', '-d',
                '--name', 'ldap-server',
                '--restart', 'always',
                '-p', '1389:389',
                '-e', 'LDAP_ORGANISATION=BNET',
                '-e', 'LDAP_DOMAIN=bnet.id',
                '-e', 'LDAP_ADMIN_PASSWORD=admin',
                'osixia/openldap:latest'
            ], check=True)
            print("LDAP server created. Waiting for initialization...")
            import time
            time.sleep(5)
            return 'created'

        result = subprocess.run(['docker', 'ps', '--filter', 'name=ldap-server', '--format', '{{.Names}}'],
                                capture_output=True, text=True)

        if not result.stdout.strip():
            print("LDAP server is stopped. Starting...")
            subprocess.run(['docker', 'start', 'ldap-server'], check=True)
            import time
            time.sleep(3)
            return 'started'

        return 'running'
    except Exception as e:
        print(f"Error checking LDAP server: {e}")
        return 'error'


def setup_ldap_structure() -> bool:
    """Create the base LDAP organizational units and groups."""
    try:
        from ldap3 import MODIFY_ADD
        import time
        time.sleep(2)

        conn = get_ldap_admin_connection()

        try:
            conn.add('ou=users,dc=bnet,dc=id', ['organizationalUnit'])
        except Exception:
            pass

        try:
            conn.add('ou=groups,dc=bnet,dc=id', ['organizationalUnit'])
        except Exception:
            pass

        try:
            conn.add('cn=nagiosadmins,ou=groups,dc=bnet,dc=id', ['groupOfNames'], {'member': 'cn=admin,dc=bnet,dc=id'})
        except Exception:
            pass

        conn.unbind()
        return True
    except Exception as e:
        print(f"Error setting up LDAP structure: {e}")
        return False


def check_admin_user_exists() -> bool:
    """Check whether any user entries exist under the LDAP users OU."""
    try:
        conn = get_ldap_admin_connection()
        conn.search('ou=users,dc=bnet,dc=id', '(objectClass=inetOrgPerson)')
        has_users = len(conn.entries) > 0
        conn.unbind()
        return has_users
    except Exception:
        return False


def log_activity(action: str, details: str = '', username: str | None = None, ip: str | None = None) -> None:
    """Append an entry to the monthly activity log file."""
    try:
        now = datetime.now()
        timestamp = now.strftime('%Y-%m-%d %H:%M:%S')
        if username is None:
            username = session.get('username', 'Unknown')
        if ip is None:
            ip = request.remote_addr
        log_entry = f"{timestamp} - User: {username} - IP: {ip} - Action: {action}"
        if details:
            log_entry += f" - Details: {details}"
        log_entry += '\n'

        # Write to monthly file: activity_logs/activity_log_2026_06.txt
        import os
        os.makedirs(ACTIVITY_LOG_DIR, exist_ok=True)
        monthly_file = f'{ACTIVITY_LOG_DIR}/activity_log_{now.strftime("%Y_%m")}.txt'
        with open(monthly_file, 'a') as f:
            f.write(log_entry)
    except Exception as e:
        print(f"Failed to log activity: {e}")


def read_activity_logs(max_lines: int = 500) -> str:
    """Read activity logs from all monthly files (newest first, up to max_lines).

    Returns concatenated log content from the most recent entries across all months.
    Files are read newest-month-first, and within each file lines are read
    newest-first so the most recent entries always appear.
    """
    import glob as glob_mod

    # Find all monthly log files, sorted newest first
    pattern = f'{ACTIVITY_LOG_DIR}/activity_log_*.txt'
    files = sorted(glob_mod.glob(pattern), reverse=True)

    # Also include legacy single file if it exists
    legacy = ACTIVITY_LOG_PATH
    if os.path.exists(legacy) and legacy not in files:
        files.append(legacy)

    all_lines: list[str] = []
    for filepath in files:
        try:
            with open(filepath, 'r') as f:
                lines = f.readlines()
                # Reverse so newest entries come first
                all_lines.extend(reversed(lines))
            if len(all_lines) >= max_lines:
                break
        except OSError:
            continue

    # Take first N (newest) — already in newest-first order
    return ''.join(all_lines[:max_lines])


def ldap_auth(username: str, password: str) -> dict:
    """Authenticate a user against LDAP and return their role."""
    try:
        server = Server(LDAP_SERVER, get_info=ALL)
        user_dn = f'uid={username},ou=users,{LDAP_BASE_DN}'

        conn = Connection(server, user_dn, password, auto_bind=True)
        conn.unbind()

        user_perms = load_user_permissions(username)

        if not user_perms or user_perms == get_default_permissions():
            admin_conn = get_ldap_admin_connection()
            admin_conn.search('ou=groups,dc=bnet,dc=id', f'(member={user_dn})', attributes=['cn'])

            role = 'user'
            if admin_conn.entries:
                for entry in admin_conn.entries:
                    group_name = str(entry.cn.value) if hasattr(entry.cn, 'value') else str(entry.cn)
                    if 'nagiosadmins' in group_name.lower():
                        role = 'admin'
                        break
            admin_conn.unbind()
        else:
            is_admin = all([
                user_perms.get('dashboard'),
                user_perms.get('servers'),
                user_perms.get('users'),
                user_perms.get('host_manager'),
                user_perms.get('monitoring_settings'),
                user_perms.get('global_settings'),
                user_perms.get('user_permissions')
            ])
            role = 'admin' if is_admin else 'user'

        return {'authenticated': True, 'role': role}
    except Exception as e:
        print(f"LDAP Auth Error: {e}")
        return {'authenticated': False, 'role': None}
