from __future__ import annotations

import subprocess

from flask import Blueprint, render_template, request, redirect, session, jsonify, flash, Response
import os, base64, requests

from services.config import CONFIG_DIR, PROXY_PORT_OFFSET
from services.encryption import decrypt_session_value, save_encrypted_json, load_encrypted_json
from services.shared_helpers import get_nagios_servers, get_monitoring_categories

nagios_proxy_bp = Blueprint('nagios_proxy', __name__)


@nagios_proxy_bp.route('/nagios/<container_name>', methods=['GET'])
def nagios_proxy_root(container_name: str) -> str | Response:
    """GET /nagios/<container_name> — render the Nagios UI for a container."""
    if 'username' not in session:
        return redirect('/')
    
    # Get container port
    result = subprocess.run(['docker', 'port', container_name, '80'], capture_output=True, text=True, timeout=10)
    if not result.stdout:
        flash('Container not found!', 'error')
        return redirect('/dashboard')
    
    port = result.stdout.strip().split(':')[1]
    proxy_port = PROXY_PORT_OFFSET + int(port)
    
    # Update credentials for current user
    username = session.get('username')
    password = decrypt_session_value(session.get('password'))
    creds_file = f'{CONFIG_DIR}/nagios_creds_{container_name}.json'
    existing = load_encrypted_json(creds_file) if os.path.exists(creds_file) else {}
    if not existing or existing.get('username') != username or existing.get('password') != password:
        save_encrypted_json(creds_file, {'username': username, 'password': password})
    
    return render_template('nagios_view.html', username=session['username'], container=container_name, 
                         proxy_port=proxy_port, nagios_servers=get_nagios_servers(), monitoring_categories=get_monitoring_categories())


@nagios_proxy_bp.route('/nagios/cgi-bin/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'], strict_slashes=False)
def nagios_cgi_proxy(path: str) -> Response | tuple[Response, int]:
    """Proxy /nagios/cgi-bin/* requests to the target Nagios container."""
    # Extract container name from referer
    referer = request.headers.get('Referer', '')
    if '/nagios/' in referer:
        container_name = referer.split('/nagios/')[1].split('/')[0].split('?')[0]
    elif '/proxy/' in referer:
        container_name = referer.split('/proxy/')[1].split('/')[0].split('?')[0]
    else:
        return jsonify({'error': 'Container not found'}), 404
    
    if 'username' not in session or 'password' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    result = subprocess.run(['docker', 'port', container_name, '80'], capture_output=True, text=True, timeout=10)
    if not result.stdout:
        return jsonify({'error': 'Container not found'}), 404
    
    port = result.stdout.strip().split(':')[1]
    username = session.get('username')
    password = decrypt_session_value(session.get('password'))
    auth_header = f"Basic {base64.b64encode(f'{username}:{password}'.encode()).decode()}"
    
    base_url = f'http://localhost:{port}'
    target_url = f'{base_url}/cgi-bin/{path}'
    
    if request.query_string:
        target_url += '?' + request.query_string.decode()
    
    method = request.method
    data = request.get_data() if method in ['POST', 'PUT'] else None
    return forward_request(method, target_url, data, auth_header)


@nagios_proxy_bp.route('/nagios/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'], strict_slashes=False)
def nagios_static_proxy(path: str) -> Response | tuple[Response, int]:
    """Proxy /nagios/* static requests to the target Nagios container."""
    # Skip if it's a container name (single word without /)
    if '/' not in path and not path.endswith('.css') and not path.endswith('.js') and not path.endswith('.gif'):
        return jsonify({'error': 'Not found'}), 404
    
    # Extract container name from referer
    referer = request.headers.get('Referer', '')
    if '/nagios/' in referer:
        container_name = referer.split('/nagios/')[1].split('/')[0].split('?')[0]
    elif '/proxy/' in referer:
        container_name = referer.split('/proxy/')[1].split('/')[0].split('?')[0]
    else:
        return jsonify({'error': 'Container not found'}), 404
    
    if 'username' not in session or 'password' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    result = subprocess.run(['docker', 'port', container_name, '80'], capture_output=True, text=True, timeout=10)
    if not result.stdout:
        return jsonify({'error': 'Container not found'}), 404
    
    port = result.stdout.strip().split(':')[1]
    username = session.get('username')
    password = decrypt_session_value(session.get('password'))
    auth_header = f"Basic {base64.b64encode(f'{username}:{password}'.encode()).decode()}"
    
    base_url = f'http://localhost:{port}'
    target_url = f'{base_url}/nagios/{path}'
    
    if request.query_string:
        target_url += '?' + request.query_string.decode()
    
    method = request.method
    data = request.get_data() if method in ['POST', 'PUT'] else None
    return forward_request(method, target_url, data, auth_header)


@nagios_proxy_bp.route('/proxy/<container_name>', methods=['GET', 'POST', 'PUT', 'DELETE'], strict_slashes=False)
@nagios_proxy_bp.route('/proxy/<container_name>/', methods=['GET', 'POST', 'PUT', 'DELETE'], strict_slashes=False)
@nagios_proxy_bp.route('/proxy/<container_name>/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'], strict_slashes=False)
def proxy_nagios(container_name: str, path: str = '') -> Response | tuple[Response, int]:
    """Proxy /proxy/<container_name>/* requests to the target Nagios container."""
    if 'username' not in session or 'password' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Get container port
    result = subprocess.run(['docker', 'port', container_name, '80'], capture_output=True, text=True, timeout=10)
    if not result.stdout:
        return jsonify({'error': 'Container not found'}), 404
    
    port = result.stdout.strip().split(':')[1]
    username = session.get('username')
    password = decrypt_session_value(session.get('password'))
    auth_header = f"Basic {base64.b64encode(f'{username}:{password}'.encode()).decode()}"
    
    return handle_proxy_path(container_name, port, path, auth_header)


def handle_proxy_path(container_name: str, port: str, path: str, auth_header: str) -> Response:
    """Route a proxy request to the correct Nagios URL path."""
    method = request.method
    data = request.get_data() if method in ['POST', 'PUT'] else None
    base_url = f'http://localhost:{port}'
    
    # Handle different path patterns
    if path.startswith('nagios/cgi-bin/'):
        sub_path = path[len('nagios/cgi-bin/'):]
        target_url = f'{base_url}/cgi-bin/{sub_path}'
    elif path.startswith('cgi-bin/'):
        sub_path = path[len('cgi-bin/'):]
        target_url = f'{base_url}/cgi-bin/{sub_path}'
    else:
        # Remove duplicate nagios/ prefix
        while path.startswith('nagios/nagios/'):
            path = path[len('nagios/'):]
        target_url = f'{base_url}/nagios/{path}' if path else f'{base_url}/nagios'
    
    if request.query_string:
        target_url += '?' + request.query_string.decode()
    
    return forward_request(method, target_url, data, auth_header)


def forward_request(method: str, url: str, data: bytes | None, auth_header: str) -> Response:
    """Forward an HTTP request to the target URL and return the proxied response."""
    headers = {key: value for key, value in request.headers if key.lower() not in ['host', 'authorization']}
    headers['Authorization'] = auth_header
    if data and 'Content-Type' not in headers:
        headers['Content-Type'] = 'application/json'
    
    response = requests.request(method, url, headers=headers, data=data, timeout=30)
    excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection', 'www-authenticate']
    filtered_headers = [(k, v) for k, v in response.headers.items() if k.lower() not in excluded_headers]
    
    # Modify content to fix relative paths
    content = response.content
    if 'text/html' in response.headers.get('Content-Type', ''):
        try:
            content = content.decode('utf-8')
            # Add base tag to fix relative URLs
            if '<head>' in content:
                container = request.path.split('/')[2] if len(request.path.split('/')) > 2 else ''
                base_tag = f'<base href="/proxy/{container}/">'
                content = content.replace('<head>', f'<head>{base_tag}', 1)
            content = content.encode('utf-8')
        except UnicodeDecodeError:
            pass
    
    return Response(content, status=response.status_code, headers=filtered_headers)
