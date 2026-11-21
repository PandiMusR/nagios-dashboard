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
from services.topology import Topology, TopologyConflict, TopologyError, read_config

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
    status = []
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
        elif key == 'status_file':
            path = PurePosixPath(value)
            if not path.is_relative_to('/opt/nagios/var') or '..' in path.parts:
                raise ApplyError('Unsupported Nagios runtime status path.')
            status.append(str(path))
    if len(include) != 1 or len(status) != 1:
        raise ApplyError('Nagios must explicitly include localhost.cfg and define one status file.')
    lines[include[0]] = f'cfg_file={candidate}\n'
    return ''.join(lines), status[0]


READY = """set -f
set -- $(awk '/^programstatus[ ]*[{]/ {found=1; next}
found && /nagios_pid=/ {sub(/^.*=/, ""); pid=$0}
found && /program_start=/ {sub(/^.*=/, ""); started=$0}
found && /}/ {print pid, started; exit}' "$1") "$2"
[ "$#" -eq 3 ] || exit 1
case "$1" in ''|*[!0-9]*) exit 1;; esac
case "$2" in ''|*[!0-9]*) exit 1;; esac
[ "$2" -ge "$3" ] && [ "$(cat "/proc/$1/comm")" = nagios ] &&
    tr '\\000' '\\n' <"/proc/$1/cmdline" | grep -Fxq /opt/nagios/etc/nagios.cfg
"""


def restart_and_check(identifier, status):
    started = str(int(time.time()))
    docker('restart', '--timeout', '10', identifier, timeout=25)
    deadline = time.monotonic() + 8
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ApplyError('Nagios did not become ready after restart.')
        try:
            docker('exec', identifier, '/bin/sh', '-c', READY, 'topology-ready', status, started,
                   timeout=min(3, remaining))
            return
        except (subprocess.SubprocessError, OSError):
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))


def file_identity(metadata):
    return metadata.st_dev, metadata.st_ino, metadata.st_ctime_ns


def update_parents(server, path, expected, changes):
    path = Path(path)
    etc = path.parent.parent
    if path.resolve() != path:
        raise ApplyError('Symbolic-link configuration paths are unsupported.')
    original, revision, metadata = read_config(path)
    if expected != revision:
        raise TopologyConflict('Configuration changed. Reload the topology before submitting again.')
    updated = Topology(original).updated(changes)
    if updated == original:
        return False
    if metadata.st_nlink != 1 or os.listxattr(path, follow_symlinks=False):
        raise ApplyError('Host configuration links or extended metadata require operator review.')
    identifier = target_container(server, etc)
    main, main_revision, main_metadata = read_config(etc / 'nagios.cfg')
    try:
        with tempfile.TemporaryDirectory(prefix='.topology-', dir=etc) as directory:
            stage = Path(directory)
            container_stage = ETC / stage.name
            validation, status = candidate_main(main, container_stage / 'localhost.cfg')
            atomic_replace_host_config(str(stage / 'localhost.cfg'), updated, metadata)
            atomic_replace_host_config(str(stage / 'nagios.cfg'), validation, main_metadata)
            stage.chmod(0o711)
            try:
                docker('exec', identifier, NAGIOS, '-v', str(container_stage / 'nagios.cfg'), timeout=15)
            except (OSError, subprocess.SubprocessError):
                raise ApplyError('Nagios rejected the candidate or verification did not complete. Configuration was not changed.') from None
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
        latest = read_config(path)
        if latest[1] != revision or file_identity(latest[2]) != file_identity(metadata):
            raise TopologyConflict('Configuration changed before publication. Reload and try again.')
        if target_container(server, etc) != identifier:
            raise TopologyConflict('The server container changed during verification. Try again.')
        atomic_replace_host_config(str(path), updated, metadata)
    except OSError:
        raise ApplyError('Could not stage, back up or publish the host configuration.') from None
    try:
        restart_and_check(identifier, status)
        if read_config(path)[0] != updated or read_config(etc / 'nagios.cfg')[1] != main_revision:
            raise ApplyError('Source changed during Nagios apply.')
    except (OSError, UnicodeError, TopologyError, subprocess.SubprocessError, ApplyError) as exc:
        try:
            if read_config(path)[0] != updated:
                raise ApplyError('Another writer modified the configuration after publication.')
            atomic_replace_host_config(str(path), original, metadata)
            if read_config(path)[1] != revision:
                raise ApplyError('Restoration checksum did not match.')
        except (OSError, UnicodeError, ApplyError, TopologyError):
            raise ApplyError('Nagios apply failed and rollback could not be verified. Contact an operator; a backup was retained.') from None
        if isinstance(exc, subprocess.TimeoutExpired):
            raise ApplyError('Previous configuration restored. Restart outcome is uncertain; an operator must verify Nagios.') from None
        try:
            restart_and_check(identifier, status)
        except (OSError, subprocess.SubprocessError, ApplyError):
            raise ApplyError('Previous configuration restored, but Nagios recovery could not be verified. Contact an operator.') from None
        raise ApplyError('Nagios apply failed. The previous configuration was restored and Nagios restarted.') from None
    return True
