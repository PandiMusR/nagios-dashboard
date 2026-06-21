from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, session, jsonify, flash, Response
import os, json, subprocess, base64, re, requests
from datetime import datetime

from services.config import CONFIG_DIR, MONITORING_CATEGORIES_PATH, MONITORING_SERVER_MAPPINGS_PATH, MONITORING_CONFIG_PATH
from services.encryption import decrypt_session_value, load_encrypted_json
from services.ldap_service import log_activity
from services.uptime_kuma import add_host_to_uptime_kuma, get_uptime_kuma_config
from services.nextcloud import upload_to_nextcloud
from utils.permissions import check_permission

host_manager_bp = Blueprint('host_manager', __name__)


def get_nagios_servers() -> list[str]:
    """Return a list of running Nagios container names."""
    result = subprocess.run(['docker', 'ps', '--filter', 'ancestor=nagios-ldap:latest', '--format', '{{.Names}}'], 
                          capture_output=True, text=True)
    return result.stdout.strip().split('\n') if result.stdout.strip() else []


def get_monitoring_categories() -> list[str]:
    """Return a deduplicated list of all known monitoring categories."""
    categories: list[str] = []
    seen: set[str] = set()

    def add_category(value: object) -> None:
        if not isinstance(value, str):
            return
        normalized = value.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            categories.append(normalized)

    for default_category in ['prioritas', 'bhome', 'diskominfo']:
        add_category(default_category)

    try:
        if os.path.exists(MONITORING_CATEGORIES_PATH):
            with open(MONITORING_CATEGORIES_PATH, 'r') as f:
                stored_categories = json.load(f)
                if isinstance(stored_categories, list):
                    for category in stored_categories:
                        add_category(category)
    except (json.JSONDecodeError, OSError):
        pass

    try:
        if os.path.exists(MONITORING_SERVER_MAPPINGS_PATH):
            with open(MONITORING_SERVER_MAPPINGS_PATH, 'r') as f:
                mappings = json.load(f)
                if isinstance(mappings, dict):
                    for category in mappings.keys():
                        add_category(category)
    except (json.JSONDecodeError, OSError):
        pass

    try:
        if os.path.exists(MONITORING_CONFIG_PATH):
            with open(MONITORING_CONFIG_PATH, 'r') as f:
                config = json.load(f)
                category_settings = config.get('category_settings', {})
                alarm_settings = config.get('alarm_settings', {})

                if isinstance(category_settings, dict):
                    for category in category_settings.keys():
                        add_category(category)

                if isinstance(alarm_settings, dict):
                    for category in alarm_settings.keys():
                        add_category(category)
    except (json.JSONDecodeError, OSError):
        pass

    return categories


@host_manager_bp.route('/host-manager/backup', methods=['POST'])
def backup_localhost_cfg() -> Response | tuple[Response, int]:
    """POST /host-manager/backup — create a backup of a server's localhost.cfg."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        server = data.get('server')
        
        backup_dir = f'/svr/{server}/etc/objects/backups'
        os.makedirs(backup_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f'localhost_{timestamp}'
        
        config_path = f'/svr/{server}/etc/objects/localhost.cfg'
        backup_path = f'{backup_dir}/{backup_name}.cfg'
        
        subprocess.run(['cp', config_path, backup_path])
        
        # Upload to Nextcloud
        cloud_success = upload_to_nextcloud(server, backup_path, backup_name)
        
        # Keep only last 10 backups
        backups = sorted([f for f in os.listdir(backup_dir) if f.endswith('.cfg')])
        if len(backups) > 10:
            for old in backups[:-10]:
                os.remove(f'{backup_dir}/{old}')
        
        log_activity('Backup Config', f'Backup created for {server}' + (' (uploaded to cloud)' if cloud_success else ''))
        return jsonify({'success': True, 'cloud': cloud_success})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@host_manager_bp.route('/host-manager/backups/<server>')
def list_localhost_backups(server: str) -> Response | tuple[Response, int]:
    """GET /host-manager/backups/<server> — list config backups for a server."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        backup_dir = f'/svr/{server}/etc/objects/backups'
        os.makedirs(backup_dir, exist_ok=True)
        
        backups = []
        for filename in sorted(os.listdir(backup_dir), reverse=True):
            if filename.endswith('.cfg'):
                filepath = os.path.join(backup_dir, filename)
                stat = os.stat(filepath)
                date_str = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                backups.append({
                    'name': filename.replace('.cfg', ''),
                    'date': date_str
                })
        
        return jsonify({'backups': backups})
    except Exception as e:
        return jsonify({'backups': [], 'error': str(e)})


@host_manager_bp.route('/host-manager/restore', methods=['POST'])
def restore_localhost_cfg() -> Response | tuple[Response, int]:
    """POST /host-manager/restore — restore a backup of localhost.cfg."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        server = data.get('server')
        backup_name = data.get('backup_name')
        
        backup_path = f'/svr/{server}/etc/objects/backups/{backup_name}.cfg'
        config_path = f'/svr/{server}/etc/objects/localhost.cfg'
        
        if not os.path.exists(backup_path):
            return jsonify({'success': False, 'error': 'Backup not found'})
        
        subprocess.run(['cp', backup_path, config_path])
        subprocess.run(['docker', 'restart', server], capture_output=True)
        
        log_activity('Restore Config', f'Restored {backup_name} for {server}')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@host_manager_bp.route('/host-manager/delete-backup/<server>/<name>', methods=['DELETE'])
def delete_localhost_backup(server: str, name: str) -> Response | tuple[Response, int]:
    """DELETE /host-manager/delete-backup/<server>/<name> — delete a config backup."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        backup_path = f'/svr/{server}/etc/objects/backups/{name}.cfg'
        if os.path.exists(backup_path):
            os.remove(backup_path)
            log_activity('Delete Backup', f'Deleted {name} for {server}')
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Not found'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@host_manager_bp.route('/host-manager/host-status/<server>', methods=['GET'])
def get_host_status_endpoint(server: str) -> Response | tuple[Response, int]:
    """GET /host-manager/host-status/<server> — get host status from Nagios."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        # Resolve container port using docker CLI (same approach as monitoring_data).
        result = subprocess.run(['docker', 'port', server, '80'], capture_output=True, text=True)
        if not result.stdout:
            return jsonify({'hosts': {}})
        port = result.stdout.strip().split(':')[-1]
        
        # Use current user credentials first to stay consistent with monitoring endpoint.
        username = session.get('username')
        password = decrypt_session_value(session.get('password'))

        # Fallback to stored server-specific creds if session creds are missing.
        creds_file = f'{CONFIG_DIR}/nagios_creds_{server}.json'
        if (not username or not password) and os.path.exists(creds_file):
            try:
                creds = load_encrypted_json(creds_file)
                username = creds.get('username', 'nagiosadmin')
                password = creds.get('password', 'nagiosadmin')
            except (json.JSONDecodeError, OSError):
                pass
        
        if not username or not password:
            username = 'nagiosadmin'
            password = 'nagiosadmin'
        
        # Create auth header
        auth_str = base64.b64encode(f'{username}:{password}'.encode()).decode()
        auth_header = f'Basic {auth_str}'
        
        # Query Nagios API
        status_url = f'http://localhost:{port}/nagios/cgi-bin/statusjson.cgi?query=hostlist&details=true'
        response = requests.get(status_url, headers={'Authorization': auth_header}, timeout=5)
        
        hosts_status = {}
        if response.status_code == 200:
            hostlist = response.json().get('data', {}).get('hostlist', {})
            for hostname, host in hostlist.items():
                status_code = host.get('status', 0)
                status = 'unknown'

                # Prefer textual fields when available.
                status_text = str(host.get('status_text') or host.get('state') or '').lower()
                if 'unreach' in status_text:
                    status = 'unreachable'
                elif 'down' in status_text:
                    status = 'down'
                elif 'up' in status_text:
                    status = 'up'
                else:
                    # Fallback numeric mapping across common Nagios JSON variants.
                    current_state = host.get('current_state')
                    if current_state == 0:
                        status = 'up'
                    elif current_state == 1:
                        status = 'down'
                    elif current_state == 2:
                        status = 'unreachable'
                    elif status_code == 2:
                        status = 'up'
                    elif status_code == 4:
                        status = 'down'
                    elif status_code == 8:
                        status = 'unreachable'
                    elif status_code == 0:
                        status = 'up'
                    elif status_code == 1:
                        status = 'down'
                
                hosts_status[hostname] = status
        
        return jsonify({'hosts': hosts_status})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'hosts': {}, 'error': str(e)})


@host_manager_bp.route('/host-manager')
def host_manager() -> str | Response:
    """GET /host-manager — render the host manager page."""
    if 'username' not in session:
        return redirect('/')
    
    if not check_permission('host_manager'):
        flash('Access denied. You do not have permission to access this page.', 'error')
        return redirect('/dashboard')
    
    # Get all nagios servers
    all_servers = get_nagios_servers()
    
    # Filter servers based on user permissions
    allowed_servers = []
    if session.get('role') == 'admin':
        allowed_servers = all_servers
    else:
        user_perms = session.get('permissions', {})
        for server in all_servers:
            if user_perms.get(f'nagios_{server}'):
                allowed_servers.append(server)
    
    # Get hosts from allowed servers only
    all_hosts = {}
    for server in allowed_servers:
        config_path = f'/svr/{server}/etc/objects/localhost.cfg'
        try:
            with open(config_path, 'r') as f:
                content = f.read()
                all_hosts[server] = content
        except OSError:
            all_hosts[server] = ''
    
    # Get available plugins per server
    server_plugins = {}
    for server in allowed_servers:
        commands_path = f'/svr/{server}/etc/objects/commands.cfg'
        plugins = []
        try:
            with open(commands_path, 'r') as f:
                content = f.read()
                # Extract command names from commands.cfg
                matches = re.findall(r'define command\s*\{[^}]*command_name\s+(\S+)', content, re.MULTILINE)
                plugins = matches
        except OSError:
            pass
        server_plugins[server] = plugins
    
    return render_template('host_manager.html', username=session['username'], 
                         servers=allowed_servers, all_hosts=all_hosts,
                         server_plugins=server_plugins,
                         nagios_servers=get_nagios_servers(), 
                         monitoring_categories=get_monitoring_categories())


@host_manager_bp.route('/host-manager/add', methods=['POST'])
def add_host() -> str | Response:
    """POST /host-manager/add — add a new host to a Nagios server."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    server = request.form.get('server')
    
    # Check if user has permission for this server
    if session.get('role') != 'admin':
        user_perms = session.get('permissions', {})
        if not user_perms.get(f'nagios_{server}'):
            flash('Access denied. You do not have permission to modify this server.', 'error')
            return redirect('/host-manager')
    
    host_name = request.form.get('host_name')
    alias = request.form.get('alias')
    address = request.form.get('address')
    parents = request.form.get('parents', '').strip()
    uptime_kuma_enabled = request.form.get('uptime_kuma_enabled') == 'on'
    
    # Get service/plugin info
    service_enabled = request.form.get('service_enabled') == 'on'
    service_plugin = request.form.get('service_plugin', '')
    service_args = request.form.get('service_args', '')
    
    # Sanitize host_name
    host_name = re.sub(r'[^a-zA-Z0-9_. -]', '', host_name)
    
    config_path = f'/svr/{server}/etc/objects/localhost.cfg'
    
    try:
        # Read existing content to check if file ends with newline
        with open(config_path, 'r') as f:
            content = f.read()
        
        # Build host definition
        host_definition = 'define host{\n'
        host_definition += '    use                     linux-server\n'
        host_definition += f'    host_name               {host_name}\n'
        if alias:
            host_definition += f'    alias                   {alias}\n'
        host_definition += f'    address                 {address}\n'
        if parents:
            host_definition += f'    parents                 {parents}\n'
        host_definition += '}\n'
        
        # Add service definition if enabled
        if service_enabled and service_plugin:
            host_definition += '\n'
            host_definition += 'define service {\n'
            host_definition += '    use                     generic-service\n'
            host_definition += f'    host_name               {host_name}\n'
            host_definition += f'    service_description     {service_plugin.replace("check_", "").replace("_", " ").title()}\n'
            if service_args:
                host_definition += f'    check_command           {service_plugin}!{service_args}\n'
            else:
                host_definition += f'    check_command           {service_plugin}\n'
            host_definition += '    notifications_enabled   1\n'
            host_definition += '}\n'
        
        # Add single newline before if content doesn't end with newline
        if content and not content.endswith('\n'):
            host_definition = '\n' + host_definition
        elif content:
            host_definition = '\n' + host_definition
        
        with open(config_path, 'a') as f:
            f.write(host_definition)
        
        # Add to Uptime Kuma if enabled
        uptime_kuma_msg = ""
        if uptime_kuma_enabled:
            monitor_id, error = add_host_to_uptime_kuma(host_name, address)
            if monitor_id:
                uptime_kuma_msg = " and added to Uptime Kuma"
                log_activity('Add Host to Uptime Kuma', f'Host: {host_name}, IP: {address}, Monitor ID: {monitor_id}')
            elif error:
                uptime_kuma_msg = f" (Uptime Kuma: {error})"
                log_activity('Add Host to Uptime Kuma Failed', f'Host: {host_name}, Error: {error}')
        
        # Restart container immediately
        subprocess.run(['docker', 'restart', server], check=True, capture_output=True)
        flash(f'Host "{host_name}" added to {server}{uptime_kuma_msg} and restarted!', 'success')
    except Exception as e:
        flash(f'Failed to add host: {str(e)}', 'error')
    
    return redirect('/host-manager')


@host_manager_bp.route('/host-manager/batch-add', methods=['POST'])
def batch_add_hosts() -> str | Response:
    """POST /host-manager/batch-add — add multiple hosts in bulk."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    servers = request.form.getlist('batch_servers[]')
    hostnames = request.form.getlist('batch_hostnames[]')
    addresses = request.form.getlist('batch_addresses[]')
    aliases = request.form.getlist('batch_alias[]')
    parents = request.form.getlist('batch_parents[]')
    uptime_kuma_enabled = request.form.getlist('batch_uptime_kuma[]')
    service_enabled = request.form.getlist('batch_service_enabled[]')
    plugins = request.form.getlist('batch_service_plugin[]')
    args = request.form.getlist('batch_service_args[]')
    
    added_by_server = {}
    
    try:
        for i in range(len(hostnames)):
            if i >= len(addresses) or i >= len(servers):
                break
            
            server = servers[i].strip()
            host_name = hostnames[i].strip()
            address = addresses[i].strip()
            alias = aliases[i].strip() if i < len(aliases) else ''
            parent = parents[i].strip() if i < len(parents) else ''
            
            if not host_name or not address:
                continue
            
            if session.get('role') != 'admin':
                user_perms = session.get('permissions', {})
                if not user_perms.get(f'nagios_{server}'):
                    continue
            
            host_name = re.sub(r'[^a-zA-Z0-9_. -]', '', host_name)
            config_path = f'/svr/{server}/etc/objects/localhost.cfg'
            
            host_def = '\ndefine host{\n'
            host_def += '    use                     linux-server\n'
            host_def += f'    host_name               {host_name}\n'
            if alias:
                host_def += f'    alias                   {alias}\n'
            host_def += f'    address                 {address}\n'
            if parent:
                host_def += f'    parents                 {parent}\n'
            host_def += '}\n'
            
            # Add service if enabled
            if i < len(service_enabled) and service_enabled[i] == 'on':
                plugin = plugins[i].strip() if i < len(plugins) else ''
                arg = args[i].strip() if i < len(args) else ''
                
                if plugin:
                    host_def += '\ndefine service {\n'
                    host_def += '    use                     generic-service\n'
                    host_def += f'    host_name               {host_name}\n'
                    host_def += f'    service_description     {plugin.replace("check_", "").replace("_", " ").title()}\n'
                    if arg:
                        host_def += f'    check_command           {plugin}!{arg}\n'
                    else:
                        host_def += f'    check_command           {plugin}\n'
                    host_def += '    notifications_enabled   1\n'
                    host_def += '}\n'
            
            with open(config_path, 'a') as f:
                f.write(host_def)
            
            # Add to Uptime Kuma if enabled
            if i < len(uptime_kuma_enabled) and uptime_kuma_enabled[i] == 'on':
                try:
                    uptime_config = get_uptime_kuma_config()
                    if uptime_config and uptime_config.get('enabled'):
                        add_host_to_uptime_kuma(host_name, address)
                except Exception as uk_error:
                    print(f'Uptime Kuma add failed for {host_name}: {str(uk_error)}')
            
            if server not in added_by_server:
                added_by_server[server] = 0
            added_by_server[server] += 1
        
        for server in added_by_server:
            subprocess.run(['docker', 'restart', server], check=True, capture_output=True)
        
        total = sum(added_by_server.values())
        if total > 0:
            flash(f'{total} host(s) added!', 'success')
        else:
            flash('No valid hosts!', 'error')
    except Exception as e:
        flash(f'Failed: {str(e)}', 'error')
    
    return redirect('/host-manager')


@host_manager_bp.route('/host-manager/delete', methods=['POST'])
def delete_host() -> str | Response:
    """POST /host-manager/delete — delete a host and its descendants."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    server = request.form.get('server')
    
    # Check if user has permission for this server
    if session.get('role') != 'admin':
        user_perms = session.get('permissions', {})
        if not user_perms.get(f'nagios_{server}'):
            flash('Access denied. You do not have permission to modify this server.', 'error')
            return redirect('/host-manager')
    
    host_name = request.form.get('host_name')
    
    config_path = f'/svr/{server}/etc/objects/localhost.cfg'
    
    try:
        with open(config_path, 'r') as f:
            content = f.read()
        
        # Split by host definitions
        host_blocks = re.split(r'(define host\s*\{[^}]*\})', content, flags=re.DOTALL)
        
        # Build host tree
        all_hosts = []
        for block in host_blocks:
            if 'define host' in block:
                name_match = re.search(r'host_name\s+(.+?)\s*$', block, re.MULTILINE)
                parent_match = re.search(r'parents\s+(.+?)\s*$', block, re.MULTILINE)
                if name_match:
                    all_hosts.append({
                        'name': name_match.group(1).strip(),
                        'parent': parent_match.group(1).strip() if parent_match else '',
                        'block': block
                    })
        
        # Find all descendants recursively
        def find_descendants(parent_name: str) -> list[str]:
            descendants = []
            for host in all_hosts:
                if host['parent'] == parent_name:
                    descendants.append(host['name'])
                    descendants.extend(find_descendants(host['name']))
            return descendants
        
        hosts_to_delete = [host_name] + find_descendants(host_name)
        
        # Remove hosts and their services
        new_blocks = []
        for block in host_blocks:
            if 'define host' in block:
                name_match = re.search(r'host_name\s+(.+?)\s*$', block, re.MULTILINE)
                if name_match and name_match.group(1).strip() not in hosts_to_delete:
                    new_blocks.append(block)
            else:
                new_blocks.append(block)
        
        updated_content = ''.join(new_blocks)
        
        # Remove all services associated with deleted hosts
        for host_to_delete in hosts_to_delete:
            service_pattern = rf'define service\s*\{{[^}}]*host_name\s+{re.escape(host_to_delete)}\s*[^}}]*\}}'
            updated_content = re.sub(service_pattern, '', updated_content, flags=re.DOTALL)
        
        # Clean up extra newlines
        updated_content = re.sub(r'\n\n\n+', '\n\n', updated_content)
        
        with open(config_path, 'w') as f:
            f.write(updated_content)
        
        # Direct restart without verification
        subprocess.run(['docker', 'restart', server], check=True, capture_output=True)
        msg = f'Deleted {len(hosts_to_delete)} host(s): {host_name}'
        if len(hosts_to_delete) > 1:
            msg += f' and {len(hosts_to_delete)-1} descendant(s)'
        flash(msg + ' - Server restarted!', 'success')
    except Exception as e:
        flash(f'Failed to delete host: {str(e)}', 'error')
    
    return redirect('/host-manager')


@host_manager_bp.route('/host-manager/edit', methods=['POST'])
def edit_host() -> str | Response:
    """POST /host-manager/edit — edit an existing host configuration."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    server = request.form.get('server')
    
    # Check if user has permission for this server
    if session.get('role') != 'admin':
        user_perms = session.get('permissions', {})
        if not user_perms.get(f'nagios_{server}'):
            flash('Access denied. You do not have permission to modify this server.', 'error')
            return redirect('/host-manager')
    
    old_host_name = request.form.get('old_host_name')
    host_name = request.form.get('host_name')
    alias = request.form.get('alias')
    address = request.form.get('address')
    parents = request.form.get('parents', '').strip()
    uptime_kuma_enabled = request.form.get('uptime_kuma_enabled') == 'on'
    
    # Get service/plugin info
    service_enabled = request.form.get('service_enabled') == 'on'
    service_plugin = request.form.get('service_plugin', '')
    service_args = request.form.get('service_args', '')
    
    # Sanitize host_name
    host_name = re.sub(r'[^a-zA-Z0-9_. -]', '', host_name)
    
    config_path = f'/svr/{server}/etc/objects/localhost.cfg'
    
    try:
        with open(config_path, 'r') as f:
            content = f.read()
        
        # Split by host definitions
        host_blocks = re.split(r'(define host\s*\{[^}]*\})', content, flags=re.DOTALL)
        
        new_blocks = []
        for block in host_blocks:
            if 'define host' in block:
                # Check if this is the host to edit
                if re.search(rf'host_name\s+{re.escape(old_host_name)}\s*$', block, re.MULTILINE):
                    # Rebuild host definition
                    new_block = 'define host{\n'
                    new_block += '    use                     linux-server\n'
                    new_block += f'    host_name               {host_name}\n'
                    if alias:
                        new_block += f'    alias                   {alias}\n'
                    new_block += f'    address                 {address}\n'
                    if parents:
                        new_block += f'    parents                 {parents}\n'
                    new_block += '}'
                    block = new_block
                
                # Update children that reference old parent name
                elif old_host_name != host_name:
                    block = re.sub(rf'(parents\s+){re.escape(old_host_name)}(\s*$)', lambda m: m.group(1) + host_name + m.group(2), block, flags=re.MULTILINE)
            
            new_blocks.append(block)
        
        updated_content = ''.join(new_blocks)
        
        # Remove existing service blocks for the old/new host first so we can rebuild cleanly.
        service_block_pattern = re.compile(r'^define service\s*\{\s*.*?^\}\s*', re.DOTALL | re.MULTILINE)
        service_hosts_to_replace = {host_name}
        if old_host_name:
            service_hosts_to_replace.add(old_host_name)

        def remove_matching_service_blocks(match: re.Match) -> str:
            block = match.group(0)
            host_match = re.search(r'^\s*host_name\s+(.+?)\s*$', block, re.MULTILINE)
            if host_match and host_match.group(1).strip() in service_hosts_to_replace:
                return ''
            return block

        updated_content = service_block_pattern.sub(remove_matching_service_blocks, updated_content)
        updated_content = re.sub(r'\n{3,}', '\n\n', updated_content).rstrip()

        # Handle service definition
        if service_enabled and service_plugin:
            new_service = '\ndefine service {\n'
            new_service += '    use                     generic-service\n'
            new_service += f'    host_name               {host_name}\n'
            new_service += f'    service_description     {service_plugin.replace("check_", "").replace("_", " ").title()}\n'
            if service_args:
                new_service += f'    check_command           {service_plugin}!{service_args}\n'
            else:
                new_service += f'    check_command           {service_plugin}\n'
            new_service += '    notifications_enabled   1\n'
            new_service += '}\n'
            updated_content += new_service
        else:
            # Clean up extra newlines after removing service blocks
            updated_content = re.sub(r'\n\n\n+', '\n\n', updated_content)

        with open(config_path, 'w') as f:
            f.write(updated_content)
        
        # Update Uptime Kuma if enabled
        uptime_kuma_msg = ""
        if uptime_kuma_enabled:
            monitor_id, error = add_host_to_uptime_kuma(host_name, address)
            if monitor_id:
                uptime_kuma_msg = " and added to Uptime Kuma"
                log_activity('Add Host to Uptime Kuma', f'Host: {host_name}, IP: {address}, Monitor ID: {monitor_id}')
            elif error:
                uptime_kuma_msg = f" (Uptime Kuma: {error})"
                log_activity('Add Host to Uptime Kuma Failed', f'Host: {host_name}, Error: {error}')
        
        # Direct restart without verification
        subprocess.run(['docker', 'restart', server], check=True, capture_output=True)
        flash(f'Host "{host_name}" updated{uptime_kuma_msg} and restarted!', 'success')
    except Exception as e:
        flash(f'Failed to update host: {str(e)}', 'error')
    
    return redirect('/host-manager')
