import importlib.util
import io
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

from flask import Flask

from services import host_config


ORIGINAL = '''define host{
    host_name               customer-a
    address                 10.10.0.1
    alias                   Original
}
'''


def load_routes():
    config = types.ModuleType('services.config')
    for name in ('GLOBAL_CONFIG_PATH', 'CONFIG_DIR', 'ACTIVITY_LOG_PATH', 'APP_ROOT',
                 'MONITORING_SERVER_MAPPINGS_PATH', 'MONITORING_CONFIG_PATH'):
        setattr(config, name, '/unused')
    config.STAGE_LABELS = {}
    config.PROXY_PORT_OFFSET = 1000
    dependencies = {
        'services.config': config,
    }
    functions = {
        'services.ldap_service': ['log_activity', 'read_activity_logs'],
        'services.uptime_kuma': ['add_host_to_uptime_kuma', 'get_uptime_kuma_config'],
        'services.encryption': ['decrypt_session_value', 'load_encrypted_json', 'save_encrypted_json', 'encrypt_value'],
        'services.shared_helpers': ['get_nagios_servers', 'get_monitoring_categories'],
        'services.down_history': ['build_down_episodes'],
        'services.nextcloud': ['upload_to_nextcloud'],
        'services.stage_service': ['get_host_stage', 'delete_host_stage', 'upsert_host_stage', 'relocate_host_comments'],
        'services.proxy_control': ['disable_container', 'enable_all', 'enable_container', 'ensure_running_and_reload', 'restart'],
        'utils.permissions': ['check_permission'],
        'utils.port_check': ['_get_all_used_ports', 'check_proxy_running'],
    }
    for name, names in functions.items():
        module = types.ModuleType(name)
        for function in names:
            setattr(module, function, Mock(return_value=None))
        dependencies[name] = module
    dependencies['services.ldap_service'].ACTIVITY_LOG_DIR = '/unused'
    dependencies['services.shared_helpers'].get_nagios_servers.return_value = ['Bhome']
    dependencies['services.shared_helpers'].get_monitoring_categories.return_value = []
    dependencies['services.proxy_control'].ensure_running_and_reload.return_value = (True, '')
    dependencies['utils.permissions'].check_permission.return_value = True
    dependencies['utils.port_check']._get_all_used_ports.return_value = set()
    root = Path(__file__).resolve().parents[1]
    routes = {}
    with patch.dict('sys.modules', dependencies):
        for name in ('api', 'host_manager', 'global_settings', 'servers'):
            spec = importlib.util.spec_from_file_location('isolated_' + name, root / 'blueprints' / (name + '.py'))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            routes[name] = module
    return routes, dependencies


class HostConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.modules, self.dependencies = load_routes()
        self.api = self.modules['api']
        self.config = self.root / 'volumes' / 'Bhome' / 'etc' / 'objects' / 'localhost.cfg'
        self.config.parent.mkdir(parents=True)
        self.config.write_text(ORIGINAL)
        self.config.chmod(0o640)
        self.backups = self.config.parent / 'backups'
        self.backups.mkdir()
        (self.backups / 'saved.cfg').write_text(ORIGINAL)
        self.settings = self.root / 'settings'
        self.settings.mkdir()
        (self.settings / 'backups').mkdir()
        self.keyfile = self.settings / 'global_config.json'
        self.keyfile.write_text(json.dumps({'api_key': 'test-key'}))
        for target, name, value in (
            (host_config, 'LOCK_DIR', str(self.root / 'locks')),
            (host_config, 'VOLUME_ROOT', str(self.root / 'volumes')),
            (self.api, 'BHOME_CONFIG_PATH', str(self.config)),
            (self.api, 'GLOBAL_CONFIG_PATH', str(self.keyfile)),
            (self.modules['global_settings'], 'CONFIG_DIR', str(self.settings)),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        command_patch = patch.object(subprocess, 'run')
        self.commands = command_patch.start()
        self.addCleanup(command_patch.stop)
        self.commands.return_value = subprocess.CompletedProcess([], 0, '', '')
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY='isolated-test-secret')
        for name, module in self.modules.items():
            self.app.register_blueprint(getattr(module, name + '_bp'))

    def client(self):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(username='test-admin', role='admin', permissions={})
        return client

    def ip(self, **changes):
        data = {'server': 'Bhome', 'old_ip': '10.10.0.1', 'new_ip': '10.11.0.1'}
        data.update(changes)
        return self.client().post('/api/hosts/change-ip', json=data, headers={'X-API-Key': 'test-key'})

    def edit(self, address='10.10.0.1'):
        return self.client().post('/host-manager/edit', data={
            'server': 'Bhome', 'old_host_name': 'customer-a', 'host_name': 'customer-a',
            'alias': 'Concurrent edit', 'address': address,
        })

    def start_blocked_ip(self, valid):
        entered, release = threading.Event(), threading.Event()
        result = {}

        def validate():
            entered.set()
            if not release.wait(5):
                raise AssertionError('Test validation release was not signaled')
            return valid, 'OK' if valid else 'invalid'

        verify = patch.object(self.api, '_verify_bhome_config', side_effect=validate)
        verify.start()
        self.addCleanup(verify.stop)

        def request():
            try:
                result['response'] = self.ip()
            except BaseException as exc:
                result['exception'] = exc

        worker = threading.Thread(target=request)
        worker.start()
        self.addCleanup(worker.join, 5)
        self.addCleanup(release.set)
        self.assertTrue(entered.wait(5), 'IP request did not reach validation')
        return worker, release, result

    def finish(self, worker, release, result):
        release.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        if 'exception' in result:
            raise result['exception']
        return result['response']

    def assert_no_staged_files(self):
        self.assertEqual(list(self.root.rglob('*.tmp')), [])

    def metadata(self, path=None):
        info = (path or self.config).stat()
        return info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)

    def test_host_edit_contends_then_retries_after_successful_ip_change(self):
        worker, release, result = self.start_blocked_ip(True)
        self.assertEqual(self.edit().status_code, 409)
        response = self.finish(worker, release, result)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.edit(address='10.11.0.1').status_code, 302)
        self.assertIn('10.11.0.1', self.config.read_text())
        self.assertIn('Concurrent edit', self.config.read_text())

    def test_host_edit_contends_then_retries_after_rollback(self):
        worker, release, result = self.start_blocked_ip(False)
        self.assertEqual(self.edit().status_code, 409)
        response = self.finish(worker, release, result)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.config.read_text(), ORIGINAL)
        self.assertEqual(self.edit().status_code, 302)
        self.assertIn('Concurrent edit', self.config.read_text())
        self.assertIn('10.10.0.1', self.config.read_text())

    def test_two_simultaneous_ip_changes_conflict(self):
        worker, release, result = self.start_blocked_ip(True)
        response = self.ip()
        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json['success'])
        self.assertEqual(self.finish(worker, release, result).status_code, 200)
        self.assertEqual(len(list(self.backups.glob('localhost_before_ip_change_*.cfg'))), 1)

    def test_ip_change_contends_while_host_edit_is_restarting(self):
        entered, release = threading.Event(), threading.Event()
        result = {}

        def restart(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return subprocess.CompletedProcess(args[0], 0, '', '')

        self.commands.side_effect = restart
        worker = threading.Thread(target=lambda: result.update(response=self.edit()))
        worker.start()
        self.addCleanup(worker.join, 5)
        self.addCleanup(release.set)
        self.assertTrue(entered.wait(5))
        self.assertEqual(self.ip().status_code, 409)
        release.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result['response'].status_code, 302)
        self.commands.side_effect = None
        self.assertEqual(self.ip().status_code, 200)
        self.assertIn('Concurrent edit', self.config.read_text())
        self.assertIn('10.11.0.1', self.config.read_text())

    def test_all_writer_routes_reject_bhome_lock_contention(self):
        archive = self.settings / 'backups' / 'saved.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            data = ORIGINAL.encode()
            entry = tarfile.TarInfo('Bhome/localhost.cfg')
            entry.size = len(data)
            tar.addfile(entry, io.BytesIO(data))
        requests = [
            ('POST', '/api/hosts/add', {'json': {'server': 'Bhome', 'host_name': 'new-host', 'address': '10.0.0.2'}}),
            ('POST', '/api/hosts/batch-add', {'json': {'server': 'Bhome', 'hosts': [{'host_name': 'new-host', 'address': '10.0.0.2'}]}}),
            ('POST', '/api/hosts/rename', {'json': {'server': 'Bhome', 'old_host_name': 'customer-a', 'host_name': 'renamed'}}),
            ('DELETE', '/api/hosts/delete', {'json': {'server': 'Bhome', 'host_name': 'customer-a'}}),
            ('POST', '/host-manager/add', {'data': {'server': 'Bhome', 'host_name': 'new-host', 'address': '10.0.0.2'}}),
            ('POST', '/host-manager/batch-add', {'data': {'batch_servers[]': ['Bhome'], 'batch_hostnames[]': ['new-host'], 'batch_addresses[]': ['10.0.0.2']}}),
            ('POST', '/host-manager/edit', {'data': {'server': 'Bhome', 'host_name': 'customer-a'}}),
            ('POST', '/host-manager/delete', {'data': {'server': 'Bhome', 'host_name': 'customer-a'}}),
            ('POST', '/host-manager/backup', {'json': {'server': 'Bhome'}}),
            ('POST', '/host-manager/restore', {'json': {'server': 'Bhome', 'backup_name': 'saved'}}),
            ('DELETE', '/host-manager/delete-backup/Bhome/saved', {}),
            ('POST', '/global-settings/backup', {'data': {'backup_name': 'contended'}}),
            ('POST', '/global-settings/restore', {'json': {'backup_name': 'saved'}}),
            ('POST', '/servers/edit-config/Bhome', {'data': {'content': 'overwrite'}}),
            ('POST', '/servers/delete/Bhome', {}),
            ('POST', '/servers/batch-delete', {'json': {'servers': ['Bhome']}}),
            ('POST', '/servers/add', {'data': {'name': 'Bhome', 'port': '8080'}}),
        ]

        def command(args, **kwargs):
            stdout = 'Bhome\n' if args[:2] == ['docker', 'ps'] and '-a' not in args else ''
            return subprocess.CompletedProcess(args, 0, stdout, '')

        self.commands.side_effect = command
        with host_config.host_config_lock(str(self.config)):
            for method, url, kwargs in requests:
                with self.subTest(endpoint=url):
                    self.commands.reset_mock()
                    response = self.client().open(url, method=method, headers={'X-API-Key': 'test-key'}, **kwargs)
                    self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
                    self.assertIn('busy', response.json['error'])
                    self.assertEqual(self.config.read_text(), ORIGINAL)
                    for call in self.commands.call_args_list:
                        self.assertEqual(call.args[0][:2], ['docker', 'ps'])

    def test_multi_server_batch_acquires_all_locks_before_writing(self):
        other = Path(host_config.host_config_path('A'))
        other.parent.mkdir(parents=True)
        other.write_text(ORIGINAL)
        data = {'batch_servers[]': ['A', 'Bhome'], 'batch_hostnames[]': ['new-a', 'new-b'],
                'batch_addresses[]': ['10.0.0.2', '10.0.0.3']}
        with host_config.host_config_lock(str(self.config)):
            self.assertEqual(self.client().post('/host-manager/batch-add', data=data).status_code, 409)
            self.assertEqual(other.read_text(), ORIGINAL)
            with host_config.host_config_lock(str(other)):
                pass
        self.assertEqual(self.client().post('/host-manager/batch-add', data=data).status_code, 302)
        self.assertIn('new-a', other.read_text())
        self.assertIn('new-b', self.config.read_text())

    def test_lock_identity_survives_replacement_and_directory_recreation(self):
        metadata = self.config.stat()
        with host_config.host_config_lock(str(self.config)):
            host_config.atomic_replace_host_config(str(self.config), ORIGINAL + '\n', metadata)
            with self.assertRaises(host_config.HostConfigBusy):
                with host_config.host_config_lock(str(self.config)):
                    pass
            shutil.rmtree(self.config.parent)
            self.config.parent.mkdir(parents=True)
            self.config.write_text(ORIGINAL)
            with self.assertRaises(host_config.HostConfigBusy):
                with host_config.host_config_lock(str(self.config)):
                    pass

    def test_batch_does_not_lock_servers_the_user_cannot_modify(self):
        other = Path(host_config.host_config_path('A'))
        other.parent.mkdir(parents=True)
        other.write_text(ORIGINAL)
        client = self.client()
        with client.session_transaction() as session:
            session.update(role='user', permissions={'nagios_A': True})
        data = {'batch_servers[]': ['A', 'Bhome'], 'batch_hostnames[]': ['new-a', 'new-b'],
                'batch_addresses[]': ['10.0.0.2', '10.0.0.3']}
        with host_config.host_config_lock(str(self.config)):
            self.assertEqual(client.post('/host-manager/batch-add', data=data).status_code, 302)
        self.assertIn('new-a', other.read_text())
        self.assertEqual(self.config.read_text(), ORIGINAL)

    def test_lock_is_shared_across_processes(self):
        context = multiprocessing.get_context('fork')
        receive, send = context.Pipe(duplex=False)

        def acquire():
            try:
                with host_config.host_config_lock(str(self.config)):
                    send.send('acquired')
            except host_config.HostConfigBusy:
                send.send('busy')
            finally:
                send.close()

        with host_config.host_config_lock(str(self.config)):
            worker = context.Process(target=acquire)
            worker.start()
            try:
                self.assertTrue(receive.poll(5))
                self.assertEqual(receive.recv(), 'busy')
                worker.join(5)
                self.assertEqual(worker.exitcode, 0)
            finally:
                if worker.is_alive():
                    worker.terminate()
                    worker.join(5)
                receive.close()

    def test_lock_order_is_sorted_and_duplicate_paths_are_deduplicated(self):
        order = []
        original_lock = host_config.host_config_lock

        def recording(path):
            order.append(path)
            return original_lock(path)

        @host_config.guard_host_config_writes
        def request():
            host_config.lock_host_configs([str(self.config), str(self.root / 'a.cfg'), str(self.config)])
            return 'done'

        with patch.object(host_config, 'host_config_lock', side_effect=recording):
            self.assertEqual(request(), 'done')
        self.assertEqual(order, sorted({str(self.config), str(self.root / 'a.cfg')}))

    def test_exception_releases_lock(self):
        with patch.object(self.api, '_verify_bhome_config', side_effect=RuntimeError('isolated failure')):
            with self.assertRaises(RuntimeError):
                self.ip()
        with host_config.host_config_lock(str(self.config)):
            pass

    def test_lock_creation_failure_returns_explicit_error(self):
        with patch.object(host_config.os, 'open', side_effect=PermissionError('denied')):
            response = self.ip()
        self.assertEqual(response.status_code, 500)
        self.assertIn('lock', response.json['error'])
        self.assertEqual(self.config.read_text(), ORIGINAL)
        self.commands.assert_not_called()

    def test_unauthorized_requests_do_not_acquire_config_locks(self):
        with patch.object(host_config.os, 'open') as acquire:
            response = self.app.test_client().post('/api/hosts/change-ip', json={'server': 'Bhome'})
            self.assertEqual(response.status_code, 401)
            response = self.app.test_client().post('/host-manager/edit', data={'server': 'Bhome'})
            self.assertEqual(response.status_code, 401)
            acquire.assert_not_called()

    def test_existing_writer_success_responses_remain_compatible(self):
        requests = [
            ('POST', '/api/hosts/add', {'json': {'server': 'Bhome', 'host_name': 'new-host', 'address': '10.0.0.2'}}, 201),
            ('POST', '/api/hosts/batch-add', {'json': {'server': 'Bhome', 'hosts': [{'host_name': 'new-host', 'address': '10.0.0.2'}]}}, 201),
            ('POST', '/api/hosts/rename', {'json': {'server': 'Bhome', 'old_host_name': 'customer-a', 'host_name': 'renamed'}}, 200),
            ('DELETE', '/api/hosts/delete', {'json': {'server': 'Bhome', 'host_name': 'customer-a'}}, 200),
            ('POST', '/host-manager/add', {'data': {'server': 'Bhome', 'host_name': 'new-host', 'address': '10.0.0.2'}}, 302),
            ('POST', '/host-manager/delete', {'data': {'server': 'Bhome', 'host_name': 'customer-a'}}, 302),
            ('POST', '/servers/edit-config/Bhome', {'data': {'content': ORIGINAL + '\n'}}, 302),
        ]
        with patch.dict('sys.modules', {'services.stage_service': self.dependencies['services.stage_service']}):
            for method, url, kwargs, expected in requests:
                with self.subTest(endpoint=url):
                    self.config.write_text(ORIGINAL)
                    response = self.client().open(url, method=method, headers={'X-API-Key': 'test-key'}, **kwargs)
                    self.assertEqual(response.status_code, expected, response.get_data(as_text=True))
                    with host_config.host_config_lock(str(self.config)):
                        pass

    def test_global_restore_copies_under_lock_and_cleans_private_directory(self):
        archive = self.settings / 'backups' / 'saved.tar.gz'
        restored = ORIGINAL.replace('Original', 'Restored')
        with tarfile.open(archive, 'w:gz') as tar:
            data = restored.encode()
            entry = tarfile.TarInfo('Bhome/localhost.cfg')
            entry.size = len(data)
            tar.addfile(entry, io.BytesIO(data))
        sources = []

        def command(args, **kwargs):
            if args[0] == 'cp':
                sources.append(Path(args[1]))
                self.assertEqual(Path(args[2]), self.config)
                with self.assertRaises(host_config.HostConfigBusy):
                    with host_config.host_config_lock(str(self.config)):
                        pass
                shutil.copyfile(args[1], args[2])
            return subprocess.CompletedProcess(args, 0, '', '')

        self.commands.side_effect = command
        response = self.client().post('/global-settings/restore', json={'backup_name': 'saved'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])
        self.assertEqual(self.config.read_text(), restored)
        self.assertEqual(len(sources), 1)
        self.assertFalse(sources[0].exists())

    def test_server_build_retains_lock_until_background_work_finishes(self):
        entered, release = threading.Event(), threading.Event()
        workers = []
        Thread = threading.Thread

        def thread(*args, **kwargs):
            worker = Thread(*args, **kwargs)
            workers.append(worker)
            return worker

        def command(args, **kwargs):
            if args[0].endswith('/create-nagios/build.sh'):
                entered.set()
                self.assertTrue(release.wait(5))
            return subprocess.CompletedProcess(args, 0, '', '')

        self.commands.side_effect = command
        self.addCleanup(release.set)
        with patch.object(self.modules['servers'].threading, 'Thread', side_effect=thread):
            response = self.client().post('/servers/add', data={'name': 'Bhome', 'port': '8080'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(entered.wait(5))
        try:
            self.assertEqual(self.ip().status_code, 409)
        finally:
            release.set()
            for worker in workers:
                worker.join(5)
                self.assertFalse(worker.is_alive())
        with host_config.host_config_lock(str(self.config)):
            pass

    def test_server_thread_start_failure_releases_reserved_lock(self):
        with patch.object(self.modules['servers'].threading, 'Thread') as thread:
            thread.return_value.start.side_effect = RuntimeError('cannot start isolated worker')
            response = self.client().post('/servers/add', data={'name': 'Bhome', 'port': '8080'})
        self.assertEqual(response.status_code, 500)
        with host_config.host_config_lock(str(self.config)):
            pass

    def test_same_owner_replacement_does_not_require_chown(self):
        before = self.metadata()
        with patch.object(host_config.os, 'fchown', side_effect=AssertionError('unnecessary chown')):
            self.assertEqual(self.ip().status_code, 200)
        self.assertEqual(self.metadata(), before)
        self.assert_no_staged_files()

    @unittest.skipUnless(os.geteuid() == 0, 'real foreign ownership requires root; portable mocked tests cover non-root failure')
    def test_real_foreign_uid_gid_and_mode_preserved_in_success_backup_and_rollback(self):
        os.chown(self.config, 65534, 65534)
        self.config.chmod(0o640)
        before = self.metadata()
        self.assertEqual(self.ip().status_code, 200)
        self.assertEqual(self.metadata(), before)
        for backup in self.backups.glob('localhost_before_ip_change_*.cfg'):
            self.assertEqual(self.metadata(backup), before)
        self.config.write_text(ORIGINAL)
        self.commands.return_value = subprocess.CompletedProcess([], 1, '', 'invalid')
        self.assertEqual(self.ip().status_code, 422)
        self.assertEqual(self.config.read_text(), ORIGINAL)
        self.assertEqual(self.metadata(), before)
        self.assert_no_staged_files()

    def test_mocked_foreign_ownership_applied_and_verified_before_publish(self):
        before = self.config.stat()
        desired = types.SimpleNamespace(st_uid=before.st_uid + 1, st_gid=before.st_gid + 1, st_mode=before.st_mode)
        owner = [before.st_uid, before.st_gid]
        fstat = os.fstat

        def reported(fd):
            actual = fstat(fd)
            return types.SimpleNamespace(st_uid=owner[0], st_gid=owner[1], st_mode=actual.st_mode)

        def chown(fd, uid, gid):
            owner[:] = [uid, gid]

        with patch.object(host_config.os, 'fstat', side_effect=reported), \
             patch.object(host_config.os, 'fchown', side_effect=chown) as change:
            host_config.atomic_replace_host_config(str(self.config), 'changed', desired)
        self.assertEqual(change.call_args.args[1:], (desired.st_uid, desired.st_gid))
        self.assertEqual(self.config.read_text(), 'changed')
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)
        self.assert_no_staged_files()

    def test_ownership_denial_aborts_without_replacing_original(self):
        before = self.config.stat()
        desired = types.SimpleNamespace(st_uid=before.st_uid + 1, st_gid=before.st_gid, st_mode=before.st_mode)
        with patch.object(host_config.os, 'fchown', side_effect=PermissionError('not permitted')), \
             patch.object(host_config.os, 'replace') as publish:
            with self.assertRaisesRegex(OSError, 'Cannot preserve'):
                host_config.atomic_replace_host_config(str(self.config), 'changed', desired)
            publish.assert_not_called()
        self.assertEqual(self.config.read_text(), ORIGINAL)
        self.assertEqual(self.config.stat().st_ino, before.st_ino)
        self.assertEqual(self.metadata(), (before.st_uid, before.st_gid, 0o640))
        self.assert_no_staged_files()

    def test_metadata_verification_rejects_silent_chown_failure(self):
        before = self.config.stat()
        desired = types.SimpleNamespace(st_uid=before.st_uid + 1, st_gid=before.st_gid, st_mode=before.st_mode)
        with patch.object(host_config.os, 'fchown'), patch.object(host_config.os, 'replace') as publish:
            with self.assertRaisesRegex(OSError, 'verification failed'):
                host_config.atomic_replace_host_config(str(self.config), 'changed', desired)
            publish.assert_not_called()
        self.assertEqual(self.config.read_text(), ORIGINAL)
        self.assert_no_staged_files()

    def test_mode_denial_returns_error_and_cleans_staging(self):
        with patch.object(host_config.os, 'fchmod', side_effect=PermissionError('denied')):
            response = self.ip()
        self.assertEqual(response.status_code, 500)
        self.assertIn('Cannot preserve', response.json['error'])
        self.assertEqual(self.config.read_text(), ORIGINAL)
        self.commands.assert_not_called()
        self.assert_no_staged_files()
        with host_config.host_config_lock(str(self.config)):
            pass

    def test_staging_sync_failure_does_not_replace_original(self):
        with patch.object(host_config.os, 'fsync', side_effect=OSError('isolated disk failure')):
            response = self.ip()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.config.read_text(), ORIGINAL)
        self.assert_no_staged_files()

    def test_rollback_failure_is_explicit_and_retains_backup(self):
        self.commands.return_value = subprocess.CompletedProcess([], 1, '', 'invalid')
        publish = self.api.atomic_replace_host_config
        calls = []

        def restore_failure(path, content, metadata):
            calls.append(path)
            if len(calls) == 3:
                raise PermissionError('restoration denied')
            return publish(path, content, metadata)

        with patch.object(self.api, 'atomic_replace_host_config', side_effect=restore_failure):
            response = self.ip()
        self.assertEqual(response.status_code, 500)
        self.assertIn('restoration failed', response.json['error'])
        self.assertEqual(Path(response.json['backup']).read_text(), ORIGINAL)
        self.assertIn('10.11.0.1', self.config.read_text())
        self.assert_no_staged_files()
        with host_config.host_config_lock(str(self.config)):
            pass

    def test_symbolic_link_target_is_rejected(self):
        link = self.config.parent / 'alias.cfg'
        link.symlink_to(self.config)
        with self.assertRaisesRegex(OSError, 'symbolic-link'):
            host_config.atomic_replace_host_config(str(link), 'changed', self.config.stat())
        self.assertEqual(self.config.read_text(), ORIGINAL)
        self.assertTrue(link.is_symlink())
        self.assert_no_staged_files()


if __name__ == '__main__':
    unittest.main()
