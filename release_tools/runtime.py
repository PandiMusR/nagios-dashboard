from contextlib import closing, contextmanager
import http.client
import os
from pathlib import Path
import sqlite3
import signal
import subprocess
import time

from .common import ReleaseError, ServiceUncertain, Tree


@contextmanager
def availability_deadline(seconds):
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise ReleaseError('unexpected existing process timer')
    def expired(signum, frame):
        raise ReleaseError('Dashboard availability deadline exceeded')
    previous = signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class OpenRCServices:
    def __init__(self, layout):
        self.layout = layout

    def _command(self, action):
        if action not in ('stop', 'start'):
            raise ReleaseError('unsupported service operation')
        try:
            result = subprocess.run(
                ['/sbin/rc-service', 'dashboard-nagios', action], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'},
            )
        except subprocess.TimeoutExpired as exc:
            raise ServiceUncertain('service control deadline exceeded') from exc
        if result.returncode:
            raise ReleaseError('Dashboard service operation failed')

    def stop(self):
        self._command('stop')
        if not self.stopped():
            raise ReleaseError('Dashboard process remains running')

    def start(self):
        if not self.stopped():
            raise ReleaseError('unexpected Dashboard process already running')
        self._command('start')

    def stopped(self):
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit():
                continue
            try:
                if 'python' not in (proc / 'comm').read_text():
                    continue
                args = (proc / 'cmdline').read_bytes().split(b'\0')
                if os.fsencode(self.layout.app / 'app.py') in args:
                    return False
                if b'app.py' in args and Path(os.readlink(proc / 'cwd')) == self.layout.app:
                    return False
            except FileNotFoundError:
                continue
            except PermissionError as exc:
                raise ReleaseError('cannot establish Dashboard process state') from exc
        return True

    def _identity(self, service, script):
        run = Tree('/run', self.layout.owner)
        try:
            data, _ = run.read(service + '.pid', limit=32, private=False)
        finally:
            run.close()
        try:
            pid = int(data.strip())
            if pid < 2:
                raise ValueError()
            proc = Path('/proc') / str(pid)
            args = (proc / 'cmdline').read_bytes().split(b'\0')
            if os.fsencode(self.layout.app / script) not in args:
                raise ValueError()
            fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
            uid = next(line for line in (proc / 'status').read_text().splitlines()
                       if line.startswith('Uid:')).split()[1:]
            if any(int(value) != self.layout.owner for value in uid):
                raise ValueError()
            return [pid, int(fields[19])]
        except (OSError, ValueError, StopIteration) as exc:
            raise ReleaseError('service identity could not be verified') from exc

    def _identities(self):
        return {
            'dashboard': self._identity('dashboard-nagios', 'app.py'),
            'collector': self._identity('nagios-poller', 'services/nagios_poller.py'),
            'proxy': self._identity('nagios-proxy', 'services/async_proxy.py'),
        }

    def _sensitive_metadata(self):
        config = Tree(self.layout.app / 'config', self.layout.owner, private=True)
        try:
            names = ['secret_key', 'host_stages.db', 'nagios_snapshot.db']
            names.extend(name for name in os.listdir(config.fd) if name.startswith('nagios_creds_')
                         and name.endswith('.json'))
            if len(names) > 259 or any(len(name) > 192 for name in names):
                raise ReleaseError('credential inventory exceeds bounded validation limits')
            result = {name: list(config.metadata(name, limit=512 * 1024 * 1024)) for name in names}
            if not 32 <= result['secret_key'][1] <= 4096:
                raise ReleaseError('session key metadata requires operator review')
            return result
        finally:
            config.close()

    def _snapshot(self, containers):
        path = self.layout.app / 'config' / 'nagios_snapshot.db'
        deadline = time.monotonic() + 2
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)) as conn:
                conn.execute('PRAGMA query_only=ON')
                conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                marks = ','.join('?' for _ in containers)
                rows = conn.execute(
                    'SELECT container,last_success_at,consecutive_failures,last_error IS NULL '
                    'FROM container_health WHERE container IN (' + marks + ')', containers,
                ).fetchall()
            result = {}
            for name, success, failures, error_free in rows:
                if (not isinstance(success, str) or not 1 <= len(success) <= 64
                        or failures != 0 or not error_free):
                    raise ReleaseError('collector is degraded')
                result[name] = success
            if set(result) != set(containers):
                raise ReleaseError('approved container inventory is not healthy')
            return result
        except sqlite3.Error as exc:
            raise ReleaseError('read-only snapshot verification failed') from exc

    def _advance(self, approval, previous):
        validation = approval['validation']
        deadline = time.monotonic() + validation['freshness_timeout']
        while True:
            current = self._snapshot(validation['containers'])
            if all(current[name] != previous[name] for name in current):
                return current
            if time.monotonic() >= deadline:
                raise ReleaseError('collector did not advance before deadline')
            time.sleep(min(1, max(0, deadline - time.monotonic())))

    def lock_probe(self, path):
        code = (
            'import fcntl,os,sys; '
            'fd=os.open(sys.argv[1],os.O_RDWR|os.O_NOFOLLOW); '
            '\ntry: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)'
            '\nexcept BlockingIOError: sys.exit(0)'
            '\nelse: sys.exit(1)'
        )
        result = subprocess.run(['/usr/bin/python3', '-I', '-B', '-c', code, str(path)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=5, env={})
        if result.returncode:
            raise ReleaseError('cross-process lock protocol was not verified')

    def preflight(self, approval):
        identities = self._identities()
        sensitive = self._sensitive_metadata()
        initial = self._snapshot(approval['validation']['containers'])
        current = self._advance(approval, initial)
        if identities != self._identities():
            raise ReleaseError('service identity changed during preflight')
        return {'identities': identities, 'snapshots': current, 'sensitive': sensitive}

    def _availability(self, seconds):
        with availability_deadline(seconds):
            self._availability_loop(seconds)

    def _availability_loop(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                for path in ('/login', '/static/css/login.css'):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ReleaseError('availability deadline exceeded')
                    conn = http.client.HTTPConnection('127.0.0.1', 80, timeout=min(2, remaining))
                    try:
                        conn.request('GET', path, headers={'Host': '127.0.0.1', 'Connection': 'close'})
                        response = conn.getresponse()
                        if response.status != 200:
                            raise OSError('unexpected availability response')
                        response.read(65536)
                    finally:
                        conn.close()
                return
            except (OSError, http.client.HTTPException):
                time.sleep(min(0.2, max(0, deadline - time.monotonic())))
        raise ReleaseError('Dashboard availability validation failed')

    def validate(self, approval, baseline, rollback=False):
        self._availability(approval['validation']['health_timeout'])
        identities = self._identities()
        for name in ('collector', 'proxy'):
            if identities[name] != baseline['identities'][name]:
                raise ReleaseError('unrelated service identity changed')
        if not rollback:
            self._advance(approval, baseline['snapshots'])
        if identities != self._identities():
            raise ReleaseError('service identity changed during validation')
        sensitive = self._sensitive_metadata()
        protected = lambda records: {name: value for name, value in records.items()
                                     if name == 'secret_key' or name.startswith('nagios_creds_')}
        if protected(sensitive) != protected(baseline['sensitive']):
            raise ReleaseError('credential metadata changed during maintenance')
