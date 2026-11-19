from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat


COHORT = (
    'blueprints/api.py',
    'blueprints/global_settings.py',
    'blueprints/host_manager.py',
    'blueprints/servers.py',
    'services/host_config.py',
)
MAX_FILE = 128 * 1024
MAX_ARTIFACT = 2 * 1024 * 1024
MAX_JSON = 128 * 1024


class ReleaseError(Exception):
    pass


class Busy(ReleaseError):
    pass


class ServiceUncertain(ReleaseError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def decode(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ReleaseError('duplicate JSON key')
            result[key] = value
        return result

    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, TypeError) as exc:
        raise ReleaseError('invalid JSON') from exc


def exact_keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ReleaseError('unexpected document fields')


def hex_string(value, length):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is None:
        raise ReleaseError('invalid identifier or checksum')
    return value


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ReleaseError('invalid integer')
    return value


def parts(name):
    if not isinstance(name, str) or not name or name.startswith('/'):
        raise ReleaseError('invalid relative path')
    result = name.split('/')
    if any(x in ('', '.', '..') or '\\' in x or '\x00' in x for x in result):
        raise ReleaseError('unsafe relative path')
    return result


def check_directory(fd, owner, private=False, upload=False):
    info = os.fstat(fd)
    forbidden = 0o007 if upload else (0o077 if private else 0o022)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner or info.st_mode & forbidden:
        raise ReleaseError('untrusted directory metadata')


def check_file(fd, owner, limit, private=True):
    info = os.fstat(fd)
    forbidden = 0o077 if private else 0o022
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != owner
            or info.st_mode & forbidden or info.st_size > limit):
        raise ReleaseError('untrusted file metadata or size')
    return info


class Tree:
    def __init__(self, path, owner, private=False, upload=False):
        self.path = Path(path)
        self.owner = owner
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            check_directory(self.fd, owner, private, upload)
        except BaseException:
            os.close(self.fd)
            raise

    def close(self):
        os.close(self.fd)

    @contextmanager
    def parent(self, name, create=False):
        names = parts(name)
        fd = os.dup(self.fd)
        try:
            for directory in names[:-1]:
                if create:
                    try:
                        os.mkdir(directory, 0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                child = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=fd)
                try:
                    check_directory(child, self.owner)
                except BaseException:
                    os.close(child)
                    raise
                os.close(fd)
                fd = child
            yield fd, names[-1]
        finally:
            os.close(fd)

    def read(self, name, limit=MAX_FILE, private=True, owner=None):
        with self.parent(name) as (parent, leaf):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
            if owner is None or owner == self.owner:
                flags |= getattr(os, 'O_NOATIME', 0)
            fd = os.open(leaf, flags, dir_fd=parent)
            try:
                info = check_file(fd, self.owner if owner is None else owner, limit, private)
                chunks = []
                size = 0
                while True:
                    chunk = os.read(fd, min(65536, limit + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > limit:
                        raise ReleaseError('file exceeded size limit')
                after = os.fstat(fd)
                if (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
                        after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise ReleaseError('file changed during read')
                if after.st_size != size:
                    raise ReleaseError('short read')
                if os.listxattr(fd):
                    raise ReleaseError('extended metadata requires operator review')
                metadata = dict(uid=info.st_uid, gid=info.st_gid,
                                mode=stat.S_IMODE(info.st_mode),
                                atime_ns=info.st_atime_ns, mtime_ns=info.st_mtime_ns)
                return b''.join(chunks), metadata
            finally:
                os.close(fd)

    def optional(self, name, **kwargs):
        try:
            return self.read(name, **kwargs)
        except FileNotFoundError:
            return None

    def metadata(self, name, limit=MAX_FILE):
        with self.parent(name) as (parent, leaf):
            fd = os.open(leaf, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=parent)
            try:
                info = check_file(fd, self.owner, limit)
                if os.listxattr(fd):
                    raise ReleaseError('extended metadata requires operator review')
                return (info.st_ino, info.st_size, info.st_mtime_ns, info.st_uid,
                        info.st_gid, stat.S_IMODE(info.st_mode))
            finally:
                os.close(fd)

    def json(self, name):
        return decode(self.read(name, MAX_JSON)[0])

    def write(self, name, data, metadata=None, exclusive=False):
        with self.parent(name, create=True) as (parent, leaf):
            temporary = '.release-' + secrets.token_hex(16)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=parent)
            try:
                view = memoryview(data)
                while view:
                    written = os.write(fd, view)
                    if not written:
                        raise ReleaseError('short write')
                    view = view[written:]
                if metadata:
                    current = os.fstat(fd)
                    if (current.st_uid, current.st_gid) != (metadata['uid'], metadata['gid']):
                        os.fchown(fd, metadata['uid'], metadata['gid'])
                    os.fchmod(fd, metadata['mode'])
                    if 'mtime_ns' in metadata:
                        os.utime(fd, ns=(metadata['atime_ns'], metadata['mtime_ns']))
                    current = os.fstat(fd)
                    if (current.st_uid, current.st_gid, stat.S_IMODE(current.st_mode)) != (
                            metadata['uid'], metadata['gid'], metadata['mode']):
                        raise ReleaseError('file metadata was not preserved')
                os.fsync(fd)
                if exclusive:
                    os.link(temporary, leaf, src_dir_fd=parent, dst_dir_fd=parent,
                            follow_symlinks=False)
                    os.unlink(temporary, dir_fd=parent)
                else:
                    os.replace(temporary, leaf, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                os.close(fd)
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass

    def write_json(self, name, value, exclusive=False):
        self.write(name, canonical(value), exclusive=exclusive)

    def remove_verified(self, name, expected):
        with self.parent(name) as (parent, leaf):
            data, _ = self.read(name, private=False)
            if digest(data) != expected:
                raise ReleaseError('refusing to remove modified code')
            os.unlink(leaf, dir_fd=parent)
            os.fsync(parent)

    @contextmanager
    def lock(self, name):
        with self.parent(name) as (parent, leaf):
            fd = os.open(leaf, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=parent)
            try:
                check_file(fd, self.owner, MAX_JSON)
                os.fsync(parent)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise Busy('another release owns the lock') from exc
                yield
            finally:
                os.close(fd)


@dataclass(frozen=True)
class Layout:
    app: Path
    control: Path
    inbox: Path
    state: Path
    locks: Path
    owner: int = 0
    upload_owner: int = 1001
    group: int = 0

    @classmethod
    def production(cls):
        return cls(Path('/svr/dashboard-nagios'), Path('/etc/nagios-release'),
                   Path('/var/lib/nagios-release/incoming/rif'),
                   Path('/var/lib/nagios-release/state'),
                   Path('/svr/dashboard-nagios/config/host_config_locks'))


def verify_absolute_ancestors(path, owner=0, upload_leaf=False):
    current = Path('/')
    for component in Path(path).parts[1:]:
        current /= component
        fd = os.open(current, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            check_directory(fd, owner, upload=upload_leaf and current == Path(path))
        finally:
            os.close(fd)
