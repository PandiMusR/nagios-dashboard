from __future__ import annotations

from flask import Blueprint, request, jsonify, Response
from datetime import datetime
import os, json, subprocess, re, threading, shutil, fcntl

from services.config import GLOBAL_CONFIG_PATH
from services.ldap_service import log_activity
from services.uptime_kuma import add_host_to_uptime_kuma

api_bp = Blueprint('api', __name__)


def _add_to_uptime_kuma_async(host_name: str, address: str) -> None:
    try:
        monitor_id, error = add_host_to_uptime_kuma(host_name, address)
        if monitor_id:
            log_activity('API: Add Host to Uptime Kuma', f'Host: {host_name}, Monitor ID: {monitor_id}', username='API')
        elif error:
            log_activity('API: Add Host to Uptime Kuma Failed', f'Host: {host_name}, Error: {error}', username='API')
    except Exception as e:
        print(f'Uptime Kuma async error for {host_name}: {e}')


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


# Servers excluded from ONU host_name auto-parse / check_status_onu auto-add
ONU_EXCLUDED_SERVERS = frozenset({'Staging'})


def _parse_onu_host_name(host_name: str, server: str = '') -> tuple[str, str | None]:
    """Parse ONU host_name format and return (transformed_name, id_ne).

    Input:  "<Customer ID> - <ID NE> - <nama site>"
    Output: ("<ID NE> - <nama site> - <Customer ID>", "<ID NE>")

    If host_name doesn't match the 3-part format, returns (host_name, None).
    Skipped entirely for servers in ONU_EXCLUDED_SERVERS (e.g. Staging).
    """
    if server in ONU_EXCLUDED_SERVERS:
        return host_name, None
    parts = [p.strip() for p in host_name.split(' - ')]
    if len(parts) == 3 and all(parts):
        customer_id, id_ne, site_name = parts
        transformed = f"{id_ne} - {site_name} - {customer_id}"
        return transformed, id_ne
    return host_name, None


def _build_host_definition(
    host_name: str, address: str, alias: str = '', parents: str = '',
    service_plugin: str = '', service_args: str = '', id_ne: str | None = None
) -> str:
    """Build a Nagios host+service definition string."""
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

    if id_ne and not service_plugin:
        host_def += '\n'
        host_def += 'define service {\n'
        host_def += '    use                     generic-service\n'
        host_def += f'    host_name               {host_name}\n'
        host_def += '    service_description     Status ONU\n'
        host_def += f'    check_command           check_status_onu!{id_ne}\n'
        host_def += '    notifications_enabled   1\n'
        host_def += '}\n'

    return host_def


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

    ONU Auto-Parse:
        If host_name matches "<Customer ID> - <ID NE> - <site name>" format
        (3 non-empty parts separated by " - "), it is automatically:
        1. Rearranged to "<ID NE> - <site name> - <Customer ID>"
        2. A check_status_onu service is added with ID NE as argument
        This behavior is skipped if service_plugin is explicitly provided,
        or if server is in ONU_EXCLUDED_SERVERS (Staging).

    Response:
    {
        "success": true,
        "host_name": "10303 - Bank PT Bank Mandiri Persero Tbk - 110103210273001",
        "original_host_name": "110103210273001 - 10303 - Bank PT Bank Mandiri Persero Tbk",
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

    # Auto-parse ONU format (skipped for Staging)
    original_host_name = host_name
    host_name, id_ne = _parse_onu_host_name(host_name, server)

    # Check server exists
    config_path = f'/svr/{server}/etc/objects/localhost.cfg'
    if not os.path.exists(config_path):
        return _error(f'Server "{server}" not found or config missing', 404)

    try:
        # Read existing content and check for duplicates
        with open(config_path, 'r') as f:
            content = f.read()

        if f'host_name               {host_name}' in content or f'host_name    {host_name}' in content:
            return _error(f'Host "{host_name}" already exists on server "{server}"', 409)

        host_def = _build_host_definition(host_name, address, alias, parents, service_plugin, service_args, id_ne)

        # Append to config file
        if content and not content.endswith('\n'):
            host_def = '\n' + host_def
        elif content:
            host_def = '\n' + host_def

        with open(config_path, 'a') as f:
            f.write(host_def)

        # Restart Nagios container
        subprocess.run(['docker', 'restart', server], check=True, capture_output=True, timeout=60)

        # Uptime Kuma integration (background thread to avoid blocking API response)
        if uptime_kuma:
            threading.Thread(
                target=_add_to_uptime_kuma_async,
                args=(host_name, address),
                daemon=True
            ).start()

        log_activity('API: Add Host', f'Host: {host_name} ({address}) to {server}', username='API')

        response_data = {
            'success': True,
            'host_name': host_name,
            'server': server,
            'message': f'Host added and Nagios restarted'
        }
        if original_host_name != host_name:
            response_data['original_host_name'] = original_host_name
        return jsonify(response_data), 201

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

    ONU Auto-Parse:
        Each host_name is checked for "<Customer ID> - <ID NE> - <site name>" format.
        If matched, host_name is rearranged and check_status_onu service is auto-added.
        Skipped if service_plugin is explicitly provided,
        or if server is in ONU_EXCLUDED_SERVERS (Staging).
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

        # Auto-parse ONU format (skipped for Staging)
        original_host_name = host_name
        host_name, id_ne = _parse_onu_host_name(host_name, server)

        if f'host_name               {host_name}' in content or f'host_name    {host_name}' in content or f'host_name               {host_name}' in new_entries:
            results.append({'host_name': host_name, 'success': False, 'error': 'Already exists'})
            fail_count += 1
            continue

        host_def = _build_host_definition(host_name, address, alias, parents, service_plugin, service_args, id_ne)

        new_entries += '\n' + host_def
        result_entry = {'host_name': host_name, 'success': True, 'address': address}
        if original_host_name != host_name:
            result_entry['original_host_name'] = original_host_name
        results.append(result_entry)
        success_count += 1

        if uptime_kuma:
            threading.Thread(
                target=_add_to_uptime_kuma_async,
                args=(host_name, address),
                daemon=True
            ).start()

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
            subprocess.run(['docker', 'restart', server], check=True, capture_output=True, timeout=60)
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


def _replace_host_name_references(content: str, old_host_name: str, host_name: str) -> tuple[str, bool]:
    """Rename a host while preserving its definition, services, and child parents."""
    found = False

    def replace_host_block(match: re.Match) -> str:
        nonlocal found
        block = match.group(0)
        host_match = re.search(r'^(\s*host_name\s+)(.+?)\s*$', block, re.MULTILINE)
        if host_match and host_match.group(2) == old_host_name:
            found = True
            return block[:host_match.start(2)] + host_name + block[host_match.end(2):]
        return block

    host_block_pattern = re.compile(r'define\s+host\s*\{[^}]*\}', re.DOTALL)
    updated = host_block_pattern.sub(replace_host_block, content)
    if not found:
        return content, False

    def replace_service_block(match: re.Match) -> str:
        block = match.group(0)
        return re.sub(
            rf'^(\s*host_name\s+){re.escape(old_host_name)}(\s*)$',
            rf'\g<1>{host_name}\2',
            block,
            flags=re.MULTILINE,
        )

    def replace_parent_reference(match: re.Match) -> str:
        parents = match.group(2)
        updated_parents = ','.join(
            host_name if parent.strip() == old_host_name else parent
            for parent in parents.split(',')
        )
        return match.group(1) + updated_parents + match.group(3)

    service_block_pattern = re.compile(r'define\s+service\s*\{[^}]*\}', re.DOTALL)
    updated = service_block_pattern.sub(replace_service_block, updated)
    return re.sub(
        r'^(\s*parents\s+)(.*?)(\s*)$',
        replace_parent_reference,
        updated,
        flags=re.MULTILINE,
    ), True


@api_bp.route('/api/hosts/rename', methods=['POST'])
def api_rename_host() -> tuple[Response, int]:
    """POST /api/hosts/rename — Rename a host and update its Nagios references.

    Auth: X-API-Key header or ?api_key query param

    Body (JSON):
    {
        "server": "BhomeTest",
        "old_host_name": "switch-gedung-a",
        "host_name": "switch-gedung-b"
    }
    """
    if not _check_api_key(request):
        return _error('Invalid or missing API key', 401)

    data = request.get_json()
    if not data:
        return _error('Request body must be JSON')

    server = data.get('server', '').strip()
    old_host_name = data.get('old_host_name', '').strip()
    host_name = data.get('host_name', '').strip()

    if not server or not old_host_name or not host_name:
        return _error('Missing required fields: server, old_host_name, host_name')

    old_host_name = re.sub(r'[^a-zA-Z0-9_. -]', '', old_host_name)
    host_name = re.sub(r'[^a-zA-Z0-9_. -]', '', host_name)
    if not old_host_name or not host_name:
        return _error('Invalid hostname after sanitization')
    if old_host_name == host_name:
        return _error('old_host_name and host_name must be different')

    config_path = f'/svr/{server}/etc/objects/localhost.cfg'
    if not os.path.exists(config_path):
        return _error(f'Server "{server}" not found', 404)

    try:
        with open(config_path, 'r') as f:
            content = f.read()

        host_pattern = re.compile(
            rf'define\s+host\s*\{{[^}}]*^\s*host_name\s+{re.escape(host_name)}\s*$[^}}]*\}}',
            re.DOTALL | re.MULTILINE,
        )
        if host_pattern.search(content):
            return _error(f'Host "{host_name}" already exists on server "{server}"', 409)

        updated_content, found = _replace_host_name_references(content, old_host_name, host_name)
        if not found:
            return _error(f'Host "{old_host_name}" not found on server "{server}"', 404)

        with open(config_path, 'w') as f:
            f.write(updated_content)

        from services.stage_service import (
            get_host_stage, delete_host_stage, upsert_host_stage, relocate_host_comments,
        )
        existing = get_host_stage(server, old_host_name)
        relocate_host_comments(server, old_host_name, server, host_name)
        if existing:
            delete_host_stage(server, old_host_name)
            upsert_host_stage(
                server,
                host_name,
                existing.get('stage', 'new'),
                updated_at=existing.get('updated_at'),
                updated_by=existing.get('updated_by'),
                note=existing.get('note', ''),
                host_up_since=existing.get('host_up_since'),
            )

        subprocess.run(['docker', 'restart', server], check=True, capture_output=True, timeout=60)
        log_activity('API: Rename Host', f'Host: {old_host_name} renamed to {host_name} on {server}', username='API')

        return jsonify({
            'success': True,
            'server': server,
            'old_host_name': old_host_name,
            'host_name': host_name,
            'message': 'Host renamed and Nagios restarted'
        }), 200
    except subprocess.CalledProcessError as e:
        return _error(f'Failed to restart Nagios: {str(e)}', 500)
    except OSError as e:
        return _error(f'File error: {str(e)}', 500)


BHOME_SERVER = 'Bhome'
BHOME_CONFIG_PATH = f'/svr/{BHOME_SERVER}/etc/objects/localhost.cfg'
_IPV4_RE = re.compile(
    r'^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$'
)
_HOST_BLOCK_RE = re.compile(r'define\s+host\s*\{[^}]*\}', re.DOTALL)
_ADDRESS_LINE_RE = re.compile(r'^(\s*address\s+)(\S+)(.*)$', re.MULTILINE)
_HOST_NAME_LINE_RE = re.compile(r'^\s*host_name\s+(.+?)\s*$', re.MULTILINE)


def _optional_bool(data: dict, key: str) -> tuple[bool, tuple[Response, int] | None]:
    if key not in data:
        return False, None
    value = data[key]
    if not isinstance(value, bool):
        return False, _error(f'{key} must be true or false')
    return value, None


def _parse_bhome_ip_request(
    data: dict,
) -> tuple[list[tuple[str, str]] | None, bool, bool, tuple[Response, int] | None]:
    server = data.get('server', '')
    if not isinstance(server, str) or server.strip() != BHOME_SERVER:
        return None, False, False, _error('server must be Bhome')

    dry_run, error = _optional_bool(data, 'dry_run')
    if error:
        return None, False, False, error
    allow_existing, error = _optional_bool(data, 'allow_existing')
    if error:
        return None, False, False, error

    if 'changes' in data:
        raw_changes = data['changes']
        if not isinstance(raw_changes, list) or not raw_changes:
            return None, False, False, _error('changes must be a non-empty list')
    elif 'old_ip' in data or 'new_ip' in data:
        raw_changes = [{'old_ip': data.get('old_ip'), 'new_ip': data.get('new_ip')}]
    else:
        return None, False, False, _error('Missing changes, or old_ip and new_ip')

    pairs: list[tuple[str, str]] = []
    seen_old: set[str] = set()
    seen_new: set[str] = set()
    for item in raw_changes:
        if not isinstance(item, dict):
            return None, False, False, _error('each change must be an object with old_ip and new_ip')
        old_ip = item.get('old_ip', '')
        new_ip = item.get('new_ip', '')
        if not isinstance(old_ip, str) or not isinstance(new_ip, str):
            return None, False, False, _error('old_ip and new_ip must be strings')
        old_ip = old_ip.strip()
        new_ip = new_ip.strip()
        if not _IPV4_RE.match(old_ip) or not _IPV4_RE.match(new_ip):
            return None, False, False, _error('old_ip and new_ip must be exact IPv4 addresses')
        if old_ip == new_ip:
            return None, False, False, _error(f'old_ip and new_ip are the same: {old_ip}')
        if old_ip in seen_old:
            return None, False, False, _error(f'duplicate old_ip: {old_ip}')
        if new_ip in seen_new:
            return None, False, False, _error(f'duplicate new_ip: {new_ip}')
        seen_old.add(old_ip)
        seen_new.add(new_ip)
        pairs.append((old_ip, new_ip))
    return pairs, dry_run, allow_existing, None


def _apply_address_map(
    content: str, mapping: dict[str, str]
) -> tuple[str, list[dict], dict[str, list[str]]]:
    index: dict[str, list[str]] = {}
    hits: list[dict] = []

    def replace_host_block(match: re.Match) -> str:
        block = match.group(0)
        host_match = _HOST_NAME_LINE_RE.search(block)
        host_name = host_match.group(1) if host_match else ''

        def replace_address(addr_match: re.Match) -> str:
            current = addr_match.group(2)
            index.setdefault(current, []).append(host_name)
            new_ip = mapping.get(current)
            if new_ip is None:
                return addr_match.group(0)
            hits.append({'host_name': host_name, 'old_ip': current, 'new_ip': new_ip})
            return addr_match.group(1) + new_ip + addr_match.group(3)

        return _ADDRESS_LINE_RE.sub(replace_address, block)

    updated = _HOST_BLOCK_RE.sub(replace_host_block, content)
    return updated, hits, index


def _audit_address_edit(before: str, after: str, mapping: dict[str, str]) -> str | None:
    if _HOST_BLOCK_RE.sub('', before) != _HOST_BLOCK_RE.sub('', after):
        return 'edit touched text outside host blocks'
    before_blocks = _HOST_BLOCK_RE.findall(before)
    after_blocks = _HOST_BLOCK_RE.findall(after)
    if len(before_blocks) != len(after_blocks):
        return 'host block count changed'
    for old_block, new_block in zip(before_blocks, after_blocks):
        old_lines = old_block.splitlines()
        new_lines = new_block.splitlines()
        if len(old_lines) != len(new_lines):
            return 'host block line count changed'
        for old_line, new_line in zip(old_lines, new_lines):
            if old_line == new_line:
                continue
            old_addr = _ADDRESS_LINE_RE.match(old_line)
            new_addr = _ADDRESS_LINE_RE.match(new_line)
            if not old_addr or not new_addr:
                return 'non-address line changed'
            if old_addr.group(1) != new_addr.group(1) or old_addr.group(3) != new_addr.group(3):
                return 'address line formatting changed'
            if mapping.get(old_addr.group(2)) != new_addr.group(2):
                return 'address changed to an unexpected value'
    return None


def _plan_bhome_address_changes(
    content: str, pairs: list[tuple[str, str]], allow_existing: bool
) -> dict:
    mapping = dict(pairs)
    updated, hits, index = _apply_address_map(content, mapping)
    missing = [old_ip for old_ip, _new_ip in pairs if old_ip not in index]
    if missing:
        return {'ok': False, 'status': 404, 'error': 'old_ip not found on Bhome', 'missing': missing}

    old_set = set(mapping)
    conflicts = []
    reported: set[str] = set()
    for _old_ip, new_ip in pairs:
        if new_ip in reported:
            continue
        reported.add(new_ip)
        if new_ip in index and new_ip not in old_set:
            conflicts.append({'new_ip': new_ip, 'host_names': index[new_ip]})
    if conflicts and not allow_existing:
        return {
            'ok': False,
            'status': 409,
            'error': 'new_ip is already used by a host that is not part of this change',
            'conflicts': conflicts,
        }

    audit_error = _audit_address_edit(content, updated, mapping)
    if audit_error:
        return {'ok': False, 'status': 500, 'error': f'Refusing to write config: {audit_error}'}

    changes = []
    for old_ip, new_ip in pairs:
        host_names = [hit['host_name'] for hit in hits if hit['old_ip'] == old_ip]
        changes.append({
            'old_ip': old_ip,
            'new_ip': new_ip,
            'host_count': len(host_names),
            'host_names': host_names,
        })
    return {
        'ok': True,
        'updated': updated,
        'changes': changes,
        'total_hosts': sum(item['host_count'] for item in changes),
    }


def _verify_bhome_config() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ['docker', 'exec', BHOME_SERVER, '/opt/nagios/bin/nagios', '-v', '/opt/nagios/etc/nagios.cfg'],
            capture_output=True, text=True, timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    output = (result.stdout or '') + (result.stderr or '')
    return result.returncode == 0, output


def _restart_bhome() -> None:
    subprocess.run(
        ['docker', 'restart', BHOME_SERVER],
        check=True, capture_output=True, timeout=120,
    )


def _change_summary(changes: list[dict]) -> str:
    summary = ', '.join(
        f"{item['old_ip']} -> {item['new_ip']} ({item['host_count']} hosts)"
        for item in changes
    )
    if len(summary) > 1500:
        return summary[:1500] + '...'
    return summary


@api_bp.route('/api/hosts/change-ip', methods=['POST'])
def api_change_ip() -> tuple[Response, int]:
    """POST /api/hosts/change-ip — Replace exact host addresses on Bhome.

    Auth: X-API-Key header or ?api_key query param

    Only the address directive is compared, as a whole token.
    10.10.0.1 does not match 10.10.0.11 or 10.10.0.19.
    host_name, services, and files other than localhost.cfg are left as they are.
    Several pairs are applied in one pass, then Nagios is validated and restarted once.

    Body (JSON):
    {
        "server": "Bhome",
        "dry_run": true,
        "allow_existing": false,
        "changes": [
            {"old_ip": "10.10.0.1", "new_ip": "10.11.0.1"}
        ]
    }

    A single pair may be sent as old_ip and new_ip instead of changes.
    dry_run previews the hosts that would change and does not write or restart.
    """
    if not _check_api_key(request):
        return _error('Invalid or missing API key', 401)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error('Request body must be JSON')

    pairs, dry_run, allow_existing, error = _parse_bhome_ip_request(data)
    if error:
        return error

    if not os.path.exists(BHOME_CONFIG_PATH):
        return _error('Server "Bhome" not found or config missing', 404)

    lock_path = os.path.join(os.path.dirname(BHOME_CONFIG_PATH), '.ip-change.lock')
    try:
        lock_fh = open(lock_path, 'a+')
    except OSError as exc:
        return _error(f'File error: {exc}', 500)

    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            with open(BHOME_CONFIG_PATH, 'r') as fh:
                content = fh.read()
        except OSError as exc:
            return _error(f'File error: {exc}', 500)

        plan = _plan_bhome_address_changes(content, pairs, allow_existing)
        if not plan['ok']:
            body = {'success': False, 'error': plan['error']}
            if 'missing' in plan:
                body['missing'] = plan['missing']
            if 'conflicts' in plan:
                body['conflicts'] = plan['conflicts']
            return jsonify(body), plan['status']

        if dry_run:
            return jsonify({
                'success': True,
                'server': BHOME_SERVER,
                'dry_run': True,
                'restarted': False,
                'total_hosts': plan['total_hosts'],
                'changes': plan['changes'],
            }), 200

        backup_dir = os.path.join(os.path.dirname(BHOME_CONFIG_PATH), 'backups')
        try:
            os.makedirs(backup_dir, exist_ok=True)
            backup_path = os.path.join(
                backup_dir,
                'localhost_before_ip_change_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.cfg',
            )
            shutil.copy2(BHOME_CONFIG_PATH, backup_path)
            tmp_path = BHOME_CONFIG_PATH + '.tmp'
            with open(tmp_path, 'w') as fh:
                fh.write(plan['updated'])
            os.replace(tmp_path, BHOME_CONFIG_PATH)
        except OSError as exc:
            tmp_path = BHOME_CONFIG_PATH + '.tmp'
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return _error(f'File error: {exc}', 500)

        ok, output = _verify_bhome_config()
        if not ok:
            shutil.copy2(backup_path, BHOME_CONFIG_PATH)
            log_activity('API: Change IP Failed', 'Bhome: nagios -v failed, config restored', username='API')
            return jsonify({
                'success': False,
                'error': 'nagios -v failed, config restored',
                'nagios_output': output[-4000:],
            }), 422

        try:
            _restart_bhome()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            log_activity(
                'API: Change IP restart failed',
                'Bhome: config written but restart failed',
                username='API',
            )
            return jsonify({
                'success': False,
                'error': f'Config written but restart failed: {exc}',
                'restarted': False,
                'backup': backup_path,
                'total_hosts': plan['total_hosts'],
                'changes': plan['changes'],
            }), 500

        log_activity('API: Change IP', f'Bhome: {_change_summary(plan["changes"])}', username='API')
        return jsonify({
            'success': True,
            'server': BHOME_SERVER,
            'dry_run': False,
            'restarted': True,
            'total_hosts': plan['total_hosts'],
            'backup': backup_path,
            'changes': plan['changes'],
        }), 200
    finally:
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
        lock_fh.close()


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

        subprocess.run(['docker', 'restart', server], check=True, capture_output=True, timeout=60)

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
        from services.stage_service import list_host_stages, STAGE_LABELS
        category_filter = request.args.get('category', '').strip()

        hosts = []
        for row in list_host_stages():
            container = row.get('container') or ''
            hostname = row.get('hostname') or ''
            if category_filter and container != category_filter:
                continue
            hosts.append({
                'host_name': hostname,
                'container': container,
                'stage': row.get('stage', 'new'),
                'stage_label': STAGE_LABELS.get(row.get('stage', 'new'), 'Unknown'),
                'note': row.get('note', ''),
                'updated_at': row.get('updated_at', ''),
                'updated_by': row.get('updated_by', '')
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
    - start_date: inclusive start (`YYYY-MM-DD` or ISO datetime)
    - end_date: inclusive end (`YYYY-MM-DD` means end of that day)
    - limit: max entries (default 100)
    """
    if not _check_api_key(request):
        return _error('Invalid or missing API key', 401)

    from services.stage_history import read_stage_history

    host = request.args.get('host', '').strip() or None
    container = request.args.get('container', '').strip() or None
    start_date = request.args.get('start_date', '').strip() or None
    end_date = request.args.get('end_date', '').strip() or None
    limit = request.args.get('limit', '100').strip()
    try:
        limit = int(limit)
    except ValueError:
        limit = 100

    try:
        entries = read_stage_history(
            host=host, container=container, limit=limit,
            start_date=start_date, end_date=end_date,
        )
        return jsonify({'success': True, 'entries': entries, 'total': len(entries)}), 200
    except Exception as e:
        return _error(f'Error: {str(e)}', 500)
