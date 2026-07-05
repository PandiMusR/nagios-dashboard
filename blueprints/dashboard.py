from __future__ import annotations

import base64, json, subprocess

from flask import Blueprint, Response, render_template, redirect, session, jsonify
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from services.encryption import decrypt_session_value
from services.docker_cache import docker_cache
from services.shared_helpers import get_nagios_servers, get_monitoring_categories

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/dashboard')
def dashboard() -> str | Response:
    """GET /dashboard — Main dashboard page."""
    if 'username' not in session:
        return redirect('/')
    
    # Debug: print session info
    print(f"DEBUG - Session: role={session.get('role')}, permissions={session.get('permissions')}")
    
    return render_template('dashboard.html', username=session['username'], nagios_servers=get_nagios_servers(), monitoring_categories=get_monitoring_categories())


def _fetch_server_stats(container_name: str, auth_header: str) -> dict | None:
    """Fetch stats for a single Nagios container. Runs in a thread."""
    try:
        # Get container port (cached)
        port_output = docker_cache.get_or_run(
            f'port_{container_name}',
            ['docker', 'port', container_name, '80']
        ).strip()
        port = port_output.split(':')[-1] if port_output else None

        if not port:
            return None

        # Get container stats (cached)
        stats_output = docker_cache.get_or_run(
            f'stats_{container_name}',
            ['docker', 'stats', container_name, '--no-stream', '--format', '{{.CPUPerc}}|{{.MemUsage}}']
        )
        cpu_usage = '0%'
        mem_usage = '0MB / 0MB'
        if stats_output.strip():
            parts = stats_output.strip().split('|')
            if len(parts) == 2:
                cpu_usage = parts[0]
                mem_usage = parts[1]

        # Get Nagios data
        status_url = f'http://localhost:{port}/nagios/cgi-bin/statusjson.cgi?query=hostlist&details=true'
        service_url = f'http://localhost:{port}/nagios/cgi-bin/statusjson.cgi?query=servicelist&details=true'

        status_resp = requests.get(status_url, headers={'Authorization': auth_header}, timeout=5)
        service_resp = requests.get(service_url, headers={'Authorization': auth_header}, timeout=5)

        hosts_up = hosts_down = hosts_unreachable = 0
        services_ok = services_warning = services_critical = services_unknown = 0

        if status_resp.status_code == 200:
            hostlist = status_resp.json().get('data', {}).get('hostlist', {})
            for hostname, host in hostlist.items():
                status_code = host.get('status', 0)
                if status_code == 2:
                    hosts_up += 1
                elif status_code == 4:
                    hosts_down += 1
                elif status_code == 8:
                    hosts_unreachable += 1

        if service_resp.status_code == 200:
            servicelist = service_resp.json().get('data', {}).get('servicelist', {})
            for hostname, services in servicelist.items():
                for service_name, service in services.items():
                    status_code = service.get('status', 0)
                    if status_code == 2:
                        services_ok += 1
                    elif status_code == 4:
                        services_warning += 1
                    elif status_code == 16:
                        services_critical += 1
                    else:
                        services_unknown += 1

        return {
            'name': container_name,
            'port': port,
            'cpu': cpu_usage,
            'memory': mem_usage,
            'hosts': {
                'up': hosts_up,
                'down': hosts_down,
                'unreachable': hosts_unreachable,
                'total': hosts_up + hosts_down + hosts_unreachable
            },
            'services': {
                'ok': services_ok,
                'warning': services_warning,
                'critical': services_critical,
                'unknown': services_unknown,
                'total': services_ok + services_warning + services_critical + services_unknown
            }
        }
    except (requests.RequestException, json.JSONDecodeError, subprocess.SubprocessError, OSError):
        return None


@dashboard_bp.route('/dashboard/stats')
def dashboard_stats() -> Response | tuple[Response, int]:
    """GET /dashboard/stats — JSON stats for all Nagios servers.

    Uses Docker cache and parallel fetching for faster response times.
    """
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        auth_header = f"Basic {base64.b64encode(f'{session.get('username')}:{decrypt_session_value(session.get('password'))}'.encode()).decode()}"

        # Get running containers (cached)
        containers_output = docker_cache.get_or_run(
            'nagios_containers_names',
            ['docker', 'ps', '--filter', 'ancestor=nagios-ldap:latest', '--format', '{{.Names}}']
        )

        containers = []
        if containers_output.strip():
            for container_name in containers_output.strip().split('\n'):
                if not container_name:
                    continue
                # Check permissions
                if session.get('role') != 'admin':
                    user_perms = session.get('permissions', {})
                    if not user_perms.get(f'nagios_{container_name}'):
                        continue
                containers.append(container_name)

        # Parallel fetch stats from all containers
        servers_stats = []
        if containers:
            with ThreadPoolExecutor(max_workers=min(len(containers), 10)) as executor:
                futures = {
                    executor.submit(_fetch_server_stats, name, auth_header): name
                    for name in containers
                }
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        if result:
                            servers_stats.append(result)
                    except Exception:
                        continue

        return jsonify({'servers': servers_stats})
    except Exception as e:
        return jsonify({'servers': [], 'error': str(e)})
