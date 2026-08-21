from __future__ import annotations

from flask import Blueprint, Response, render_template, request, redirect, session, jsonify, flash
import logging, os, json, subprocess, base64, requests, csv, io
from datetime import datetime

from services.config import (
    MONITORING_CATEGORIES_PATH, MONITORING_SERVER_MAPPINGS_PATH, MONITORING_CONFIG_PATH,
    STAGE_NEW, STAGE_CS, STAGE_RESOLVED, STAGE_LABELS
)
from services.encryption import decrypt_session_value
from services.ldap_service import log_activity
from services.stage_service import (
    get_host_stage, upsert_host_stage, delete_host_stage,
)
from services.poller_db import container_fetch_errors, list_snapshot_hosts, set_host_acknowledged
from services.stage_history import append_stage_history
from utils.permissions import check_permission

monitoring_bp = Blueprint('monitoring', __name__)
logger = logging.getLogger(__name__)


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
    if not check_permission('monitoring'):
        flash('Access denied. You do not have permission to access this page.', 'error')
        return redirect('/dashboard')

    return render_template('monitoring.html', username=session['username'], page=page,
                         hosts=[], total_down=0,
                         nagios_servers=get_nagios_servers(), monitoring_categories=get_monitoring_categories())


def _container_errors(containers: list[str]) -> list[str]:
    return container_fetch_errors(containers)


def _fetch_monitoring_hosts(page: str) -> tuple[list[dict], list[str]]:
    """Read monitoring host data for a category from the poller snapshot.

    Returns (hosts, errors). A failed/stale container is reported in errors and
    is NOT treated as an empty (all-UP) result. Last known hosts are still shown.
    """
    server_mappings = {}
    try:
        if os.path.exists(MONITORING_SERVER_MAPPINGS_PATH):
            with open(MONITORING_SERVER_MAPPINGS_PATH) as f:
                server_mappings = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass

    category_servers = server_mappings.get(page, [])
    if not isinstance(category_servers, list):
        category_servers = []

    use_service_plugin = False
    try:
        if os.path.exists(MONITORING_CONFIG_PATH):
            with open(MONITORING_CONFIG_PATH) as f:
                config = json.load(f)
                use_service_plugin = config.get('category_settings', {}).get(page, {}).get(
                    'use_service_plugin', False
                )
    except (json.JSONDecodeError, OSError):
        pass

    errors = _container_errors(category_servers)
    all_hosts: list[dict] = []
    now = datetime.now()

    for row in list_snapshot_hosts(category_servers, down_only=True, include_acked=False):
        try:
            hostname = row['hostname']
            container_name = row['container']
            status_code = int(row.get('status_code') or 0)
            stage_info = get_host_stage(container_name, hostname) or {
                'stage': STAGE_NEW,
                'updated_at': '',
                'updated_by': '',
                'note': '',
                'host_up_since': None,
            }
            last_check_ms = int(row.get('last_check_ms') or 0)
            last_state_ms = int(row.get('last_state_change_ms') or 0)
            last_check = datetime.fromtimestamp(last_check_ms / 1000)
            last_state = datetime.fromtimestamp(last_state_ms / 1000)
            dur = now - last_state
            status_label = 'UNREACHABLE' if status_code == 8 else 'DOWN'
            if use_service_plugin:
                status_info = row.get('service_plugin_output') or row.get('plugin_output') or ''
            else:
                status_info = row.get('plugin_output') or ''
            all_hosts.append({
                'host_name': row.get('name') or hostname,
                'ip_address': row.get('address') or 'N/A',
                'status': status_label,
                'last_check': last_check.strftime('%Y-%m-%d %H:%M:%S'),
                'last_state_change': last_state_ms,
                'duration_str': str(dur).split('.')[0],
                'status_information': status_info,
                'container': container_name,
                'port': row.get('port') or '',
                'stage': stage_info.get('stage', STAGE_NEW),
                'stage_label': STAGE_LABELS.get(
                    stage_info.get('stage', STAGE_NEW), 'New / Unacknowledged'
                ),
                'stage_updated_by': stage_info.get('updated_by', ''),
                'stage_updated_at': stage_info.get('updated_at', ''),
                'stage_note': stage_info.get('note', ''),
            })
        except (ValueError, TypeError, KeyError, OSError):
            logger.warning('Failed to process a snapshot host on container %s', row.get('container'))
            continue

    all_hosts.sort(key=lambda x: x['last_state_change'], reverse=True)

    if session.get('permissions', {}).get('cr_view_only'):
        all_hosts = [h for h in all_hosts if h.get('stage') == STAGE_CS]

    return all_hosts, errors


@monitoring_bp.route('/monitoring/<page>/data')
def monitoring_data(page: str) -> Response | tuple[Response, int]:
    """GET /monitoring/<page>/data — JSON monitoring data for a category."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('monitoring'):
        return jsonify({'error': 'Access denied'}), 403

    try:
        all_hosts, errors = _fetch_monitoring_hosts(page)
        return jsonify({
            'hosts': all_hosts,
            'total_down': len(all_hosts),
            'errors': errors,
            'incomplete': bool(errors),
        })
    except Exception:
        logger.warning('Monitoring data load failed for category %s', page)
        return jsonify({
            'hosts': [],
            'total_down': 0,
            'errors': ['Failed to load monitoring data'],
            'incomplete': True,
        })


@monitoring_bp.route('/monitoring/<page>/export-csv')
def export_monitoring_csv(page: str) -> Response | tuple[Response, int]:
    """GET /monitoring/<page>/export-csv — Download monitoring data as CSV."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('monitoring'):
        return jsonify({'error': 'Access denied'}), 403

    try:
        hosts, _errors = _fetch_monitoring_hosts(page)
    except Exception:
        return jsonify({'error': 'Failed to fetch monitoring data'}), 500

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
    if not check_permission('monitoring'):
        return jsonify({'error': 'Access denied'}), 403

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
    if not check_permission('monitoring'):
        return jsonify({'error': 'Access denied'}), 403

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
    existing = get_host_stage(container, host_name)
    old_stage = existing.get('stage', STAGE_NEW) if existing else STAGE_NEW

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

        delete_host_stage(container, host_name)
        set_host_acknowledged(container, host_name, True)
        append_stage_history(host_name, container, old_stage, stage, username, comment)
        log_activity('Stage Resolved + ACK', f'Host {host_name} on {container} resolved and acknowledged. Comment: {comment}')
        return jsonify({'success': True, 'action': 'resolved_and_acked'})

    upsert_host_stage(
        container,
        host_name,
        stage,
        updated_at=now.isoformat(),
        updated_by=username,
        note=comment,
        host_up_since=existing.get('host_up_since') if existing else None,
    )
    append_stage_history(host_name, container, old_stage, stage, username, comment)
    note_msg = f' Note: {comment}' if comment else ''
    log_activity('Stage Updated', f'Host {host_name} on {container} set to stage "{STAGE_LABELS[stage]}" by {username}.{note_msg}')
    return jsonify({'success': True, 'action': 'stage_updated', 'stage': stage, 'stage_label': STAGE_LABELS[stage]})


@monitoring_bp.route('/monitoring/batch-set-stage', methods=['POST'])
def batch_set_stage() -> Response | tuple[Response, int]:
    """POST /monitoring/batch-set-stage — Set stage for multiple hosts at once."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('monitoring'):
        return jsonify({'error': 'Access denied'}), 403

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

    for host in hosts:
        host_name = host.get('name', '').strip()
        container = host.get('container', '').strip()
        port = host.get('port', '').strip()

        if not host_name or not container:
            fail_count += 1
            continue

        existing = get_host_stage(container, host_name)
        old_stage = existing.get('stage', STAGE_NEW) if existing else STAGE_NEW

        if stage == STAGE_RESOLVED:
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
                    delete_host_stage(container, host_name)
                    set_host_acknowledged(container, host_name, True)
                    history_entries.append((host_name, container, old_stage, stage, username, note))
                    success_count += 1
                else:
                    fail_count += 1
            except (requests.RequestException, json.JSONDecodeError):
                fail_count += 1
        else:
            upsert_host_stage(
                container,
                host_name,
                stage,
                updated_at=now.isoformat(),
                updated_by=username,
                note=note if note else (existing.get('note', '') if existing else ''),
                host_up_since=existing.get('host_up_since') if existing else None,
            )
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
