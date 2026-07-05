from __future__ import annotations

from flask import Blueprint, Response, render_template, request, redirect, session, jsonify, flash
import os, json, subprocess, base64, requests, csv, io
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from services.config import (
    CONFIG_DIR, MONITORING_CATEGORIES_PATH, MONITORING_SERVER_MAPPINGS_PATH, MONITORING_CONFIG_PATH,
    STAGE_NEW, STAGE_CS, STAGE_ESCALATED, STAGE_WATCHLIST, STAGE_RESOLVED, STAGE_LABELS, STAGE_RETAIN_MINUTES
)
from services.encryption import decrypt_session_value
from services.ldap_service import log_activity
from services.stage_service import load_host_stages, save_host_stages, host_stages_transaction, get_stage_key, _stages_lock
from services.docker_cache import docker_cache
from services.stage_history import append_stage_history
from utils.permissions import check_permission

monitoring_bp = Blueprint('monitoring', __name__)


def get_nagios_servers() -> list[str]:
    """Return list of running Nagios container names."""
    result = subprocess.run(['docker', 'ps', '--filter', 'ancestor=nagios-ldap:latest', '--format', '{{.Names}}'],
                          capture_output=True, text=True, timeout=10)
    return result.stdout.strip().split('\n') if result.stdout.strip() else []


def get_monitoring_categories() -> list[str]:
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


@monitoring_bp.route('/monitoring/<page>')
def monitoring(page: str) -> str | Response:
    """GET /monitoring/<page> — Monitoring page for a given category."""
    if 'username' not in session:
        return redirect('/')

    return render_template('monitoring.html', username=session['username'], page=page,
                         hosts=[], total_down=0,
                         nagios_servers=get_nagios_servers(), monitoring_categories=get_monitoring_categories())


def _fetch_container_data(container_name: str, port: str, auth_header: str, use_service_plugin: bool) -> list[dict]:
    """Fetch host data from a single Nagios container. Runs in a thread."""
    hosts = []
    try:
        status_url = f'http://localhost:{port}/nagios/cgi-bin/statusjson.cgi?query=hostlist&details=true'
        object_url = f'http://localhost:{port}/nagios/cgi-bin/objectjson.cgi?details=true&query=hostlist'

        status_resp = requests.get(status_url, headers={'Authorization': auth_header}, timeout=5)
        object_resp = requests.get(object_url, headers={'Authorization': auth_header}, timeout=5)

        if status_resp.status_code != 200 or object_resp.status_code != 200:
            return hosts

        status_data = status_resp.json()
        object_data = object_resp.json()

        hostlist = status_data.get('data', {}).get('hostlist', {})
        ip_mapping = {h: d.get('address', 'N/A') for h, d in object_data.get('data', {}).get('hostlist', {}).items()}

        service_data = {}
        if use_service_plugin:
            service_url = f'http://localhost:{port}/nagios/cgi-bin/statusjson.cgi?query=servicelist&details=true'
            service_resp = requests.get(service_url, headers={'Authorization': auth_header}, timeout=5)
            if service_resp.status_code == 200:
                services = service_resp.json().get('data', {}).get('servicelist', {})
                for hostname, host_services in services.items():
                    for service_name, service_info in host_services.items():
                        service_data[hostname] = service_info.get('plugin_output', '')
                        break

        for hostname, host in hostlist.items():
            hosts.append({
                'hostname': hostname,
                'host': host,
                'container_name': container_name,
                'port': port,
                'ip_mapping': ip_mapping,
                'service_data': service_data,
            })
    except (requests.RequestException, json.JSONDecodeError, ValueError, KeyError):
        pass
    return hosts


def _fetch_monitoring_hosts(page: str) -> list[dict]:
    """Fetch monitoring host data for a category. Shared by monitoring_data and export_csv.

    Returns list of host dicts with stage info. Handles stage transitions
    (UP cleanup, flapping retention, auto-create New).
    """
    # Load server mappings for this category
    server_mappings = {}
    try:
        if os.path.exists(MONITORING_SERVER_MAPPINGS_PATH):
            with open(MONITORING_SERVER_MAPPINGS_PATH, 'r') as f:
                server_mappings = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass

    category_servers = server_mappings.get(page, [])

    # Check if category uses service plugin
    use_service_plugin = False
    try:
        if os.path.exists(MONITORING_CONFIG_PATH):
            with open(MONITORING_CONFIG_PATH, 'r') as f:
                config = json.load(f)
                use_service_plugin = config.get('category_settings', {}).get(page, {}).get('use_service_plugin', False)
    except (json.JSONDecodeError, OSError):
        pass

    auth_header = f"Basic {base64.b64encode(f'{session.get('username')}:{decrypt_session_value(session.get('password'))}'.encode()).decode()}"
    all_hosts = []

    # Load host stages once before processing all containers (thread-safe)
    with _stages_lock:
        host_stages = load_host_stages()
    stages_dirty = False

    # Get all running nagios containers (cached for 15s)
    docker_output = docker_cache.get_or_run(
        'nagios_containers',
        ['docker', 'ps', '--filter', 'ancestor=nagios-ldap:latest', '--format', '{{.Names}}:{{.Ports}}']
    )

    # Collect containers to fetch from
    containers_to_fetch = []
    if docker_output:
        for line in docker_output.strip().split('\n'):
            if ':' in line:
                container_name, ports = line.split(':', 1)
                if container_name not in category_servers:
                    continue
                if '->' in ports:
                    port = ports.split(':')[1].split('->')[0]
                    containers_to_fetch.append((container_name, port))

    # Parallel fetch from all containers
    if containers_to_fetch:
        with ThreadPoolExecutor(max_workers=min(len(containers_to_fetch), 10)) as executor:
            futures = {
                executor.submit(_fetch_container_data, name, port, auth_header, use_service_plugin): name
                for name, port in containers_to_fetch
            }
            for future in as_completed(futures):
                try:
                    raw_hosts = future.result()
                    for item in raw_hosts:
                        hostname = item['hostname']
                        host = item['host']
                        container_name = item['container_name']
                        port = item['port']
                        ip_mapping = item['ip_mapping']
                        service_data = item['service_data']

                        now = datetime.now()
                        status_code = host.get('status', 0)
                        host_is_down = status_code in (4, 8)
                        host_is_up = status_code == 2
                        stage_key = get_stage_key(container_name, hostname)
                        stage_info = host_stages.get(stage_key)

                        # --- Handle UP hosts ---
                        if host_is_up and stage_info:
                            current_stage = stage_info.get('stage', STAGE_NEW)

                            if current_stage == STAGE_WATCHLIST:
                                if not stage_info.get('host_up_since'):
                                    stage_info['host_up_since'] = now.isoformat()
                                    stages_dirty = True
                                else:
                                    try:
                                        up_since = datetime.fromisoformat(stage_info['host_up_since'])
                                        if (now - up_since).total_seconds() > STAGE_RETAIN_MINUTES * 60:
                                            del host_stages[stage_key]
                                            stages_dirty = True
                                            stage_info = None
                                    except (ValueError, TypeError):
                                        del host_stages[stage_key]
                                        stages_dirty = True
                                        stage_info = None
                            else:
                                del host_stages[stage_key]
                                stages_dirty = True
                                stage_info = None
                            continue

                        # --- Handle DOWN hosts ---
                        if not host_is_down:
                            continue

                        if host.get('problem_has_been_acknowledged', False):
                            if stage_info:
                                del host_stages[stage_key]
                                stages_dirty = True
                            continue

                        if stage_info and stage_info.get('host_up_since'):
                            stage_info['host_up_since'] = None
                            stages_dirty = True

                        if not stage_info:
                            stage_info = {
                                'stage': STAGE_NEW,
                                'updated_at': now.isoformat(),
                                'updated_by': 'system',
                                'host_up_since': None
                            }
                            host_stages[stage_key] = stage_info
                            stages_dirty = True

                        last_check = datetime.fromtimestamp(host.get('last_check', 0)/1000)
                        last_state = datetime.fromtimestamp(host.get('last_state_change', 0)/1000)
                        dur = now - last_state
                        status_label = "UNREACHABLE" if status_code == 8 else "DOWN"
                        status_info = service_data.get(hostname, host.get('plugin_output', '')) if use_service_plugin else host.get('plugin_output', '')

                        all_hosts.append({
                            'host_name': host.get('name', hostname),
                            'ip_address': ip_mapping.get(hostname, 'N/A'),
                            'status': status_label,
                            'last_check': last_check.strftime("%Y-%m-%d %H:%M:%S"),
                            'last_state_change': host.get('last_state_change', 0),
                            'duration_str': str(dur).split('.')[0],
                            'status_information': status_info,
                            'container': container_name,
                            'port': port,
                            'stage': stage_info.get('stage', STAGE_NEW),
                            'stage_label': STAGE_LABELS.get(stage_info.get('stage', STAGE_NEW), 'New / Unacknowledged'),
                            'stage_updated_by': stage_info.get('updated_by', ''),
                            'stage_updated_at': stage_info.get('updated_at', ''),
                            'stage_note': stage_info.get('note', ''),
                        })
                except Exception:
                    continue

    # Save stages once after processing all containers (thread-safe)
    if stages_dirty:
        save_host_stages(host_stages)

    # Sort by last_state_change descending (newest first)
    all_hosts.sort(key=lambda x: x['last_state_change'], reverse=True)

    # Filter for cr_view_only users — only show CR Verification stage
    if session.get('permissions', {}).get('cr_view_only'):
        all_hosts = [h for h in all_hosts if h.get('stage') == STAGE_CS]

    return all_hosts


@monitoring_bp.route('/monitoring/<page>/data')
def monitoring_data(page: str) -> Response | tuple[Response, int]:
    """GET /monitoring/<page>/data — JSON monitoring data for a category."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        all_hosts = _fetch_monitoring_hosts(page)
        return jsonify({'hosts': all_hosts, 'total_down': len(all_hosts)})
    except Exception as e:
        return jsonify({'hosts': [], 'total_down': 0, 'error': str(e)})


@monitoring_bp.route('/monitoring/<page>/export-csv')
def export_monitoring_csv(page: str) -> Response | tuple[Response, int]:
    """GET /monitoring/<page>/export-csv — Download monitoring data as CSV."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        hosts = _fetch_monitoring_hosts(page)
    except Exception as e:
        return jsonify({'error': f'Failed to fetch data: {str(e)}'}), 500

    # Apply filters from query params (same as frontend)
    server_filter = request.args.get('server', '')
    status_filter = request.args.get('status', '')
    stage_filter = request.args.get('stage', '')
    keyword_filter = request.args.get('keyword', '').lower()

    if server_filter:
        hosts = [h for h in hosts if h.get('container') == server_filter]
    if status_filter:
        hosts = [h for h in hosts if h.get('status') == status_filter]
    if stage_filter:
        hosts = [h for h in hosts if h.get('stage') == stage_filter]
    if keyword_filter:
        hosts = [h for h in hosts if keyword_filter in h.get('host_name', '').lower()
                 or keyword_filter in h.get('status_information', '').lower()
                 or keyword_filter in h.get('ip_address', '').lower()]

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        'Server', 'Host', 'IP Address', 'Status', 'Stage', 'Stage Note',
        'Duration', 'Last Check', 'Detail', 'Updated By', 'Updated At'
    ])

    # Data rows
    for host in hosts:
        writer.writerow([
            host.get('container', ''),
            host.get('host_name', ''),
            host.get('ip_address', ''),
            host.get('status', ''),
            host.get('stage_label', ''),
            host.get('stage_note', ''),
            host.get('duration_str', ''),
            host.get('last_check', ''),
            host.get('status_information', ''),
            host.get('stage_updated_by', ''),
            host.get('stage_updated_at', ''),
        ])

    # Build response with UTF-8 BOM for Excel compatibility
    csv_content = '\ufeff' + output.getvalue()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'monitoring_{page}_{timestamp}.csv'

    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@monitoring_bp.route('/monitoring/acknowledge', methods=['POST'])
def acknowledge_host() -> Response:
    """POST /monitoring/acknowledge — Acknowledge a single host problem in Nagios."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    host_name = request.form.get('host_name')
    port = request.form.get('port')
    comment = request.form.get('comment', '').strip()

    if not comment:
        flash('Comment is required!', 'error')
        return redirect(request.referrer or '/dashboard')

    try:
        username = session.get('username')
        password = decrypt_session_value(session.get('password'))
        auth_header = f"Basic {base64.b64encode(f'{username}:{password}'.encode()).decode()}"

        cmd_url = f'http://localhost:{port}/nagios/cgi-bin/cmd.cgi'

        # Nagios command untuk acknowledge host problem
        data = {
            'cmd_typ': '33',  # ACKNOWLEDGE_HOST_PROBLEM
            'cmd_mod': '2',
            'host': host_name,
            'com_author': username,
            'com_data': comment,
            'sticky_ack': 'on',
            'send_notification': 'on',
            'btnSubmit': 'Commit'
        }

        response = requests.post(cmd_url, data=data, headers={'Authorization': auth_header}, timeout=5)

        if response.status_code == 200:
            flash(f'Host "{host_name}" acknowledged successfully!', 'success')
        else:
            flash(f'Failed to acknowledge host!', 'error')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')

    return redirect(request.referrer or '/dashboard')


@monitoring_bp.route('/monitoring/set-stage', methods=['POST'])
def set_stage() -> Response | tuple[Response, int]:
    """Set stage for a host. Only sends Nagios ACK when stage is 'resolved'."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid request'}), 400

    host_name = data.get('host_name', '').strip()
    container = data.get('container', '').strip()
    port = data.get('port', '').strip()
    stage = data.get('stage', '').strip()
    comment = data.get('comment', '').strip()

    if not host_name or not container or not stage:
        return jsonify({'error': 'Missing required fields'}), 400

    if stage not in STAGE_LABELS:
        return jsonify({'error': 'Invalid stage'}), 400

    username = session.get('username')
    now = datetime.now()
    stage_key = get_stage_key(container, host_name)

    if stage == STAGE_RESOLVED:
        # Resolved: ACK to Nagios + remove stage entry
        if not comment:
            return jsonify({'error': 'Comment is required for Resolved stage'}), 400
        try:
            password = decrypt_session_value(session.get('password'))
            auth_header = f"Basic {base64.b64encode(f'{username}:{password}'.encode()).decode()}"
            cmd_url = f'http://localhost:{port}/nagios/cgi-bin/cmd.cgi'
            ack_data = {
                'cmd_typ': '33',  # ACKNOWLEDGE_HOST_PROBLEM
                'cmd_mod': '2',
                'host': host_name,
                'com_author': username,
                'com_data': comment,
                'sticky_ack': 'on',
                'send_notification': 'on',
                'btnSubmit': 'Commit'
            }
            resp = requests.post(cmd_url, data=ack_data, headers={'Authorization': auth_header}, timeout=5)
            if resp.status_code != 200:
                return jsonify({'error': 'Nagios ACK failed'}), 500
        except Exception as e:
            return jsonify({'error': f'Nagios ACK error: {str(e)}'}), 500

        # Remove stage entry (host will disappear from monitoring on next refresh)
        with host_stages_transaction() as host_stages:
            old_stage = host_stages.get(stage_key, {}).get('stage', STAGE_NEW)
            host_stages.pop(stage_key, None)
        # Write history after transaction
        append_stage_history(host_name, container, old_stage, stage, username, comment)
        log_activity('Stage Resolved + ACK', f'Host {host_name} on {container} resolved and acknowledged. Comment: {comment}')
        return jsonify({'success': True, 'action': 'resolved_and_acked'})
    else:
        # Non-resolved: only update dashboard stage, DO NOT ACK Nagios
        with host_stages_transaction() as host_stages:
            existing = host_stages.get(stage_key, {})
            old_stage = existing.get('stage', STAGE_NEW)
            host_stages[stage_key] = {
                'stage': stage,
                'updated_at': now.isoformat(),
                'updated_by': username,
                'note': comment,
                'host_up_since': existing.get('host_up_since')  # preserve flapping tracker
            }
        # Write history after transaction
        append_stage_history(host_name, container, old_stage, stage, username, comment)
        note_msg = f' Note: {comment}' if comment else ''
        log_activity('Stage Updated', f'Host {host_name} on {container} set to stage "{STAGE_LABELS[stage]}" by {username}.{note_msg}')
        return jsonify({'success': True, 'action': 'stage_updated', 'stage': stage, 'stage_label': STAGE_LABELS[stage]})


@monitoring_bp.route('/monitoring/batch-set-stage', methods=['POST'])
def batch_set_stage() -> Response | tuple[Response, int]:
    """POST /monitoring/batch-set-stage — Set stage for multiple hosts at once."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid request'}), 400

    hosts = data.get('hosts', [])
    stage = data.get('stage', '').strip()
    note = data.get('note', '').strip()

    if not hosts:
        return jsonify({'error': 'No hosts selected'}), 400
    if stage not in STAGE_LABELS:
        return jsonify({'error': 'Invalid stage'}), 400
    if stage == STAGE_RESOLVED and not note:
        return jsonify({'error': 'Note is required for Resolved stage'}), 400

    username = session.get('username')
    now = datetime.now()
    success_count = 0
    fail_count = 0
    history_entries: list[tuple[str, str, str, str, str, str]] = []

    with host_stages_transaction() as host_stages:
        for host in hosts:
            host_name = host.get('name', '').strip()
            container = host.get('container', '').strip()
            port = host.get('port', '').strip()

            if not host_name or not container:
                fail_count += 1
                continue

            stage_key = get_stage_key(container, host_name)
            old_stage = host_stages.get(stage_key, {}).get('stage', STAGE_NEW)

            if stage == STAGE_RESOLVED:
                # Resolved: ACK to Nagios + remove stage entry
                try:
                    password = decrypt_session_value(session.get('password'))
                    auth_header = f"Basic {base64.b64encode(f'{username}:{password}'.encode()).decode()}"
                    cmd_url = f'http://localhost:{port}/nagios/cgi-bin/cmd.cgi'
                    ack_data = {
                        'cmd_typ': '33',
                        'cmd_mod': '2',
                        'host': host_name,
                        'com_author': username,
                        'com_data': note,
                        'sticky_ack': 'on',
                        'send_notification': 'on',
                        'btnSubmit': 'Commit'
                    }
                    resp = requests.post(cmd_url, data=ack_data, headers={'Authorization': auth_header}, timeout=5)
                    if resp.status_code == 200:
                        host_stages.pop(stage_key, None)
                        history_entries.append((host_name, container, old_stage, stage, username, note))
                        success_count += 1
                    else:
                        fail_count += 1
                except (requests.RequestException, json.JSONDecodeError):
                    fail_count += 1
            else:
                # Non-resolved: only update dashboard stage
                existing = host_stages.get(stage_key, {})
                host_stages[stage_key] = {
                    'stage': stage,
                    'updated_at': now.isoformat(),
                    'updated_by': username,
                    'note': note if note else existing.get('note', ''),
                    'host_up_since': existing.get('host_up_since')
                }
                history_entries.append((host_name, container, old_stage, stage, username, note))
                success_count += 1

    # Write history entries after transaction completes
    for entry in history_entries:
        try:
            append_stage_history(*entry)
        except Exception as e:
            print(f'[Batch Stage] Failed to write history for {entry[0]}: {e}')

    log_activity('Batch Stage Updated', f'{success_count} host(s) set to "{STAGE_LABELS[stage]}" by {username}. Note: {note}')

    return jsonify({
        'success': True,
        'success_count': success_count,
        'fail_count': fail_count,
        'stage': stage,
        'stage_label': STAGE_LABELS[stage]
    })
