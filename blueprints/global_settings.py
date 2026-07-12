from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, session, jsonify, flash, send_file, Response
import os, json, subprocess
from datetime import datetime

from services.config import CONFIG_DIR, ACTIVITY_LOG_PATH, GLOBAL_CONFIG_PATH, MONITORING_SERVER_MAPPINGS_PATH, MONITORING_CONFIG_PATH
from services.ldap_service import log_activity, read_activity_logs, ACTIVITY_LOG_DIR
from services.shared_helpers import get_nagios_servers, get_monitoring_categories
from services.encryption import encrypt_value
from utils.permissions import check_permission

global_settings_bp = Blueprint('global_settings', __name__)


@global_settings_bp.route('/global-settings')
def global_settings() -> str | Response:
    """GET /global-settings — render the global settings page."""
    if 'username' not in session:
        return redirect('/')
    
    if not check_permission('global_settings'):
        flash('Access denied. You do not have permission to access this page.', 'error')
        return redirect('/dashboard')
    
    # Load global config
    global_config = {}
    try:
        if os.path.exists(GLOBAL_CONFIG_PATH):
            with open(GLOBAL_CONFIG_PATH, 'r') as f:
                global_config = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    
    categories = get_monitoring_categories()
    
    # Load server mappings
    server_mappings = {}
    try:
        if os.path.exists(MONITORING_SERVER_MAPPINGS_PATH):
            with open(MONITORING_SERVER_MAPPINGS_PATH, 'r') as f:
                server_mappings = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    
    # Load monitoring config
    monitoring_config = {'refresh_interval': 30, 'alarm_settings': {}}
    try:
        if os.path.exists(MONITORING_CONFIG_PATH):
            with open(MONITORING_CONFIG_PATH, 'r') as f:
                monitoring_config = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    
    # Get all nagios servers
    nagios_servers_list = get_nagios_servers()
    
    # Load activity logs
    activity_logs = read_activity_logs(500)
    
    return render_template('global_settings.html', username=session['username'],
                         global_config=global_config, activity_logs=activity_logs,
                         categories=categories, server_mappings=server_mappings,
                         monitoring_config=monitoring_config, nagios_servers_list=nagios_servers_list,
                         nagios_servers=get_nagios_servers(), 
                         monitoring_categories=get_monitoring_categories())


@global_settings_bp.route('/global-settings/backup', methods=['POST'])
def create_backup() -> str | Response:
    """POST /global-settings/backup — create a tar.gz backup of all configs."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('global_settings'):
        flash('Access denied.', 'error')
        return redirect('/dashboard')
    
    try:
        import tarfile
        from datetime import datetime
        
        backup_name = request.form.get('backup_name', '').strip()
        if not backup_name:
            backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        backup_dir = f'{CONFIG_DIR}/backups'
        os.makedirs(backup_dir, exist_ok=True)
        
        backup_file = f'{backup_dir}/{backup_name}.tar.gz'
        
        with tarfile.open(backup_file, 'w:gz') as tar:
            result = subprocess.run(['docker', 'ps', '--filter', 'ancestor=nagios-ldap:latest', '--format', '{{.Names}}'], 
                                  capture_output=True, text=True, timeout=10)
            if result.stdout:
                for server in result.stdout.strip().split('\n'):
                    if server:
                        config_path = f'/svr/{server}/etc/objects/localhost.cfg'
                        if os.path.exists(config_path):
                            tar.add(config_path, arcname=f'{server}/localhost.cfg')
        
        # Keep only last 10 backups
        backups = sorted([f for f in os.listdir(backup_dir) if f.endswith('.tar.gz')])
        if len(backups) > 10:
            for old_backup in backups[:-10]:
                os.remove(f'{backup_dir}/{old_backup}')
        
        log_activity('Create Backup', f'Backup "{backup_name}" created')
        flash(f'Backup "{backup_name}" created successfully!', 'success')
    except Exception as e:
        flash(f'Failed to create backup: {str(e)}', 'error')
    
    return redirect('/global-settings')


@global_settings_bp.route('/global-settings/backups')
def list_backups() -> Response | tuple[Response, int]:
    """GET /global-settings/backups — list all config backups as JSON."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('global_settings'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        backup_dir = f'{CONFIG_DIR}/backups'
        os.makedirs(backup_dir, exist_ok=True)
        
        backups = []
        for filename in sorted(os.listdir(backup_dir), reverse=True):
            if filename.endswith('.tar.gz'):
                filepath = os.path.join(backup_dir, filename)
                stat = os.stat(filepath)
                size = stat.st_size
                size_str = f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/1024/1024:.1f} MB"
                date_str = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                backups.append({
                    'name': filename.replace('.tar.gz', ''),
                    'date': date_str,
                    'size': size_str
                })
        
        return jsonify({'backups': backups})
    except Exception as e:
        return jsonify({'backups': [], 'error': str(e)})


@global_settings_bp.route('/global-settings/restore', methods=['POST'])
def restore_backup() -> Response | tuple[Response, int]:
    """POST /global-settings/restore — restore a tar.gz backup."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('global_settings'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        import tarfile
        data = request.get_json()
        backup_name = data.get('backup_name')
        
        backup_file = f'{CONFIG_DIR}/backups/{backup_name}.tar.gz'
        if not os.path.exists(backup_file):
            return jsonify({'success': False, 'error': 'Backup not found'})
        
        with tarfile.open(backup_file, 'r:gz') as tar:
            tar.extractall('/tmp/restore_temp', filter='data')
        
        for server_dir in os.listdir('/tmp/restore_temp'):
            server_path = f'/tmp/restore_temp/{server_dir}'
            if os.path.isdir(server_path):
                config_file = f'{server_path}/localhost.cfg'
                if os.path.exists(config_file):
                    dest = f'/svr/{server_dir}/etc/objects/localhost.cfg'
                    subprocess.run(['cp', config_file, dest], timeout=10)
                    subprocess.run(['docker', 'restart', server_dir], capture_output=True, timeout=60)
        
        subprocess.run(['rm', '-rf', '/tmp/restore_temp'], timeout=10)
        
        log_activity('Restore Backup', f'Backup "{backup_name}" restored')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@global_settings_bp.route('/global-settings/download-backup/<name>')
def download_backup(name: str) -> Response | tuple[Response, int]:
    """GET /global-settings/download-backup/<name> — download a backup file."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('global_settings'):
        return jsonify({'error': 'Access denied'}), 403
    
    backup_file = f'{CONFIG_DIR}/backups/{name}.tar.gz'
    if os.path.exists(backup_file):
        return send_file(backup_file, as_attachment=True)
    return jsonify({'error': 'Backup not found'}), 404


@global_settings_bp.route('/global-settings/delete-backup/<name>', methods=['DELETE'])
def delete_backup(name: str) -> tuple[dict, int]:
    """DELETE /global-settings/delete-backup/<name> — delete a backup file."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('global_settings'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        backup_file = f'{CONFIG_DIR}/backups/{name}.tar.gz'
        if os.path.exists(backup_file):
            os.remove(backup_file)
            log_activity('Delete Backup', f'Backup "{name}" deleted')
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Backup not found'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@global_settings_bp.route('/global-settings/upload-backup', methods=['POST'])
def upload_backup() -> str | Response:
    """POST /global-settings/upload-backup — upload a tar.gz backup file."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('global_settings'):
        flash('Access denied.', 'error')
        return redirect('/dashboard')
    
    try:
        backup_file = request.files.get('backup_file')
        if not backup_file or not backup_file.filename.endswith('.tar.gz'):
            flash('Invalid backup file', 'error')
            return redirect('/global-settings')
        
        backup_dir = f'{CONFIG_DIR}/backups'
        os.makedirs(backup_dir, exist_ok=True)
        
        filename = backup_file.filename
        filepath = os.path.join(backup_dir, filename)
        backup_file.save(filepath)
        
        log_activity('Upload Backup', f'Backup "{filename}" uploaded')
        flash(f'Backup "{filename}" uploaded successfully!', 'success')
    except Exception as e:
        flash(f'Failed to upload backup: {str(e)}', 'error')
    
    return redirect('/global-settings')


@global_settings_bp.route('/global-settings/update-nextcloud', methods=['POST'])
def update_nextcloud_config() -> str | Response:
    """POST /global-settings/update-nextcloud — update Nextcloud configuration."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('global_settings'):
        flash('Access denied.', 'error')
        return redirect('/dashboard')
    
    share_link = request.form.get('nextcloud_share', '').strip()
    password = request.form.get('nextcloud_password', '').strip()
    
    try:
        config = {}
        if os.path.exists(GLOBAL_CONFIG_PATH):
            with open(GLOBAL_CONFIG_PATH, 'r') as f:
                config = json.load(f)
        
        config['nextcloud_share'] = share_link
        config['nextcloud_password'] = encrypt_value(password) if password else ''
        
        with open(GLOBAL_CONFIG_PATH, 'w') as f:
            json.dump(config, f)
        
        log_activity('Update Nextcloud Config', 'Nextcloud configuration updated')
        flash('Nextcloud configuration saved!', 'success')
    except Exception as e:
        log_activity('Update Nextcloud Config Failed', str(e))
        flash(f'Failed to save: {str(e)}', 'error')
    
    return redirect('/global-settings')


@global_settings_bp.route('/global-settings/update-domain', methods=['POST'])
def update_domain() -> str | Response:
    """POST /global-settings/update-domain — update the domain configuration."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('global_settings'):
        flash('Access denied.', 'error')
        return redirect('/dashboard')
    
    domain = request.form.get('domain', '').strip()
    
    try:
        config = {}
        if os.path.exists(GLOBAL_CONFIG_PATH):
            with open(GLOBAL_CONFIG_PATH, 'r') as f:
                config = json.load(f)
        
        config['domain'] = domain
        
        with open(GLOBAL_CONFIG_PATH, 'w') as f:
            json.dump(config, f)
        
        log_activity('Update Domain', f'Domain set to: {domain if domain else "(empty)"}')
        flash('Domain configuration updated!', 'success')
    except Exception as e:
        log_activity('Update Domain Failed', str(e))
        flash(f'Failed to update domain: {str(e)}', 'error')
    
    return redirect('/global-settings')


@global_settings_bp.route('/global-settings/update-uptime-kuma', methods=['POST'])
def update_uptime_kuma() -> str | Response:
    """POST /global-settings/update-uptime-kuma — update Uptime Kuma configuration."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('global_settings'):
        flash('Access denied.', 'error')
        return redirect('/dashboard')
    
    uptime_kuma_url = request.form.get('uptime_kuma_url', '').strip()
    uptime_kuma_username = request.form.get('uptime_kuma_username', '').strip()
    uptime_kuma_password = request.form.get('uptime_kuma_password', '').strip()
    uptime_kuma_enabled = request.form.get('uptime_kuma_enabled') == '1'
    
    try:
        config = {}
        if os.path.exists(GLOBAL_CONFIG_PATH):
            with open(GLOBAL_CONFIG_PATH, 'r') as f:
                config = json.load(f)
        
        config['uptime_kuma_url'] = uptime_kuma_url
        config['uptime_kuma_username'] = uptime_kuma_username
        config['uptime_kuma_enabled'] = uptime_kuma_enabled
        
        # Only update password if provided
        if uptime_kuma_password:
            config['uptime_kuma_password'] = encrypt_value(uptime_kuma_password)
        
        with open(GLOBAL_CONFIG_PATH, 'w') as f:
            json.dump(config, f)
        
        log_activity('Update Uptime Kuma Config', f'URL: {uptime_kuma_url}, Enabled: {uptime_kuma_enabled}')
        flash('Uptime Kuma configuration updated!', 'success')
    except Exception as e:
        log_activity('Update Uptime Kuma Config Failed', str(e))
        flash(f'Failed to update Uptime Kuma config: {str(e)}', 'error')
    
    return redirect('/global-settings')


@global_settings_bp.route('/global-settings/logs')
def get_activity_logs() -> Response | tuple[Response, int]:
    """GET /global-settings/logs — return recent activity logs as JSON."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    logs = read_activity_logs(500)
    return jsonify({'logs': logs})


@global_settings_bp.route('/global-settings/clear-logs', methods=['POST'])
def clear_activity_logs() -> tuple[dict, int]:
    """POST /global-settings/clear-logs — clear all activity logs."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('global_settings'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        import glob as glob_mod
        # Clear all monthly log files
        for f in glob_mod.glob(f'{ACTIVITY_LOG_DIR}/activity_log_*.txt'):
            os.remove(f)
        # Also clear legacy file
        if os.path.exists(ACTIVITY_LOG_PATH):
            os.remove(ACTIVITY_LOG_PATH)
        log_activity('Clear Logs', 'Activity logs cleared')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@global_settings_bp.route('/global-settings/generate-api-key', methods=['POST'])
def generate_api_key() -> tuple[dict, int]:
    """POST /global-settings/generate-api-key — Generate a new API key."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('global_settings'):
        return jsonify({'error': 'Access denied'}), 403

    try:
        import secrets
        new_key = secrets.token_urlsafe(32)

        config = {}
        if os.path.exists(GLOBAL_CONFIG_PATH):
            with open(GLOBAL_CONFIG_PATH, 'r') as f:
                config = json.load(f)

        config['api_key'] = new_key

        with open(GLOBAL_CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)

        log_activity('Generate API Key', 'New API key generated')
        return jsonify({'success': True, 'api_key': new_key})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
