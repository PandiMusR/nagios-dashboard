from __future__ import annotations

import logging

from flask import Blueprint, Response, jsonify, redirect, render_template, session

from services.poller_db import (
    container_fetch_error_map,
    count_hosts_by_container,
    list_container_health,
    list_snapshot_containers,
)
from services.shared_helpers import get_monitoring_categories, get_nagios_servers

dashboard_bp = Blueprint('dashboard', __name__)
logger = logging.getLogger(__name__)

_EMPTY_HOSTS = {'up': 0, 'down': 0, 'unreachable': 0, 'total': 0}


def _can_view_container(container_name: str) -> bool:
    if session.get('role') == 'admin':
        return True
    return bool(session.get('permissions', {}).get(f'nagios_{container_name}'))


@dashboard_bp.route('/dashboard')
def dashboard() -> str | Response:
    """GET /dashboard — Main dashboard page."""
    if 'username' not in session:
        return redirect('/')

    return render_template(
        'dashboard.html',
        username=session['username'],
        nagios_servers=get_nagios_servers(),
        monitoring_categories=get_monitoring_categories(),
    )


@dashboard_bp.route('/dashboard/stats')
def dashboard_stats() -> Response | tuple[Response, int]:
    """GET /dashboard/stats — JSON stats from the CGI snapshot, not live Nagios."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        running = get_nagios_servers()
        names: list[str] = []
        seen: set[str] = set()
        for name in [*running, *list_snapshot_containers()]:
            if not name or name in seen:
                continue
            seen.add(name)
            if _can_view_container(name):
                names.append(name)

        health_map = list_container_health(names)
        host_counts = count_hosts_by_container(names)
        error_map = container_fetch_error_map(names)
        errors = list(error_map.values())

        servers_stats = []
        for name in names:
            health = health_map.get(name) or {}
            hosts = host_counts.get(name) or dict(_EMPTY_HOSTS)
            services_ok = int(health.get('services_ok') or 0)
            services_warning = int(health.get('services_warning') or 0)
            services_critical = int(health.get('services_critical') or 0)
            services_unknown = int(health.get('services_unknown') or 0)
            servers_stats.append({
                'name': name,
                'port': health.get('port') or '',
                'fetch_error': error_map.get(name),
                'hosts': hosts,
                'services': {
                    'ok': services_ok,
                    'warning': services_warning,
                    'critical': services_critical,
                    'unknown': services_unknown,
                    'total': services_ok + services_warning + services_critical + services_unknown,
                },
            })

        return jsonify({
            'servers': servers_stats,
            'errors': errors,
            'incomplete': bool(errors),
        })
    except Exception:
        logger.warning('Dashboard stats load failed')
        return jsonify({
            'servers': [],
            'errors': ['Failed to load dashboard stats'],
            'incomplete': True,
        })
