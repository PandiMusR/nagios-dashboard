import json
import multiprocessing
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_release_publisher as baseline
from release_tools.builder import build
from release_tools.common import COHORT, ReleaseError, ServiceUncertain, canonical, digest
from release_tools.runtime import OpenRCServices, controller_absent, process_identity


CONTROLLER = '''import json,os,sys
from pathlib import Path
repo,root,action,gate,output=sys.argv[1:]
gate=int(gate); output=int(output)
def send(value):os.write(output,(json.dumps(value)+'\\n').encode())
send({'ready':True})
if os.read(gate,1)!=b'G':sys.exit(125)
sys.path.insert(0,repo)
from release_tools.common import Layout
from release_tools.publisher import Publisher
layout=Layout(*(Path(root)/name for name in ('app','control','inbox','state','locks')),
              owner=os.getuid(),upload_owner=os.getuid(),group=os.getgid())
publisher=Publisher(layout,None,clock=lambda:1000)
guard=publisher.startup_allowed() if action=='start' else False
publisher.close()
send({'guard':guard})
if os.read(gate,1)!=b'C':sys.exit(125)
marker=Path(root)/'running'
if action=='start':
 values=[p.read_bytes() for folder in ('blueprints','services') for p in (layout.app/folder).glob('*.py')]
 marker.touch()
 send({'mixed':any(v.startswith(b'old =') for v in values) and any(v.startswith(b'new =') for v in values)})
else:
 marker.unlink(missing_ok=True)
 send({'stopped':True})
'''


class PendingServices(baseline.FakeServices):
    def __init__(self, fixture, action):
        super().__init__()
        self.fixture = fixture
        self.action = action
        self.marker = fixture.root / 'running'
        self.marker.touch()
        self.child = None
        self.guard = False
        self.gate = None
        self.output = None
        fixture.addCleanup(self.cleanup)

    def receive(self):
        if not select.select([self.output], [], [], 5)[0]:
            raise AssertionError('fixture barrier deadline exceeded')
        return json.loads(self.output.readline())

    def perform(self, action, spawned, completed):
        if action != self.action or self.child is not None:
            return super().perform(action, spawned, completed)
        self.calls.append(action)
        read_gate, self.gate = os.pipe()
        output, write_output = os.pipe()
        self.output = os.fdopen(output, 'rb', buffering=0)
        self.child = subprocess.Popen(
            [sys.executable, '-I', '-B', '-c', CONTROLLER, str(Path(__file__).resolve().parents[1]),
             str(self.fixture.root), action, str(read_gate), str(write_output)],
            pass_fds=(read_gate, write_output), start_new_session=True,
        )
        os.close(read_gate)
        os.close(write_output)
        assert self.receive() == {'ready': True}
        spawned(process_identity(self.child.pid))
        os.write(self.gate, b'G')
        self.guard = self.receive()['guard']
        raise KeyboardInterrupt('publisher interrupted with a surviving controller')

    def resume(self):
        os.write(self.gate, b'C')
        result = self.receive()
        self.child.wait(timeout=5)
        return result

    def stopped(self):
        return not self.marker.exists()

    def stop(self):
        self.calls.append('stop')
        self.marker.unlink(missing_ok=True)

    def start(self):
        self.calls.append('start')
        if not self.stopped():
            raise ReleaseError('Dashboard already running')
        self.marker.touch()

    def recovery_quiescent(self, record):
        return controller_absent(record['controller'])

    def cleanup(self):
        if self.child is not None:
            if self.child.poll() is None:
                self.child.kill()
            self.child.wait(timeout=5)
        if self.gate is not None:
            os.close(self.gate)
        if self.output is not None:
            self.output.close()


class ControllerRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = baseline.PublisherTests('test_valid_release_preserves_persistent_data_and_locks')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def interrupt(self, action):
        service = PendingServices(self.f, action)
        self.f.services = service
        with self.assertRaises(KeyboardInterrupt):
            self.f.publisher().publish()
        return service

    def attest(self, **changes):
        record = json.loads((self.f.layout.state / 'service-operation.json').read_text())
        value = {'schema': 1, 'approval_id': self.f.approval['approval_id'],
                 'operation_id': record['operation_id'], 'operation_sha256': digest(canonical(record)),
                 'expires_at': 1100, 'quiescent': True, 'dashboard_stopped': True,
                 'uncertain_processes_terminated': True}
        value.update(changes)
        self.f.document('controller-recovery.json', value)

    def refuse_recovery(self):
        publisher = self.f.publisher()
        with patch.object(publisher.app, 'write', side_effect=AssertionError('unsafe source restore')):
            with self.assertRaisesRegex(ReleaseError, 'uncertain'):
                publisher.publish()
        self.assertEqual(self.f.journal()['phase'], 'MANUAL_INTERVENTION')
        self.assertFalse(publisher.startup_allowed())

    def test_interrupted_start_with_surviving_controller(self):
        service = self.interrupt('start')
        self.assertTrue(service.guard)
        self.assertIsNone(service.child.poll())
        self.refuse_recovery()

    def test_interrupted_stop_with_surviving_controller(self):
        service = self.interrupt('stop')
        self.refuse_recovery()
        self.assertFalse(service.stopped())
        self.f.assert_before()

    def test_delayed_start_cannot_load_mixed_rollback_cohort(self):
        service = self.interrupt('start')
        self.refuse_recovery()
        self.assertFalse(service.resume()['mixed'])
        self.assertEqual(self.f.journal()['phase'], 'MANUAL_INTERVENTION')
        for name in COHORT:
            self.assertEqual((self.f.layout.app / name).read_bytes(), self.f.after[name])

    def test_delayed_stop_cannot_invalidate_completed_recovery(self):
        service = self.interrupt('stop')
        self.refuse_recovery()
        self.assertTrue(service.resume()['stopped'])
        self.assertEqual(self.f.journal()['phase'], 'MANUAL_INTERVENTION')

    def test_repeated_recovery_preserves_pending_operation(self):
        self.interrupt('start')
        path = self.f.layout.state / 'service-operation.json'
        original = path.read_bytes()
        self.refuse_recovery()
        self.refuse_recovery()
        self.assertEqual(path.read_bytes(), original)

    def test_pid_disappearance_is_not_descendant_quiescence(self):
        service = self.interrupt('stop')
        service.resume()
        self.refuse_recovery()

    def test_stale_pid_identity_does_not_authorize_recovery(self):
        service = self.interrupt('stop')
        service.resume()
        path = self.f.layout.state / 'service-operation.json'
        record = json.loads(path.read_text())
        record['controller'] = process_identity(os.getpid())
        record['controller']['start_ticks'] += 1
        path.write_bytes(canonical(record))
        self.refuse_recovery()

    def test_unknown_controller_state_fails_closed_even_with_attestation(self):
        service = self.interrupt('stop')
        service.resume()
        self.attest()
        with patch.object(service, 'recovery_quiescent', return_value=False):
            self.refuse_recovery()

    def test_live_controller_cannot_be_attested_away(self):
        service = self.interrupt('stop')
        service.marker.unlink()
        self.attest()
        self.refuse_recovery()

    def test_running_dashboard_cannot_be_attested_away(self):
        service = self.interrupt('start')
        service.resume()
        self.attest()
        self.refuse_recovery()

    def test_untrusted_reconciliation_record_is_rejected(self):
        service = self.interrupt('stop')
        service.resume()
        self.attest()
        (self.f.layout.control / 'controller-recovery.json').chmod(0o644)
        self.refuse_recovery()

    def test_malformed_operation_is_preserved_and_blocks_recovery(self):
        self.interrupt('stop')
        path = self.f.layout.state / 'service-operation.json'
        path.write_bytes(b'{"invalid":true}\n')
        self.refuse_recovery()
        self.assertEqual(path.read_bytes(), b'{"invalid":true}\n')

    def test_abrupt_publisher_exit_leaves_live_controller_blocked(self):
        gate, write_gate = os.pipe()
        output, write_output = os.pipe()
        layout = self.f.layout
        def run_publisher():
            service = baseline.FakeServices()
            def perform(action, spawned, completed):
                child = subprocess.Popen(
                    [sys.executable, '-I', '-B', '-c',
                     "import os,sys; g,o=map(int,sys.argv[1:]); os.write(o,b'R'); "
                     "os.read(g,1); os.write(o,b'D')", str(gate), str(write_output)],
                    pass_fds=(gate, write_output), start_new_session=True,
                )
                spawned(process_identity(child.pid))
                os._exit(73)
            service.perform = perform
            baseline.Publisher(layout, service, clock=lambda: 1000).publish()
        process = multiprocessing.get_context('fork').Process(target=run_publisher)
        process.start()
        os.close(write_output)
        try:
            self.assertTrue(select.select([output], [], [], 5)[0])
            self.assertEqual(os.read(output, 1), b'R')
            process.join(5)
            self.assertEqual(process.exitcode, 73)
            record = json.loads((layout.state / 'service-operation.json').read_text())
            self.assertFalse(controller_absent(record['controller']))
            self.refuse_recovery()
            self.f.assert_before()
            os.write(write_gate, b'C')
            self.assertTrue(select.select([output], [], [], 5)[0])
            self.assertEqual(os.read(output, 1), b'D')
            self.assertEqual(self.f.journal()['phase'], 'MANUAL_INTERVENTION')
        finally:
            if process.is_alive():
                process.terminate()
                process.join(5)
            os.close(write_gate)
            os.close(gate)
            os.close(output)

    def test_verified_quiescence_allows_recovery_once(self):
        service = self.interrupt('start')
        service.resume()
        service.marker.unlink()
        self.attest()
        with self.assertRaisesRegex(ReleaseError, 'rolled back'):
            self.f.publisher().publish()
        self.f.assert_before()
        self.assertEqual(self.f.journal()['phase'], 'ROLLED_BACK')
        calls = service.calls[:]
        with self.assertRaisesRegex(ReleaseError, 'consumed'):
            self.f.publisher().publish()
        self.assertEqual(service.calls, calls)

    def test_wrong_or_expired_attestation_is_rejected(self):
        service = self.interrupt('stop')
        service.resume()
        for changes in ({'operation_sha256': '0' * 64}, {'expires_at': 999},
                        {'operation_id': 'b' * 32}, {'uncertain_processes_terminated': False}):
            with self.subTest(changes=changes):
                self.attest(**changes)
                self.refuse_recovery()

    def test_guard_rejects_start_from_unrelated_process(self):
        self.interrupt('start')
        self.assertFalse(self.f.publisher().startup_allowed())

    def test_intent_is_durable_before_service_launch(self):
        service = self.f.services
        original = service.perform
        def observe(action, spawned, completed):
            record = json.loads((self.f.layout.state / 'service-operation.json').read_text())
            self.assertEqual(record['status'], 'intent')
            self.assertEqual(record['action'], action)
            original(action, spawned, completed)
        with patch.object(service, 'perform', side_effect=observe):
            self.assertEqual(self.f.publisher().publish(), 'committed')

    def test_interruption_before_controller_identity_remains_manual(self):
        with patch.object(self.f.services, 'perform', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.f.publisher().publish()
        self.refuse_recovery()

    def test_legacy_ambiguous_journal_does_not_auto_abort(self):
        self.interrupt('stop')
        (self.f.layout.state / 'service-operation.json').unlink()
        with self.assertRaisesRegex(ReleaseError, 'legacy controller'):
            self.f.publisher().publish()
        self.assertEqual(self.f.journal()['phase'], 'MANUAL_INTERVENTION')


class BackupReadbackTests(unittest.TestCase):
    def setUp(self):
        self.f = baseline.PublisherTests('test_valid_release_preserves_persistent_data_and_locks')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def inject(self, change):
        publisher = self.f.publisher()
        original = publisher.state.write
        modified = []
        def write(name, data, metadata=None, **options):
            original(name, data, metadata, **options)
            if name.startswith('backups/') and not modified:
                change(self.f.layout.state / name)
                modified.append(name)
        with patch.object(publisher.state, 'write', side_effect=write):
            with self.assertRaises((ReleaseError, OSError)):
                publisher.publish()
        self.assertNotIn('stop', self.f.services.calls)
        self.assertNotIn('start', self.f.services.calls)
        self.assertFalse((self.f.layout.state / 'used').exists())
        self.f.assert_before()
        events = list((self.f.layout.state / 'events').rglob('backup-*.json'))
        self.assertEqual(len(events), 1)

    def test_corruption_immediately_after_backup_creation(self):
        self.inject(lambda path: path.write_bytes(b'corrupt = True\n'))

    def test_truncated_backup(self):
        self.inject(lambda path: path.write_bytes(b''))

    def test_missing_backup(self):
        self.inject(lambda path: path.unlink())

    def test_backup_metadata_mismatch(self):
        self.inject(lambda path: path.chmod(0o644))

    def test_failed_backup_read(self):
        publisher = self.f.publisher()
        original = publisher.state.read
        def read(name, *args, **options):
            if name.startswith('backups/') and (self.f.layout.state / name).exists():
                raise PermissionError('fixture backup read denied')
            return original(name, *args, **options)
        with patch.object(publisher.state, 'read', side_effect=read):
            with self.assertRaises(PermissionError):
                publisher.publish()
        self.assertNotIn('stop', self.f.services.calls)
        self.f.assert_before()

    def test_all_backup_inputs_are_verified_before_stop(self):
        publisher = self.f.publisher()
        original_read = publisher.state.read
        original_perform = self.f.services.perform
        verified = set()
        def read(name, *args, **options):
            result = original_read(name, *args, **options)
            if name.startswith('backups/'):
                verified.add(name.split('/', 2)[2])
            return result
        def perform(*args):
            self.assertEqual(verified, set(self.f.before))
            return original_perform(*args)
        with patch.object(publisher.state, 'read', side_effect=read), \
                patch.object(self.f.services, 'perform', side_effect=perform):
            self.assertEqual(publisher.publish(), 'committed')


class GitProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        for name in COHORT:
            path = self.repo / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'original = True\n')
        self.commit('original')
        self.original = self.git('rev-parse', 'HEAD').decode().strip()
        for name in COHORT:
            (self.repo / name).write_bytes(b'replacement = True\n')
        self.commit('replacement')
        self.replacement = self.git('rev-parse', 'HEAD').decode().strip()

    def git(self, *args):
        return subprocess.check_output(['/usr/bin/git', '-C', str(self.repo), *args],
                                       stderr=subprocess.DEVNULL)

    def commit(self, message):
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 'commit', '-qm', message)

    def test_replacement_refs_do_not_change_pinned_artifact_or_manifest(self):
        before = build(self.repo, self.original, self.root / 'before')
        self.git('replace', self.original, self.replacement)
        after = build(self.repo, self.original, self.root / 'after')
        self.assertEqual(before, after)
        self.assertEqual(after['commit'], self.original)
        self.assertEqual((self.root / 'before/release.tar').read_bytes(),
                         (self.root / 'after/release.tar').read_bytes())
        self.assertEqual(after['files'][COHORT[0]]['sha256'], digest(b'original = True\n'))
        self.assertEqual(self.git('replace', '-l').decode().strip(), self.original)

    def test_inherited_git_environment_cannot_redirect_repository(self):
        overrides = {'GIT_DIR': str(self.root / 'unexpected'), 'GIT_COMMON_DIR': '/nonexistent',
                     'GIT_WORK_TREE': '/nonexistent', 'GIT_OBJECT_DIRECTORY': '/nonexistent',
                     'GIT_ALTERNATE_OBJECT_DIRECTORIES': '/nonexistent',
                     'GIT_REPLACE_REF_BASE': 'refs/attacker/', 'GIT_NAMESPACE': 'unexpected',
                     'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.bare',
                     'GIT_CONFIG_VALUE_0': 'true', 'GIT_NO_REPLACE_OBJECTS': '0'}
        with patch.dict(os.environ, overrides):
            manifest = build(self.repo, self.original, self.root / 'output')
        self.assertEqual(manifest['files'][COHORT[0]]['sha256'], digest(b'original = True\n'))

    def test_every_git_subprocess_uses_identical_trusted_contract(self):
        run = subprocess.run
        observed = []
        def invoke(args, **options):
            observed.append((args, options['env']))
            return run(args, **options)
        with patch('release_tools.builder.subprocess.run', side_effect=invoke):
            build(self.repo, self.original, self.root / 'output')
        self.assertGreater(len(observed), 5)
        for args, environment in observed:
            self.assertEqual(args[:2], ['/usr/bin/git', '--no-replace-objects'])
            self.assertEqual(environment, observed[0][1])
            self.assertEqual(environment['GIT_NO_REPLACE_OBJECTS'], '1')
            self.assertNotIn('GIT_DIR', environment)


class RuntimeLifecycleTests(unittest.TestCase):
    def test_identity_persistence_failure_closes_gate_without_service_exec(self):
        service = OpenRCServices(None)
        actual_popen = subprocess.Popen
        children = []
        def spawn(args, **options):
            args = list(args)
            prefix = ("import sys; sys.addaudithook(lambda event,args: "
                      "(_ for _ in ()).throw(RuntimeError('exec denied by fixture')) "
                      "if event == 'os.exec' else None); ")
            args[4] = prefix + args[4]
            child = actual_popen(args, **options)
            children.append(child)
            return child
        with patch('release_tools.runtime.subprocess.Popen', side_effect=spawn):
            with self.assertRaisesRegex(OSError, 'durability'):
                service._command('start', lambda value: (_ for _ in ()).throw(OSError('durability')))
        self.assertEqual(children[0].wait(timeout=5), 125)

    def test_controller_exit_with_detached_descendant_is_uncertain(self):
        service = OpenRCServices(None)
        actual_popen = subprocess.Popen
        output, output_write = os.pipe()
        gate, gate_write = os.pipe()
        fixture = '''import os,sys
permit,output,gate=map(int,sys.argv[1:])
if os.read(permit,1)!=b'1':sys.exit(125)
ready,ready_write=os.pipe()
pid=os.fork()
if pid==0:
 os.close(ready); os.setsid(); os.write(ready_write,b'R'); os.close(ready_write)
 os.write(output,(str(os.getpid())+'\\n').encode()); os.close(output)
 os.read(gate,1); os._exit(0)
os.close(ready_write); os.read(ready,1); os._exit(9)
'''
        def spawn(args, **options):
            permit = options['pass_fds'][0]
            options['pass_fds'] = (permit, output_write, gate)
            return actual_popen([sys.executable, '-I', '-B', '-c', fixture,
                                 str(permit), str(output_write), str(gate)], **options)
        try:
            with patch('release_tools.runtime.subprocess.Popen', side_effect=spawn):
                with self.assertRaisesRegex(ServiceUncertain, 'descendants'):
                    service._command('start')
            self.assertTrue(select.select([output], [], [], 5)[0])
            descendant = int(os.read(output, 64).strip())
            self.assertFalse(controller_absent(process_identity(descendant)))
            self.assertEqual(service.controller.returncode, 9)
        finally:
            os.write(gate_write, b'C')
            for fd in (output, output_write, gate, gate_write):
                os.close(fd)

    def test_controller_absence_does_not_kill_reused_pid(self):
        identity = process_identity(os.getpid())
        self.assertFalse(controller_absent(identity))
        identity['start_ticks'] += 1
        with patch('os.kill', side_effect=AssertionError('must not signal unrelated process')):
            self.assertTrue(controller_absent(identity))

    def test_unreadable_controller_identity_is_not_quiescence(self):
        with patch('release_tools.runtime.process_identity', side_effect=ServiceUncertain('unknown')):
            self.assertFalse(controller_absent(process_identity(os.getpid())))

    def test_timeout_never_claims_completion_or_kills_unknown_descendants(self):
        service = OpenRCServices(None)
        calls = []
        with patch('release_tools.runtime.subprocess.Popen') as popen, \
                patch('release_tools.runtime.process_identity', return_value=process_identity(os.getpid())), \
                patch.object(service, 'stopped', return_value=True):
            popen.return_value.wait.side_effect = subprocess.TimeoutExpired('fixture', 30)
            popen.return_value.poll.return_value = None
            with self.assertRaises(ServiceUncertain):
                service.perform('start', lambda identity: calls.append('spawned'),
                                lambda: calls.append('completed'))
            popen.return_value.kill.assert_not_called()
            popen.return_value.terminate.assert_not_called()
        self.assertEqual(calls, ['spawned'])

    def test_service_state_mismatch_does_not_claim_completion(self):
        service = OpenRCServices(None)
        with patch.object(service, '_command'), patch.object(service, 'stopped', return_value=True):
            with self.assertRaises(ServiceUncertain):
                service.perform('start', lambda value: None,
                                lambda: self.fail('uncertain operation completed'))


if __name__ == '__main__':
    unittest.main()
