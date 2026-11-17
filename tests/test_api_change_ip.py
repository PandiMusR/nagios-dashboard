import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from flask import Flask
from services import host_config


def load_api():
    config = types.ModuleType('services.config')
    config.GLOBAL_CONFIG_PATH = '/unused/global_config.json'
    ldap = types.ModuleType('services.ldap_service')
    ldap.log_activity = Mock()
    kuma = types.ModuleType('services.uptime_kuma')
    kuma.add_host_to_uptime_kuma = Mock()
    spec = importlib.util.spec_from_file_location(
        'api_change_ip_under_test', Path(__file__).resolve().parents[1] / 'blueprints/api.py',
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        'services.config': config,
        'services.ldap_service': ldap,
        'services.uptime_kuma': kuma,
    }):
        spec.loader.exec_module(module)
    return module


api = load_api()
ORIGINAL = '''define host{
    host_name               customer-a
    address                 10.10.0.1 ; keep this comment
    alias                   Site 10.10.0.1
}
define host{
    host_name               customer-b
    address                 10.10.0.11
    parents                 customer-a
}
define service{
    host_name               customer-a
    check_command           check_ping!10.10.0.1
}
'''


class ChangeIPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / 'localhost.cfg'
        self.config.write_text(ORIGINAL)
        self.config.chmod(0o640)
        self.keyfile = Path(self.tmp.name) / 'global_config.json'
        self.keyfile.write_text(json.dumps({'api_key': 'test-key'}))
        for name, value in (
            ('BHOME_CONFIG_PATH', str(self.config)),
            ('GLOBAL_CONFIG_PATH', str(self.keyfile)),
        ):
            patcher = patch.object(api, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        lock_patch = patch.object(host_config, 'LOCK_DIR', str(Path(self.tmp.name) / 'locks'))
        lock_patch.start()
        self.addCleanup(lock_patch.stop)
        commands_patch = patch.object(api.subprocess, 'run')
        self.commands = commands_patch.start()
        self.addCleanup(commands_patch.stop)
        self.commands.return_value = subprocess.CompletedProcess([], 0, 'OK', '')
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.register_blueprint(api.api_bp)
        self.client = app.test_client()

    def send(self, **overrides):
        data = {
            'server': 'Bhome',
            'changes': [{'old_ip': '10.10.0.1', 'new_ip': '10.11.0.1'}],
        }
        data.update(overrides)
        return self.client.post('/api/hosts/change-ip', json=data,
                                headers={'X-API-Key': 'test-key'})

    def assert_untouched(self):
        self.assertEqual(self.config.read_text(), ORIGINAL)
        self.commands.assert_not_called()
        self.assertFalse((self.config.parent / 'backups').exists())

    def test_auth_required(self):
        response = self.client.post('/api/hosts/change-ip', json={'server': 'Bhome'})
        self.assertEqual(response.status_code, 401)
        self.assert_untouched()

    def test_malformed_or_non_object_json(self):
        for body in ('{bad', '[]', 'null', '42'):
            with self.subTest(body=body):
                response = self.client.post('/api/hosts/change-ip', data=body,
                    content_type='application/json', headers={'X-API-Key': 'test-key'})
                self.assertEqual(response.status_code, 400)
        self.assert_untouched()

    def test_only_bhome(self):
        for server in ('BhomeTest', '../Bhome', '', None, 123):
            self.assertEqual(self.send(server=server).status_code, 400)
        self.assert_untouched()

    def test_invalid_flags(self):
        for field in ('dry_run', 'allow_existing'):
            self.assertEqual(self.send(**{field: 'false'}).status_code, 400)
        self.assert_untouched()

    def test_invalid_changes(self):
        for changes in ([], {}, [None], [{}],
                        [{'old_ip': 12, 'new_ip': '10.1.1.1'}],
                        [{'old_ip': '10.10.0.1', 'new_ip': '10.10.0.1'}]):
            with self.subTest(changes=changes):
                self.assertEqual(self.send(changes=changes).status_code, 400)
        self.assert_untouched()

    def test_invalid_ipv4(self):
        for address in ('999.1.1.1', '10.1.1.1/24', 'host.local', '::1',
                        '010.1.1.1', '10.1.1.1\naddress 10.2.2.2'):
            self.assertEqual(self.send(changes=[{
                'old_ip': '10.10.0.1', 'new_ip': address,
            }]).status_code, 400)
        self.assert_untouched()

    def test_duplicate_mapping(self):
        for changes in (
            [{'old_ip': '10.10.0.1', 'new_ip': '10.11.0.1'},
             {'old_ip': '10.10.0.1', 'new_ip': '10.11.0.2'}],
            [{'old_ip': '10.10.0.1', 'new_ip': '10.11.0.1'},
             {'old_ip': '10.10.0.11', 'new_ip': '10.11.0.1'}],
        ):
            self.assertEqual(self.send(changes=changes).status_code, 400)
        self.assert_untouched()

    def test_dry_run_exact_match(self):
        response = self.send(dry_run=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['total_hosts'], 1)
        self.assertEqual(response.json['changes'][0]['host_names'], ['customer-a'])
        self.assertFalse(response.json['restarted'])
        self.assert_untouched()

    def test_single_pair_format(self):
        response = self.client.post('/api/hosts/change-ip', json={
            'server': 'Bhome', 'old_ip': '10.10.0.1', 'new_ip': '10.11.0.1',
            'dry_run': True,
        }, headers={'X-API-Key': 'test-key'})
        self.assertEqual(response.status_code, 200)
        self.assert_untouched()

    def test_missing_ip_rejects_entire_batch(self):
        response = self.send(changes=[
            {'old_ip': '10.10.0.1', 'new_ip': '10.11.0.1'},
            {'old_ip': '10.99.0.1', 'new_ip': '10.11.0.2'},
        ])
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json['missing'], ['10.99.0.1'])
        self.assert_untouched()

    def test_conflict(self):
        response = self.send(changes=[{'old_ip': '10.10.0.1', 'new_ip': '10.10.0.11'}])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['conflicts'][0]['host_names'], ['customer-b'])
        self.assert_untouched()

    def test_allow_existing(self):
        response = self.send(dry_run=True, allow_existing=True, changes=[
            {'old_ip': '10.10.0.1', 'new_ip': '10.10.0.11'},
        ])
        self.assertEqual(response.status_code, 200)
        self.assert_untouched()

    def test_swap_does_not_cascade(self):
        response = self.send(changes=[
            {'old_ip': '10.10.0.1', 'new_ip': '10.10.0.11'},
            {'old_ip': '10.10.0.11', 'new_ip': '10.10.0.1'},
        ])
        self.assertEqual(response.status_code, 200)
        content = self.config.read_text()
        self.assertIn('address                 10.10.0.11 ; keep this comment', content)
        self.assertIn('address                 10.10.0.1\n', content)
        self.assertEqual(self.commands.call_count, 2)

    def test_write_backup_validate_restart_once(self):
        response = self.send()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['restarted'])
        self.assertEqual(Path(response.json['backup']).read_text(), ORIGINAL)
        self.assertEqual(self.config.read_text(), ORIGINAL.replace(
            'address                 10.10.0.1 ;', 'address                 10.11.0.1 ;'))
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)
        self.assertFalse(Path(str(self.config) + '.tmp').exists())
        self.assertEqual(self.commands.call_count, 2)
        self.assertEqual(self.commands.call_args_list[0].args[0], [
            'docker', 'exec', 'Bhome', '/opt/nagios/bin/nagios', '-v', '/opt/nagios/etc/nagios.cfg'])
        self.assertEqual(self.commands.call_args_list[1].args[0], ['docker', 'restart', 'Bhome'])

    def test_failed_validation_restores_config(self):
        self.commands.return_value = subprocess.CompletedProcess([], 1, '', 'invalid config')
        response = self.send()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.config.read_text(), ORIGINAL)
        self.commands.assert_called_once()

    def test_validation_timeout_restores_config(self):
        self.commands.side_effect = subprocess.TimeoutExpired('nagios', 120)
        self.assertEqual(self.send().status_code, 422)
        self.assertEqual(self.config.read_text(), ORIGINAL)
        self.commands.assert_called_once()

    def test_restart_failure_reports_written_config_and_backup(self):
        self.commands.side_effect = [subprocess.CompletedProcess([], 0, 'OK', ''),
                                    subprocess.CalledProcessError(1, 'docker')]
        response = self.send()
        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.json['restarted'])
        self.assertIn('Config written but restart failed', response.json['error'])
        self.assertEqual(Path(response.json['backup']).read_text(), ORIGINAL)
        self.assertNotEqual(self.config.read_text(), ORIGINAL)

    def test_busy_lock_returns_conflict_without_writing(self):
        with host_config.host_config_lock(str(self.config)):
            self.assertEqual(self.send().status_code, 409)
            self.assert_untouched()

    def test_file_write_failure_keeps_original(self):
        with patch.object(api.os, 'replace', side_effect=OSError('write failed')):
            self.assertEqual(self.send().status_code, 500)
        self.assertEqual(self.config.read_text(), ORIGINAL)
        self.commands.assert_not_called()
        self.assertFalse(Path(str(self.config) + '.tmp').exists())

    def test_audit_rejects_unexpected_changes(self):
        self.assertIsNotNone(api._audit_address_edit(ORIGINAL, ORIGINAL.replace(
            'customer-a', 'renamed'), {'10.10.0.1': '10.11.0.1'}))


if __name__ == '__main__':
    unittest.main()
