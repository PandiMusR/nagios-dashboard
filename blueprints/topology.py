from __future__ import annotations

from datetime import datetime
import json
import os
import re
import sqlite3
import stat
import subprocess

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, session
from flask_wtf.csrf import CSRFError

from services.host_config import guard_host_config_writes, host_config_path, lock_host_configs
from services.ldap_service import log_activity
from services.poller_db import snapshot_stale_after_seconds, topology_snapshot
from services.shared_helpers import get_nagios_servers
from services.topology import MAX_HOSTS, MAX_PARENTS, Topology, TopologyConflict, TopologyError, read_config, valid_host
from services.topology_write import ApplyError, update_parents

topology_bp = Blueprint('topology', __name__)
SERVER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')
REVISION = re.compile(r'[a-f0-9]{64}')
MAX_BODY = 128 * 1024
STATUS = {1: 'PENDING', 2: 'UP', 4: 'DOWN', 8: 'UNREACHABLE'}


def access(server, *, registered=True):
    if not session.get('username'):
        return 401
    if not SERVER.fullmatch(server):
        return 404
    if session.get('role') != 'admin' and session.get('permissions', {}).get('nagios_' + server) is not True:
        return 403
    if registered:
        try:
            if server not in get_nagios_servers():
                return 404
        except (OSError, subprocess.SubprocessError):
            return 503
    return None


def can_edit(server):
    allowed = os.environ.get('NAGIOS_TOPOLOGY_WRITABLE_SERVERS', '').split(',')
    return session.get('role') == 'admin' and server in {entry.strip() for entry in allowed}


def error(message, code):
    return jsonify(error=message), code


@topology_bp.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@topology_bp.errorhandler(CSRFError)
def csrf_error(_exc):
    return error('The security token is missing or expired. Reload the page.', 400)


def safe_snapshot(server):
    try:
        rows, health = topology_snapshot(server, MAX_HOSTS)
    except (sqlite3.Error, OSError):
        return {'hosts': {}, 'last_success': None, 'stale': True}
    last_success = health[0] if health else None
    stale = True
    if last_success:
        try:
            when = datetime.fromisoformat(last_success)
            age = (datetime.now(when.tzinfo) - when).total_seconds()
            stale = bool(health[1]) or age < 0 or age > snapshot_stale_after_seconds()
        except (TypeError, ValueError, OverflowError):
            pass
    return {'hosts': {name: STATUS.get(code, 'UNKNOWN') for name, code in rows},
            'last_success': last_success, 'stale': stale}


@topology_bp.get('/topology/<server>')
def page(server):
    denied = access(server)
    if denied == 401:
        return redirect('/')
    if denied:
        abort(denied)
    return render_template('topology.html', server=server, editable=can_edit(server))


@topology_bp.get('/api/topology/<server>')
def graph(server):
    denied = access(server)
    if denied:
        return error('Topology access denied or server unavailable.', denied)
    try:
        source, revision, _ = read_config(host_config_path(server))
        nodes, edges, warnings = Topology(source).graph()
    except FileNotFoundError:
        return error('This server has no localhost.cfg topology.', 404)
    except TopologyConflict as exc:
        return error(str(exc), 409)
    except TopologyError as exc:
        return error(str(exc), 422)
    except (OSError, UnicodeError):
        return error('Host configuration is unavailable or is not UTF-8.', 422)
    snapshot = safe_snapshot(server)
    names = {node['id'] for node in nodes}
    snapshot['hosts'] = {name: status for name, status in snapshot['hosts'].items() if name in names}
    return jsonify(server=server, nodes=nodes, edges=edges, warnings=warnings, revision=revision,
                   snapshot=snapshot, can_edit=can_edit(server))


@topology_bp.get('/api/topology/<server>/status')
def status(server):
    denied = access(server, registered=False)
    if denied:
        return error('Topology access denied or server unavailable.', denied)
    try:
        if not stat.S_ISREG(os.lstat(host_config_path(server)).st_mode):
            raise OSError
    except OSError:
        return error('Topology source is unavailable.', 404)
    return jsonify(safe_snapshot(server))


def unique_fields(items):
    result = {}
    for key, value in items:
        if key in result:
            raise TopologyError('JSON field names must be unique.')
        result[key] = value
    return result


def parse_update():
    length = request.content_length
    if length is None or not 0 < length <= MAX_BODY:
        raise TopologyError('Expected a bounded JSON request of at most 128 KiB.')
    if not request.is_json:
        raise TopologyError('Expected a JSON request.')
    try:
        data = json.loads(request.stream.read(MAX_BODY + 1), object_pairs_hook=unique_fields)
    except (ValueError, RecursionError):
        raise TopologyError('Invalid JSON request.') from None
    if (not isinstance(data, dict) or set(data) != {'revision', 'changes'}
            or not isinstance(data['revision'], str) or not REVISION.fullmatch(data['revision'])
            or not isinstance(data['changes'], dict) or not 0 < len(data['changes']) <= MAX_HOSTS):
        raise TopologyError('Provide a configuration revision and a nonempty set of parent changes.')
    for host, parents in data['changes'].items():
        if (not valid_host(host) or not isinstance(parents, list) or len(parents) > MAX_PARENTS
                or any(not valid_host(parent) for parent in parents)):
            raise TopologyError('Invalid host name or parents list.')
    return data['revision'], data['changes']


@topology_bp.post('/api/topology/<server>/parents')
@guard_host_config_writes
def parents(server):
    denied = access(server)
    if denied or not can_edit(server):
        return error('Topology editing is unavailable for this account or server.', denied or 403)
    try:
        revision, changes = parse_update()
    except TopologyError as exc:
        return error(str(exc), 400)
    path = host_config_path(server)
    lock_host_configs([path])
    try:
        changed = update_parents(server, path, revision, changes)
    except TopologyConflict as exc:
        return error(str(exc), 409)
    except TopologyError as exc:
        return error(str(exc), 422)
    except ApplyError as exc:
        return error(str(exc), 503)
    except (OSError, UnicodeError):
        return error('Host configuration is unavailable or is not UTF-8.', 422)
    if changed:
        try:
            log_activity('Update Topology', f'{server}: {len(changes)} submitted host changes')
        except OSError:
            current_app.logger.warning('Could not record topology activity')
    return jsonify(success=True, changed=changed)
