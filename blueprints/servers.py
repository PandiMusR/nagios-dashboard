from __future__ import annotations

from flask import Blueprint, Response, render_template, request, redirect, session, jsonify, flash
import os, json, subprocess, threading, time

from services.config import APP_ROOT, CONFIG_DIR, PROXY_PORT_OFFSET
from services.encryption import decrypt_session_value, save_encrypted_json
from services.ldap_service import log_activity
from services.shared_helpers import get_nagios_servers, get_monitoring_categories
from utils.port_check import _get_all_used_ports, check_proxy_running
from utils.permissions import check_permission

servers_bp = Blueprint('servers', __name__)


@servers_bp.route('/servers')
def servers() -> str | Response:
    """GET /servers — List all Nagios server containers."""
    if 'username' not in session:
        return redirect('/')
    
    if not check_permission('servers'):
        flash('Access denied. You do not have permission to access this page.', 'error')
        return redirect('/dashboard')
    
    # Get list of nagios containers
    result = subprocess.run(['docker', 'ps', '-a', '--filter', 'ancestor=nagios-ldap:latest', '--format', '{{json .}}'], 
                          capture_output=True, text=True, timeout=10)
    
    server_list = []
    if result.stdout:
        for line in result.stdout.strip().split('\n'):
            if line:
                container = json.loads(line)
                ports = container.get('Ports', '')
                port = ports.split(':')[1].split('->')[0] if '->' in ports else 'N/A'
                
                # Check proxy status
                proxy_port = PROXY_PORT_OFFSET + int(port) if port != 'N/A' else 0
                proxy_status = check_proxy_running(proxy_port)
                
                # Check container status
                container_running = 'Up' in container.get('Status', '')
                
                server_list.append({
                    'name': container.get('Names', ''),
                    'port': port,
                    'proxy_port': proxy_port,
                    'proxy_running': proxy_status,
                    'container_running': container_running,
                    'status': container.get('Status', '')
                })
    
    return render_template('servers.html', username=session['username'], servers=server_list, nagios_servers=get_nagios_servers(), monitoring_categories=get_monitoring_categories())


@servers_bp.route('/servers/add', methods=['POST'])
def add_server() -> Response | tuple[Response, int]:
    """POST /servers/add — Create a new Nagios server container."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    if not check_permission('servers'):
        return jsonify({'success': False, 'error': 'Access denied. You do not have permission to create servers.'}), 403
    
    name = request.form.get('name', '').strip()
    port = request.form.get('port', '').strip()
    
    # Validate inputs
    if not name or not port:
        return jsonify({'success': False, 'error': 'Server name and port are required'}), 400
    
    if not name.replace('-', '').replace('_', '').isalnum():
        return jsonify({'success': False, 'error': 'Server name can only contain alphanumeric characters, hyphens, and underscores'}), 400
    
    try:
        port_int = int(port)
        if port_int < 1000 or port_int > 65535:
            return jsonify({'success': False, 'error': 'Port must be between 1000 and 65535'}), 400
    except ValueError:
        return jsonify({'success': False, 'error': 'Port must be a valid number'}), 400
    
    # Check if container name exists in Docker
    result = subprocess.run(['docker', 'ps', '-a', '--filter', f'name=^{name}$', '--format', '{{.Names}}'], 
                          capture_output=True, text=True, timeout=5)
    if result.stdout.strip():
        log_activity('Add Server Failed', f'Server name "{name}" already exists as Docker container')
        return jsonify({'success': False, 'error': f'Server name "{name}" already exists!'})
    
    # Check if port is in use
    used_ports = _get_all_used_ports()
    
    # Check if main port or proxy port is used
    proxy_port = 1000 + port_int
    if port_int in used_ports:
        log_activity('Add Server Failed', f'Port {port_int} already in use')
        return jsonify({'success': False, 'error': f'Port {port_int} is already in use by another service!'}), 400
    
    if proxy_port in used_ports:
        log_activity('Add Server Failed', f'Proxy port {proxy_port} already in use')
        return jsonify({'success': False, 'error': f'Proxy port {proxy_port} is already in use. Please choose a different port.'}), 400
    
    try:
        # Get credentials before threading
        username = session.get('username')
        password = decrypt_session_value(session.get('password'))
        # Capture ip before entering thread (request context unavailable inside thread)
        client_ip = request.remote_addr
        
        # Start build process in background
        def build_server() -> None:
            try:
                # Run build script with error capture
                result = subprocess.run([f'{APP_ROOT}/create-nagios/build.sh', name, str(port_int)], 
                                      capture_output=True, text=True, timeout=600)  # 10 minute timeout
                
                if result.returncode != 0:
                    error_msg = result.stderr or result.stdout or 'Unknown error'
                    log_activity('Add Server Failed', f'Build script failed for "{name}": {error_msg}', username=username, ip=client_ip)
                    print(f"Build script error for {name}: {error_msg}")
                    return
                
                # Save credentials (encrypted)
                creds_file = f'{CONFIG_DIR}/nagios_creds_{name}.json'
                save_encrypted_json(creds_file, {'username': username, 'password': password})
                
                # Start proxy
                result = subprocess.run(['python3', f'{APP_ROOT}/start_proxy_daemon.py', name, str(port_int), str(proxy_port)],
                                      capture_output=True, text=True, timeout=60)
                
                if result.returncode != 0:
                    error_msg = result.stderr or result.stdout or 'Unknown error'
                    log_activity('Add Server', f'Server "{name}" container created, but proxy failed: {error_msg}', username=username, ip=client_ip)
                    print(f"Proxy error for {name}: {error_msg}")
                else:
                    log_activity('Add Server', f'Server "{name}" created successfully on port {port_int}', username=username, ip=client_ip)
                    
            except subprocess.TimeoutExpired:
                log_activity('Add Server Failed', f'Server creation for "{name}" timed out', username=username, ip=client_ip)
                print(f"Timeout building server {name}")
            except Exception as e:
                log_activity('Add Server Failed', f'Error building server "{name}": {str(e)}', username=username, ip=client_ip)
                print(f"Exception building server {name}: {str(e)}")
        
        thread = threading.Thread(target=build_server)
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'name': name})
    except Exception as e:
        log_activity('Add Server Failed', f'Failed to create server "{name}": {str(e)}')
        return jsonify({'success': False, 'error': 'Failed to create server!'}), 500


@servers_bp.route('/servers/batch-start', methods=['POST'])
def batch_start_servers() -> Response | tuple[Response, int]:
    """POST /servers/batch-start — Start multiple Nagios containers."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    servers_list = request.json.get('servers', [])
    if not servers_list:
        return jsonify({'success': False, 'error': 'No servers selected'})
    
    try:
        for server in servers_list:
            subprocess.run(['docker', 'start', server], capture_output=True, timeout=30)
        log_activity('Batch Start', f'Started {len(servers_list)} servers')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@servers_bp.route('/api/servers/check-port/<int:port>')
def check_port_available(port: int) -> Response | tuple[Response, int]:
    """Check if a port is available for use"""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    if port < 1000 or port > 65535:
        return jsonify({'available': False, 'reason': 'Port must be between 1000 and 65535'})
    
    used_ports = _get_all_used_ports()
    
    proxy_port = 1000 + port
    is_available = port not in used_ports and proxy_port not in used_ports
    
    return jsonify({
        'available': is_available,
        'port': port,
        'proxy_port': proxy_port,
        'reason': None if is_available else f'Port {port} or proxy port {proxy_port} is in use'
    })


@servers_bp.route('/api/servers/get-available-port')
def get_available_port() -> Response | tuple[Response, int]:
    """Find and return an available port"""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    used_ports = _get_all_used_ports()
    
    # Find first available port starting from 8080
    recommended_port = None
    for test_port in range(8080, 65536):
        proxy_port = 1000 + test_port
        if test_port not in used_ports and proxy_port not in used_ports:
            recommended_port = test_port
            break
    
    if recommended_port:
        return jsonify({'available': True, 'port': recommended_port, 'proxy_port': 1000 + recommended_port})
    else:
        return jsonify({'available': False, 'reason': 'No available ports found'})


@servers_bp.route('/servers/batch-restart', methods=['POST'])
def batch_restart_servers() -> Response | tuple[Response, int]:
    """POST /servers/batch-restart — Restart multiple Nagios containers."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    servers_list = request.json.get('servers', [])
    if not servers_list:
        return jsonify({'success': False, 'error': 'No servers selected'})
    
    try:
        for server in servers_list:
            subprocess.run(['docker', 'restart', server], capture_output=True, timeout=60)
        log_activity('Batch Restart', f'Restarted {len(servers_list)} servers')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@servers_bp.route('/servers/batch-delete', methods=['POST'])
def batch_delete_servers() -> Response | tuple[Response, int]:
    """POST /servers/batch-delete — Delete multiple Nagios containers and their data."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    data = request.get_json()
    servers_list = data.get('servers', []) if data else []
    
    if not servers_list:
        return jsonify({'success': False, 'error': 'No servers selected'})
    
    try:
        for server in servers_list:
            # Validate server exists before deleting
            from services.shared_helpers import get_nagios_servers as _get_servers
            valid_servers = _get_servers()
            if server not in valid_servers:
                log_activity('Batch Delete Failed', f'Unknown server: {server}')
                continue
            # Stop and remove container
            subprocess.run(['docker', 'stop', server], capture_output=True, timeout=30)
            subprocess.run(['docker', 'rm', server], capture_output=True, timeout=30)
            subprocess.run(['rm', '-rf', f'/svr/{server}'], capture_output=True, timeout=30)
        
        log_activity('Batch Delete', f'Deleted {len(servers_list)} servers: {", ".join(servers_list)}')
        return jsonify({'success': True})
    except Exception as e:
        log_activity('Batch Delete Failed', str(e))
        return jsonify({'success': False, 'error': str(e)})


@servers_bp.route('/servers/check-config/<name>')
def check_config(name: str) -> Response | tuple[Response, int]:
    """GET /servers/check-config/<name> — Validate Nagios config for a server."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        result = subprocess.run(
            ['docker', 'exec', name, '/opt/nagios/bin/nagios', '-v', '/opt/nagios/etc/nagios.cfg'],
            capture_output=True, text=True, timeout=30
        )
        
        output = result.stdout + result.stderr
        success = result.returncode == 0
        
        return jsonify({
            'success': success,
            'output': output,
            'returncode': result.returncode
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@servers_bp.route('/servers/start-all-containers', methods=['POST'])
def start_all_containers() -> Response | tuple[Response, int]:
    """POST /servers/start-all-containers — Start all stopped Nagios containers."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        result = subprocess.run(['docker', 'ps', '-a', '--filter', 'ancestor=nagios-ldap:latest', '--format', '{{.Names}}'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.stdout:
            containers = result.stdout.strip().split('\n')
            for container in containers:
                if container:
                    subprocess.run(['docker', 'start', container], capture_output=True, timeout=30)
            
            log_activity('Start All Containers', 'All containers started')
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'No containers found'})
    except Exception as e:
        log_activity('Start All Containers Failed', str(e))
        return jsonify({'success': False, 'error': str(e)})


@servers_bp.route('/servers/start-all-proxies', methods=['POST'])
def start_all_proxies() -> Response | tuple[Response, int]:
    """POST /servers/start-all-proxies — Start proxies for all running Nagios containers."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        result = subprocess.run(['docker', 'ps', '--filter', 'ancestor=nagios-ldap:latest', '--format', '{{.Names}}'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.stdout:
            containers = result.stdout.strip().split('\n')
            for container in containers:
                if container:
                    port_result = subprocess.run(['docker', 'port', container, '80'], capture_output=True, text=True, timeout=10)
                    if port_result.stdout:
                        port = port_result.stdout.strip().split(':')[1]
                        proxy_port = PROXY_PORT_OFFSET + int(port)
                        
                        username = session.get('username')
                        password = decrypt_session_value(session.get('password'))
                        creds_file = f'{CONFIG_DIR}/nagios_creds_{container}.json'
                        save_encrypted_json(creds_file, {'username': username, 'password': password})
                        
                        subprocess.run(['python3', f'{APP_ROOT}/start_proxy_daemon.py', container, port, str(proxy_port)], timeout=60)
            
            log_activity('Start All Proxies', 'All proxies started')
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'No running containers found'})
    except Exception as e:
        log_activity('Start All Proxies Failed', str(e))
        return jsonify({'success': False, 'error': str(e)})


@servers_bp.route('/servers/start-all', methods=['POST'])
def start_all_servers() -> Response | tuple[Response, int]:
    """POST /servers/start-all — Start all containers and their proxies."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        # Get all nagios containers
        result = subprocess.run(['docker', 'ps', '-a', '--filter', 'ancestor=nagios-ldap:latest', '--format', '{{.Names}}'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.stdout:
            containers = result.stdout.strip().split('\n')
            for container in containers:
                if container:
                    # Start container
                    subprocess.run(['docker', 'start', container], capture_output=True, timeout=30)
                    
                    # Start proxy
                    port_result = subprocess.run(['docker', 'port', container, '80'], capture_output=True, text=True, timeout=10)
                    if port_result.stdout:
                        port = port_result.stdout.strip().split(':')[1]
                        proxy_port = PROXY_PORT_OFFSET + int(port)
                        
                        # Store credentials
                        username = session.get('username')
                        password = decrypt_session_value(session.get('password'))
                        creds_file = f'{CONFIG_DIR}/nagios_creds_{container}.json'
                        save_encrypted_json(creds_file, {'username': username, 'password': password})
                        
                        # Start proxy
                        subprocess.run(['python3', f'{APP_ROOT}/start_proxy_daemon.py', container, port, str(proxy_port)], timeout=60)
            
            log_activity('Start All', 'All servers and proxies started')
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'No servers found'})
    except Exception as e:
        log_activity('Start All Failed', str(e))
        return jsonify({'success': False, 'error': str(e)})


@servers_bp.route('/servers/check/<name>')
def check_server(name: str) -> Response | tuple[Response, int]:
    """GET /servers/check/<name> — Check if a Docker container exists."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    result = subprocess.run(['docker', 'ps', '-a', '--filter', f'name=^{name}$', '--format', '{{.Names}}'], 
                          capture_output=True, text=True, timeout=10)
    exists = bool(result.stdout.strip())
    return jsonify({'exists': exists})


@servers_bp.route('/servers/delete/<name>', methods=['POST'])
def delete_server(name: str) -> Response:
    """POST /servers/delete/<name> — Stop and remove a Nagios server container."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        subprocess.run(['docker', 'stop', name], check=True, capture_output=True, timeout=30)
        subprocess.run(['docker', 'rm', name], check=True, capture_output=True, timeout=30)
        subprocess.run(['rm', '-rf', f'/svr/{name}'], check=True, capture_output=True, timeout=30)
        flash(f'Server "{name}" deleted successfully!', 'success')
        return redirect('/servers')
    except (subprocess.CalledProcessError, OSError):
        flash('Failed to delete server!', 'error')
        return redirect('/servers')


@servers_bp.route('/servers/restart/<name>', methods=['POST'])
def restart_server(name: str) -> Response:
    """POST /servers/restart/<name> — Restart a Nagios server container."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        subprocess.run(['docker', 'restart', name], check=True, capture_output=True, timeout=60)
        flash(f'Server "{name}" restarted successfully!', 'success')
        return redirect('/servers')
    except (subprocess.CalledProcessError, OSError):
        flash('Failed to restart server!', 'error')
        return redirect('/servers')


@servers_bp.route('/servers/stop/<name>', methods=['POST'])
def stop_server(name: str) -> Response:
    """POST /servers/stop/<name> — Stop a Nagios server container."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        subprocess.run(['docker', 'stop', name], check=True, capture_output=True, timeout=30)
        flash(f'Server "{name}" stopped successfully!', 'success')
        return redirect('/servers')
    except (subprocess.CalledProcessError, OSError):
        flash('Failed to stop server!', 'error')
        return redirect('/servers')


@servers_bp.route('/servers/edit-config/<name>', methods=['GET', 'POST'])
def edit_server_config(name: str) -> str | Response:
    """GET/POST /servers/edit-config/<name> — View or update Nagios config file."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    config_path = f'/svr/{name}/etc/objects/localhost.cfg'
    
    if request.method == 'POST':
        content = request.form.get('content')
        try:
            with open(config_path, 'w') as f:
                f.write(content)
            
            # Restart nagios container to apply changes
            subprocess.run(['docker', 'exec', name, '/opt/nagios/bin/nagios', '-v', '/opt/nagios/etc/nagios.cfg'], 
                         capture_output=True, text=True, timeout=30)
            subprocess.run(['docker', 'restart', name], check=True, capture_output=True, timeout=60)
            
            log_activity('Edit Config', f'Config for "{name}" updated')
            flash(f'Config for "{name}" updated and restarted!', 'success')
            return redirect('/servers')
        except Exception as e:
            log_activity('Edit Config Failed', f'Failed to update config for "{name}": {str(e)}')
            flash(f'Failed to update config: {str(e)}', 'error')
            return redirect('/servers')
    
    # GET request - show editor
    try:
        with open(config_path, 'r') as f:
            content = f.read()
        return render_template('edit_config.html', username=session['username'], 
                             server_name=name, content=content,
                             nagios_servers=get_nagios_servers(), 
                             monitoring_categories=get_monitoring_categories())
    except Exception as e:
        flash(f'Failed to read config: {str(e)}', 'error')
        return redirect('/servers')


@servers_bp.route('/servers/plugins/<name>')
def list_plugins(name: str) -> Response | tuple[Response, int]:
    """GET /servers/plugins/<name> — List plugins for a Nagios server."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    plugin_dir = f'/svr/{name}/plugin'
    plugins = []
    
    try:
        if os.path.exists(plugin_dir):
            for filename in os.listdir(plugin_dir):
                filepath = os.path.join(plugin_dir, filename)
                if os.path.isfile(filepath):
                    size = os.path.getsize(filepath)
                    size_str = f"{size} bytes" if size < 1024 else f"{size/1024:.1f} KB"
                    plugins.append({'name': filename, 'size': size_str})
    except Exception:
        return jsonify({'error': 'Internal server error'}), 500
    
    return jsonify({'plugins': plugins})


@servers_bp.route('/servers/plugins/upload', methods=['POST'])
def upload_plugin() -> Response | tuple[Response, int]:
    """POST /servers/plugins/upload — Upload a plugin file to a server."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    server = request.form.get('server')
    plugin_file = request.files.get('plugin_file')
    
    if not plugin_file or not plugin_file.filename:
        return jsonify({'success': False, 'error': 'No file provided'})
    
    try:
        plugin_dir = f'/svr/{server}/plugin'
        os.makedirs(plugin_dir, exist_ok=True)

        from werkzeug.utils import secure_filename
        safe_name = secure_filename(plugin_file.filename)
        if not safe_name:
            flash('Invalid filename', 'danger')
            return jsonify({'success': False, 'error': 'Invalid filename'})
        filepath = os.path.join(plugin_dir, safe_name)
        plugin_file.save(filepath)
        
        # Make executable
        os.chmod(filepath, 0o755)
        
        log_activity('Upload Plugin', f'Plugin "{plugin_file.filename}" uploaded to {server}')
        return jsonify({'success': True})
    except Exception as e:
        log_activity('Upload Plugin Failed', f'Failed to upload plugin to {server}: {str(e)}')
        return jsonify({'success': False, 'error': str(e)})


@servers_bp.route('/servers/plugins/<name>/<filename>', methods=['DELETE'])
def delete_plugin(name: str, filename: str) -> Response | tuple[Response, int]:
    """DELETE /servers/plugins/<name>/<filename> — Remove a plugin file from a server."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        filepath = os.path.join(f'/svr/{name}/plugin', filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            log_activity('Delete Plugin', f'Plugin "{filename}" deleted from {name}')
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'File not found'})
    except Exception as e:
        log_activity('Delete Plugin Failed', f'Failed to delete plugin from {name}: {str(e)}')
        return jsonify({'success': False, 'error': str(e)})


@servers_bp.route('/servers/start/<name>', methods=['POST'])
def start_server(name: str) -> Response:
    """POST /servers/start/<name> — Start a stopped Nagios server container."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        subprocess.run(['docker', 'start', name], check=True, capture_output=True, timeout=30)
        flash(f'Server "{name}" started successfully!', 'success')
        return redirect('/servers')
    except (subprocess.CalledProcessError, OSError):
        flash('Failed to start server!', 'error')
        return redirect('/servers')


@servers_bp.route('/proxy/start/<name>', methods=['POST'])
def start_proxy(name: str) -> Response:
    """POST /proxy/start/<name> — Start the proxy for a Nagios server."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        result = subprocess.run(['docker', 'port', name, '80'], capture_output=True, text=True, timeout=10)
        if result.stdout:
            port = result.stdout.strip().split(':')[1]
            proxy_port = PROXY_PORT_OFFSET + int(port)
            
            # Store credentials for proxy
            username = session.get('username')
            password = decrypt_session_value(session.get('password'))
            creds_file = f'{CONFIG_DIR}/nagios_creds_{name}.json'
            save_encrypted_json(creds_file, {'username': username, 'password': password})
            
            # Log start attempt
            with open(f'/tmp/proxy_start_{name}.log', 'w') as log:
                log.write(f'Starting proxy for {name}\n')
                log.write(f'Port: {port}, Proxy Port: {proxy_port}\n')
                log.write(f'Script: {APP_ROOT}/start_proxy.sh {name} {port} {proxy_port}\n')
            
            # Start proxy using Python daemon script
            result = subprocess.run(['python3', f'{APP_ROOT}/start_proxy_daemon.py', name, port, str(proxy_port)], 
                                  capture_output=True, text=True, timeout=60)
            
            with open(f'/tmp/proxy_start_{name}.log', 'a') as log:
                log.write(f'Return code: {result.returncode}\n')
                log.write(f'Stdout: {result.stdout}\n')
                log.write(f'Stderr: {result.stderr}\n')
            
            time.sleep(2)
            
            # Check if proxy is running
            check = subprocess.run(['lsof', '-i', f':{proxy_port}', '-t'], capture_output=True, text=True, timeout=5)
            
            with open(f'/tmp/proxy_start_{name}.log', 'a') as log:
                log.write(f'Check running: {check.stdout}\n')
            
            if check.stdout.strip():
                flash(f'Proxy for "{name}" started on port {proxy_port}!', 'success')
            else:
                flash(f'Proxy failed to start. Check /tmp/proxy_start_{name}.log and /tmp/proxy_{name}.log', 'error')
        return redirect('/servers')
    except Exception as e:
        flash(f'Failed to start proxy: {str(e)}', 'error')
        return redirect('/servers')


@servers_bp.route('/proxy/stop/<name>', methods=['POST'])
def stop_proxy(name: str) -> Response:
    """POST /proxy/stop/<name> — Stop the proxy for a Nagios server."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        result = subprocess.run(['docker', 'port', name, '80'], capture_output=True, text=True, timeout=10)
        if result.stdout:
            port = result.stdout.strip().split(':')[1]
            proxy_port = PROXY_PORT_OFFSET + int(port)
            subprocess.run(['pkill', '-f', f'proxy.py {name} {port}'], check=True, capture_output=True, timeout=10)
            flash(f'Proxy for "{name}" stopped!', 'success')
        return redirect('/servers')
    except (subprocess.CalledProcessError, OSError):
        flash('Failed to stop proxy!', 'error')
        return redirect('/servers')


@servers_bp.route('/proxy/restart/<name>', methods=['POST'])
def restart_proxy(name: str) -> Response:
    """POST /proxy/restart/<name> — Restart the proxy for a Nagios server."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('servers'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        result = subprocess.run(['docker', 'port', name, '80'], capture_output=True, text=True, timeout=10)
        if result.stdout:
            port = result.stdout.strip().split(':')[1]
            proxy_port = PROXY_PORT_OFFSET + int(port)
            
            # Kill existing
            subprocess.run(['pkill', '-9', '-f', f'proxy.py {name}'], capture_output=True, timeout=10)
            
            # Store credentials
            username = session.get('username')
            password = decrypt_session_value(session.get('password'))
            creds_file = f'{CONFIG_DIR}/nagios_creds_{name}.json'
            save_encrypted_json(creds_file, {'username': username, 'password': password})
            
            # Start new
            subprocess.run(['python3', f'{APP_ROOT}/start_proxy_daemon.py', name, port, str(proxy_port)], timeout=60)
            
            flash(f'Proxy for "{name}" restarted!', 'success')
        return redirect('/servers')
    except (subprocess.CalledProcessError, OSError):
        flash('Failed to restart proxy!', 'error')
        return redirect('/servers')
