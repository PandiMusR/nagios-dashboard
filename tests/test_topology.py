import hashlib
from datetime import datetime
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask, jsonify
from flask_wtf.csrf import CSRFProtect, generate_csrf

from services import host_config, poller_db
from services.topology import Topology, TopologyError
from services.topology_write import ApplyError

with patch.dict(os.environ, {'LDAP_ADMIN_PASSWORD': 'synthetic-tests'}):
    from blueprints import topology as routes, users

SOURCE = (Path(__file__).parent / 'fixtures/topology/localhost.cfg').read_text()
MAIN = (Path(__file__).parent / 'fixtures/topology/nagios.cfg').read_text()


class GraphTests(unittest.TestCase):
    def test_single_host_and_empty_configuration(self):
        self.assertEqual(Topology('; empty\n').graph(), ([], [], []))
        nodes, edges, warnings = Topology('define host{\n host_name only\n}\n').graph()
        self.assertEqual((nodes[0]['id'], nodes[0]['level'], edges, warnings), ('only', 0, [], []))

    def test_hierarchy_has_multiple_parents_and_roots(self):
        nodes, edges, warnings = Topology(SOURCE).graph()
        self.assertEqual({n['id']: n['level'] for n in nodes}, {'AP1': 2, 'KELURAHAN': 1, 'POP001': 0, 'POP002': 0})
        self.assertIn({'parent': 'POP002', 'child': 'AP1'}, edges)
        self.assertEqual(warnings, [])

    def test_unknown_parent_is_reported_on_read(self):
        _, edges, warnings = Topology(SOURCE.replace('parents POP001 ;', 'parents OTHER ;')).graph()
        self.assertNotIn({'parent': 'OTHER', 'child': 'KELURAHAN'}, edges)
        self.assertEqual(warnings, ['Some parents are outside this localhost.cfg.'])

    def test_unsafe_object_definitions_are_refused(self):
        for source in ('define host {\n host_name missing-close',
                       'define host {\n address 192.0.2.1\n}\n',
                       'define host {\n host_name lone\n host_name duplicate\n}\n',
                       SOURCE + 'define host {\n host_name AP1\n}\n'):
            with self.subTest(source=source[-50:]), self.assertRaises(TopologyError):
                Topology(source)

    def test_add_remove_replace_and_preserve_unrelated_bytes(self):
        source = SOURCE.replace('\n', '\r\n')
        topology = Topology(source)
        self.assertEqual(topology.updated({'KELURAHAN': ['POP002']}),
                         source.replace('parents POP001 ;', 'parents POP002 ;'))
        self.assertEqual(topology.updated({'KELURAHAN': [], 'AP1': ['POP002']}),
                         source.replace('parents POP001 ;', ';').replace('parents KELURAHAN,POP002', 'parents POP002'))
        added = topology.updated({'POP002': ['POP001']})
        self.assertEqual(Topology(added).hosts['POP002'].parents, ['POP001'])
        self.assertEqual(added.replace('    parents POP001\r\n', ''), source)

    def test_removing_last_explicit_parent_masks_template_inheritance(self):
        source = SOURCE.replace('    parents POP001 ;', '    use generic-host\n    parents POP001 ;')
        self.assertEqual(Topology(source).updated({'KELURAHAN': []}),
                         source.replace('parents POP001 ;', 'parents null ;'))

    def test_rejects_self_cycle_duplicate_unknown_and_cross_server(self):
        for changes in ({'AP1': ['AP1']}, {'POP001': ['AP1']}, {'AP1': ['POP002', 'POP002']},
                        {'AP1': ['MISSING']}, {'other-server-host': ['POP002']}, {'AP1': ['bad\nname']}):
            with self.subTest(changes=changes), self.assertRaises(TopologyError):
                Topology(SOURCE).updated(changes)

    def test_no_op_keeps_order_and_formatting(self):
        self.assertEqual(Topology(SOURCE).updated({'AP1': ['POP002', 'KELURAHAN']}), SOURCE)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.cfg = root / 'fixture/etc/objects/localhost.cfg'
        self.cfg.parent.mkdir(parents=True)
        self.cfg.write_text(SOURCE)
        self.cfg.chmod(0o640)
        (self.cfg.parent.parent / 'nagios.cfg').write_text(MAIN)
        self.db = root / 'snapshot.db'
        with sqlite3.connect(self.db) as conn:
            conn.executescript(poller_db._SCHEMA)
            conn.executemany('INSERT INTO host_snapshot(container, hostname, status_code) VALUES (?,?,?)',
                             [('fixture', 'AP1', 8), ('fixture', 'POP001', 2), ('other', 'AP1', 4)])
            conn.execute('INSERT INTO container_health(container,last_success_at) VALUES (?,?)',
                         ('fixture', datetime.now().isoformat()))
        app = Flask(__name__)
        app.secret_key = 'synthetic-topology-test'
        app.config['TESTING'] = True
        app.before_request(routes.reject_unbounded_parent_request)
        CSRFProtect(app)
        app.register_blueprint(routes.topology_bp)
        app.register_blueprint(users.users_bp)

        @app.get('/test-token')
        def token():
            return jsonify(token=generate_csrf())

        self.client = app.test_client()
        self.revision = hashlib.sha256(SOURCE.encode()).hexdigest()
        self.patch(host_config, 'VOLUME_ROOT', str(root))
        self.patch(host_config, 'LOCK_DIR', str(root / 'locks'))
        self.patch(poller_db, 'DEFAULT_DB_PATH', str(self.db))
        self.patch(routes, 'get_nagios_servers', lambda: ['fixture','other'])
        self.audit = self.patch(routes, 'log_activity')
        self.env = patch.dict(os.environ, {'NAGIOS_TOPOLOGY_WRITABLE_SERVERS': 'fixture'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def patch(self, target, name, value=None):
        patcher = patch.object(target, name) if value is None else patch.object(target, name, value)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def login(self, role='admin', permissions=None):
        with self.client.session_transaction() as session:
            session.update(username='fixture-user', role=role, permissions=permissions or {})
        self.csrf = self.client.get('/test-token').json['token']

    def submit(self, changes=None, server='fixture', revision=None, csrf=True):
        return self.client.post(f'/api/topology/{server}/parents',
                                headers={'X-CSRFToken': self.csrf} if csrf else {},
                                json={'revision': revision or self.revision,
                                      'changes': changes if changes is not None else {'KELURAHAN': ['POP002']}})

    def test_guest_and_unpermitted_view(self):
        self.assertEqual(self.client.get('/topology/fixture').status_code, 302)
        self.assertEqual(self.client.get('/api/topology/fixture').status_code, 401)
        self.login('user')
        self.assertEqual(self.client.get('/api/topology/fixture').status_code, 403)
        self.assertEqual(self.client.get('/api/topology/fixture/status').status_code, 403)

    def test_read_only_scoped_snapshot_and_csrf(self):
        self.login('user', {'nagios_fixture': True, 'host_manager': True})
        graph = self.client.get('/api/topology/fixture')
        self.assertEqual(graph.status_code, 200)
        self.assertFalse(graph.json['can_edit'])
        self.assertEqual(graph.json['snapshot']['hosts'], {'AP1': 'UNREACHABLE','POP001': 'UP'})
        self.assertFalse(graph.json['snapshot']['stale'])
        self.assertEqual(self.client.get('/api/topology/other').status_code, 403)
        self.assertEqual(self.submit().status_code, 403)
        self.login()
        self.assertEqual(self.submit(csrf=False).status_code, 400)

    def test_missing_snapshot_is_unknown_and_no_database_is_created(self):
        self.db.unlink()
        self.login()
        response = self.client.get('/api/topology/fixture/status')
        self.assertEqual(response.json, {'hosts': {}, 'last_success': None, 'stale': True})
        self.assertFalse(self.db.exists())

    def test_operator_allowlist_and_traversal(self):
        self.login()
        self.assertEqual(self.submit(server='other').status_code, 403)
        self.assertEqual(self.submit(server='..').status_code, 404)
        self.assertEqual(self.submit(server='missing').status_code, 404)
        self.assertEqual(self.submit(changes={'host-from-other': ['POP002']}).status_code, 422)
        self.assertEqual(self.cfg.read_text(), SOURCE)

    def test_malformed_and_oversized_body(self):
        self.login()
        self.assertEqual(self.submit(changes={}).status_code, 400)
        for raw in ('{bad', '["bad"]', '{"revision":0,"revision":1}', ' ' * (routes.MAX_BODY + 1)):
            result = self.client.post('/api/topology/fixture/parents', data=raw, content_type='application/json',
                                      headers={'X-CSRFToken': self.csrf})
            self.assertEqual(result.status_code, 400)
        self.assertEqual(self.cfg.read_text(), SOURCE)

    def test_non_admin_cannot_mutate_privileged_accounts(self):
        self.login('user', {'nagios_fixture': True, 'users': True})
        for path in ('/users/add', '/users/edit/synthetic-admin', '/users/delete/synthetic-admin'):
            self.assertEqual(self.client.post(path, headers={'X-CSRFToken': self.csrf}).status_code, 403)

    def test_stale_revision_and_shared_lock_contention(self):
        self.login()
        self.assertEqual(self.submit(revision='0' * 64).status_code, 409)
        with host_config.host_config_lock(str(self.cfg)):
            self.assertEqual(self.submit().status_code, 409)
        self.assertEqual(self.cfg.read_text(), SOURCE)

    def test_no_op_does_not_contact_docker(self):
        self.login()
        with patch('services.topology_write.docker') as docker:
            self.assertEqual(self.submit({'KELURAHAN': ['POP001']}).json, {'success': True, 'changed': False})
            docker.assert_not_called()

    def fixture_docker(self, *args, **options):
        return self.cfg.read_text() if options.get('capture') else None

    def test_non_json_request_is_rejected_before_csrf_form_parsing(self):
        self.login()
        with patch('flask.Request._load_form_data', side_effect=AssertionError('unexpected form parse')):
            result = self.client.post('/api/topology/fixture/parents', data='test=value',
                                      content_type='application/x-www-form-urlencoded')
        self.assertEqual(result.status_code, 400)
        self.assertEqual(result.json['error'], 'Expected a JSON request.')

    def test_success_stages_before_publication_and_preserves_metadata(self):
        self.login()
        before = self.cfg.stat()

        def verify(*args, **kwargs):
            if kwargs.get('capture'):
                return self.cfg.read_text()
            self.assertEqual(self.cfg.read_text(), SOURCE)
            candidate = self.cfg.parent.parent / Path(args[-1]).parent.name / 'localhost.cfg'
            self.assertIn('parents POP002 ;', candidate.read_text())

        with patch('services.topology_write.target_container', return_value='fixture-id'), \
                patch('services.topology_write.docker', side_effect=verify), \
                patch('services.topology_write.restart_and_check') as restart:
            self.assertEqual(self.submit().json, {'success': True, 'changed': True})
        restart.assert_called_once()
        self.assertEqual(self.cfg.read_text(), SOURCE.replace('parents POP001 ;', 'parents POP002 ;'))
        self.assertEqual((self.cfg.stat().st_uid, self.cfg.stat().st_gid, self.cfg.stat().st_mode),
                         (before.st_uid, before.st_gid, before.st_mode))
        self.assertEqual(next((self.cfg.parent / 'backups').iterdir()).read_text(), SOURCE)
        self.audit.assert_called_once()

    def test_nagios_validation_failure_leaves_source_untouched(self):
        self.login()
        with patch('services.topology_write.target_container', return_value='fixture-id'), \
                patch('services.topology_write.docker', side_effect=subprocess.CalledProcessError(1, 'fixture')), \
                patch('services.topology_write.restart_and_check') as restart:
            result = self.submit()
        self.assertEqual(result.status_code, 503)
        restart.assert_not_called()
        self.assertEqual(self.cfg.read_text(), SOURCE)
        self.assertFalse(list(self.cfg.parent.parent.glob('.topology-*')))

    def test_restart_failure_rolls_back_and_rechecks_previous_config(self):
        self.login()
        with patch('services.topology_write.target_container', return_value='fixture-id'), \
                patch('services.topology_write.docker', side_effect=self.fixture_docker), \
                patch('services.topology_write.restart_and_check', side_effect=[ApplyError('fixture'), None]) as restart:
            result = self.submit()
        self.assertEqual(result.status_code, 503)
        self.assertIn('restored', result.json['error'])
        self.assertEqual(restart.call_count, 2)
        self.assertEqual(self.cfg.read_text(), SOURCE)

    def test_timeout_restores_source_without_launching_a_second_restart(self):
        self.login()
        with patch('services.topology_write.target_container', return_value='fixture-id'), \
                patch('services.topology_write.docker', side_effect=self.fixture_docker), \
                patch('services.topology_write.restart_and_check',
                      side_effect=subprocess.TimeoutExpired('fixture', 25)) as restart:
            result = self.submit()
        self.assertEqual(result.status_code, 503)
        self.assertIn('uncertain', result.json['error'])
        restart.assert_called_once()
        self.assertEqual(self.cfg.read_text(), SOURCE)

    def test_same_bytes_with_new_metadata_are_preserved_on_failed_apply(self):
        self.login()

        def fail_after_metadata_update(*args):
            self.cfg.chmod(0o600)
            raise ApplyError('fixture')

        with patch('services.topology_write.target_container', return_value='fixture-id'), \
                patch('services.topology_write.docker', side_effect=self.fixture_docker), \
                patch('services.topology_write.restart_and_check', side_effect=fail_after_metadata_update):
            result = self.submit()
        self.assertEqual(result.status_code, 503)
        self.assertIn('rollback could not be verified', result.json['error'])
        self.assertEqual(self.cfg.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.cfg.read_text(), SOURCE.replace('parents POP001 ;', 'parents POP002 ;'))

    def test_running_nagios_with_old_effective_parents_requires_rollback(self):
        self.login()

        def docker(*args, **options):
            return SOURCE if options.get('capture') else None

        with patch('services.topology_write.target_container', return_value='fixture-id'), \
                patch('services.topology_write.docker', side_effect=docker), \
                patch('services.topology_write.restart_and_check') as restart:
            result = self.submit()
        self.assertEqual(result.status_code, 503)
        self.assertIn('previous configuration was restored', result.json['error'])
        self.assertEqual(restart.call_count, 2)
        self.assertEqual(self.cfg.read_text(), SOURCE)
        self.audit.assert_not_called()

    def test_unsupported_nagios_includes_are_refused_before_verification(self):
        self.login()
        (self.cfg.parent.parent / 'nagios.cfg').write_text(MAIN + 'cfg_dir=/opt/nagios/etc/objects\n')
        with patch('services.topology_write.target_container', return_value='fixture-id'), \
                patch('services.topology_write.docker') as docker:
            result = self.submit()
        self.assertEqual(result.status_code, 503)
        self.assertEqual(self.cfg.read_text(), SOURCE)
        docker.assert_not_called()

    def test_concurrent_noncooperating_change_during_verification_survives(self):
        self.login()
        other = SOURCE + '\n# external writer\n'

        def change_during_verification(*args, **options):
            if options.get('capture'):
                return SOURCE
            self.cfg.write_text(other)

        with patch('services.topology_write.target_container', return_value='fixture-id'), \
                patch('services.topology_write.docker', side_effect=change_during_verification), \
                patch('services.topology_write.restart_and_check') as restart:
            self.assertEqual(self.submit().status_code, 409)
        restart.assert_not_called()
        self.assertEqual(self.cfg.read_text(), other)


if __name__ == '__main__':
    unittest.main()
