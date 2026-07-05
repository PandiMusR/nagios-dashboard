from __future__ import annotations

from flask import Blueprint, Response, render_template, request, redirect, session, jsonify, flash
import json, subprocess
from ldap3 import MODIFY_ADD

from services.config import LDAP_BASE_DN
from services.ldap_service import get_ldap_admin_connection
from services.shared_helpers import get_nagios_servers, get_monitoring_categories
from utils.permissions import load_user_permissions, get_default_permissions, save_user_permissions, save_user_password, get_user_password, check_permission

users_bp = Blueprint('users', __name__)


@users_bp.route('/users')
def users() -> str | Response:
    """GET /users — List all LDAP users."""
    if 'username' not in session:
        return redirect('/')

    if not check_permission('users'):
        flash('Access denied. You do not have permission to access this page.', 'error')
        return redirect('/dashboard')

    user_list = []
    try:
        conn = get_ldap_admin_connection()
        conn.search('ou=users,dc=bnet,dc=id', '(objectClass=inetOrgPerson)', attributes=['uid', 'cn', 'sn'])

        for entry in conn.entries:
            user_list.append({
                'uid': str(entry.uid),
                'cn': str(entry.cn),
                'sn': str(entry.sn),
                'dn': entry.entry_dn
            })
        conn.unbind()
    except Exception as e:
        flash(f'Error loading users: {str(e)}', 'error')

    return render_template('users.html', username=session['username'], users=user_list, nagios_servers=get_nagios_servers(), monitoring_categories=get_monitoring_categories())


@users_bp.route('/user-permissions')
def user_permissions() -> str | Response:
    """GET /user-permissions — Manage user permission assignments."""
    if 'username' not in session:
        return redirect('/')

    if session.get('role') != 'admin':
        flash('Access denied. Only administrators can manage user permissions.', 'error')
        return redirect('/dashboard')

    user_list = []
    try:
        conn = get_ldap_admin_connection()

        conn.search('ou=groups,dc=bnet,dc=id', '(cn=nagiosadmins)', attributes=['member'])
        admin_members = []
        if conn.entries:
            admin_members = [str(m) for m in conn.entries[0].member.values] if hasattr(conn.entries[0], 'member') else []

        conn.search('ou=users,dc=bnet,dc=id', '(objectClass=inetOrgPerson)', attributes=['uid'])

        for entry in conn.entries:
            uid = str(entry.uid)
            user_dn = f'uid={uid},ou=users,dc=bnet,dc=id'
            in_nagiosadmins = user_dn in admin_members

            perms = load_user_permissions(uid)

            if not perms or perms == get_default_permissions():
                is_admin = in_nagiosadmins
            else:
                is_admin = all([
                    perms.get('dashboard'),
                    perms.get('servers'),
                    perms.get('users'),
                    perms.get('host_manager'),
                    perms.get('monitoring_settings'),
                    perms.get('global_settings'),
                    perms.get('user_permissions')
                ])

            user_list.append({
                'uid': uid,
                'is_admin': is_admin,
                'permissions': perms
            })
        conn.unbind()
    except Exception as e:
        flash(f'Error loading users: {str(e)}', 'error')

    return render_template('user_permissions.html', username=session['username'],
                         users=user_list, users_json=json.dumps(user_list),
                         nagios_servers=get_nagios_servers(),
                         monitoring_categories=get_monitoring_categories())


@users_bp.route('/user-permissions/get/<username>')
def get_user_permissions_api(username: str) -> Response | tuple[Response, int]:
    """GET /user-permissions/get/<username> — Retrieve permissions for a user."""
    if 'username' not in session or session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        permissions = load_user_permissions(username)
        return jsonify({'permissions': permissions, 'username': username})
    except Exception as e:
        print(f"Error loading permissions for {username}: {e}")
        return jsonify({'error': str(e)}), 500


@users_bp.route('/user-permissions/update', methods=['POST'])
def update_user_permissions() -> Response:
    """POST /user-permissions/update — Save updated permissions for a user."""
    if 'username' not in session or session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 401

    username = request.form.get('username')
    permissions = {
        'dashboard': request.form.get('dashboard') == 'on',
        'host_manager': request.form.get('host_manager') == 'on',
        'servers': request.form.get('servers') == 'on',
        'users': request.form.get('users') == 'on',
        'user_permissions': request.form.get('user_permissions') == 'on',
        'monitoring_settings': request.form.get('monitoring_settings') == 'on',
        'global_settings': request.form.get('global_settings') == 'on',
        'cr_view_only': request.form.get('cr_view_only') == 'on'
    }
    for key in request.form:
        if key.startswith('monitoring_') or key.startswith('nagios_'):
            permissions[key] = request.form.get(key) == 'on'

    if save_user_permissions(username, permissions):
        password = get_user_password(username)
        if password:
            result = subprocess.run(['docker', 'ps', '--filter', 'ancestor=nagios-ldap:latest', '--format', '{{.Names}}'],
                                  capture_output=True, text=True, timeout=10)
            if result.stdout:
                for container in result.stdout.strip().split('\n'):
                    if container:
                        subprocess.run(['docker', 'exec', container, 'htpasswd', '-D', '/opt/nagios/etc/htpasswd.users', username],
                                     capture_output=True, timeout=10)
                        if permissions.get(f'nagios_{container}'):
                            subprocess.run(['docker', 'exec', container, 'htpasswd', '-b', '/opt/nagios/etc/htpasswd.users', username, password],
                                         capture_output=True, timeout=10)

        flash(f'Permissions updated for user "{username}"!', 'success')
    else:
        flash('Failed to update permissions!', 'error')

    return redirect('/user-permissions')


@users_bp.route('/users/add', methods=['POST'])
def add_user() -> Response:
    """POST /users/add — Create a new LDAP user."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    uid = request.form.get('uid')
    cn = request.form.get('cn')
    sn = request.form.get('sn')
    password = request.form.get('password')
    role = request.form.get('role', 'user')

    try:
        conn = get_ldap_admin_connection()

        user_dn = f'uid={uid},ou=users,{LDAP_BASE_DN}'
        uid_num = str(hash(uid) % 10000 + 1000)

        conn.add(user_dn, ['inetOrgPerson', 'posixAccount'], {
            'cn': cn,
            'sn': sn,
            'uid': uid,
            'userPassword': password,
            'uidNumber': uid_num,
            'gidNumber': uid_num,
            'homeDirectory': f'/home/{uid}'
        })

        group_dn = 'cn=nagiosadmins,ou=groups,dc=bnet,dc=id'
        conn.modify(group_dn, {'member': [(MODIFY_ADD, [user_dn])]})

        if role != 'admin':
            permissions = {
                'dashboard': request.form.get('dashboard') == 'on',
                'host_manager': request.form.get('host_manager') == 'on',
                'servers': request.form.get('servers') == 'on',
                'users': request.form.get('users') == 'on',
                'user_permissions': request.form.get('user_permissions') == 'on',
                'monitoring_settings': request.form.get('monitoring_settings') == 'on',
                'global_settings': request.form.get('global_settings') == 'on',
                'cr_view_only': request.form.get('cr_view_only') == 'on'
            }
            for key in request.form:
                if key.startswith('monitoring_') or key.startswith('nagios_'):
                    permissions[key] = request.form.get(key) == 'on'
            save_user_permissions(uid, permissions)

        conn.unbind()

        save_user_password(uid, password)

        result = subprocess.run(['docker', 'ps', '--filter', 'ancestor=nagios-ldap:latest', '--format', '{{.Names}}'],
                              capture_output=True, text=True, timeout=10)
        if result.stdout:
            for container in result.stdout.strip().split('\n'):
                if container:
                    if role == 'admin' or request.form.get(f'nagios_{container}') == 'on':
                        subprocess.run(['docker', 'exec', container, 'htpasswd', '-b', '/opt/nagios/etc/htpasswd.users', uid, password],
                                     capture_output=True, timeout=10)

        flash(f'User "{uid}" added successfully as {role}!', 'success')
    except Exception as e:
        flash(f'Failed to add user: {str(e)}', 'error')

    return redirect('/users')


@users_bp.route('/users/edit/<uid>', methods=['POST'])
def edit_user(uid: str) -> Response:
    """POST /users/edit/<uid> — Update an LDAP user's details."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    cn = request.form.get('cn')
    sn = request.form.get('sn')
    password = request.form.get('password')

    try:
        conn = get_ldap_admin_connection()

        user_dn = f'uid={uid},ou=users,{LDAP_BASE_DN}'
        changes = {}

        if cn:
            changes['cn'] = [('MODIFY_REPLACE', [cn])]
        if sn:
            changes['sn'] = [('MODIFY_REPLACE', [sn])]
        if password:
            changes['userPassword'] = [('MODIFY_REPLACE', [password])]
            save_user_password(uid, password)

        if changes:
            conn.modify(user_dn, changes)

        conn.unbind()
        flash(f'User "{uid}" updated successfully!', 'success')
    except Exception as e:
        flash(f'Failed to update user: {str(e)}', 'error')

    return redirect('/users')


@users_bp.route('/users/delete/<uid>', methods=['POST'])
def delete_user(uid: str) -> Response:
    """POST /users/delete/<uid> — Delete an LDAP user."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        conn = get_ldap_admin_connection()

        user_dn = f'uid={uid},ou=users,{LDAP_BASE_DN}'

        group_dn = 'cn=nagiosadmins,ou=groups,dc=bnet,dc=id'
        conn.modify(group_dn, {'member': [('MODIFY_DELETE', [user_dn])]})

        conn.delete(user_dn)

        conn.unbind()
        flash(f'User "{uid}" deleted successfully!', 'success')
    except Exception as e:
        flash(f'Failed to delete user: {str(e)}', 'error')

    return redirect('/users')
