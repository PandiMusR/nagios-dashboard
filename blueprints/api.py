from __future__ import annotations

from flask import Blueprint, request, jsonify, Response
import os, json, subprocess, re

from services.config import CONFIG_DIR, GLOBAL_CONFIG_PATH
from services.ldap_service import log_activity
from services.uptime_kuma import add_host_to_uptime_kuma

api_bp = Blueprint('api', __name__)


def _get_api_key() -> str:
    """Load API key from global_config.json."""
    try:
        if os.path.exists(GLOBAL_CONFIG_PATH):
            with open(GLOBAL_CONFIG_PATH, 'r') as f:
                config = json.load(f)
                return config.get('api_key', '')
    except (json.JSONDecodeError, OSError):
        pass
    return ''


def _check_api_key(request_obj: request) -> bool:
    """Validate API key from X-API-Key header or ?api_key query param."""
    api_key = _get_api_key()
    if not api_key:
        return False
    provided = request_obj.headers.get('X-API-Key', '') or request_obj.args.get('api_key', '')
    return provided == api_key


def _error(message: str, status: int = 400) -> tuple[Response, int]:
    """Return a JSON error response."""
    return jsonify({'success': False, 'error': message}), status


@api_bp.route('/api/hosts/add', methods=['POST'])
def api_add_host() -> tuple[Response, int]:
    """POST /api/hosts/add — Add a host to a Nagios server via API.

    Auth: X-API-Key header or ?api_key query param

    Body (JSON):
    {
        "server": "BhomeTest",              // required — Nagios container name
        "host_name": "switch-gedung-a",     // required
        "address": "192.168.1.100",         // required — IP address
        "alias": "Switch Gedung A",         // optional
        "parents": "router-pusat",          // optional
        "service_plugin": "check_ping",     // optional — Nagios plugin name
        "service_args": "100,20%!500,60%",  // optional — plugin arguments
        "uptime_kuma": false                // optional — add to Uptime Kuma monitoring
    }

    Response:
    {
        "success": true,
        "host_name": "switch-gedung-a",
        "server": "BhomeTest",
        "message": "Host added and Nagios restarted"
    }
    """
    if not _check_api_key(request):
        return _error('Invalid or missing API key', 401)

    data = request.get_json()
    if not data:
        return _error('Request body must be JSON')

    server = data.get('server', '').strip()
    host_name = data.get('host_name', '').strip()
    address = data.get('address', '').strip()
    alias = data.get('alias', '').strip()
    parents = data.get('parents', '').strip()
    service_plugin = data.get('service_plugin', '').strip()
    service_args = data.get('service_args', '').strip()
    uptime_kuma = data.get('uptime_kuma', False)

    # Validation
    if not server:
        return _error('Missing required field: server')
    if not host_name:
        return _error('Missing required field: host_name')
    if not address:
        return _error('Missing required field: address')

    # Sanitize host_name
    host_name = re.sub(r'[^a-zA-Z0-9_. -]', '', host_name)
    if not host_name:
        return _error('Invalid host_name after sanitization')

    # Check server exists
    config_path = f'/svr/{server}/etc/objects/localhost.cfg'
    if not os.path.exists(config_path):
        return _error(f'Server "{server}" not found or config missing', 404)

    try:
        # Read existing content
        with open(config_path, 'r') as f:
            content = f.read()

        # Check for duplicate host_name
        if f'host_name               {host_name}' in content or f'host_name    {host_name}' in content:
            return _error(f'Host "{host_name}" already exists on server "{server}"', 409)

        # Build host definition
        host_def = 'define host{\n'
        host_def += '    use                     linux-server\n'
        host_def += f'    host_name               {host_name}\n'
        if alias:
            host_def += f'    alias                   {alias}\n'
        host_def += f'    address                 {address}\n'
        if parents:
            host_def += f'    parents                 {parents}\n'
        host_def += '}\n'

        # Add service definition if plugin specified
        if service_plugin:
            host_def += '\n'
            host_def += 'define service {\n'
            host_def += '    use                     generic-service\n'
            host_def += f'    host_name               {host_name}\n'
            host_def += f'    service_description     {service_plugin.replace("check_", "").replace("_", " ").title()}\n'
            if service_args:
                host_def += f'    check_command           {service_plugin}!{service_args}\n'
            else:
                host_def += f'    check_command           {service_plugin}\n'
            host_def += '    notifications_enabled   1\n'
            host_def += '}\n'

        # Append to config file
        if content and not content.endswith('\n'):
            host_def = '\n' + host_def
        elif content:
            host_def = '\n' + host_def

        with open(config_path, 'a') as f:
            f.write(host_def)

        # Restart Nagios container
        subprocess.run(['docker', 'restart', server], check=True, capture_output=True)

        # Uptime Kuma integration
        uptime_kuma_msg = ''
        if uptime_kuma:
            monitor_id, error = add_host_to_uptime_kuma(host_name, address)
            if monitor_id:
                uptime_kuma_msg = ' + Uptime Kuma'
                log_activity('API: Add Host to Uptime Kuma', f'Host: {host_name}, IP: {address}, Monitor ID: {monitor_id}', username='API')
            elif error:
                uptime_kuma_msg = f' (Uptime Kuma error: {error})'
                log_activity('API: Add Host to Uptime Kuma Failed', f'Host: {host_name}, Error: {error}', username='API')

        log_activity('API: Add Host', f'Host: {host_name} ({address}) to {server}{uptime_kuma_msg}', username='API')

        return jsonify({
            'success': True,
            'host_name': host_name,
            'server': server,
            'message': f'Host added and Nagios restarted{uptime_kuma_msg}'
        }), 201

    except subprocess.CalledProcessError as e:
        return _error(f'Failed to restart Nagios container: {str(e)}', 500)
    except OSError as e:
        return _error(f'File error: {str(e)}', 500)


@api_bp.route('/api/hosts/batch-add', methods=['POST'])
def api_batch_add_hosts() -> tuple[Response, int]:
    """POST /api/hosts/batch-add — Add multiple hosts at once via API.

    Auth: X-API-Key header or ?api_key query param

    Body (JSON):
    {
        "server": "BhomeTest",
        "hosts": [
            {"host_name": "switch-1", "address": "192.168.1.1", "alias": "Switch 1"},
            {"host_name": "switch-2", "address": "192.168.1.2", "parents": "router-1"}
        ],
        "service_plugin": "check_ping",     // optional — applied to all hosts
        "service_args": "100,20%!500,60%",   // optional
        "uptime_kuma": false                  // optional
    }
    """
    if not _check_api_key(request):
        return _error('Invalid or missing API key', 401)

    data = request.get_json()
    if not data:
        return _error('Request body must be JSON')

    server = data.get('server', '').strip()
    hosts = data.get('hosts', [])
    service_plugin = data.get('service_plugin', '').strip()
    service_args = data.get('service_args', '').strip()
    uptime_kuma = data.get('uptime_kuma', False)

    if not server:
        return _error('Missing required field: server')
    if not hosts or not isinstance(hosts, list):
        return _error('Missing or invalid "hosts" array')

    config_path = f'/svr/{server}/etc/objects/localhost.cfg'
    if not os.path.exists(config_path):
        return _error(f'Server "{server}" not found', 404)

    results = []
    success_count = 0
    fail_count = 0

    try:
        with open(config_path, 'r') as f:
            content = f.read()
    except OSError as e:
        return _error(f'Cannot read config: {str(e)}', 500)

    new_entries = ''

    for host_data in hosts:
        host_name = host_data.get('host_name', '').strip()
        address = host_data.get('address', '').strip()
        alias = host_data.get('alias', '').strip()
        parents = host_data.get('parents', '').strip()

        host_name = re.sub(r'[^a-zA-Z0-9_. -]', '', host_name)

        if not host_name or not address:
            results.append({'host_name': host_name, 'success': False, 'error': 'Missing host_name or address'})
            fail_count += 1
            continue

        if f'host_name               {host_name}' in content or f'host_name    {host_name}' in content:
            results.append({'host_name': host_name, 'success': False, 'error': 'Already exists'})
            fail_count += 1
            continue

        host_def = 'define host{\n'
        host_def += '    use                     linux-server\n'
        host_def += f'    host_name               {host_name}\n'
        if alias:
            host_def += f'    alias                   {alias}\n'
        host_def += f'    address                 {address}\n'
        if parents:
            host_def += f'    parents                 {parents}\n'
        host_def += '}\n'

        if service_plugin:
            host_def += '\n'
            host_def += 'define service {\n'
            host_def += '    use                     generic-service\n'
            host_def += f'    host_name               {host_name}\n'
            host_def += f'    service_description     {service_plugin.replace("check_", "").replace("_", " ").title()}\n'
            if service_args:
                host_def += f'    check_command           {service_plugin}!{service_args}\n'
            else:
                host_def += f'    check_command           {service_plugin}\n'
            host_def += '    notifications_enabled   1\n'
            host_def += '}\n'

        new_entries += '\n' + host_def
        results.append({'host_name': host_name, 'success': True, 'address': address})
        success_count += 1

        if uptime_kuma:
            monitor_id, error = add_host_to_uptime_kuma(host_name, address)
            if monitor_id:
                log_activity('API: Add Host to Uptime Kuma', f'Host: {host_name}, Monitor ID: {monitor_id}', username='API')

    # Write all at once
    if new_entries:
        try:
            with open(config_path, 'a') as f:
                f.write(new_entries)
        except OSError as e:
            return _error(f'Failed to write config: {str(e)}', 500)

    # Restart once
    if success_count > 0:
        try:
            subprocess.run(['docker', 'restart', server], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            return _error(f'Hosts written but restart failed: {str(e)}', 500)

    log_activity('API: Batch Add Hosts', f'{success_count} added, {fail_count} failed on {server}', username='API')

    return jsonify({
        'success': True,
        'server': server,
        'success_count': success_count,
        'fail_count': fail_count,
        'results': results
    }), 201


@api_bp.route('/api/hosts/delete', methods=['DELETE'])
def api_delete_host() -> tuple[Response, int]:
    """DELETE /api/hosts/delete — Delete a host from a Nagios server.

    Auth: X-API-Key header

    Body (JSON):
    {
        "server": "BhomeTest",
        "host_name": "switch-gedung-a"
    }
    """
    if not _check_api_key(request):
        return _error('Invalid or missing API key', 401)

    data = request.get_json()
    if not data:
        return _error('Request body must be JSON')

    server = data.get('server', '').strip()
    host_name = data.get('host_name', '').strip()

    if not server or not host_name:
        return _error('Missing required fields: server, host_name')

    config_path = f'/svr/{server}/etc/objects/localhost.cfg'
    if not os.path.exists(config_path):
        return _error(f'Server "{server}" not found', 404)

    try:
        with open(config_path, 'r') as f:
            content = f.read()

        # Remove host and its service definitions
        pattern = rf'define host\s*\{{[^}}]*host_name\s+{re.escape(host_name)}[^}}]*\}}'
        new_content = re.sub(pattern, '', content)

        # Also remove service definitions for this host
        pattern2 = rf'define service\s*\{{[^}}]*host_name\s+{re.escape(host_name)}[^}}]*\}}'
        new_content = re.sub(pattern2, '', new_content)

        # Clean up extra blank lines
        new_content = re.sub(r'\n{3,}', '\n\n', new_content)

        if new_content == content:
            return _error(f'Host "{host_name}" not found on server "{server}"', 404)

        with open(config_path, 'w') as f:
            f.write(new_content)

        subprocess.run(['docker', 'restart', server], check=True, capture_output=True)

        log_activity('API: Delete Host', f'Host: {host_name} from {server}', username='API')

        return jsonify({
            'success': True,
            'host_name': host_name,
            'server': server,
            'message': 'Host deleted and Nagios restarted'
        }), 200

    except subprocess.CalledProcessError as e:
        return _error(f'Failed to restart Nagios: {str(e)}', 500)
    except OSError as e:
        return _error(f'File error: {str(e)}', 500)


@api_bp.route('/api/servers', methods=['GET'])
def api_list_servers() -> tuple[Response, int]:
    """GET /api/servers — List all running Nagios servers.

    Auth: X-API-Key header
    """
    if not _check_api_key(request):
        return _error('Invalid or missing API key', 401)

    try:
        result = subprocess.run(
            ['docker', 'ps', '--filter', 'ancestor=nagios-ldap:latest', '--format', '{{.Names}}:{{.Ports}}'],
            capture_output=True, text=True, timeout=5
        )
        servers = []
        if result.stdout.strip():
            for line in result.stdout.strip().split('\n'):
                if ':' in line:
                    name, ports = line.split(':', 1)
                    port = ''
                    if '->' in ports:
                        port = ports.split(':')[1].split('->')[0]
                    servers.append({'name': name, 'port': port})
        return jsonify({'success': True, 'servers': servers}), 200
    except (subprocess.SubprocessError, OSError) as e:
        return _error(f'Failed to list servers: {str(e)}', 500)


@api_bp.route('/api/hosts', methods=['GET'])
def api_list_hosts() -> tuple[Response, int]:
    """GET /api/hosts?server=BhomeTest — List hosts on a Nagios server.

    Auth: X-API-Key header
    """
    if not _check_api_key(request):
        return _error('Invalid or missing API key', 401)

    server = request.args.get('server', '').strip()
    if not server:
        return _error('Missing required query param: server')

    config_path = f'/svr/{server}/etc/objects/localhost.cfg'
    if not os.path.exists(config_path):
        return _error(f'Server "{server}" not found', 404)

    try:
        with open(config_path, 'r') as f:
            content = f.read()

        hosts = []
        # Parse host definitions
        import re as re_mod
        for match in re_mod.finditer(r'define\s+host\s*\{([^}]+)\}', content, re_mod.DOTALL):
            block = match.group(1)
            host_name = re_mod.search(r'host_name\s+(\S+)', block)
            address = re_mod.search(r'address\s+(\S+)', block)
            alias = re_mod.search(r'alias\s+(.+)', block)
            parents = re_mod.search(r'parents\s+(\S+)', block)
            if host_name:
                hosts.append({
                    'host_name': host_name.group(1),
                    'address': address.group(1) if address else '',
                    'alias': alias.group(1).strip() if alias else '',
                    'parents': parents.group(1) if parents else ''
                })

        return jsonify({'success': True, 'server': server, 'hosts': hosts, 'total': len(hosts)}), 200
    except OSError as e:
        return _error(f'File error: {str(e)}', 500)


@api_bp.route('/api/monitoring', methods=['GET'])
def api_monitoring() -> tuple[Response, int]:
    """GET /api/monitoring — Get current monitoring data (DOWN hosts).

    Auth: X-API-Key header

    Optional query params:
    - category: filter by monitoring category (e.g., "bhome")
    """
    if not _check_api_key(request):
        return _error('Invalid or missing API key', 401)

    # This returns a simplified view — the full monitoring data requires session auth
    # For API, we return host_stages data
    try:
        from services.stage_service import load_host_stages, STAGE_LABELS
        host_stages = load_host_stages()

        category_filter = request.args.get('category', '').strip()

        hosts = []
        for key, data in host_stages.items():
            container, hostname = key.split('__', 1) if '__' in key else ('', key)
            if category_filter and container != category_filter:
                continue
            hosts.append({
                'host_name': hostname,
                'container': container,
                'stage': data.get('stage', 'new'),
                'stage_label': STAGE_LABELS.get(data.get('stage', 'new'), 'Unknown'),
                'note': data.get('note', ''),
                'updated_at': data.get('updated_at', ''),
                'updated_by': data.get('updated_by', '')
            })

        return jsonify({'success': True, 'hosts': hosts, 'total': len(hosts)}), 200
    except Exception as e:
        return _error(f'Error: {str(e)}', 500)


@api_bp.route('/api/stage-history', methods=['GET'])
def api_stage_history() -> tuple[Response, int]:
    """GET /api/stage-history — Query stage change history.

    Auth: X-API-Key header

    Optional query params:
    - host: filter by hostname
    - container: filter by container name
    - limit: max entries (default 100)
    """
    if not _check_api_key(request):
        return _error('Invalid or missing API key', 401)

    from services.stage_history import read_stage_history

    host = request.args.get('host', '').strip() or None
    container = request.args.get('container', '').strip() or None
    limit = request.args.get('limit', '100').strip()
    try:
        limit = int(limit)
    except ValueError:
        limit = 100

    try:
        entries = read_stage_history(host=host, container=container, limit=limit)
        return jsonify({'success': True, 'entries': entries, 'total': len(entries)}), 200
    except Exception as e:
        return _error(f'Error: {str(e)}', 500)
