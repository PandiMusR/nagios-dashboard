from __future__ import annotations

from flask import Blueprint, Response, render_template, request, redirect, session, jsonify, flash
import os, json, subprocess, base64
from datetime import datetime
from ldap3 import Server, Connection, ALL

from services.config import LDAP_SERVER, LDAP_BASE_DN, LDAP_ADMIN_DN, HOST_STAGES_PATH, MONITORING_CATEGORIES_PATH, MONITORING_SERVER_MAPPINGS_PATH, MONITORING_CONFIG_PATH
from services.encryption import encrypt_session_value, decrypt_session_value
from services.ldap_service import get_ldap_admin_connection, check_admin_user_exists, ldap_auth, log_activity, check_ldap_server, setup_ldap_structure
from services.active_users import active_users
from utils.permissions import load_user_permissions, get_default_permissions

auth_bp = Blueprint('auth', __name__)


def _get_nagios_servers() -> list[str]:
    """Return list of running Nagios container names."""
    import subprocess
    result = subprocess.run(['docker', 'ps', '--filter', 'ancestor=nagios-ldap:latest', '--format', '{{.Names}}'],
                          capture_output=True, text=True)
    return result.stdout.strip().split('\n') if result.stdout.strip() else []


def _get_monitoring_categories() -> list[str]:
    """Collect and return deduplicated monitoring category names from config files."""
    categories = []
    seen = set()

    def add_category(value: object) -> None:
        if not isinstance(value, str):
            return
        normalized = value.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            categories.append(normalized)

    for default_category in ['prioritas', 'bhome', 'diskominfo']:
        add_category(default_category)

    for path in [MONITORING_CATEGORIES_PATH, MONITORING_SERVER_MAPPINGS_PATH, MONITORING_CONFIG_PATH]:
        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            add_category(item)
                    elif isinstance(data, dict):
                        for key in data.keys():
                            add_category(key)
                        for key in data.get('category_settings', {}).keys():
                            add_category(key)
                        for key in data.get('alarm_settings', {}).keys():
                            add_category(key)
        except (json.JSONDecodeError, OSError):
            pass
    return categories


@auth_bp.route('/health')
def health() -> tuple[Response, int]:
    """GET /health — Health check for LDAP, host stages file, and Nagios containers."""
    checks = {}
    all_ok = True

    # 1. LDAP connectivity
    try:
        conn = get_ldap_admin_connection()
        conn.unbind()
        checks['ldap'] = 'ok'
    except Exception as e:
        checks['ldap'] = f'error: {e}'
        all_ok = False

    # 2. Host stages file accessible
    try:
        if os.path.exists(HOST_STAGES_PATH):
            with open(HOST_STAGES_PATH, 'r') as f:
                json.load(f)
            checks['host_stages'] = 'ok'
        else:
            checks['host_stages'] = 'missing (will be created on first use)'
    except Exception as e:
        checks['host_stages'] = f'error: {e}'
        all_ok = False

    # 3. At least one Nagios container running
    try:
        result = subprocess.run(['docker', 'ps', '--filter', 'ancestor=nagios-ldap:latest', '--format', '{{.Names}}'],
                                capture_output=True, text=True, timeout=10)
        containers = [c for c in result.stdout.strip().split('\n') if c]
        if containers:
            checks['nagios_containers'] = f'ok ({len(containers)} running)'
        else:
            checks['nagios_containers'] = 'warning: no containers running'
    except Exception as e:
        checks['nagios_containers'] = f'error: {e}'
        all_ok = False

    status_code = 200 if all_ok else 503
    return jsonify({'status': 'healthy' if all_ok else 'degraded', 'checks': checks}), status_code


@auth_bp.route('/')
def index() -> str | Response:
    """GET / — Root redirect to dashboard, setup, or login page."""
    if 'username' in session:
        return redirect('/dashboard')
    
    # Check if first time setup needed (no users AND LDAP ready)
    try:
        if not check_admin_user_exists():
            return redirect('/setup')
    except Exception:
        # If LDAP not ready, show login page with error
        return render_template('login.html', error='LDAP server not ready. Please wait...')
    
    return render_template('login.html')


@auth_bp.route('/setup', methods=['GET', 'POST'])
def setup() -> str | Response:
    """GET/POST /setup — First-time admin account creation."""
    # Block setup if already has users
    if check_admin_user_exists():
        flash('Setup already completed. Please login.', 'info')
        return redirect('/')
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        cn = request.form.get('cn')
        sn = request.form.get('sn')
        
        try:
            from ldap3 import Server, Connection, ALL, MODIFY_ADD
            import time
            
            # Retry connection
            for attempt in range(5):
                try:
                    conn = get_ldap_admin_connection()
                    break
                except Exception as e:
                    if attempt < 4:
                        time.sleep(2)
                    else:
                        raise Exception(f"Cannot connect to LDAP: {str(e)}")
            
            # Ensure structure exists
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
            
            user_dn = f'uid={username},ou=users,{LDAP_BASE_DN}'
            uid_num = '1000'
            
            # Add user
            result = conn.add(user_dn, ['inetOrgPerson', 'posixAccount'], {
                'cn': cn,
                'sn': sn,
                'uid': username,
                'userPassword': password,
                'uidNumber': uid_num,
                'gidNumber': uid_num,
                'homeDirectory': f'/home/{username}'
            })
            
            if not result:
                raise Exception(f"Failed to add user: {conn.result}")
            
            # Add to nagiosadmins group (first user is always admin)
            group_dn = 'cn=nagiosadmins,ou=groups,dc=bnet,dc=id'
            conn.modify(group_dn, {'member': [(MODIFY_ADD, [user_dn])]})
            
            conn.unbind()
            flash(f'Administrator account "{username}" created successfully! Please login.', 'success')
            return redirect('/')
        except Exception as e:
            return render_template('setup.html', error=f'Failed to create user: {str(e)}')
    
    return render_template('setup.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login() -> str | Response:
    """GET/POST /login — Authenticate user via LDAP and start session."""
    if request.method == 'GET':
        if 'username' in session:
            return redirect('/dashboard')
        return render_template('login.html')
    
    # POST method
    username = request.form.get('username')
    password = request.form.get('password')
    
    auth_result = ldap_auth(username, password)
    if auth_result['authenticated']:
        session['username'] = username
        session['password'] = encrypt_session_value(password)
        session['role'] = auth_result['role']
        
        # Load user permissions
        user_perms = load_user_permissions(username)
        session['permissions'] = user_perms
        
        log_activity('Login', f'User {username} logged in successfully as {auth_result["role"]}')
        return redirect('/dashboard')
    log_activity('Login Failed', f'Failed login attempt for user {username}')
    return render_template('login.html', error='Invalid credentials')


@auth_bp.route('/logout')
def logout() -> Response:
    """GET /logout — Log out current user and clear session."""
    username = session.get('username')
    if username:
        active_users.remove(username)
    log_activity('Logout', f'User {username} logged out')
    session.pop('username', None)
    session.pop('password', None)
    return redirect('/')


@auth_bp.route('/api/change-password', methods=['POST'])
def change_password() -> Response | tuple[Response, int]:
    """POST /api/change-password — Change the current user's LDAP password."""
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        old_password = data.get('old_password')
        new_password = data.get('new_password')
        username = session.get('username')
        
        # Validate old password first
        auth_result = ldap_auth(username, old_password)
        if not auth_result['authenticated']:
            return jsonify({'success': False, 'message': 'Password lama tidak sesuai'}), 400
        
        # Change password in LDAP
        try:
            server = Server(LDAP_SERVER, get_info=ALL)
            user_dn = f'uid={username},ou=users,{LDAP_BASE_DN}'
            
            # Connect as the user first to change their own password
            conn = Connection(server, user_dn, old_password, auto_bind=True)
            
            # Use modify operation to change password
            from ldap3 import MODIFY_REPLACE
            conn.modify(user_dn, {'userPassword': [(MODIFY_REPLACE, [new_password])]})
            
            if conn.result['result'] == 0:  # Success
                conn.unbind()
                # Update session password
                session['password'] = encrypt_session_value(new_password)
                log_activity('Change Password', f'User {username} changed their password successfully')
                return jsonify({'success': True, 'message': 'Password berhasil diubah'})
            else:
                conn.unbind()
                error_msg = conn.result.get('description', 'Gagal mengubah password')
                return jsonify({'success': False, 'message': error_msg}), 400
                
        except Exception as e:
            print(f"LDAP Password Change Error: {e}")
            # If LDAP modify fails, try alternative method using bind
            try:
                # Some LDAP servers require binding with admin account
                admin_server = Server(LDAP_SERVER, get_info=ALL)
                admin_conn = get_ldap_admin_connection()
                
                from ldap3 import MODIFY_REPLACE
                admin_conn.modify(user_dn, {'userPassword': [(MODIFY_REPLACE, [new_password])]})
                
                if admin_conn.result['result'] == 0:
                    admin_conn.unbind()
                    session['password'] = encrypt_session_value(new_password)
                    log_activity('Change Password', f'User {username} changed their password successfully')
                    return jsonify({'success': True, 'message': 'Password berhasil diubah'})
                else:
                    admin_conn.unbind()
                    return jsonify({'success': False, 'message': 'Gagal mengubah password di server'}), 400
            except Exception as admin_error:
                print(f"Admin LDAP Password Change Error: {admin_error}")
                return jsonify({'success': False, 'message': 'Terjadi kesalahan pada server'}), 500
    
    except Exception as e:
        print(f"Change Password API Error: {e}")
        return jsonify({'success': False, 'message': 'Terjadi kesalahan pada server'}), 500


@auth_bp.route('/active-users')
def active_users_page() -> str | Response:
    """GET /active-users — Show currently active users (admin only, hidden page)."""
    if 'username' not in session:
        return redirect('/')
    if session.get('role') != 'admin':
        return jsonify({'error': 'Admin only'}), 403

    users = active_users.get_active_users()
    return render_template('active_users.html', users=users, total=len(users),
                         nagios_servers=_get_nagios_servers(), monitoring_categories=_get_monitoring_categories())


@auth_bp.route('/stage-history')
def stage_history_page() -> str | Response:
    """GET /stage-history — View stage change history."""
    if 'username' not in session:
        return redirect('/')

    from services.stage_history import read_stage_history
    from services.config import STAGE_LABELS

    host = request.args.get('host', '').strip() or None
    container = request.args.get('container', '').strip() or None
    limit = request.args.get('limit', '100').strip()
    try:
        limit = int(limit)
    except ValueError:
        limit = 100

    entries = read_stage_history(host=host, container=container, limit=limit)
    return render_template('stage_history.html', entries=entries, limit=limit, stage_labels=STAGE_LABELS,
                         nagios_servers=_get_nagios_servers(), monitoring_categories=_get_monitoring_categories())


@auth_bp.route('/activity-logs')
def activity_logs_page() -> str | Response:
    """GET /activity-logs — View user activity logs."""
    if 'username' not in session:
        return redirect('/')

    from services.ldap_service import read_activity_logs

    limit = request.args.get('limit', '500').strip()
    try:
        limit = int(limit)
    except ValueError:
        limit = 500

    logs = read_activity_logs(limit)
    return render_template('activity_logs.html', logs=logs, limit=limit,
                         nagios_servers=_get_nagios_servers(), monitoring_categories=_get_monitoring_categories())
