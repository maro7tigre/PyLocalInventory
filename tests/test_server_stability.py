"""Isolated HTTP server tests: no PostgreSQL instance or business data."""
import base64
import concurrent.futures
import hashlib
import http.client
import io
import json
import logging
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from logging.handlers import RotatingFileHandler
from unittest.mock import patch
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QPushButton
from PySide6.QtCore import QTimer
from psycopg2.pool import PoolError
from core.attachments import DEFAULT_MAX_BYTES
from core.network.client import RemoteDatabase
from core.network.server import DatabaseServer
from ui.dialogs.network_dialog import NetworkDialog


class Cursor:
    def __init__(self):
        self.closed = False

    def execute(self, statement, params=None):
        self.statement = statement

    def fetchone(self) -> tuple:
        return (1,)

    def close(self):
        self.closed = True


class Connection:
    closed = False

    def __init__(self):
        self.cursor_instance = Cursor()
        self.rollbacks = 0

    def cursor(self):
        self.cursor_instance = Cursor()
        return self.cursor_instance

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class Pool:
    def __init__(self):
        self.lock = threading.Lock()
        self.available = []
        self.outstanding = set()
        self.high_water = 0
        self.closed = False
        self.created = []

    def getconn(self):
        with self.lock:
            if len(self.outstanding) >= 10:
                raise RuntimeError('pool exhausted')
            if self.available:
                connection = self.available.pop()
            else:
                connection = Connection()
                self.created.append(connection)
            self.outstanding.add(connection)
            self.high_water = max(self.high_water, len(self.outstanding))
            return connection

    def putconn(self, connection, close=False):
        with self.lock:
            self.outstanding.remove(connection)
            if close:
                connection.close()
            else:
                self.available.append(connection)

    def closeall(self):
        with self.lock:
            self.closed = True


class HostServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        profile = type('Profile', (), {
            'database_name': 'isolated_test',
            'get_value': lambda self, _key: '',
        })()
        manager = type('Manager', (), {'selected_profile': profile})()
        database = type('HostDatabase', (), {'profile_manager': manager, 'registered_classes': {}})()
        self.server = DatabaseServer(database, port=0, request_timeout=0.2,
                                     max_request_bytes=2 * 1024 * 1024,
                                     max_request_threads=12)
        self.pool = Pool()

    def tearDown(self):
        self.server.stop()

    @unittest.skipUnless(os.name == 'nt', 'Windows process memory API only')
    def test_windows_ram_diagnostics_matches_independent_working_set(self):
        from core.memory_utils import process_memory_mb
        from scripts.host_stability_soak import resident_memory_mb
        measured = process_memory_mb(refresh=True)
        independent = resident_memory_mb()
        self.assertIsNotNone(independent)
        assert independent is not None
        self.assertGreater(measured, 1)
        self.assertLess(abs(measured - independent), 20)

    def start_server(self):
        with patch('core.network.server.load_server_config', return_value={}), patch(
            'core.network.server.ThreadedConnectionPool', return_value=self.pool
        ):
            self.server.start()
        self.assertTrue(self.server.is_running)

    def request(self, path, data=None, token=None, method=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        req = urllib.request.Request(
            f'http://127.0.0.1:{self.server.port}{path}',
            data=data, headers=headers, method=method or ('POST' if data is not None else 'GET'),
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers)

    def login(self):
        user = {'id': 1, 'username': 'test', 'permissions': {}, 'role_id': 1, 'is_superadmin': True}
        with patch('core.network.server.UserManager.verify_login', return_value=user), patch(
            'core.database.Database.get_sale_catalog', return_value={'products': [], 'services': []}
        ):
            status, body, _headers = self.request('/login', b'{"username":"test","password":"placeholder"}')
        self.assertEqual(status, 200)
        return json.loads(body)['token']

    def test_start_stop_listener_and_health(self):
        self.start_server()
        self.assertEqual(self.server.health_status(), {
            'gui_process_alive': True, 'server_thread_alive': True,
            'listener_available': True,
        })
        status, body, _ = self.request('/health')
        self.assertEqual(status, 401)
        self.assertNotIn(b'database_accessible', body)
        token = self.login()
        status, body, _ = self.request('/health', token=token)
        self.assertEqual(status, 200)
        self.assertTrue(all(json.loads(body).values()))
        self.server.stop()
        self.assertFalse(self.server.is_running)
        self.assertTrue(self.pool.closed)

    def test_pool_connections_use_configured_statement_timeout(self):
        self.server.database_statement_timeout_ms = 1234
        with patch('core.network.server.load_server_config', return_value={}), patch(
            'core.network.server.ThreadedConnectionPool', return_value=self.pool
        ) as create_pool:
            self.server.start()

        self.assertEqual(
            create_pool.call_args.kwargs['options'],
            '-c statement_timeout=1234',
        )
        self.assertTrue(self.server.is_running)

    def test_unexpected_thread_exit_is_reported_and_status_updates(self):
        with patch('core.network.server._BoundedHTTPServer.serve_forever',
                   side_effect=RuntimeError('listener exited')), patch(
                   'core.network.server.load_server_config', return_value={}), patch(
                   'core.network.server.ThreadedConnectionPool', return_value=self.pool
                   ), self.assertLogs('core.network.server', level='ERROR') as captured:
            self.server.start()
            thread = self.server._thread
            self.assertIsNotNone(thread)
            if thread is not None:
                thread.join(2)
        self.assertFalse(self.server.is_running)
        self.assertFalse(self.server.health_status()['listener_available'])
        self.assertIn('server_thread_failed', '\n'.join(captured.output))
        self.assertIn('RuntimeError', '\n'.join(captured.output))

        indicator = NetworkDialog.__new__(NetworkDialog)
        QDialog.__init__(indicator)
        indicator.main_window = type('MainWindow', (), {'network_server': self.server})()
        indicator.status_label = QLabel()
        indicator.toggle_btn = QPushButton()
        indicator.ip_label = QLabel()
        indicator.port_input = QLineEdit()
        indicator._refresh_hosting_status()
        self.assertEqual(indicator.status_label.text(), 'Status: Server unavailable')
        self.assertEqual(indicator.toggle_btn.text(), 'Start Hosting')
        timer = QTimer(indicator)
        timer.start(1000)
        indicator._hosting_status_timer = timer
        indicator.done(0)
        self.assertFalse(timer.isActive())
        indicator.close()

    def test_bind_failure_closes_pool_and_does_not_claim_running(self):
        occupied = socket.socket()
        occupied.bind(('0.0.0.0', 0))
        occupied.listen()
        self.server.port = occupied.getsockname()[1]
        try:
            with patch('core.network.server.load_server_config', return_value={}), patch(
                'core.network.server.ThreadedConnectionPool', return_value=self.pool
            ), self.assertRaises(OSError):
                self.server.start()
        finally:
            occupied.close()
        self.assertTrue(self.pool.closed)
        self.assertFalse(self.server.is_running)

    def test_thread_start_failure_closes_pool_and_listener(self):
        with patch('core.network.server.load_server_config', return_value={}), patch(
            'core.network.server.ThreadedConnectionPool', return_value=self.pool
        ), patch('core.network.server.threading.Thread.start', side_effect=RuntimeError('cannot start')):
            with self.assertRaises(RuntimeError):
                self.server.start()
        self.assertTrue(self.pool.closed)
        self.assertFalse(self.server.is_running)

    def test_incomplete_and_oversized_body_release_request_threads(self):
        self.start_server()
        connection = http.client.HTTPConnection('127.0.0.1', self.server.port, timeout=3)
        connection.putrequest('POST', '/login')
        connection.putheader('Content-Length', '20')
        connection.endheaders()
        connection.send(b'{')
        response = connection.getresponse()
        self.assertEqual(response.status, 408)
        response.read()
        connection.close()

        connection = http.client.HTTPConnection('127.0.0.1', self.server.port, timeout=3)
        connection.putrequest('POST', '/login')
        connection.putheader('Content-Length', str(self.server.max_request_bytes + 1))
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 413)
        response.read()
        connection.close()
        self.assertEqual(self.pool.high_water, 0)
        httpd = self.server._httpd
        self.assertIsNotNone(httpd)
        if httpd is None:
            return
        deadline = time.monotonic() + 2
        while httpd.active_requests and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(httpd.active_requests, 0)

    def test_incomplete_headers_release_thread_and_capacity_is_bounded(self):
        self.server.max_request_threads = 1
        self.server.request_timeout = 1.0
        self.start_server()
        httpd = self.server._httpd
        assert httpd is not None
        incomplete = socket.create_connection(('127.0.0.1', self.server.port))
        try:
            incomplete.sendall(b'POST /login HTTP/1.1\r\nHost: localhost\r\n')
            deadline = time.monotonic() + 1
            while not httpd.active_requests and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(httpd.active_requests, 1)
            with self.assertLogs('core.network.server', level='WARNING') as captured:
                try:
                    self.request('/health')
                except (OSError, urllib.error.URLError, http.client.RemoteDisconnected):
                    pass
            self.assertIn('http_capacity_exhausted', '\n'.join(captured.output))
            deadline = time.monotonic() + 2
            while httpd.active_requests and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(httpd.active_requests, 0)
            self.assertEqual(self.request('/health')[0], 401)
        finally:
            incomplete.close()

    def test_trickled_headers_hit_absolute_deadline(self):
        self.start_server()
        sock = socket.create_connection(('127.0.0.1', self.server.port))
        try:
            sock.sendall(b'POST /login HTTP/1.1\r\n')
            # Each fragment arrives before the per-socket timeout. The
            # whole-header deadline must still release the request slot.
            for _ in range(5):
                time.sleep(0.06)
                try:
                    sock.sendall(b'X-Continued: a\r\n')
                except OSError:
                    break
            httpd = self.server._httpd
            assert httpd is not None
            deadline = time.monotonic() + 2
            while httpd.active_requests and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(httpd.active_requests, 0)
            self.assertEqual(self.pool.high_water, 0)
        finally:
            sock.close()

    def test_body_budget_bounds_concurrent_large_uploads(self):
        self.server.request_timeout = 1.0
        self.server.max_inflight_body_bytes = self.server.max_request_bytes
        self.start_server()
        first = socket.create_connection(('127.0.0.1', self.server.port))
        try:
            first.sendall(
                f'POST /login HTTP/1.1\r\nHost: localhost\r\nContent-Length: '
                f'{self.server.max_request_bytes}\r\n\r\n{{'.encode()
            )
            deadline = time.monotonic() + 2
            while not self.server._body_inflight and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(self.server._body_inflight, self.server.max_request_bytes)
            status, response, _ = self.request('/login', b'{}')
            self.assertEqual(status, 503)
            self.assertNotIn(b'database', response)
        finally:
            first.close()
        deadline = time.monotonic() + 2
        while self.server._body_inflight and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.server._body_inflight, 0)

    def test_database_probe_reports_failure_without_public_details(self):
        self.start_server()
        token = self.login()
        with patch.object(self.pool, 'getconn', side_effect=RuntimeError('offline')):
            status, data, _ = self.request('/health', token=token)
        self.assertEqual(status, 503)
        self.assertFalse(json.loads(data)['database_accessible'])
        self.assertNotIn(b'offline', data)
        self.assertEqual(self.request('/health')[0], 401)
        self.assertEqual(self.server._checked_out, 0)

    def test_pool_exhaustion_is_classified_and_recovery_keeps_service_running(self):
        self.start_server()
        token = self.login()
        with patch.object(self.pool, 'getconn', side_effect=PoolError('pool exhausted')):
            status, data, _ = self.request(
                '/rpc', b'{"method":"get_items","args":["Products"]}', token
            )
            self.assertEqual(status, 503)
            self.assertNotIn(b'pool exhausted', data)
            self.assertEqual(self.server._checked_out, 0)
        with patch('core.database.Database.get_items', return_value=[]):
            self.assertEqual(self.request(
                '/rpc', b'{"method":"get_items","args":["Products"]}', token
            )[0], 200)
        self.assertTrue(self.server.is_running)

    def test_failed_rollback_discards_connection_and_recovers(self):
        self.start_server()
        token = self.login()
        bad_connection = self.pool.available[-1]
        with patch.object(bad_connection, 'rollback', side_effect=OSError('broken')):
            self.assertEqual(self.request('/health', token=token)[0], 200)
        self.assertTrue(bad_connection.closed)
        self.assertEqual(self.request('/health', token=token)[0], 200)
        self.assertEqual(len(self.pool.outstanding), 0)

    def test_stop_defers_pool_close_until_in_flight_request_finishes(self):
        self.start_server()
        token = self.login()
        entered = threading.Event()
        release = threading.Event()

        def fetch(_db, _section, **_kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return []

        with patch('core.database.Database.get_items', fetch):
            task = threading.Thread(target=lambda: self.request(
                '/rpc', b'{"method":"get_items","args":["Products"]}', token
            ))
            task.start()
            try:
                self.assertTrue(entered.wait(2))
                self.server.stop()
                self.assertFalse(self.pool.closed)
            finally:
                release.set()
                task.join(3)
        deadline = time.monotonic() + 2
        while not self.pool.closed and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.pool.closed)
        self.assertFalse(self.pool.outstanding)

    def test_login_rpc_and_concurrent_pool_cleanup(self):
        self.start_server()
        token = self.login()
        def fetch(_db, section, **_kwargs):
            time.sleep(0.02)
            return [{'ID': 1}]
        with patch('core.database.Database.get_items', fetch):
            def call(_):
                status, body, _headers = self.request(
                    '/rpc', json.dumps({'method': 'get_items', 'args': ['Products']}).encode(), token
                )
                return status, json.loads(body)
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                results = list(executor.map(call, range(20)))
        self.assertTrue(all(status == 200 and result['result'] == [{'ID': 1}]
                            for status, result in results))
        self.assertEqual(len(self.pool.outstanding), 0)
        self.assertEqual(self.server._checked_out, 0)
        self.assertGreater(self.pool.high_water, 1)
        self.assertTrue(all(connection.rollbacks for connection in self.pool.created))

    def test_existing_remote_database_client_login_and_rpc(self):
        self.start_server()
        user = {'id': 1, 'username': 'test', 'permissions': {},
                'role_id': 1, 'is_superadmin': True}
        client = RemoteDatabase(None, '127.0.0.1', self.server.port, 'test', 'placeholder')
        try:
            with patch('core.network.server.UserManager.verify_login', return_value=user), patch(
                'core.database.Database.get_sale_catalog', return_value={}
            ):
                self.assertTrue(client.connect())
            with patch('core.database.Database.get_items', return_value=[{'ID': 7}]):
                self.assertEqual(client.get_items('Products'), [{'ID': 7}])
        finally:
            client.close()

    def test_repeated_authentication_releases_database_connections(self):
        self.start_server()
        for _ in range(30):
            self.assertTrue(self.login())
        self.assertEqual(self.server._checked_out, 0)
        self.assertEqual(len(self.pool.outstanding), 0)
        self.assertTrue(all(connection.cursor_instance.closed for connection in self.pool.created))
        self.assertTrue(all(connection.rollbacks for connection in self.pool.created))

    def test_client_disconnect_during_rpc_does_not_strand_checkout(self):
        self.start_server()
        token = self.login()
        entered = threading.Event()
        release = threading.Event()

        def fetch(_database, _section, **_kwargs):
            entered.set()
            if not release.wait(3):
                raise TimeoutError('test worker not released')
            return []

        with patch('core.database.Database.get_items', fetch):
            client = socket.create_connection(('127.0.0.1', self.server.port))
            body = b'{"method":"get_items","args":["Products"]}'
            client.sendall(
                f'POST /rpc HTTP/1.1\r\nHost: localhost\r\n'
                f'Authorization: Bearer {token}\r\nContent-Length: {len(body)}\r\n\r\n'.encode()
                + body
            )
            try:
                self.assertTrue(entered.wait(2))
            finally:
                client.close()
                release.set()
        deadline = time.monotonic() + 2
        while self.pool.outstanding and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(len(self.pool.outstanding), 0)
        self.assertEqual(self.server._checked_out, 0)
        self.assertEqual(self.request('/health', token=token)[0], 200)

    def test_host_restart_requires_new_login_and_accepts_client_again(self):
        self.start_server()
        old_token = self.login()
        port = self.server.port
        self.server.stop()
        self.assertTrue(self.pool.closed)
        restarted_pool = Pool()
        restarted_server = DatabaseServer(
            self.server.database, port=port, request_timeout=0.2,
            max_request_bytes=2 * 1024 * 1024,
        )
        self.server = restarted_server
        with patch('core.network.server.load_server_config', return_value={}), patch(
            'core.network.server.ThreadedConnectionPool', return_value=restarted_pool
        ):
            self.server.start()
        self.assertTrue(self.server.is_running)
        self.assertEqual(self.request('/health', token=old_token)[0], 401)
        fresh_token = self.login()
        with patch('core.database.Database.get_items', return_value=[{'ID': 3}]):
            status, response, _ = self.request(
                '/rpc', b'{"method":"get_items","args":["Products"]}', fresh_token
            )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response)['result'], [{'ID': 3}])
        self.assertEqual(restarted_pool.outstanding, set())

    def test_request_logs_do_not_contain_credentials_or_rpc_payload(self):
        self.start_server()
        user = {'id': 1, 'username': 'private-user', 'permissions': {},
                'role_id': 1, 'is_superadmin': True}
        with patch('core.network.server.UserManager.verify_login', return_value=user), patch(
            'core.database.Database.get_sale_catalog', return_value={}
        ), self.assertLogs('core.network.server', level='INFO') as captured:
            status, response, _ = self.request(
                '/login', b'{"username":"private-user","password":"secret-password"}'
            )
            self.assertEqual(status, 200)
            token = json.loads(response)['token']
            with patch('core.database.Database.get_items', return_value=[]):
                self.assertEqual(self.request('/rpc', json.dumps({
                    'method': 'get_items', 'args': ['Products'],
                    'kwargs': {'search_text': 'private-customer'},
                }).encode(), token)[0], 200)
        logs = '\n'.join(captured.output)
        for secret in (b'secret-password', b'private-user', b'private-customer',
                       token.encode()):
            self.assertNotIn(secret.decode(), logs)

    def test_request_diagnostics_rotate_in_isolated_log_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            log_file = Path(directory) / 'host.log'
            handler = RotatingFileHandler(log_file, maxBytes=300, backupCount=2,
                                          encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s %(threadName)s %(message)s'))
            server_logger = logging.getLogger('core.network.server')
            server_logger.addHandler(handler)
            try:
                self.start_server()
                token = self.login()
                with patch('core.database.Database.get_items', return_value=[]):
                    for _ in range(5):
                        self.assertEqual(self.request(
                            '/rpc', b'{"method":"get_items","args":["Products"]}', token
                        )[0], 200)
                handler.flush()
                self.assertTrue(log_file.exists())
                self.assertTrue((Path(directory) / 'host.log.1').exists())
            finally:
                server_logger.removeHandler(handler)
                handler.close()

    def test_attachment_payload_and_streamed_backup(self):
        self.assertGreater(self.server.max_request_bytes, 1024 * 1024 * 4 // 3)
        self.assertGreaterEqual(DatabaseServer(None).max_request_bytes,
                                (DEFAULT_MAX_BYTES * 4 + 2) // 3 + 1024 * 1024)
        self.start_server()
        token = self.login()
        content = base64.b64encode(b'%PDF-' + b'x' * 1024 * 1024).decode('ascii')
        body = json.dumps({'method': 'upload_attachment',
                           'args': ['sale', 1, 'test.pdf', content]}).encode()
        with patch('core.database.Database.upload_attachment', return_value={'id': 4}):
            status, response, _headers = self.request('/rpc', body, token)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response)['result'], {'id': 4})

        def fake_archive(work_dir):
            path = f'{work_dir}/archive.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('database/test.backup', b'PGDMP-test')
            return path
        with patch.object(self.server, '_create_client_backup_archive', side_effect=fake_archive):
            status, archive, headers = self.request('/backup', token=token)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'application/zip')
        with zipfile.ZipFile(io.BytesIO(archive)) as zipfile_obj:
            self.assertEqual(zipfile_obj.read('database/test.backup'), b'PGDMP-test')

    def test_maximum_supported_attachment_round_trip_uses_only_temporary_storage(self):
        class AttachmentConnection(Connection):
            relative_path = None

            def commit(self):
                self.commits = getattr(self, 'commits', 0) + 1

            def cursor(self):
                owner = self
                class AttachmentCursor(Cursor):
                    def execute(self, statement, params=None):
                        if statement.startswith('INSERT INTO attachments'):
                            if params is None:
                                raise ValueError('Attachment test requires INSERT parameters')
                            owner.relative_path = params[-1]
                        self.statement = statement

                    def fetchone(self):
                        if self.statement.startswith('INSERT INTO attachments'):
                            return (1,)
                        return ('sale', 1, owner.relative_path)
                self.cursor_instance = AttachmentCursor()
                return self.cursor_instance

        self.pool.available.append(AttachmentConnection())
        configured = DatabaseServer(None)
        self.server.max_request_bytes = configured.max_request_bytes
        self.server.max_inflight_body_bytes = configured.max_inflight_body_bytes
        self.server.request_timeout = 10
        self.start_server()
        token = self.login()
        payload = b'%PDF-' + b'x' * (DEFAULT_MAX_BYTES - 5)
        original_digest = hashlib.sha256(payload).digest()
        encoded = base64.b64encode(payload).decode('ascii')
        body = json.dumps({'method': 'upload_attachment',
                           'args': ['sale', 1, 'test.pdf', encoded]}).encode()
        self.assertLess(len(body), self.server.max_request_bytes)

        with tempfile.TemporaryDirectory() as temp, patch(
            'core.attachments.storage_root', return_value=Path(temp)
        ), patch('core.attachments.AttachmentService._ready'), patch(
            'core.attachments.AttachmentService._snapshot', return_value={}
        ), patch('core.attachments.AttachmentService._record_change'):
            status, response, _ = self.request('/rpc', body, token)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(response)['result'], 1)
            status, response, _ = self.request('/rpc',
                b'{"method":"download_attachment","args":[1]}', token)
            self.assertEqual(status, 200)
            self.assertEqual(hashlib.sha256(base64.b64decode(json.loads(response)['result'])).digest(),
                             original_digest)
            self.assertEqual(len(list(Path(temp).rglob('*.pdf'))), 1)
        self.assertFalse(self.pool.outstanding)


if __name__ == '__main__':
    unittest.main()
