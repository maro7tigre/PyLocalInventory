"""
LAN server exposing a Database instance over HTTP+JSON, with per-user,
per-section role permissions enforced on every request.

Design notes:
- The server checks out its own connection from a psycopg2 ThreadedConnectionPool
  to the same Postgres schema the host's GUI already has open, one connection
  per in-flight request (ThreadingHTTPServer dispatches each request on its own
  thread). Each request gets a throwaway `Database` instance wrapping its
  checked-out connection/cursor, so concurrent requests never share connection
  state - Postgres's own MVCC (concurrent readers, row-level write locking)
  does the actual concurrency control instead of one global lock serializing
  every request like the old single-sqlite-connection design did.
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
import threading
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from psycopg2.pool import ThreadedConnectionPool

from core.database import Database
from core.pg_config import load_server_config
from core.user_manager import UserManager, SECTION_GROUP
from core.network.protocol import classify_sql, DEFAULT_PORT
from core.runtime_paths import user_data_root

# method name -> (kind, index into `args` holding the section name)
_SECTION_METHODS = {
    'add_item': ('write', 1),                  # add_item(data, section)
    'update_item': ('write', 2),                # update_item(item_id, data, section)
    'delete_item': ('delete', 1),               # delete_item(item_id, section)
    'get_items': ('read', 0),                   # get_items(section)
    'get_items_by_operation_id': ('read', 1),   # get_items_by_operation_id(operation_id, section)
}
_ATTACHMENT_METHODS = {
    'list_attachments': ('read', 0),
    'download_attachment': ('read', None),
    'get_attachment_thumbnail': ('read', None),
    'upload_attachment': ('write', 0),
    'update_attachment': ('write', None),
    'delete_attachment': ('delete', None),
}
_CLIENT_ACCOUNT_METHODS = {
    'get_client_account', 'get_client_sales', 'add_client_payment'
}
_REPORT_METHODS = {'get_reports', 'list_report_users', 'save_report', 'delete_report'}
_PRODUCT_READ_METHODS = {'get_product_stock_levels'}
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

    if method == 'save_sale_with_items':
        if not user['permissions'].get('Sales', {}).get('write'):
            return False, "You don't have write access to Sales"
        pending = args[4] if len(args) > 4 and isinstance(args[4], list) else []
        required = {
            "client": "Clients", "product": "Products", "service": "Services"
        }
        for entity in pending:
            section = required.get(str(entity.get("type") or "").casefold())
            if section and not user["permissions"].get(section, {}).get("write"):
                return False, f"You don't have write access to {section}"
        return True, None

    if method == 'save_import_with_items':
        if not user['permissions'].get('Imports', {}).get('write'):
            return False, "You don't have write access to Imports"
        items = args[1] if len(args) > 1 and isinstance(args[1], list) else []
        if items and not user['permissions'].get('Products', {}).get('write'):
            return False, "You don't have permission to create or update Products"
        return True, None

    if method in _REPORT_METHODS:
        if method in ('get_reports',):
            return True, None
        if method == 'list_report_users':
            return (
                (True, None) if user["is_superadmin"]
                else (False, "Only a Super Admin can list report users")
            )
        needed = 'delete' if method == 'delete_report' else 'write'
        if not user['permissions'].get('Reports', {}).get(needed):
            return False, f"You don't have {needed} access to Reports"
        return True, None

    if method in _PRODUCT_READ_METHODS:
        if not user['permissions'].get('Products', {}).get('read'):
            return False, "You don't have read access to Products"
        return True, None

    if method == 'cursor.execute':
        sql = args[0] if args else ''
        kind, table = classify_sql(sql)
        if kind == 'schema':
            return True, None
        section = SECTION_GROUP.get(table) if table else None
        if not section:
            return False, f"No permission mapping for table '{table}' - contact your admin"
        if section == "Reports" and kind == "read":
            return False, "Reports must be read through the ownership-filtered API"
        needed = _ACTION_FOR_KIND[kind]
        if not user['permissions'].get(section, {}).get(needed):
            return False, f"You don't have {needed} access to {section}"
        return True, None

    if method in _SECTION_METHODS:
        kind, idx = _SECTION_METHODS[method]
        section = args[idx] if len(args) > idx else kwargs.get('section')
        mapped = SECTION_GROUP.get(section, section)
        needed = _ACTION_FOR_KIND[kind]
        if method == "get_items" and mapped == "Reports":
            return True, None
        if not user['permissions'].get(mapped, {}).get(needed):
            return False, f"You don't have {needed} access to {mapped}"
        return True, None

    if method in _CLIENT_ACCOUNT_METHODS:
        if not user['permissions'].get('Clients', {}).get('read'):
            return False, "You don't have read access to Clients"
        if (method == 'add_client_payment'
                and not user['permissions'].get('Sales', {}).get('write')):
            return False, "You don't have write access to Sales"
        return True, None

    if method in _ATTACHMENT_METHODS:
        kind, index = _ATTACHMENT_METHODS[method]
        # Attachment id alone cannot reveal scope cheaply before dispatch; both
        # supported scopes are customer business data, so require access to both.
        if index is None:
            permitted = all(user['permissions'].get(section, {}).get(_ACTION_FOR_KIND[kind])
                            for section in ('Clients', 'Sales'))
        else:
            entity = args[index] if len(args) > index else ''
            section = 'Clients' if entity == 'client' else 'Sales' if entity == 'sale' else None
            permitted = bool(section and user['permissions'].get(section, {}).get(_ACTION_FOR_KIND[kind]))
        if not permitted:
            return False, "You don't have permission to manage these attachments"
        return True, None

    return False, f"Method '{method}' is not permitted over the network"


class DatabaseServer:
    """Hosts `database` on the LAN so other PyLocalInventory instances can
    connect as clients. `database` should already be connected (the host
    keeps using it normally in its own window) - this class never touches it
    directly, only its own connection pool to the same Postgres schema.
    """

    def __init__(self, database, port=DEFAULT_PORT):
        self.database = database
        self.port = port
        self.sessions = _SessionStore()
        self.database_name = None
        self.schema_name = None
        self._pool = None
        self._httpd = None
        self._thread = None

    @property
    def is_running(self):
        return self._httpd is not None

    def start(self):
        if self._httpd:
            return

        pg_config = load_server_config()
        selected_profile = self.database.profile_manager.selected_profile
        if getattr(selected_profile, 'database_name', None):
            database_name = selected_profile.database_name
            self.database_name = database_name
            self.schema_name = None
            self._pool = ThreadedConnectionPool(
                2, 10,
                host=pg_config.get('host'),
                port=pg_config.get('port'),
                dbname=database_name,
                user=pg_config.get('user'),
                password=pg_config.get('password'),
            )
        else:
            schema_name = selected_profile.schema_name or Database._profile_schema_name(
                selected_profile.get_value('company name') or selected_profile.name
            )
            self.database_name = None
            self.schema_name = schema_name

            self._pool = ThreadedConnectionPool(
                2, 10,
                host=pg_config.get('host'),
                port=pg_config.get('port'),
                dbname=pg_config.get('database'),
                user=pg_config.get('user'),
                password=pg_config.get('password'),
                options=f'-c search_path={schema_name}',
            )

        self._httpd = ThreadingHTTPServer(('0.0.0.0', self.port), self._make_handler())
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        self._httpd = None
        self._thread = None
        if self._pool:
            self._pool.closeall()
        self._pool = None

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

    def _borrow_database(self):
        """Check out a pooled connection and wrap it in a throwaway Database
        instance, so each request/login gets its own connection/cursor pair -
        never shared across threads - while reusing Database's/UserManager's
        existing SQL logic unchanged."""
        conn = self._pool.getconn()
        request_db = Database(profile_manager=None)
        request_db.registered_classes = self.database.registered_classes
        request_db.database_name = self.database_name
        request_db.schema_name = self.schema_name
        request_db.conn = conn
        request_db.cursor = conn.cursor()
        return request_db

    def _return_database(self, request_db):
        try:
            request_db.cursor.close()
        except Exception:
            pass
        self._pool.putconn(request_db.conn)

    def _dispatch(self, method, args, kwargs, user=None):
        request_db = self._borrow_database()
        try:
            if method == 'cursor.execute':
                sql = args[0]
                params = args[1] if len(args) > 1 and args[1] else []
                cur = request_db.cursor
                cur.execute(sql, params)
                kind, _table = classify_sql(sql)
                # Each RPC borrows a different pooled connection, so leaving
                # DDL uncommitted and calling conn.commit in a later RPC cannot
                # commit the original transaction. Commit all mutating SQL in
                # the request that executed it.
                if kind in ('schema', 'write', 'delete'):
                    request_db.conn.commit()
                result = {'rowcount': cur.rowcount}
                if cur.description:
                    result['rows'] = cur.fetchall()
                    result['description'] = [d[0] for d in cur.description]
                return result

            if method == 'conn.commit':
                request_db.conn.commit()
                return None
            if method == 'conn.rollback':
                request_db.conn.rollback()
                return None

            if method == 'save_sale_with_items':
                return request_db.save_sale_with_items(*args, **kwargs, user=user)

            if method == 'save_import_with_items':
                return request_db.save_import_with_items(*args, **kwargs, user=user)

            if method == 'get_reports':
                owner_id = args[0] if args else None
                date_from = args[1] if len(args) > 1 else None
                date_to = args[2] if len(args) > 2 else None
                report_type = args[3] if len(args) > 3 else None
                return request_db.get_items_for_user(
                    "Reports", user, owner_id, date_from, date_to, report_type
                )
            if method == 'list_report_users':
                return request_db.list_report_users()
            if method == 'save_report':
                return request_db.save_report_for_user(*args, user=user)
            if method == 'delete_report':
                return request_db.delete_report_for_user(*args, user=user)
            if method == 'get_product_stock_levels':
                return request_db.get_product_stock_levels()
            if method in _CLIENT_ACCOUNT_METHODS:
                return getattr(request_db, method)(*args, **kwargs, user=user)

            if method == 'get_items' and args and args[0] in ('Sales', 'Sales_Items', 'Reports'):
                return request_db.get_items_for_user(args[0], user)
            if method == 'get_items_by_operation_id' and len(args) > 1:
                return request_db.get_operation_items_for_user(args[0], args[1], user)
            if method == 'add_item' and len(args) > 1 and args[1] == 'Reports':
                return request_db.save_report_for_user(None, args[0], user)
            if method == 'update_item' and len(args) > 2 and args[2] == 'Reports':
                return bool(request_db.save_report_for_user(args[0], args[1], user))
            if method == 'delete_item' and len(args) > 1 and args[1] == 'Reports':
                return request_db.delete_report_for_user(args[0], user)

            if (method in _SECTION_METHODS or method in _ATTACHMENT_METHODS
                    or method in _CLIENT_ACCOUNT_METHODS or method in _REPORT_METHODS
                    or method in _PRODUCT_READ_METHODS or method in _ALWAYS_ALLOWED):
                return getattr(request_db, method)(*args, **kwargs)

            raise ValueError(f"Method not allowed over network: {method}")
        finally:
            self._return_database(request_db)

    @staticmethod
    def _write_sales_log(message):
        try:
            log_dir = os.path.join(user_data_root(), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, 'network_sales.log'), 'a', encoding='utf-8') as stream:
                stream.write(f"[{datetime.now().isoformat(timespec='seconds')}] server {message}\n")
        except OSError:
            pass

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
                request_db = server_obj._borrow_database()
                try:
                    user_manager = UserManager(request_db)
                    user = user_manager.verify_login(
                        body.get('username', ''), body.get('password', '')
                    )
                finally:
                    server_obj._return_database(request_db)

                if not user:
                    return self._send_json(401, {'error': 'Invalid username or password'})
                token = server_obj.sessions.create(user)
                self._send_json(200, {
                    'token': token,
                    'user_id': user['id'],
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

                if method == 'save_sale_with_items':
                    sale_data = args[0] if args else {}
                    items = args[1] if len(args) > 1 else []
                    server_obj._write_sales_log(
                        f"received user={user.get('username')} sale_id={args[2] if len(args) > 2 else None} "
                        f"client_id={sale_data.get('client_id')} client_identifier={sale_data.get('client_username')} date={sale_data.get('date')} "
                        f"vat={sale_data.get('tva')} notes_present={bool(sale_data.get('notes'))} "
                        f"items_array={isinstance(items, list)} items_received={len(items) if isinstance(items, list) else 'invalid'} "
                        f"items={items}"
                    )

                allowed, reason = _check_permission(user, method, args, kwargs)
                if not allowed:
                    return self._send_json(403, {'error': reason})

                try:
                    result = server_obj._dispatch(method, args, kwargs, user=user)
                except ValueError as e:
                    if method == 'save_sale_with_items':
                        server_obj._write_sales_log(f"validation=failed transaction=rollback error={e}")
                    return self._send_json(400, {'error': str(e)})
                except Exception as e:
                    if method == 'save_sale_with_items':
                        server_obj._write_sales_log(f"validation_or_transaction=rollback error={e}")
                    return self._send_json(500, {'error': str(e)})
                if method == 'save_sale_with_items':
                    server_obj._write_sales_log(f"validation=ok transaction=commit result={result}")
                self._send_json(200, {'result': result})

        return Handler
