"""
LAN server exposing a Database instance over HTTP+JSON, with per-user,
per-section role permissions enforced on every request.

Design notes:
- The server opens its OWN sqlite connection to the same .db file the host's
  GUI already has open (check_same_thread=False, since ThreadingHTTPServer
  dispatches each request on its own thread). This avoids ever sharing a
  cursor object between the GUI thread and network worker threads - the host
  behaves like two independent processes on the same SQLite file, which is
  exactly the WAL + busy_timeout setup Database.connect() already sets up for
  ("safe on network shares").
- Most UI code talks to Database through add_item/update_item/get_items/
  delete_item (which already take a `section` argument, used directly for the
  permission check). A fair amount of older UI code bypasses that and runs
  raw SQL via `database.cursor.execute(...)` / `database.conn.commit()`
  instead - rather than refactoring every one of those call sites, this
  server also proxies `cursor.execute` / `conn.commit` / `conn.rollback`
  generically, parsing the target table out of the SQL to resolve a section.
"""
import json
import secrets
import socket
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.database import Database
from core.user_manager import UserManager, SECTION_GROUP
from core.network.protocol import classify_sql, DEFAULT_PORT

# method name -> (kind, index into `args` holding the section name)
_SECTION_METHODS = {
    'add_item': ('write', 1),                  # add_item(data, section)
    'update_item': ('write', 2),                # update_item(item_id, data, section)
    'delete_item': ('delete', 1),               # delete_item(item_id, section)
    'get_items': ('read', 0),                   # get_items(section)
    'get_items_by_operation_id': ('read', 1),   # get_items_by_operation_id(operation_id, section)
}
_ALWAYS_ALLOWED = {'begin_transaction', 'commit_transaction', 'rollback_transaction'}
_ACTION_FOR_KIND = {'read': 'read', 'write': 'write', 'delete': 'delete'}


class _SessionStore:
    """In-memory token -> authenticated-user map. Lost on server restart, which
    is fine - clients just log in again."""

    def __init__(self):
        self._sessions = {}
        self._lock = threading.Lock()

    def create(self, user):
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[token] = user
        return token

    def get(self, token):
        with self._lock:
            return self._sessions.get(token)

    def drop(self, token):
        with self._lock:
            self._sessions.pop(token, None)


def _check_permission(user, method, args, kwargs):
    """Returns (allowed: bool, reason: str|None)."""
    if user['is_superadmin']:
        return True, None
    if method in _ALWAYS_ALLOWED or method in ('conn.commit', 'conn.rollback'):
        return True, None

    if method == 'cursor.execute':
        sql = args[0] if args else ''
        kind, table = classify_sql(sql)
        if kind == 'schema':
            return True, None
        section = SECTION_GROUP.get(table) if table else None
        if not section:
            return False, f"No permission mapping for table '{table}' - contact your admin"
        needed = _ACTION_FOR_KIND[kind]
        if not user['permissions'].get(section, {}).get(needed):
            return False, f"You don't have {needed} access to {section}"
        return True, None

    if method in _SECTION_METHODS:
        kind, idx = _SECTION_METHODS[method]
        section = args[idx] if len(args) > idx else kwargs.get('section')
        mapped = SECTION_GROUP.get(section, section)
        needed = _ACTION_FOR_KIND[kind]
        if not user['permissions'].get(mapped, {}).get(needed):
            return False, f"You don't have {needed} access to {mapped}"
        return True, None

    return False, f"Method '{method}' is not permitted over the network"


class DatabaseServer:
    """Hosts `database` on the LAN so other PyLocalInventory instances can
    connect as clients. `database` should already be connected (the host
    keeps using it normally in its own window) - this class never touches it
    directly, only its own secondary connection to the same file.
    """

    def __init__(self, database, port=DEFAULT_PORT):
        self.database = database
        self.port = port
        # Bound to _server_db once start() creates it - login/RPC run on worker
        # threads, so this must never touch the GUI thread's own connection.
        self.user_manager = None
        self.sessions = _SessionStore()
        self._server_db = None
        self._lock = threading.Lock()
        self._httpd = None
        self._thread = None

    @property
    def is_running(self):
        return self._httpd is not None

    def start(self):
        if self._httpd:
            return

        db_path = self.database.profile_manager.selected_profile.database_path
        server_db = Database(profile_manager=None)
        server_db.registered_classes = self.database.registered_classes
        server_db.conn = sqlite3.connect(db_path, check_same_thread=False)
        server_db.cursor = server_db.conn.cursor()
        server_db.cursor.execute("PRAGMA foreign_keys = ON")
        server_db.conn.execute("PRAGMA busy_timeout=5000")
        self._server_db = server_db
        self.user_manager = UserManager(server_db)

        self._httpd = ThreadingHTTPServer(('0.0.0.0', self.port), self._make_handler())
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        self._httpd = None
        self._thread = None
        if self._server_db and self._server_db.conn:
            self._server_db.conn.close()
        self._server_db = None

    @staticmethod
    def local_ip():
        """Best-effort LAN IP to show the super-admin so they can share it."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))  # no packet actually sent, just picks a route
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            try:
                return socket.gethostbyname(socket.gethostname())
            except Exception:
                return '127.0.0.1'

    def _dispatch(self, method, args, kwargs):
        server_db = self._server_db

        if method == 'cursor.execute':
            sql = args[0]
            params = args[1] if len(args) > 1 and args[1] else []
            cur = server_db.cursor
            cur.execute(sql, params)
            kind, _table = classify_sql(sql)
            if kind in ('write', 'delete'):
                server_db.conn.commit()
            result = {'lastrowid': cur.lastrowid, 'rowcount': cur.rowcount}
            if cur.description:
                result['rows'] = cur.fetchall()
                result['description'] = [d[0] for d in cur.description]
            return result

        if method == 'conn.commit':
            server_db.conn.commit()
            return None
        if method == 'conn.rollback':
            server_db.conn.rollback()
            return None

        if method in _SECTION_METHODS or method in _ALWAYS_ALLOWED:
            return getattr(server_db, method)(*args, **kwargs)

        raise ValueError(f"Method not allowed over network: {method}")

    def _make_handler(self):
        server_obj = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *log_args):
                pass  # keep the console output of the app clean

            def _send_json(self, status, payload):
                body = json.dumps(payload, default=str).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json(self):
                length = int(self.headers.get('Content-Length', 0) or 0)
                raw = self.rfile.read(length) if length else b''
                return json.loads(raw.decode('utf-8')) if raw else {}

            def do_POST(self):
                try:
                    if self.path == '/login':
                        return self._handle_login()
                    if self.path == '/rpc':
                        return self._handle_rpc()
                    self._send_json(404, {'error': 'not found'})
                except Exception as e:
                    self._send_json(500, {'error': str(e)})

            def _handle_login(self):
                body = self._read_json()
                user = server_obj.user_manager.verify_login(
                    body.get('username', ''), body.get('password', '')
                )
                if not user:
                    return self._send_json(401, {'error': 'Invalid username or password'})
                token = server_obj.sessions.create(user)
                self._send_json(200, {
                    'token': token,
                    'username': user['username'],
                    'is_superadmin': user['is_superadmin'],
                    'permissions': user['permissions'],
                })

            def _handle_rpc(self):
                auth_header = self.headers.get('Authorization') or ''
                token = auth_header[7:] if auth_header.startswith('Bearer ') else ''
                user = server_obj.sessions.get(token) if token else None
                if not user:
                    return self._send_json(401, {'error': 'Authentication required'})

                body = self._read_json()
                method = body.get('method', '')
                args = body.get('args', [])
                kwargs = body.get('kwargs', {})

                allowed, reason = _check_permission(user, method, args, kwargs)
                if not allowed:
                    return self._send_json(403, {'error': reason})

                with server_obj._lock:
                    try:
                        result = server_obj._dispatch(method, args, kwargs)
                    except Exception as e:
                        return self._send_json(500, {'error': str(e)})
                self._send_json(200, {'result': result})

        return Handler
