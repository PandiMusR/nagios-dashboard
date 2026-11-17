from __future__ import annotations

import fcntl
import hashlib
import os
import stat
import tempfile
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from functools import wraps

from flask import jsonify

VOLUME_ROOT = '/svr'
LOCK_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'host_config_locks')
_mutation = ContextVar('host_config_mutation', default=None)


class HostConfigBusy(Exception):
    pass


class HostConfigError(Exception):
    pass


def host_config_path(server: str) -> str:
    return f'{VOLUME_ROOT}/{server}/etc/objects/localhost.cfg'


@contextmanager
def host_config_lock(path: str):
    identity = os.path.realpath(path)
    os.makedirs(LOCK_DIR, mode=0o700, exist_ok=True)
    lock_path = os.path.join(LOCK_DIR, hashlib.sha256(os.fsencode(identity)).hexdigest() + '.lock')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HostConfigBusy('Nagios host configuration is busy; retry later') from exc
        yield
    finally:
        os.close(fd)


def guard_host_config_writes(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        with ExitStack() as stack:
            token = _mutation.set((stack, set()))
            try:
                return function(*args, **kwargs)
            except HostConfigBusy as exc:
                return jsonify({'success': False, 'error': str(exc)}), 409
            except HostConfigError as exc:
                return jsonify({'success': False, 'error': str(exc)}), 500
            finally:
                _mutation.reset(token)
    return guarded


def lock_host_configs(paths) -> None:
    stack, held = _mutation.get()
    identities = sorted({os.path.realpath(path) for path in paths} - held)
    if held and identities and identities[0] < max(held):
        raise RuntimeError('Host configuration locks must be acquired in sorted path order')
    for path in identities:
        try:
            stack.enter_context(host_config_lock(path))
        except OSError as exc:
            raise HostConfigError('Cannot acquire Nagios host configuration lock') from exc
        held.add(path)


def atomic_replace_host_config(path: str, content: str, metadata: os.stat_result) -> None:
    if os.path.islink(path):
        raise OSError('Refusing to replace a symbolic-link host configuration')
    directory = os.path.dirname(path)
    fd, staged = tempfile.mkstemp(prefix='.' + os.path.basename(path) + '.', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(content)
            handle.flush()
            current = os.fstat(handle.fileno())
            try:
                if (current.st_uid, current.st_gid) != (metadata.st_uid, metadata.st_gid):
                    os.fchown(handle.fileno(), metadata.st_uid, metadata.st_gid)
                os.fchmod(handle.fileno(), stat.S_IMODE(metadata.st_mode))
            except OSError as exc:
                raise OSError('Cannot preserve host configuration ownership and permissions') from exc
            verified = os.fstat(handle.fileno())
            if (verified.st_uid, verified.st_gid, stat.S_IMODE(verified.st_mode)) != (
                metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)
            ):
                raise OSError('Host configuration metadata verification failed')
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)
