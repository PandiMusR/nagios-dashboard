from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import subprocess
import tempfile
import time

from services.host_config import atomic_replace_host_config
from services.topology import MAX_CONFIG, Topology, TopologyConflict, TopologyError, read_config

ETC = PurePosixPath('/opt/nagios/etc')
LIVE = ETC / 'objects/localhost.cfg'
NAGIOS = '/opt/nagios/bin/nagios'


class ApplyError(Exception):
    pass


def docker(*args, timeout=10, capture=False):
    return subprocess.run(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', *args], check=True, timeout=timeout,
                          stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, text=True).stdout


def target_container(server, etc):
    try:
        raw = docker('inspect', '--type', 'container', '--format',
                     '{{json .Id}}\n{{json .Name}}\n{{json .State.Running}}\n{{json .Mounts}}',
                     server, capture=True)
        identifier, name, running, mounts = (json.loads(line) for line in raw.splitlines())
    except (ValueError, OSError, subprocess.SubprocessError):
        raise ApplyError('Cannot verify the selected Nagios container.') from None
    related = [mount for mount in mounts if PurePosixPath(mount['Destination']).is_relative_to(ETC)
               or ETC.is_relative_to(PurePosixPath(mount['Destination']))]
    if (not re.fullmatch(r'[0-9a-f]{64}', identifier) or name != '/' + server or not running
            or len(related) != 1):
        raise ApplyError('The selected container layout does not support safe topology updates.')
    mount = related[0]
    if (mount['Type'] != 'bind' or mount['Destination'] != str(ETC)
            or mount['Source'] != str(etc) or not mount['RW']):
        raise ApplyError('The selected container does not share the expected writable config directory.')
    return identifier


def candidate_main(main, candidate):
    lines = main.splitlines(keepends=True)
    include = []
    runtime = {'status_file': [], 'object_cache_file': []}
    for index, line in enumerate(lines):
        code = line.strip()
        if not code or code.startswith(('#', ';')):
            continue
        key, _, value = code.partition('=')
        key, value = key.strip(), value.strip()
        if key == 'cfg_file':
            path = PurePosixPath(value)
            if not path.is_absolute() or '..' in path.parts:
                raise ApplyError('Only explicit absolute Nagios configuration includes are supported.')
            if path == LIVE:
                include.append(index)
        elif key == 'cfg_dir':
            raise ApplyError('Directory-based Nagios includes require operator validation before editing.')
        elif key in runtime:
            path = PurePosixPath(value)
            if not path.is_relative_to('/opt/nagios/var') or '..' in path.parts:
                raise ApplyError('Unsupported Nagios runtime file path.')
            runtime[key].append(str(path))
    if len(include) != 1 or any(len(entries) != 1 for entries in runtime.values()):
        raise ApplyError('Nagios must explicitly include localhost.cfg and define one status and object cache file.')
    lines[include[0]] = f'cfg_file={candidate}\n'
    return ''.join(lines), runtime['status_file'][0], runtime['object_cache_file'][0]


READY = """set -f
cache="$3"
set -- $(awk '/^programstatus[ ]*[{]/ {found=1; next}
found && /nagios_pid=/ {sub(/^.*=/, ""); pid=$0}
found && /program_start=/ {sub(/^.*=/, ""); started=$0}
found && /}/ {print pid, started; exit}' "$1") "$2"
[ "$#" -eq 3 ] || exit 1
case "$1" in ''|*[!0-9]*) exit 1;; esac
case "$2" in ''|*[!0-9]*) exit 1;; esac
[ "$2" -ge "$3" ] && [ "$(stat -c %Y "$cache")" -ge "$2" ] &&
    [ "$(cat "/proc/$1/comm")" = nagios ] &&
    tr '\\000' '\\n' <"/proc/$1/cmdline" | grep -Fxq /opt/nagios/etc/nagios.cfg
"""


def restart_and_check(identifier, status, cache):
    started = str(int(time.time()))
    docker('restart', '--timeout', '10', identifier, timeout=25)
    deadline = time.monotonic() + 8
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ApplyError('Nagios did not become ready after restart.')
        try:
            docker('exec', identifier, '/bin/sh', '-c', READY, 'topology-ready', status, started, cache,
                   timeout=min(3, remaining))
            return
        except (subprocess.SubprocessError, OSError):
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))


def runtime_parents(identifier, cache, names):
    limit = 4 * MAX_CONFIG
    try:
        text = docker('exec', identifier, '/usr/bin/head', '-c', str(limit + 1), cache,
                      timeout=3, capture=True)
        if len(text.encode('utf-8')) > limit:
            raise ApplyError('The Nagios object cache exceeds the verification limit.')
        hosts = Topology(text).hosts
        return {name: set(hosts[name].parents) for name in names}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        raise ApplyError('Could not verify the active Nagios parent relationships.') from None


def file_identity(metadata):
    return (metadata.st_dev, metadata.st_ino, metadata.st_ctime_ns, metadata.st_mtime_ns,
            metadata.st_uid, metadata.st_gid, metadata.st_mode, metadata.st_nlink)


def update_parents(server, path, expected, changes):
    path = Path(path)
    etc = path.parent.parent
    if path.resolve() != path:
        raise ApplyError('Symbolic-link configuration paths are unsupported.')
    original, revision, metadata = read_config(path)
    if expected != revision:
        raise TopologyConflict('Configuration changed. Reload the topology before submitting again.')
    topology = Topology(original)
    updated = topology.updated(changes)
    if updated == original:
        return False
    if metadata.st_nlink != 1 or os.listxattr(path, follow_symlinks=False):
        raise ApplyError('Host configuration links or extended metadata require operator review.')
    intended = {name: set(parents) for name, parents in changes.items()
                if sorted(topology.hosts[name].parents) != sorted(parents)}
    identifier = target_container(server, etc)
    main, main_revision, main_metadata = read_config(etc / 'nagios.cfg')
    try:
        with tempfile.TemporaryDirectory(prefix='.topology-', dir=etc) as directory:
            stage = Path(directory)
            container_stage = ETC / stage.name
            validation, status, cache = candidate_main(main, container_stage / 'localhost.cfg')
            atomic_replace_host_config(str(stage / 'localhost.cfg'), updated, metadata)
            atomic_replace_host_config(str(stage / 'nagios.cfg'), validation, main_metadata)
            stage.chmod(0o711)
            try:
                docker('exec', identifier, NAGIOS, '-v', str(container_stage / 'nagios.cfg'), timeout=15)
            except (OSError, subprocess.SubprocessError):
                raise ApplyError('Nagios rejected the candidate or verification did not complete. Configuration was not changed.') from None
        old_runtime = runtime_parents(identifier, cache, intended)
        if any(set(topology.hosts[name].parents) != old_runtime[name] for name in intended
               if topology.hosts[name].parent_line is not None or not topology.hosts[name].uses_template):
            raise ApplyError('The active Nagios parents differ from localhost.cfg. Reconcile the running configuration first.')
        latest = read_config(path)
        if (latest[1] != revision or file_identity(latest[2]) != file_identity(metadata)
                or read_config(etc / 'nagios.cfg')[1] != main_revision):
            raise TopologyConflict('Configuration changed during verification. Reload and try again.')
        backup_dir = path.parent / 'backups'
        backup_dir.mkdir(mode=0o700, exist_ok=True)
        if backup_dir.resolve() != backup_dir or not stat.S_ISDIR(backup_dir.lstat().st_mode):
            raise ApplyError('The configuration backup directory is unsafe.')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        backup = backup_dir / f'localhost_{stamp}_topology_{secrets.token_hex(6)}.cfg'
        atomic_replace_host_config(str(backup), original, metadata)
        if read_config(backup)[1] != revision:
            raise ApplyError('The configuration backup could not be verified.')
        if target_container(server, etc) != identifier:
            raise TopologyConflict('The server container changed during verification. Try again.')
        latest = read_config(path)
        if (latest[1] != revision or file_identity(latest[2]) != file_identity(metadata)
                or read_config(etc / 'nagios.cfg')[1] != main_revision):
            raise TopologyConflict('Configuration changed before publication. Reload and try again.')
        atomic_replace_host_config(str(path), updated, metadata)
    except OSError:
        raise ApplyError('Could not stage, back up or publish the host configuration.') from None
    published = None
    try:
        installed = read_config(path)
        if installed[0] != updated:
            raise ApplyError('Source changed after publication.')
        published = file_identity(installed[2])
        restart_and_check(identifier, status, cache)
        if runtime_parents(identifier, cache, intended) != intended:
            raise ApplyError('Nagios did not load the intended parent relationships.')
        installed = read_config(path)
        if (installed[0] != updated or file_identity(installed[2]) != published
                or read_config(etc / 'nagios.cfg')[1] != main_revision):
            raise ApplyError('Source changed during Nagios apply.')
    except (OSError, UnicodeError, TopologyError, subprocess.SubprocessError, ApplyError) as exc:
        try:
            installed = read_config(path)
            if installed[0] != updated or file_identity(installed[2]) != published:
                raise ApplyError('Another writer modified the configuration after publication.')
            atomic_replace_host_config(str(path), original, metadata)
            if read_config(path)[1] != revision:
                raise ApplyError('Restoration checksum did not match.')
        except (OSError, UnicodeError, ApplyError, TopologyError):
            raise ApplyError('Nagios apply failed and rollback could not be verified. Contact an operator; a backup was retained.') from None
        if isinstance(exc, subprocess.TimeoutExpired):
            raise ApplyError('Previous configuration restored. Restart outcome is uncertain; an operator must verify Nagios.') from None
        try:
            if read_config(etc / 'nagios.cfg')[1] != main_revision:
                raise ApplyError('The main configuration changed during apply.')
            restart_and_check(identifier, status, cache)
            if runtime_parents(identifier, cache, old_runtime) != old_runtime:
                raise ApplyError('Nagios did not reload the previous parent relationships.')
        except (OSError, UnicodeError, TopologyError, subprocess.SubprocessError, ApplyError):
            raise ApplyError('Previous configuration restored, but Nagios recovery could not be verified. Contact an operator.') from None
        raise ApplyError('Nagios apply failed. The previous configuration was restored and Nagios restarted.') from None
    return True
