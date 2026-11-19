"""Host lifecycle diagnostics: no PostgreSQL instance or business data."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import logging
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QPushButton

from core.build_info import APP_BUILD_ID
from core.network.server import DatabaseServer, _safe_stack
from tests.test_server_stability import Pool
from ui.dialogs.network_dialog import NetworkDialog


def make_server(port=0, **kwargs):
    profile = type('Profile', (), {
        'database_name': 'isolated_test',
        'get_value': lambda self, _key: '',
    })()
    manager = type('Manager', (), {'selected_profile': profile})()
    database = type('HostDatabase', (), {
        'profile_manager': manager,
        'registered_classes': {},
    })()
    return DatabaseServer(database, port=port, **kwargs)


class HostLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.server = make_server(request_timeout=0.2)
        self.pool = Pool()

    def tearDown(self):
        self.server.stop()

    def start_server(self):
        with patch('core.network.server.load_server_config', return_value={}), patch(
            'core.network.server.ThreadedConnectionPool', return_value=self.pool
        ):
            self.server.start()

    def wait_for_state(self, state, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.server.snapshot()['state'] == state:
                return self.server.snapshot()
            time.sleep(0.02)
        self.fail(f'Host did not reach state {state!r}; '
                  f'last snapshot: {self.server.snapshot()}')

    def test_initial_state_and_noop_stop_are_truthful(self):
        snapshot = self.server.snapshot()
        self.assertEqual(snapshot['state'], 'not_started')
        self.assertEqual(snapshot['reason'], 'initial')
        self.assertFalse(snapshot['thread_alive'])
        self.assertFalse(snapshot['listener_available'])
        self.assertEqual(snapshot['sessions'], 0)
        self.assertTrue(snapshot['build_id'])
        self.assertNotEqual(APP_BUILD_ID, 'sales-table-total-ht-ttc-2026-08-05-v2')

        self.server.stop()
        self.assertEqual(self.server.snapshot()['state'], 'not_started')

    def test_stop_logs_sanitized_caller_and_default_reason(self):
        self.start_server()
        with self.assertLogs('core.network.server', level='INFO') as captured:
            self.server.stop()
        logs = '\n'.join(captured.output)
        self.assertIn('host_stop_requested reason=unspecified', logs)
        self.assertIn('caller=', logs)
        self.assertIn('test_host_lifecycle_diagnostics.py:', logs)
        self.assertIn('server.py:', logs)
        self.assertNotIn('def test_stop_logs', logs)
        self.assertNotIn('raise ', logs)

    def test_application_startup_marker_is_not_filtered_by_root_level(self):
        import main as entrypoint
        self.assertTrue(entrypoint.logger.isEnabledFor(logging.INFO))

    def test_heartbeat_records_running_host_health(self):
        self.server.heartbeat_seconds = 0.2
        with self.assertLogs('core.network.server', level='INFO') as captured:
            self.start_server()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if 'host_heartbeat' in '\n'.join(captured.output):
                    break
                time.sleep(0.05)
        logs = '\n'.join(captured.output)
        self.assertIn('host_heartbeat', logs)
        self.assertIn('listener=True', logs)
        self.assertIn(f'build_id={APP_BUILD_ID}', logs)

    def test_start_and_stop_log_each_transition(self):
        with self.assertLogs('core.network.server', level='INFO') as captured:
            self.start_server()
        self.assertEqual(self.server.snapshot()['state'], 'running')
        self.assertTrue(self.server.snapshot()['thread_alive'])
        self.assertTrue(self.server.snapshot()['listener_available'])

        with self.assertLogs('core.network.server', level='INFO') as stopped_logs:
            self.server.stop(reason='operator_stop')
        snapshot = self.server.snapshot()
        self.assertEqual(snapshot['state'], 'stopped')
        self.assertEqual(snapshot['reason'], 'stop_completed')
        self.assertEqual(snapshot['previous_state'], 'stopping')
        self.assertEqual(snapshot['previous_reason'], 'operator_stop')
        self.assertFalse(snapshot['thread_alive'])
        self.assertFalse(snapshot['listener_available'])
        self.assertTrue(self.pool.closed)
        self.assertIsNone(self.server._monitor_thread)

        logs = '\n'.join(captured.output + stopped_logs.output)
        self.assertIn('host_state from=not_started to=starting reason=start_requested', logs)
        self.assertIn('host_state from=starting to=running reason=start_succeeded', logs)
        self.assertIn('host_state from=running to=stopping reason=operator_stop', logs)
        self.assertIn('host_state from=stopping to=stopped reason=stop_completed', logs)

    def test_repeated_stop_is_safe_and_preserves_final_state(self):
        self.start_server()
        self.server.stop()
        self.server.stop()
        snapshot = self.server.snapshot()
        self.assertEqual(snapshot['state'], 'stopped')
        self.assertTrue(self.pool.closed)

    def test_unexpected_serving_thread_exit_is_recorded_without_message(self):
        secret = 'customer-name-and-password-placeholder'
        with patch('core.network.server._BoundedHTTPServer.serve_forever',
                   side_effect=RuntimeError(secret)), patch(
                   'core.network.server.load_server_config', return_value={}), patch(
                   'core.network.server.ThreadedConnectionPool', return_value=self.pool
                   ), self.assertLogs('core.network.server', level='ERROR') as captured:
            self.server.start()
            thread = self.server._thread
            if thread is not None:
                thread.join(2)

        snapshot = self.server.snapshot()
        self.assertEqual(snapshot['state'], 'thread_exited')
        self.assertEqual(snapshot['reason'], 'serving_thread_failed')
        self.assertIn(snapshot['previous_state'], ('starting', 'running'))
        self.assertEqual(snapshot['last_error_category'], 'RuntimeError')
        self.assertFalse(self.server.is_running)

        logs = '\n'.join(captured.output)
        self.assertIn('server_thread_failed', logs)
        self.assertIn('host_state', logs)
        self.assertIn('to=thread_exited', logs)
        self.assertNotIn(secret, logs)
        self.assertNotIn('password', logs.lower())

    def test_cleanup_after_thread_death_preserves_the_failure_history(self):
        secret = 'thread-failure-message'
        with patch('core.network.server._BoundedHTTPServer.serve_forever',
                   side_effect=RuntimeError(secret)), patch(
                   'core.network.server.load_server_config', return_value={}), patch(
                   'core.network.server.ThreadedConnectionPool', return_value=self.pool
                   ):
            self.server.start()
            thread = self.server._thread
            if thread is not None:
                thread.join(2)

        self.server.stop(reason='stale_server_cleanup')
        snapshot = self.server.snapshot()
        self.assertEqual(snapshot['state'], 'stopped')
        self.assertEqual(snapshot['previous_state'], 'stopping')
        self.assertEqual(snapshot['last_unhealthy_state'], 'thread_exited')
        self.assertEqual(snapshot['last_unhealthy_reason'], 'serving_thread_failed')
        self.assertIsNotNone(snapshot['last_unhealthy_at'])
        self.assertEqual(snapshot['last_error_category'], 'RuntimeError')
        self.assertIsNotNone(snapshot['last_error_at'])
        self.assertFalse(self.server.is_running)

    def test_monitor_detects_serving_thread_that_vanished(self):
        release = threading.Event()

        def fake_serve(_server):
            release.wait(3)

        with patch.object(DatabaseServer, '_serve', fake_serve), patch(
            'core.network.server.load_server_config', return_value={}
        ), patch('core.network.server.ThreadedConnectionPool', return_value=self.pool):
            self.server.start()
            self.assertEqual(self.server.snapshot()['state'], 'running')
            thread = self.server._thread
            self.assertIsNotNone(thread)
            release.set()
            if thread is not None:
                thread.join(2)

        snapshot = self.wait_for_state('thread_exited')
        self.assertEqual(snapshot['reason'], 'serving_thread_not_alive')

    def test_safe_stack_has_no_source_lines_or_exception_message(self):
        def fail():
            raise RuntimeError('private-customer-value')

        try:
            fail()
        except RuntimeError as error:
            rendered = _safe_stack(error)
        self.assertIn('test_host_lifecycle_diagnostics.py:', rendered)
        self.assertIn(':fail', rendered)
        self.assertNotIn('private-customer-value', rendered)
        self.assertNotIn('raise RuntimeError', rendered)

    def test_start_failure_records_sanitized_state(self):
        secret = 'password=super-secret-value'
        with patch('core.network.server.load_server_config', return_value={}), patch(
            'core.network.server.ThreadedConnectionPool',
            side_effect=RuntimeError(secret)
        ), self.assertLogs('core.network.server', level='ERROR') as captured:
            with self.assertRaises(RuntimeError):
                self.server.start()

        snapshot = self.server.snapshot()
        self.assertEqual(snapshot['state'], 'failed')
        self.assertEqual(snapshot['reason'], 'start_failed')
        self.assertEqual(snapshot['last_error_category'], 'RuntimeError')
        self.assertFalse(snapshot['thread_alive'])
        self.assertFalse(snapshot['listener_available'])
        self.assertIsNone(self.server._monitor_thread)

        logs = '\n'.join(captured.output)
        self.assertIn('server_start_failed', logs)
        self.assertIn('to=failed', logs)
        self.assertNotIn(secret, logs)
        self.assertNotIn('super-secret-value', logs)

    def test_stop_cleanup_continues_after_listener_shutdown_failure(self):
        self.start_server()
        httpd = self.server._httpd
        self.assertIsNotNone(httpd)
        if httpd is None:
            return
        with patch.object(httpd, 'shutdown', side_effect=OSError('listener stuck')), \
                patch.object(httpd, 'server_close', wraps=httpd.server_close) as close_listener, \
                self.assertLogs('core.network.server', level='ERROR') as captured:
            with patch.object(self.pool, 'closeall', wraps=self.pool.closeall) as close_pool:
                self.server.stop(reason='operator_stop')

        close_listener.assert_called_once()
        close_pool.assert_called_once()
        self.assertTrue(self.pool.closed)
        snapshot = self.server.snapshot()
        self.assertEqual(snapshot['state'], 'failed')
        self.assertEqual(snapshot['reason'], 'stop_cleanup_failed')
        self.assertEqual(snapshot['last_error_category'], 'OSError')
        self.assertFalse(self.server.is_running)
        self.assertIn('host_stop_step_failed step=listener_shutdown', '\n'.join(captured.output))


class HostStatusUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_dialog(self, server, last_snapshot=None):
        indicator = NetworkDialog.__new__(NetworkDialog)
        QDialog.__init__(indicator)
        indicator.main_window = type('MainWindow', (), {
            'network_server': server,
            'host_last_snapshot': last_snapshot,
        })()
        indicator.status_label = QLabel()
        indicator.status_detail_label = QLabel()
        indicator.toggle_btn = QPushButton()
        indicator.ip_label = QLabel()
        indicator.port_input = QLineEdit()
        return indicator

    def test_not_hosting_explains_application_start(self):
        indicator = self.make_dialog(None)
        try:
            indicator._refresh_hosting_status()
            self.assertEqual(indicator.status_label.text(), 'Status: Not hosting')
            self.assertEqual(indicator.toggle_btn.text(), 'Start Hosting')
            detail = indicator.status_detail_label.text()
            self.assertIn('has not been started since this application opened', detail)
            self.assertIn('does not resume automatically', detail)
            self.assertIn('Build:', detail)
            self.assertIn('PID:', detail)
        finally:
            indicator.close()

    def test_not_hosting_shows_last_recorded_state(self):
        last = {
            'state': 'stopped',
            'state_since': '2026-10-20T09:00:00+01:00',
            'reason': 'operator_stop',
            'last_error_category': None,
        }
        indicator = self.make_dialog(None, last_snapshot=last)
        try:
            indicator._refresh_hosting_status()
            self.assertEqual(indicator.status_label.text(), 'Status: Not hosting')
            detail = indicator.status_detail_label.text()
            self.assertIn('Last Host state: stopped', detail)
            self.assertIn('operator_stop', detail)
            self.assertIn('does not resume automatically', detail)
        finally:
            indicator.close()

    def test_not_hosting_shows_unhealthy_history_after_cleanup(self):
        last = {
            'state': 'stopped',
            'state_since': '2026-10-20T09:05:00+01:00',
            'reason': 'stop_completed',
            'previous_state': 'stopping',
            'previous_reason': 'stale_server_cleanup',
            'last_unhealthy_state': 'thread_exited',
            'last_unhealthy_reason': 'serving_thread_failed',
            'last_unhealthy_at': '2026-10-20T09:04:50+01:00',
            'last_error_category': 'RuntimeError',
            'last_error_at': '2026-10-20T09:04:50+01:00',
        }
        indicator = self.make_dialog(None, last_snapshot=last)
        try:
            indicator._refresh_hosting_status()
            self.assertEqual(indicator.status_label.text(), 'Status: Not hosting')
            detail = indicator.status_detail_label.text()
            self.assertIn('Last Host state: stopped', detail)
            self.assertIn('Last unhealthy state: thread_exited', detail)
            self.assertIn('serving_thread_failed', detail)
            self.assertIn('Last error: RuntimeError', detail)
        finally:
            indicator.close()

    def test_live_status_shows_counters_and_dead_object_is_explained(self):
        server = make_server(request_timeout=0.2)
        pool = Pool()
        indicator = self.make_dialog(server)
        try:
            with patch('core.network.server.load_server_config', return_value={}), patch(
                'core.network.server.ThreadedConnectionPool', return_value=pool
            ):
                server.start()
            with self.assertLogs('ui.dialogs.network_dialog', level='INFO') as captured:
                indicator._refresh_hosting_status()
                self.assertEqual(indicator.status_label.text(), 'Status: Hosting')
                detail = indicator.status_detail_label.text()
                self.assertIn('Serving thread alive', detail)
                self.assertIn('Active requests:', detail)
                self.assertIn('Sessions:', detail)
                self.assertIn('Build:', detail)
                self.assertIn('PID:', detail)

                server.stop()
                indicator._refresh_hosting_status()
                self.assertEqual(indicator.status_label.text(), 'Status: Server unavailable')
                self.assertIn('Host state: stopped', indicator.status_detail_label.text())
                self.assertIn('not both available', indicator.status_detail_label.text())

            ui_logs = '\n'.join(captured.output)
            self.assertIn('host_ui_status previous=none status=Status: Hosting', ui_logs)
            self.assertIn(
                'previous=Status: Hosting status=Status: Server unavailable', ui_logs
            )
            self.assertIn(f'build_id={APP_BUILD_ID}', ui_logs)
        finally:
            server.stop()
            indicator.close()


if __name__ == '__main__':
    unittest.main()
