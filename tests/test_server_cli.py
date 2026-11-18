"""Headless server CLI: no PostgreSQL instance or business data."""
import contextlib
import io
import socket
import threading
import time
import unittest
from unittest.mock import patch

import server as server_cli
from core.network.protocol import DEFAULT_PORT
from core.network.server import port_in_use
from tests.test_server_stability import Pool


class _Profile:
    database_name = 'isolated_test'
    config_path = '/nonexistent/config.json'

    def __init__(self, name='main'):
        self.name = name

    def get_value(self, _key):
        return ''


class _Manager:
    profiles_path = '/nonexistent'

    def __init__(self, names):
        self.available_profiles = {name: _Profile(name) for name in names}
        self.selected_profile = None

    def load_profile(self, name):
        self.selected_profile = self.available_profiles.get(name)
        return self.selected_profile is not None


def _quiet(function, *args):
    with contextlib.redirect_stdout(io.StringIO()) as output:
        result = function(*args)
    return result, output.getvalue()


class ProfileSelectionTests(unittest.TestCase):
    def load(self, names, requested=None):
        with patch('core.profiles.ProfileManager', return_value=_Manager(names)):
            return server_cli._load_profile(requested)

    def test_only_profile_is_selected_without_a_name(self):
        _manager, profile = self.load(['shop'])
        self.assertEqual(profile.name, 'shop')

    def test_several_profiles_need_an_explicit_choice(self):
        with self.assertRaises(SystemExit) as raised:
            self.load(['shop', 'depot'])
        self.assertIn('depot, shop', str(raised.exception))
        _manager, profile = self.load(['shop', 'depot'], 'depot')
        self.assertEqual(profile.name, 'depot')

    def test_unknown_or_missing_profile_is_reported(self):
        with self.assertRaises(SystemExit) as raised:
            self.load(['shop'], 'typo')
        self.assertIn("'typo' not found", str(raised.exception))
        with self.assertRaises(SystemExit) as raised:
            self.load([])
        self.assertIn('No profile found', str(raised.exception))


class ArgumentTests(unittest.TestCase):
    def test_serve_defaults_to_the_shared_port(self):
        args = server_cli.build_parser().parse_args(['serve'])
        self.assertEqual(args.port, DEFAULT_PORT)
        self.assertIsNone(args.profile)

    def test_serve_refuses_a_port_another_process_answers_on(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            self.assertTrue(port_in_use(port))
            args = server_cli.build_parser().parse_args(['serve', '--port', str(port)])
            with patch('core.profiles.ProfileManager', return_value=_Manager(['shop'])):
                with self.assertRaises(SystemExit) as raised:
                    server_cli.cmd_serve(args)
            self.assertIn('already in use', str(raised.exception))
        self.assertFalse(port_in_use(port))


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        manager = _Manager(['shop'])
        manager.load_profile('shop')
        self.supervisor = server_cli._Supervisor(manager, manager.selected_profile, 0)
        self.supervisor.database = type('HostDatabase', (), {
            'profile_manager': manager, 'registered_classes': {},
        })()
        self.patches = [
            patch('core.network.server.load_server_config', return_value={}),
            patch('core.network.server.ThreadedConnectionPool', side_effect=lambda *a, **k: Pool()),
            patch.object(server_cli, '_SUPERVISE_SECONDS', 0.05),
        ]
        for active in self.patches:
            active.start()
        self.thread = None

    def tearDown(self):
        self.supervisor.stop_requested.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
        if self.supervisor.server is not None:
            self.supervisor.server.stop()
        for active in self.patches:
            active.stop()

    def start(self):
        started, _output = _quiet(self.supervisor._start_listener)
        self.assertTrue(started)
        # Port 0 asks the OS for a free port; a restart must reuse the one
        # clients already know.
        self.supervisor.port = self.supervisor.server.port
        self.thread = threading.Thread(
            target=lambda: _quiet(self.supervisor._supervise), daemon=True)
        self.thread.start()

    def wait_until(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(0.02)
        return False

    def test_status_reports_a_running_server(self):
        self.start()
        args = server_cli.build_parser().parse_args(
            ['status', '--port', str(self.supervisor.server.port)])
        code, output = _quiet(server_cli.cmd_status, args)
        self.assertEqual(code, server_cli.EXIT_OK)
        self.assertIn('Running', output)

    def test_status_reports_nothing_listening(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            free_port = probe.getsockname()[1]
        args = server_cli.build_parser().parse_args(['status', '--port', str(free_port)])
        code, output = _quiet(server_cli.cmd_status, args)
        self.assertEqual(code, server_cli.EXIT_ERROR)
        self.assertIn('Not reachable', output)

    def test_dead_serving_thread_is_restarted_on_the_same_port(self):
        self.start()
        server = self.supervisor.server
        port = server.port
        sessions = server.sessions
        token = sessions.create({'id': 1})
        first_thread = server._thread

        # Ends serve_forever without going through stop(), as a crashed
        # accept loop would.
        server._httpd.shutdown()

        self.assertTrue(self.wait_until(
            lambda: server.is_running and server._thread is not first_thread))
        self.assertEqual(server.port, port)
        self.assertEqual(server.snapshot()['state'], 'running')
        self.assertIs(server.sessions, sessions)
        self.assertIsNotNone(sessions.get(token))

    def test_unreachable_database_rebuilds_the_pool(self):
        self.start()
        server = self.supervisor.server
        first_pool = server._pool
        with patch.object(server_cli, '_DATABASE_PROBE_SECONDS', 0.05), patch.object(
            server, 'health_status', return_value={'database_accessible': False},
        ):
            self.assertTrue(self.wait_until(lambda: server._pool is not first_pool))
        self.assertTrue(server.is_running)

    def test_stop_request_ends_supervision(self):
        self.start()
        self.supervisor.stop_requested.set()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())


if __name__ == '__main__':
    unittest.main()
