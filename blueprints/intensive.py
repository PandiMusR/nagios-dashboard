from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, session

from services.intensive_db import (
    add_configured_host,
    delete_configured_host,
    fetch_history,
    fetch_latest_by_host,
    load_configured_hosts,
)
from services.ldap_service import log_activity
from services.shared_helpers import get_monitoring_categories, get_nagios_servers
from utils.permissions import check_permission

intensive_bp = Blueprint('intensive', __name__)

RANGE_HOURS = {
    '1h': 1,
    '6h': 6,
    '24h': 24,
    '7d': 168,
}
MAX_CHART_POINTS = 800


def _downsample(rows: list[dict], max_points: int = MAX_CHART_POINTS) -> list[dict]:
    if len(rows) <= max_points:
        return rows
    step = (len(rows) - 1) / (max_points - 1)
    picked = [rows[round(i * step)] for i in range(max_points)]
    if picked[-1] is not rows[-1]:
        picked[-1] = rows[-1]
    return picked


def _merged_hosts() -> list[dict]:
    configured = load_configured_hosts()
    latest = fetch_latest_by_host()
    hosts = list(configured)
    hosts.sort(key=lambda h: (not h.get('enabled', True), h.get('name') or h['id']))
    for host in hosts:
        last = latest.get(host['id'])
        host['last_status'] = last['status'] if last else 'unknown'
        host['last_latency_ms'] = last['latency_ms'] if last else None
        host['last_ts'] = last['ts'] if last else None
    return hosts


@intensive_bp.route('/intensive')
def intensive_page() -> str | Response:
    """GET /intensive — Intensive ping monitors page."""
    if 'username' not in session:
        return redirect('/login')
    if not check_permission('monitoring'):
        flash('Access denied', 'error')
        return redirect('/dashboard')
    return render_template(
        'intensive.html',
        username=session['username'],
        nagios_servers=get_nagios_servers(),
        monitoring_categories=get_monitoring_categories(),
    )


@intensive_bp.route('/api/intensive/data')
def intensive_data() -> tuple[Response, int]:
    """GET /api/intensive/data — latency/loss history for Chart.js."""
    if 'username' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    if not check_permission('monitoring'):
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    range_key = (request.args.get('range') or '24h').strip().lower()
    if range_key not in RANGE_HOURS:
        range_key = '24h'
    since = (datetime.now() - timedelta(hours=RANGE_HOURS[range_key])).isoformat(timespec='seconds')

    try:
        hosts = _merged_hosts()
    except (OSError, json.JSONDecodeError):
        hosts = []

    enabled_ids = [h['id'] for h in hosts if h.get('enabled', True)]
    requested_host = (request.args.get('host') or '').strip()
    if requested_host and any(h['id'] == requested_host for h in hosts):
        host_id = requested_host
    elif enabled_ids:
        host_id = enabled_ids[0]
    elif hosts:
        host_id = hosts[0]['id']
    else:
        return jsonify({
            'success': True,
            'hosts': [],
            'host': None,
            'range': range_key,
            'stats': {
                'status': 'unknown',
                'latency_ms': None,
                'avg_latency_ms': None,
                'packet_loss_pct': None,
                'uptime_pct': None,
                'samples': 0,
            },
            'series': {'labels': [], 'latency': [], 'packet_loss': []},
        })

    selected = next((h for h in hosts if h['id'] == host_id), None)
    try:
        rows = fetch_history(host_id, since)
    except OSError:
        rows = []

    samples = len(rows)
    up_count = sum(1 for r in rows if r.get('status') == 'up')
    latencies = [r['latency_ms'] for r in rows if r.get('latency_ms') is not None]
    losses = [r['packet_loss_pct'] for r in rows if r.get('packet_loss_pct') is not None]
    last = rows[-1] if rows else None
    chart_rows = _downsample(rows)

    stats = {
        'status': last['status'] if last else 'unknown',
        'latency_ms': last['latency_ms'] if last else None,
        'avg_latency_ms': round(sum(latencies) / len(latencies), 3) if latencies else None,
        'packet_loss_pct': round(sum(losses) / len(losses), 2) if losses else None,
        'uptime_pct': round(100.0 * up_count / samples, 2) if samples else None,
        'samples': samples,
    }

    return jsonify({
        'success': True,
        'hosts': hosts,
        'host': selected,
        'range': range_key,
        'stats': stats,
        'series': {
            'labels': [r['ts'] for r in chart_rows],
            'latency': [r['latency_ms'] for r in chart_rows],
            'packet_loss': [r['packet_loss_pct'] for r in chart_rows],
        },
    })


_ADDRESS_RE = re.compile(r'^[A-Za-z0-9._:-]{1,253}$')


def _parse_host_payload() -> tuple[str, str, int] | tuple[None, str, None]:
    data = request.get_json(silent=True) or {}
    name = str(data.get('name') or '').strip()
    address = str(data.get('address') or '').strip()
    try:
        interval = int(data.get('interval_seconds') or 20)
    except (TypeError, ValueError):
        return None, 'Interval must be a number', None
    if not name or len(name) > 80:
        return None, 'Name is required (max 80 characters)', None
    if not _ADDRESS_RE.match(address):
        return None, 'Address must be a hostname or IP', None
    if interval < 10 or interval > 300:
        return None, 'Interval must be between 10 and 300 seconds', None
    return name, address, interval


@intensive_bp.route('/api/intensive/hosts', methods=['POST'])
def intensive_add_host() -> tuple[Response, int]:
    """POST /api/intensive/hosts — add a target to intensive_hosts.json."""
    if 'username' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    if not check_permission('monitoring'):
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    parsed = _parse_host_payload()
    if parsed[0] is None:
        return jsonify({'success': False, 'error': parsed[1]}), 400
    name, address, interval = parsed
    try:
        record = add_configured_host(name, address, interval)
    except (OSError, ValueError):
        return jsonify({'success': False, 'error': 'Failed to save host'}), 500
    log_activity('Intensive: Add Host', f'{record["id"]} {address} every {interval}s')
    return jsonify({'success': True, 'host': record}), 201


@intensive_bp.route('/api/intensive/hosts/<host_id>', methods=['DELETE'])
def intensive_delete_host(host_id: str) -> tuple[Response, int]:
    """DELETE /api/intensive/hosts/<id> — remove a target from intensive_hosts.json."""
    if 'username' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    if not check_permission('monitoring'):
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    host_id = (host_id or '').strip()
    if not host_id or len(host_id) > 60:
        return jsonify({'success': False, 'error': 'Invalid host id'}), 400
    try:
        deleted = delete_configured_host(host_id)
    except OSError:
        return jsonify({'success': False, 'error': 'Failed to update hosts'}), 500
    if not deleted:
        return jsonify({'success': False, 'error': 'Host not found'}), 404
    log_activity('Intensive: Delete Host', host_id)
    return jsonify({'success': True, 'id': host_id})
