import ast
from contextlib import ExitStack
import io
import os
import re
import secrets
import sys
import tarfile
import time

from .common import (
    COHORT, MAX_ARTIFACT, MAX_FILE, Layout, ReleaseError, ServiceUncertain, Tree,
    digest, exact_keys, hex_string, integer, verify_absolute_ancestors,
)


TERMINAL = {'COMMITTED', 'ROLLED_BACK', 'ABORTED', 'MANUAL_INTERVENTION'}
START_TARGET = {'INSTALLED', 'VERIFYING', 'COMMITTED'}
START_BEFORE = {'ROLLBACK_READY', 'ROLLED_BACK', 'ABORTED'}
PHASES = TERMINAL | START_TARGET | START_BEFORE | {
    'READY', 'STOPPING', 'STOPPED', 'INSTALLING', 'ROLLBACK_STOPPING', 'ROLLING_BACK',
}


def approval_document(value, now=None):
    exact_keys(value, {'schema', 'approval_id', 'commit', 'not_before', 'expires_at',
                       'artifact_sha256', 'artifact_size', 'files', 'validation'})
    if type(value['schema']) is not int or value['schema'] != 1:
        raise ReleaseError('unsupported approval schema')
    hex_string(value['approval_id'], 32)
    hex_string(value['commit'], 40)
    hex_string(value['artifact_sha256'], 64)
    integer(value['artifact_size'], 1, MAX_ARTIFACT)
    integer(value['not_before'], 0, 2**53)
    integer(value['expires_at'], value['not_before'] + 1, 2**53)
    if now is not None and not value['not_before'] <= now < value['expires_at']:
        raise ReleaseError('approval is outside its execution window')
    exact_keys(value['files'], COHORT)
    for name, entry in value['files'].items():
        exact_keys(entry, {'sha256', 'size', 'uid', 'gid', 'mode', 'before'})
        hex_string(entry['sha256'], 64)
        integer(entry['size'], 1, MAX_FILE)
        if any(type(entry[k]) is not int for k in ('uid', 'gid', 'mode')):
            raise ReleaseError('invalid target metadata')
        if (entry['uid'], entry['gid'], entry['mode']) != (0, 0, 0o644):
            raise ReleaseError('target metadata is not approved for this cohort')
        before = entry['before']
        if before is None:
            if name != 'services/host_config.py':
                raise ReleaseError('required baseline file may not be absent')
        else:
            exact_keys(before, {'sha256', 'size'})
            hex_string(before['sha256'], 64)
            integer(before['size'], 1, MAX_FILE)
    validation = value['validation']
    exact_keys(validation, {'containers', 'health_timeout', 'freshness_timeout'})
    containers = validation['containers']
    if (not isinstance(containers, list) or not 1 <= len(containers) <= 128
            or any(not isinstance(x, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', x)
                   is None for x in containers) or len(set(containers)) != len(containers)):
        raise ReleaseError('invalid approved container inventory')
    integer(validation['health_timeout'], 1, 30)
    integer(validation['freshness_timeout'], 1, 180)
    return value


def artifact_files(data, approval):
    if len(data) != approval['artifact_size'] or digest(data) != approval['artifact_sha256']:
        raise ReleaseError('artifact integrity mismatch')
    files = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:', ignore_zeros=True) as archive:
            for member in archive:
                if (member.name not in COHORT or member.name in files or not member.isreg()
                        or member.size != approval['files'][member.name]['size']
                        or member.size > MAX_FILE):
                    raise ReleaseError('invalid archive member')
                handle = archive.extractfile(member)
                if handle is None:
                    raise ReleaseError('unreadable archive member')
                with handle:
                    content = handle.read(MAX_FILE + 1)
                if digest(content) != approval['files'][member.name]['sha256']:
                    raise ReleaseError('member integrity mismatch')
                ast.parse(content, filename=member.name)
                files[member.name] = content
    except (tarfile.TarError, SyntaxError, UnicodeError, ValueError) as exc:
        raise ReleaseError('invalid artifact format or Python syntax') from exc
    if set(files) != set(COHORT):
        raise ReleaseError('incomplete artifact')
    return files


class Publisher:
    def __init__(self, layout, services, clock=time.time):
        self.layout = layout
        self.services = services
        self.clock = clock
        self.stack = ExitStack()
        try:
            self.app = self._tree(layout.app)
            self.control = self._tree(layout.control, private=True)
            self.state = self._tree(layout.state, private=True)
            self.inbox = self._tree(layout.inbox, upload=True)
            self.locks = self._tree(layout.locks, private=True)
            for name in COHORT:
                with self.app.parent(name):
                    pass
        except BaseException:
            self.stack.close()
            raise

    def _tree(self, path, **options):
        tree = Tree(path, self.layout.owner, **options)
        self.stack.callback(tree.close)
        return tree

    def close(self):
        self.stack.close()

    def _current(self, name):
        value = self.app.optional(name, private=False)
        if value is not None:
            data, metadata = value
            if (metadata['uid'], metadata['gid'], metadata['mode']) != (
                    self.layout.owner, self.layout.group, 0o644):
                raise ReleaseError('unexpected production code metadata')
            return {'sha256': digest(data), 'size': len(data)}, metadata, data
        return None

    def _matches(self, approval, target):
        for name in COHORT:
            current = self._current(name)
            expected = approval['files'][name] if target else approval['files'][name]['before']
            actual = current[0] if current else None
            expected_hash = None if expected is None else {k: expected[k] for k in ('sha256', 'size')}
            if actual != expected_hash:
                raise ReleaseError('production checksum baseline mismatch')

    def _maintenance(self, approval):
        value = self.control.json('maintenance.json')
        exact_keys(value, {'approval_id', 'expires_at', 'drained', 'startup_guard_installed'})
        if (value['approval_id'] != approval['approval_id']
                or type(value['expires_at']) is not int or value['expires_at'] <= self.clock()
                or value['drained'] is not True or value['startup_guard_installed'] is not True):
            raise ReleaseError('maintenance freeze or startup guard is not attested')

    def _journal(self):
        saved = self.state.optional('current.json', limit=128 * 1024)
        if saved is None:
            return None
        from .common import decode
        value = decode(saved[0])
        exact_keys(value, {'schema', 'phase', 'approval', 'backups', 'baseline', 'reason'})
        if (type(value['schema']) is not int or value['schema'] != 1
                or not isinstance(value['phase'], str) or value['phase'] not in PHASES):
            raise ReleaseError('unrecognized journal')
        approval_document(value['approval'])
        exact_keys(value['backups'], COHORT)
        if not isinstance(value['baseline'], dict) or not isinstance(value['reason'], str):
            raise ReleaseError('invalid recovery journal')
        for name, metadata in value['backups'].items():
            before = value['approval']['files'][name]['before']
            if metadata is None:
                if before is not None:
                    raise ReleaseError('missing recovery metadata')
            else:
                exact_keys(metadata, {'uid', 'gid', 'mode', 'atime_ns', 'mtime_ns'})
                if before is None or any(type(x) is not int for x in metadata.values()):
                    raise ReleaseError('invalid recovery metadata')
                if (metadata['uid'], metadata['gid'], metadata['mode']) != (
                        self.layout.owner, self.layout.group, 0o644):
                    raise ReleaseError('unapproved recovery metadata')
        return value

    def _save(self, journal, phase, reason=''):
        journal['phase'] = phase
        journal['reason'] = reason
        self.state.write_json('current.json', journal)
        event = str(time.time_ns()) + '-' + secrets.token_hex(8) + '.json'
        self.state.write_json('events/' + journal['approval']['approval_id'] + '/' + event, {
            'approval_id': journal['approval']['approval_id'], 'commit': journal['approval']['commit'],
            'phase': phase, 'reason': reason, 'time': int(self.clock()),
        }, exclusive=True)

    def _backup_name(self, approval, name):
        return 'backups/' + approval['approval_id'] + '/' + name

    def _backup(self, approval):
        metadata = {}
        for name in COHORT:
            current = self._current(name)
            metadata[name] = current[1] if current else None
            if current:
                backup_name = self._backup_name(approval, name)
                existing = self.state.optional(backup_name)
                if existing is None:
                    self.state.write(backup_name, current[2], exclusive=True)
                elif digest(existing[0]) != current[0]['sha256']:
                    raise ReleaseError('existing backup does not match production')
        return metadata

    def _verify_recovery(self, journal):
        files = {}
        approval = journal['approval']
        for name in COHORT:
            current = self._current(name)
            actual = current[0] if current else None
            entry = approval['files'][name]
            target = {k: entry[k] for k in ('sha256', 'size')}
            if actual not in (entry['before'], target):
                raise ReleaseError('unrecognized production changes prevent recovery')
            if entry['before'] is not None:
                data, _ = self.state.read(self._backup_name(approval, name))
                if {'sha256': digest(data), 'size': len(data)} != entry['before']:
                    raise ReleaseError('recovery backup integrity mismatch')
                files[name] = data
        return files

    def _rollback(self, journal):
        try:
            files = self._verify_recovery(journal)
            self._save(journal, 'ROLLBACK_STOPPING', 'release_failed')
            if not self.services.stopped():
                self.services.stop()
            if not self.services.stopped():
                raise ReleaseError('Dashboard did not stop for recovery')
            self._save(journal, 'ROLLING_BACK', 'release_failed')
            for name in COHORT:
                self._verify_recovery(journal)
                if name in files:
                    self.app.write(name, files[name], journal['backups'][name])
                elif self._current(name) is not None:
                    self.app.remove_verified(name, journal['approval']['files'][name]['sha256'])
            self._matches(journal['approval'], False)
            self._save(journal, 'ROLLBACK_READY', 'release_failed')
            self.services.start()
            self.services.validate(journal['approval'], journal['baseline'], rollback=True)
            self._save(journal, 'ROLLED_BACK', 'release_failed')
        except Exception as exc:
            self._save(journal, 'MANUAL_INTERVENTION', 'recovery_failed')
            raise ReleaseError('automatic recovery failed; operator intervention required') from exc

    def _recover(self, journal):
        self._maintenance(journal['approval'])
        if journal['phase'] in ('READY', 'STOPPING') and not self.services.stopped():
            self._matches(journal['approval'], False)
            self._save(journal, 'ABORTED', 'interrupted_before_install')
            raise ReleaseError('interrupted attempt consumed; baseline remains installed')
        self._rollback(journal)
        raise ReleaseError('interrupted attempt rolled back; new approval required')

    def publish(self):
        with self.state.lock('publisher.lock'):
            journal = self._journal()
            if journal and journal['phase'] not in TERMINAL:
                return self._recover(journal)
            approval = approval_document(self.control.json('approval.json'), self.clock())
            used = self.state.optional('used/' + approval['approval_id'] + '.json', limit=1024)
            if used:
                if (journal and journal['approval'] == approval and journal['phase'] == 'COMMITTED'):
                    self._matches(approval, True)
                    return 'already-current'
                raise ReleaseError('approval consumed; independent reapproval required')
            if journal and journal['phase'] == 'MANUAL_INTERVENTION':
                raise ReleaseError('operator must resolve the prior failed recovery')
            self._maintenance(approval)
            self._matches(approval, False)
            artifact, _ = self.inbox.read(approval['approval_id'] + '.tar', MAX_ARTIFACT,
                                          private=True, owner=self.layout.upload_owner)
            files = artifact_files(artifact, approval)
            for name, data in files.items():
                staged = 'staged/' + approval['approval_id'] + '/' + name
                existing = self.state.optional(staged)
                if existing is None:
                    self.state.write(staged, data, exclusive=True)
                elif existing[0] != data:
                    raise ReleaseError('verified staging is inconsistent')
            with self.locks.lock('.publisher-probe.lock'):
                self.services.lock_probe(self.layout.locks / '.publisher-probe.lock')
            baseline = self.services.preflight(approval)
            self._maintenance(approval)
            self._matches(approval, False)
            backups = self._backup(approval)
            if approval_document(self.control.json('approval.json'), self.clock()) != approval:
                raise ReleaseError('approval changed during preparation')
            self._maintenance(approval)
            journal = {'schema': 1, 'phase': 'READY', 'approval': approval, 'backups': backups,
                       'baseline': baseline, 'reason': ''}
            self.state.write_json('used/' + approval['approval_id'] + '.json',
                                  {'commit': approval['commit']}, exclusive=True)
            self._save(journal, 'READY')
            try:
                self._save(journal, 'STOPPING')
                self.services.stop()
                if not self.services.stopped():
                    raise ReleaseError('Dashboard did not stop')
                self._save(journal, 'STOPPED')
                self._matches(approval, False)
                self._save(journal, 'INSTALLING')
                metadata = {'uid': self.layout.owner, 'gid': self.layout.group, 'mode': 0o644}
                for name in COHORT:
                    staged, _ = self.state.read('staged/' + approval['approval_id'] + '/' + name)
                    if digest(staged) != approval['files'][name]['sha256']:
                        raise ReleaseError('staged content changed')
                    self.app.write(name, staged, metadata)
                self._matches(approval, True)
                self._save(journal, 'INSTALLED')
                self.services.start()
                self._save(journal, 'VERIFYING')
                self.services.validate(approval, baseline)
                self._save(journal, 'COMMITTED')
                return 'committed'
            except Exception as exc:
                if isinstance(exc, ServiceUncertain):
                    self._save(journal, 'MANUAL_INTERVENTION', 'service_control_uncertain')
                    raise ReleaseError('service control uncertain; operator review required') from exc
                if journal['phase'] == 'STOPPING' and not self.services.stopped():
                    self._save(journal, 'MANUAL_INTERVENTION', 'stop_failed')
                    raise ReleaseError('stop failed; code unchanged; operator review required') from exc
                self._rollback(journal)
                raise ReleaseError('release failed and was rolled back') from exc

    def startup_allowed(self):
        try:
            journal = self._journal()
            if journal is None:
                approval = approval_document(self.control.json('approval.json'))
                self._matches(approval, False)
            elif journal['phase'] in START_TARGET:
                self._matches(journal['approval'], True)
            elif journal['phase'] in START_BEFORE:
                self._matches(journal['approval'], False)
            else:
                return False
            return True
        except (ReleaseError, OSError):
            return False


def main(argv=None, guard=False):
    if (sys.argv[1:] if argv is None else argv):
        print('arguments are not accepted', file=sys.stderr)
        return 64
    if os.geteuid() != 0:
        print('an independently authorized root entry point is required', file=sys.stderr)
        return 77
    publisher = None
    try:
        layout = Layout.production()
        for path in (layout.app, layout.control, layout.state, layout.locks):
            verify_absolute_ancestors(path)
        verify_absolute_ancestors(layout.inbox, upload_leaf=True)
        from .runtime import OpenRCServices
        publisher = Publisher(layout, OpenRCServices(layout))
        if guard:
            return 0 if publisher.startup_allowed() else 1
        print(publisher.publish())
        return 0
    except Exception:
        print('release refused or failed; authorized operator must inspect protected state', file=sys.stderr)
        return 1
    finally:
        if publisher:
            publisher.close()
