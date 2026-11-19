from contextlib import contextmanager
import io
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sqlite3
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

from release_tools.builder import build
from release_tools.common import (
    Busy, COHORT, Layout, ReleaseError, ServiceUncertain, Tree, canonical, digest,
)
from release_tools.publisher import Publisher, main
from release_tools.runtime import OpenRCServices


PIN = '8c4b2e2d8ee289d658935f998f12498ed83d51e0'


def archive_bytes(files, members=None):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, kind in members or [(name, 'file') for name in COHORT]:
            member = tarfile.TarInfo(name)
            data = files.get(name, b'pass\n')
            member.mode = 0o644
            if kind == 'symlink':
                member.type = tarfile.SYMTYPE
                member.linkname = '/etc/passwd'
            elif kind == 'hardlink':
                member.type = tarfile.LNKTYPE
                member.linkname = COHORT[0]
            elif kind == 'fifo':
                member.type = tarfile.FIFOTYPE
            else:
                member.size = len(data)
            archive.addfile(member, io.BytesIO(data) if member.isreg() else None)
    return buffer.getvalue()


class FakeServices:
    def __init__(self):
        self.running = True
        self.calls = []
        self.fail_stop = False
        self.fail_starts = 0
        self.fail_health = False
        self.fail_rollback = False
        self.uncertain = False

    def lock_probe(self, path):
        self.calls.append('probe')

    def preflight(self, approval):
        self.calls.append('preflight')
        return {'fixture': 'baseline'}

    def stopped(self):
        return not self.running

    def stop(self):
        self.calls.append('stop')
        if self.uncertain:
            raise ServiceUncertain('fixture uncertainty')
        if self.fail_stop:
            raise ReleaseError('fixture stop failure')
        self.running = False

    def start(self):
        self.calls.append('start')
        if self.fail_starts:
            self.fail_starts -= 1
            raise ReleaseError('fixture start failure')
        self.running = True

    def validate(self, approval, baseline, rollback=False):
        self.calls.append('validate-rollback' if rollback else 'validate')
        if self.fail_rollback if rollback else self.fail_health:
            raise ReleaseError('fixture health failure')


def contend(path, connection):
    tree = Tree(path, os.getuid(), private=True)
    try:
        with tree.lock('publisher.lock'):
            connection.send('locked')
            connection.recv()
    finally:
        tree.close()
        connection.close()


def abrupt_install_exit(layout):
    publisher = Publisher(layout, FakeServices(), clock=lambda: 1000)
    original = publisher.app.write
    def exit_after_rename(name, data, metadata=None, **kwargs):
        original(name, data, metadata, **kwargs)
        os._exit(73)
    publisher.app.write = exit_after_rename
    publisher.publish()


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in ('app', 'control', 'inbox', 'state', 'locks'):
            (self.root / name).mkdir(mode=0o700)
        self.layout = Layout(*(self.root / name for name in ('app', 'control', 'inbox', 'state', 'locks')),
                             owner=os.getuid(), upload_owner=os.getuid(), group=os.getgid())
        for directory in ('blueprints', 'services', 'config'):
            (self.layout.app / directory).mkdir(mode=0o700)
        self.before = {name: ('old = ' + repr(name) + '\n').encode() for name in COHORT[:-1]}
        self.after = {name: ('new = ' + repr(name) + '\n').encode() for name in COHORT}
        for name, data in self.before.items():
            path = self.layout.app / name
            path.write_bytes(data)
            path.chmod(0o644)
            os.utime(path, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
        self.persistent = self.layout.app / 'config' / 'fixture.db'
        self.persistent.write_bytes(b'isolated persistent fixture, not a real database')
        self.existing_lock = self.layout.locks / ('a' * 64 + '.lock')
        self.existing_lock.write_bytes(b'preserve this persistent lock')
        self.existing_lock.chmod(0o600)
        self.approval = {
            'schema': 1, 'approval_id': 'a' * 32, 'commit': PIN,
            'not_before': 900, 'expires_at': 1100,
            'artifact_sha256': '', 'artifact_size': 0,
            'files': {name: {
                'sha256': digest(data), 'size': len(data), 'uid': 0, 'gid': 0, 'mode': 0o644,
                'before': None if name not in self.before else {
                    'sha256': digest(self.before[name]), 'size': len(self.before[name]),
                },
            } for name, data in self.after.items()},
            'validation': {'containers': ['fixture'], 'health_timeout': 1, 'freshness_timeout': 1},
        }
        self.services = FakeServices()
        self.upload(archive_bytes(self.after))
        self.freeze()
        self.publishers = []
        self.addCleanup(self.close_publishers)

    def close_publishers(self):
        for publisher in self.publishers:
            publisher.close()

    def document(self, name, value):
        path = self.layout.control / name
        path.write_bytes(canonical(value))
        path.chmod(0o600)

    def upload(self, data, approve=True):
        path = self.layout.inbox / (self.approval['approval_id'] + '.tar')
        path.write_bytes(data)
        path.chmod(0o600)
        if approve:
            self.approval['artifact_sha256'] = digest(data)
            self.approval['artifact_size'] = len(data)
            self.document('approval.json', self.approval)

    def freeze(self, **changes):
        value = {'approval_id': self.approval['approval_id'], 'expires_at': 1100,
                 'drained': True, 'startup_guard_installed': True}
        value.update(changes)
        self.document('maintenance.json', value)

    def publisher(self):
        publisher = Publisher(self.layout, self.services, clock=lambda: 1000)
        self.publishers.append(publisher)
        return publisher

    def journal(self):
        return json.loads((self.layout.state / 'current.json').read_text())

    def assert_before(self):
        for name in COHORT:
            path = self.layout.app / name
            if name in self.before:
                self.assertEqual(path.read_bytes(), self.before[name])
                self.assertEqual(path.stat().st_mode & 0o777, 0o644)
                self.assertEqual(path.stat().st_mtime_ns, 1_600_000_000_000_000_000)
            else:
                self.assertFalse(path.exists())

    def assert_rejected_before_stop(self):
        with self.assertRaises((ReleaseError, OSError)):
            self.publisher().publish()
        self.assertNotIn('stop', self.services.calls)
        self.assert_before()

    def test_valid_release_preserves_persistent_data_and_locks(self):
        self.assertEqual(self.publisher().publish(), 'committed')
        for name, data in self.after.items():
            self.assertEqual((self.layout.app / name).read_bytes(), data)
        self.assertEqual(self.journal()['phase'], 'COMMITTED')
        self.assertEqual(self.persistent.read_bytes(), b'isolated persistent fixture, not a real database')
        self.assertEqual(self.existing_lock.read_bytes(), b'preserve this persistent lock')
        self.assertTrue((self.layout.locks / '.publisher-probe.lock').exists())
        self.assertEqual(self.services.calls, ['probe', 'preflight', 'stop', 'start', 'validate'])

    def test_invalid_artifact_checksum(self):
        self.approval['artifact_sha256'] = '0' * 64
        self.document('approval.json', self.approval)
        self.assert_rejected_before_stop()

    def test_modified_artifact_after_approval(self):
        self.upload(b'not the approved bytes', approve=False)
        self.assert_rejected_before_stop()

    def test_member_checksum_is_independent_of_archive_checksum(self):
        changed = dict(self.after)
        changed[COHORT[0]] = b'x' * len(self.after[COHORT[0]])
        self.upload(archive_bytes(changed))
        self.assert_rejected_before_stop()

    def test_unexpected_archive_member(self):
        self.upload(archive_bytes(self.after, [(name, 'file') for name in COHORT]
                                  + [('config/secret_key', 'file')]))
        self.assert_rejected_before_stop()

    def test_concatenated_archive_cannot_hide_unexpected_members(self):
        data = archive_bytes(self.after) + archive_bytes({}, [('config/hidden', 'file')])
        self.upload(data)
        self.assert_rejected_before_stop()

    def test_missing_archive_member(self):
        self.upload(archive_bytes(self.after, [(name, 'file') for name in COHORT[:-1]]))
        self.assert_rejected_before_stop()

    def test_path_traversal(self):
        self.upload(archive_bytes(self.after, [('../outside.py', 'file')]))
        self.assert_rejected_before_stop()
        self.assertFalse((self.root / 'outside.py').exists())

    def test_absolute_archive_path(self):
        self.upload(archive_bytes(self.after, [('/outside.py', 'file')]))
        self.assert_rejected_before_stop()

    def test_archive_symlinks_hardlinks_and_special_files(self):
        for kind in ('symlink', 'hardlink', 'fifo'):
            with self.subTest(kind=kind):
                self.upload(archive_bytes(self.after, [(COHORT[0], kind)]))
                self.assert_rejected_before_stop()

    def test_duplicate_archive_member(self):
        self.upload(archive_bytes(self.after, [(name, 'file') for name in COHORT]
                                  + [(COHORT[0], 'file')]))
        self.assert_rejected_before_stop()

    def test_source_syntax_rejected(self):
        self.after[COHORT[0]] = b'invalid python !!!\n'
        self.approval['files'][COHORT[0]].update(
            sha256=digest(self.after[COHORT[0]]), size=len(self.after[COHORT[0]]))
        self.upload(archive_bytes(self.after))
        self.assert_rejected_before_stop()

    def test_incorrect_production_baseline(self):
        (self.layout.app / COHORT[0]).write_bytes(b'other = True\n')
        with self.assertRaises(ReleaseError):
            self.publisher().publish()
        self.assertNotIn('stop', self.services.calls)

    def test_target_file_symlink(self):
        target = self.layout.app / COHORT[0]
        target.unlink()
        target.symlink_to(self.persistent)
        with self.assertRaises((OSError, ReleaseError)):
            self.publisher().publish()
        self.assertEqual(self.persistent.read_bytes(), b'isolated persistent fixture, not a real database')
        self.assertNotIn('stop', self.services.calls)

    def test_parent_directory_symlink(self):
        services = self.layout.app / 'services'
        services.rmdir()
        services.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises((OSError, ReleaseError)):
            self.publisher().publish()
        self.assertNotIn('stop', self.services.calls)

    def test_hardlinked_production_file(self):
        os.link(self.layout.app / COHORT[0], self.root / 'other-link')
        self.assert_rejected_before_stop()

    def test_upload_symlink(self):
        path = self.layout.inbox / (self.approval['approval_id'] + '.tar')
        path.unlink()
        path.symlink_to(self.persistent)
        self.assert_rejected_before_stop()

    def test_upload_hardlink(self):
        path = self.layout.inbox / (self.approval['approval_id'] + '.tar')
        os.link(path, self.root / 'upload-link')
        self.assert_rejected_before_stop()

    def test_duplicate_attempt_is_noop(self):
        publisher = self.publisher()
        publisher.publish()
        calls = list(self.services.calls)
        self.assertEqual(publisher.publish(), 'already-current')
        self.assertEqual(self.services.calls, calls)

    def test_each_transition_has_a_separate_audit_record(self):
        self.publisher().publish()
        events = sorted((self.layout.state / 'events' / self.approval['approval_id']).glob('*.json'))
        phases = [json.loads(path.read_text())['phase'] for path in events]
        self.assertEqual(phases, ['READY', 'STOPPING', 'STOPPED', 'INSTALLING',
                                  'INSTALLED', 'VERIFYING', 'COMMITTED'])

    def test_concurrent_attempt_rejected_by_real_process_lock(self):
        context = multiprocessing.get_context('fork')
        parent, child = context.Pipe()
        process = context.Process(target=contend, args=(self.layout.state, child))
        process.start()
        child.close()
        try:
            self.assertTrue(parent.poll(5))
            self.assertEqual(parent.recv(), 'locked')
            with self.assertRaises(Busy):
                self.publisher().publish()
            self.assertEqual(self.services.calls, [])
        finally:
            parent.send('release')
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join()
            parent.close()
        self.assertEqual(process.exitcode, 0)

    def test_interrupted_replacement_recovers_on_next_invocation(self):
        publisher = self.publisher()
        original = publisher.app.write
        def interrupt(name, data, metadata=None, **kwargs):
            original(name, data, metadata, **kwargs)
            raise KeyboardInterrupt()
        with patch.object(publisher.app, 'write', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                publisher.publish()
        self.assertEqual(self.journal()['phase'], 'INSTALLING')
        self.assertFalse(publisher.startup_allowed())
        with self.assertRaisesRegex(ReleaseError, 'rolled back'):
            self.publisher().publish()
        self.assert_before()
        self.assertEqual(self.journal()['phase'], 'ROLLED_BACK')

    def test_abrupt_process_exit_has_durable_recoverable_journal(self):
        context = multiprocessing.get_context('fork')
        process = context.Process(target=abrupt_install_exit, args=(self.layout,))
        process.start()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join()
            self.fail('fixture child did not exit')
        self.assertEqual(process.exitcode, 73)
        self.assertEqual(self.journal()['phase'], 'INSTALLING')
        self.services.running = False
        publisher = self.publisher()
        self.assertFalse(publisher.startup_allowed())
        with self.assertRaisesRegex(ReleaseError, 'rolled back'):
            publisher.publish()
        self.assert_before()

    def test_interruption_after_new_file_creation_removes_only_owned_module(self):
        publisher = self.publisher()
        original = publisher.app.write
        def interrupt(name, data, metadata=None, **kwargs):
            original(name, data, metadata, **kwargs)
            if name == 'services/host_config.py':
                raise KeyboardInterrupt()
        with patch.object(publisher.app, 'write', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                publisher.publish()
        with self.assertRaises(ReleaseError):
            self.publisher().publish()
        self.assert_before()
        self.assertTrue(self.existing_lock.exists())

    def test_interrupted_before_service_stop_does_not_restart_service(self):
        publisher = self.publisher()
        with patch.object(self.services, 'stop', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                publisher.publish()
        with self.assertRaisesRegex(ReleaseError, 'baseline remains'):
            self.publisher().publish()
        self.assertEqual(self.services.calls, ['probe', 'preflight'])
        self.assertEqual(self.journal()['phase'], 'ABORTED')
        self.assert_before()

    def test_interrupted_rollback_is_recoverable(self):
        publisher = self.publisher()
        self.services.fail_health = True
        original = publisher.app.write
        interrupted = False
        def interrupt(name, data, metadata=None, **kwargs):
            nonlocal interrupted
            original(name, data, metadata, **kwargs)
            if name == COHORT[0] and data == self.before[name] and not interrupted:
                interrupted = True
                raise KeyboardInterrupt()
        with patch.object(publisher.app, 'write', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                publisher.publish()
        self.assertEqual(self.journal()['phase'], 'ROLLING_BACK')
        with self.assertRaisesRegex(ReleaseError, 'rolled back'):
            self.publisher().publish()
        self.assert_before()

    def test_failed_service_stop_leaves_code_and_requires_operator(self):
        self.services.fail_stop = True
        with self.assertRaisesRegex(ReleaseError, 'stop failed'):
            self.publisher().publish()
        self.assert_before()
        self.assertEqual(self.journal()['phase'], 'MANUAL_INTERVENTION')
        self.assertNotIn('start', self.services.calls)

    def test_uncertain_service_controller_does_not_rewrite_code(self):
        self.services.uncertain = True
        with self.assertRaisesRegex(ReleaseError, 'uncertain'):
            self.publisher().publish()
        self.assert_before()
        self.assertEqual(self.journal()['phase'], 'MANUAL_INTERVENTION')

    def test_failed_service_start_rolls_back(self):
        self.services.fail_starts = 1
        with self.assertRaisesRegex(ReleaseError, 'was rolled back'):
            self.publisher().publish()
        self.assert_before()
        self.assertTrue(self.services.running)

    def test_failed_health_validation_rolls_back(self):
        self.services.fail_health = True
        with self.assertRaisesRegex(ReleaseError, 'was rolled back'):
            self.publisher().publish()
        self.assert_before()
        self.assertEqual(self.journal()['phase'], 'ROLLED_BACK')

    def test_replacement_exception_rolls_back_without_waiting_for_retry(self):
        publisher = self.publisher()
        original = publisher.app.write
        failed = False
        def fail_once(name, data, metadata=None, **kwargs):
            nonlocal failed
            original(name, data, metadata, **kwargs)
            if not failed:
                failed = True
                raise OSError('fixture failure after rename')
        with patch.object(publisher.app, 'write', side_effect=fail_once):
            with self.assertRaisesRegex(ReleaseError, 'was rolled back'):
                publisher.publish()
        self.assert_before()

    def test_metadata_failure_does_not_replace_original(self):
        publisher = self.publisher()
        with patch('release_tools.common.os.fchmod', side_effect=PermissionError('fixture denial')):
            with self.assertRaises(PermissionError):
                publisher.app.write(COHORT[0], self.after[COHORT[0]],
                                    {'uid': os.getuid(), 'gid': os.getgid(), 'mode': 0o644})
        self.assert_before()
        self.assertFalse(list((self.layout.app / 'blueprints').glob('.release-*')))

    @unittest.skipUnless(hasattr(os, 'O_NOATIME'), 'Linux no-atime descriptor support required')
    def test_rollback_preserves_captured_timestamps(self):
        self.services.fail_health = True
        with self.assertRaises(ReleaseError):
            self.publisher().publish()
        for name in self.before:
            info = (self.layout.app / name).stat()
            self.assertEqual(info.st_atime_ns, 1_600_000_000_000_000_000)
            self.assertEqual(info.st_mtime_ns, 1_600_000_000_000_000_000)

    def test_failed_rollback_requires_operator_and_blocks_startup(self):
        self.services.fail_health = True
        self.services.fail_rollback = True
        publisher = self.publisher()
        with self.assertRaisesRegex(ReleaseError, 'operator intervention'):
            publisher.publish()
        self.assertEqual(self.journal()['phase'], 'MANUAL_INTERVENTION')
        self.assertFalse(publisher.startup_allowed())
        self.assertTrue((self.layout.state / 'backups' / self.approval['approval_id'] / COHORT[0]).exists())

    def test_modified_backup_prevents_unsafe_rollback(self):
        publisher = self.publisher()
        def fail_validation(*args, **kwargs):
            backup = self.layout.state / 'backups' / self.approval['approval_id'] / COHORT[0]
            backup.write_bytes(b'modified = True\n')
            raise ReleaseError('health failed')
        with patch.object(self.services, 'validate', side_effect=fail_validation):
            with self.assertRaisesRegex(ReleaseError, 'operator intervention'):
                publisher.publish()
        self.assertEqual((self.layout.app / COHORT[0]).read_bytes(), self.after[COHORT[0]])

    def test_unrecognized_changes_prevent_rollback(self):
        def modify_then_fail(*args, **kwargs):
            (self.layout.app / COHORT[0]).write_bytes(b'unreviewed = True\n')
            raise ReleaseError('health failed')
        with patch.object(self.services, 'validate', side_effect=modify_then_fail):
            with self.assertRaisesRegex(ReleaseError, 'operator intervention'):
                self.publisher().publish()
        self.assertEqual((self.layout.app / COHORT[0]).read_bytes(), b'unreviewed = True\n')

    def test_incorrect_production_permissions(self):
        (self.layout.app / COHORT[0]).chmod(0o666)
        with self.assertRaises(ReleaseError):
            self.publisher().publish()
        self.assertNotIn('stop', self.services.calls)

    def test_incorrect_approval_permissions(self):
        (self.layout.control / 'approval.json').chmod(0o644)
        self.assert_rejected_before_stop()

    def test_incorrect_ownership(self):
        other = Layout(self.layout.app, self.layout.control, self.layout.inbox,
                       self.layout.state, self.layout.locks, owner=os.getuid() + 1)
        with self.assertRaises(ReleaseError):
            Publisher(other, self.services)

    def test_missing_approval(self):
        (self.layout.control / 'approval.json').unlink()
        self.assert_rejected_before_stop()

    def test_expired_approval(self):
        self.approval['expires_at'] = 999
        self.document('approval.json', self.approval)
        self.assert_rejected_before_stop()

    def test_future_approval(self):
        self.approval['not_before'] = 1001
        self.document('approval.json', self.approval)
        self.assert_rejected_before_stop()

    def test_approval_replay_after_rollback(self):
        self.services.fail_health = True
        publisher = self.publisher()
        with self.assertRaises(ReleaseError):
            publisher.publish()
        calls = list(self.services.calls)
        with self.assertRaisesRegex(ReleaseError, 'consumed'):
            publisher.publish()
        self.assertEqual(calls, self.services.calls)

    def test_consumed_approval_cannot_be_replayed_without_current_journal(self):
        directory = self.layout.state / 'used'
        directory.mkdir(mode=0o700)
        marker = directory / (self.approval['approval_id'] + '.json')
        marker.write_text('{}')
        marker.chmod(0o600)
        self.assert_rejected_before_stop()

    def test_missing_or_expired_maintenance_freeze(self):
        self.freeze(expires_at=999)
        self.assert_rejected_before_stop()
        self.freeze(drained=False)
        self.assert_rejected_before_stop()
        self.freeze(startup_guard_installed=False)
        self.assert_rejected_before_stop()

    def test_unknown_approval_fields_are_not_paths_or_commands(self):
        self.approval['app_path'] = '/unapproved'
        self.document('approval.json', self.approval)
        self.assert_rejected_before_stop()

    def test_duplicate_json_keys_rejected(self):
        path = self.layout.control / 'approval.json'
        path.write_bytes(b'{"schema":1,"schema":1}')
        self.assert_rejected_before_stop()

    def test_startup_guard_before_after_and_tampered_release(self):
        publisher = self.publisher()
        self.assertTrue(publisher.startup_allowed())
        publisher.publish()
        self.assertTrue(publisher.startup_allowed())
        (self.layout.app / COHORT[0]).write_bytes(b'tampered = True\n')
        self.assertFalse(publisher.startup_allowed())

    def test_corrupt_journal_blocks_startup(self):
        publisher = self.publisher()
        publisher.publish()
        value = self.journal()
        value['phase'] = []
        publisher.state.write_json('current.json', value)
        self.assertFalse(publisher.startup_allowed())

    def test_deadline_rechecked_after_slow_preflight(self):
        def expire(*args):
            self.freeze(expires_at=999)
            return {}
        with patch.object(self.services, 'preflight', side_effect=expire):
            self.assert_rejected_before_stop()

    def test_approval_revocation_during_preflight(self):
        def revoke(*args):
            changed = dict(self.approval, commit='0' * 40)
            self.document('approval.json', changed)
            return {}
        with patch.object(self.services, 'preflight', side_effect=revoke):
            self.assert_rejected_before_stop()

    def test_approval_expiration_during_preflight(self):
        publisher = self.publisher()
        def expire(*args):
            publisher.clock = lambda: 1200
            self.freeze(expires_at=1300)
            return {}
        with patch.object(self.services, 'preflight', side_effect=expire):
            with self.assertRaisesRegex(ReleaseError, 'window'):
                publisher.publish()
        self.assertNotIn('stop', self.services.calls)

    def test_cli_rejects_all_arguments_before_constructing_production_paths(self):
        self.assertEqual(main(['--app', str(self.root)]), 64)


class BuilderTests(unittest.TestCase):
    def test_git_objects_ignore_modified_worktree_and_untracked_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / 'repo'
            repo.mkdir()
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            for name in COHORT:
                path = repo / name
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(b'approved = True\n')
            subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture',
                            '-c', 'user.email=fixture@example.invalid', 'commit', '-q', '-m', 'fixture'],
                           check=True)
            commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD']).decode().strip()
            (repo / COHORT[0]).write_bytes(b'uncommitted = True\n')
            (repo / 'secret.fixture').write_bytes(b'not a real credential')
            manifest = build(repo, commit, root / 'output')
            self.assertEqual(manifest['files'][COHORT[0]]['sha256'], digest(b'approved = True\n'))
            self.assertEqual(set(manifest['files']), set(COHORT))

    def test_reproducible_pinned_build(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            one = build(repo, PIN, root / 'one')
            two = build(repo, PIN, root / 'two')
            self.assertEqual(one, two)
            self.assertEqual((root / 'one/release.tar').read_bytes(),
                             (root / 'two/release.tar').read_bytes())
            self.assertEqual((root / 'one/manifest.json').read_bytes(),
                             (root / 'two/manifest.json').read_bytes())
            self.assertEqual(set(one['files']), set(COHORT))
            with tarfile.open(root / 'one/release.tar', mode='r:') as archive:
                self.assertEqual([m.name for m in archive], list(COHORT))

    def test_builder_rejects_symbolic_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ReleaseError):
                build('.', 'origin/main', Path(directory) / 'out')

    def test_missing_required_file_rejected(self):
        repo = Path(__file__).resolve().parents[1]
        old = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', '167eb47']).decode().strip()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ReleaseError):
                build(repo, old, Path(directory) / 'out')


class RuntimeTests(unittest.TestCase):
    def test_availability_deadline_bounds_slow_response_body(self):
        service = OpenRCServices(Layout.production())
        def stalled_read(*args):
            time.sleep(5)
        with patch('release_tools.runtime.http.client.HTTPConnection') as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 200
            response.read.side_effect = stalled_read
            started = time.monotonic()
            with self.assertRaisesRegex(ReleaseError, 'deadline'):
                service._availability(1)
            self.assertLess(time.monotonic() - started, 3)
            connection.return_value.close.assert_called()

    @contextmanager
    def snapshot_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            (app / 'config').mkdir()
            database = app / 'config/nagios_snapshot.db'
            conn = sqlite3.connect(database)
            conn.execute('CREATE TABLE container_health '
                         '(container TEXT PRIMARY KEY,last_success_at TEXT,'
                         'consecutive_failures INTEGER,last_error TEXT)')
            conn.execute("INSERT INTO container_health VALUES ('fixture','2026-01-01T00:00:00',0,NULL)")
            conn.commit()
            conn.close()
            layout = Layout(app, app, app, app, app, owner=os.getuid())
            yield OpenRCServices(layout), database

    def test_snapshot_query_is_readonly_and_preserves_database(self):
        with self.snapshot_fixture() as (service, database):
            before = database.read_bytes()
            self.assertEqual(service._snapshot(['fixture']), {'fixture': '2026-01-01T00:00:00'})
            self.assertEqual(database.read_bytes(), before)

    def test_snapshot_missing_database_is_not_created(self):
        with self.snapshot_fixture() as (service, database):
            database.unlink()
            with self.assertRaises(ReleaseError):
                service._snapshot(['fixture'])
            self.assertFalse(database.exists())

    def test_snapshot_failure_and_missing_inventory_fail_closed(self):
        with self.snapshot_fixture() as (service, database):
            with self.assertRaises(ReleaseError):
                service._snapshot(['unknown'])
            conn = sqlite3.connect(database)
            conn.execute('UPDATE container_health SET consecutive_failures=1')
            conn.commit()
            conn.close()
            with self.assertRaises(ReleaseError):
                service._snapshot(['fixture'])

    def test_snapshot_stagnation_has_bounded_deadline(self):
        service = OpenRCServices(Layout.production())
        with patch.object(service, '_snapshot', return_value={'fixture': 'unchanged'}), \
                patch('release_tools.runtime.time.monotonic', side_effect=[0, 2]):
            with self.assertRaisesRegex(ReleaseError, 'deadline'):
                service._advance({'validation': {'containers': ['fixture'], 'freshness_timeout': 1}},
                                 {'fixture': 'unchanged'})

    def test_service_controller_has_fixed_commands_and_cleared_environment(self):
        service = OpenRCServices(Layout.production())
        with patch('release_tools.runtime.subprocess.run') as run:
            run.return_value.returncode = 0
            service._command('start')
        args, options = run.call_args
        self.assertEqual(args[0], ['/sbin/rc-service', 'dashboard-nagios', 'start'])
        self.assertNotIn('shell', options)
        self.assertNotIn('PYTHONPATH', options['env'])
        with self.assertRaises(ReleaseError):
            service._command('restart')

    def test_controller_timeout_is_explicitly_uncertain(self):
        service = OpenRCServices(Layout.production())
        with patch('release_tools.runtime.subprocess.run', side_effect=subprocess.TimeoutExpired('fixture', 30)):
            with self.assertRaises(ServiceUncertain):
                service._command('start')

    def test_posix_cross_process_probe_uses_only_temporary_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Tree(directory, os.getuid(), private=True)
            try:
                with tree.lock('probe.lock'):
                    OpenRCServices(Layout.production()).lock_probe(Path(directory) / 'probe.lock')
                self.assertTrue((Path(directory) / 'probe.lock').exists())
            finally:
                tree.close()


if __name__ == '__main__':
    unittest.main()
