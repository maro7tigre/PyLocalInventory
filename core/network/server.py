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
import shutil
import tempfile
import logging
import sys
import time
import traceback
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from psycopg2.pool import PoolError, ThreadedConnectionPool

from core.database import Database
from core import pg_backup
from core.attachments import DEFAULT_MAX_BYTES, attachment_backup_root
from core.pg_config import load_server_config
from core.user_manager import UserManager, SECTION_GROUP
from core.network.protocol import classify_sql, DEFAULT_PORT
from core.build_info import APP_BUILD_ID

logger = logging.getLogger(__name__)
# The application root logger normally remains at WARNING; lifecycle and
# request INFO records must still reach the existing rotating handlers.
logger.setLevel(logging.INFO)

_DEFAULT_BODY_BYTES = max(64 * 1024 * 1024, (DEFAULT_MAX_BYTES * 4 + 2) // 3 + 2 * 1024 * 1024)


def _positive_int_env(name, default):
    try:
        value = int(os.getenv(name, str(default)))
        if value > 0:
            return value
    except ValueError:
        pass
    logger.warning("Invalid server limit configuration name=%s; using default", name)
    return default


def _format_frames(frames):
    rendered = []
    for frame in frames:
        filename = os.path.basename(frame.filename) or '<unknown>'
        rendered.append(f'{filename}:{frame.lineno}:{frame.name}')
    return ' <- '.join(rendered) if rendered else 'unavailable'


def _safe_stack(error):
    """Privacy-safe traceback: file basename, line number and function only.

    ``traceback.format_tb`` includes the source line for every frame, which can
    contain SQL text, literals, or values interpolated into a call. Exception
    messages are deliberately excluded too because they can echo caller data.
    """
    traceback_obj = getattr(error, '__traceback__', None)
    return _format_frames(traceback.extract_tb(traceback_obj))


def _caller_stack():
    """Sanitized call chain at this point, including this function's caller."""
    return _format_frames(traceback.extract_stack()[:-1])


class _RequestBodyError(Exception):
    def __init__(self, status, category, message):
        super().__init__(message)
        self.status = status
        self.category = category


class _BoundedHTTPServer(ThreadingHTTPServer):
    """Bound active request threads, including clients still sending headers."""

    request_queue_size = 16

    def __init__(self, address, handler, max_threads):
        self._slots = threading.BoundedSemaphore(max_threads)
        self._active_lock = threading.Lock()
        self.active_requests = 0
        self.max_threads = max_threads
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            logger.warning("http_capacity_exhausted active=%d limit=%d", self.active_requests, self.max_threads)
            try:
                self.shutdown_request(request)
            except OSError:
                logger.warning('http_capacity_close_failed')
            return
        with self._active_lock:
            self.active_requests += 1
        try:
            super().process_request(request, client_address)
        except Exception:
            with self._active_lock:
                self.active_requests -= 1
            self._slots.release()
            self.shutdown_request(request)
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._active_lock:
                self.active_requests -= 1
            self._slots.release()

    def handle_error(self, request, client_address):
        # socketserver's default prints the exception (which can include
        # request data) to stderr. Keep only a stack and the exception class.
        error = sys.exc_info()[1]
        if error is not None:
            logger.error('http_worker_unhandled category=%s stack=%s',
                         type(error).__name__, _safe_stack(error))

# method name -> (kind, index into `args` holding the section name)
_SECTION_METHODS = {
    'add_item': ('write', 1),                  # add_item(data, section)
    'update_item': ('write', 2),                # update_item(item_id, data, section)
    'delete_item': ('delete', 1),               # delete_item(item_id, section)
    'get_items': ('read', 0),                   # get_items(section)
    'get_items_by_operation_id': ('read', 1),   # get_items_by_operation_id(operation_id, section)
    'get_items_by_operation_ids': ('read', 1),  # get_items_by_operation_ids(operation_ids, section)
    # get_sale_catalog is handled by its own dedicated branch below (its args
    # are booleans, not a section name - see the `if method == 'get_sale_catalog'` check).
    'get_operation_summary_items': ('read', 0),  # get operation summaries for Sales/Imports
    'get_changes': ('read', 0),                 # get_changes(section, since_seq, limit)
}
_ATTACHMENT_METHODS = {
    'get_attachment': ('read', None),           # get_attachment(attachment_id) - no owner arg
    'get_attachment_thumbnail': ('read', None),  # get_attachment_thumbnail(attachment_id) - no owner arg
    'get_attachment_thumbnails_bulk': ('read', None),  # get_attachment_thumbnails_bulk(attachment_ids)
    'update_attachment': ('write', None),       # update_attachment(attachment_id, display_name, ...)
    'list_attachments': ('read', 0),            # list_attachments(entity_type, entity_id)
    'upload_attachment': ('write', 0),          # upload_attachment(entity_type, entity_id, ...)
    'download_attachment': ('read', None),      # download_attachment(attachment_id) - no owner arg
    'delete_attachment': ('delete', None),      # delete_attachment(attachment_id) - no owner arg
}
_CLIENT_ACCOUNT_METHODS = {
    'get_client_account', 'get_client_sales', 'get_client_sale_summaries',
    'get_client_sale_items', 'add_client_payment', 'update_client_payment',
    'delete_client_payment',
}
_CLIENT_PAYMENT_WRITE_METHODS = {
    'add_client_payment', 'update_client_payment', 'delete_client_payment',
}
_SUPPLIER_ACCOUNT_METHODS = {
    'get_supplier_account', 'get_supplier_import_summaries',
    'get_supplier_import_items', 'add_supplier_payment',
    'update_supplier_payment', 'delete_supplier_payment',
}
_SUPPLIER_PAYMENT_WRITE_METHODS = {
    'add_supplier_payment', 'update_supplier_payment', 'delete_supplier_payment',
}
_REPORT_METHODS = {'get_reports', 'list_report_users', 'save_report', 'delete_report'}
_PRODUCT_READ_METHODS = {'get_product_stock_levels', 'get_product_stock_levels_for_product_ids'}
_FACTURE_METHODS = {
    'get_next_facture_preview', 'get_facture', 'list_factures',
    'get_facture_payments', 'get_facture_draft_from_sale', 'get_facture_draft_from_sales', 'get_invoiced_total_for_sources', 'save_facture_with_items', 'create_facture_from_sale',
    'add_facture_payment', 'update_facture_payment', 'delete_facture_payment', 'delete_facture',
}
_FACTURE_WRITE_METHODS = {
    'save_facture_with_items', 'create_facture_from_sale', 'add_facture_payment', 'update_facture_payment',
}
_ALWAYS_ALLOWED = {
    'begin_transaction', 'commit_transaction', 'rollback_transaction',
    'get_dashboard_snapshot',
}
_ACTION_FOR_KIND = {'read': 'read', 'write': 'write', 'delete': 'delete'}
_LOGGABLE_METHODS = (
    set(_SECTION_METHODS) | set(_ATTACHMENT_METHODS) | _CLIENT_ACCOUNT_METHODS |
    _SUPPLIER_ACCOUNT_METHODS | _REPORT_METHODS | _PRODUCT_READ_METHODS |
    _FACTURE_METHODS | _ALWAYS_ALLOWED | {
        'cursor.execute', 'conn.commit', 'conn.rollback', 'get_sale_catalog',
        'save_sale_with_items', 'save_import_with_items',
        'save_product_with_opening_stock', 'update_product_with_stock',
        'get_next_devis_preview', 'get_import_bl_number', 'get_next_bl_preview',
    }
)


def _method_label(method):
    return method if isinstance(method, str) and method in _LOGGABLE_METHODS else 'unrecognized'


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

    def count(self):
        with self._lock:
            return len(self._sessions)


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

    if method in ('save_product_with_opening_stock', 'update_product_with_stock'):
        if not user['permissions'].get('Products', {}).get('write'):
            return False, "You don't have write access to Products"
        # Opening/adjustment stock is part of the product write itself. The
        # backend owns the ledger entry, so users do not need separate access
        # to create arbitrary supplier imports.
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

    if method == 'get_next_devis_preview':
        # Read-only advisory Devis proposal; gated by Sales read/write access.
        if not (user['permissions'].get('Sales', {}).get('read')
                or user['permissions'].get('Sales', {}).get('write')):
            return False, "You don't have read access to Sales"
        return True, None

    if method in _FACTURE_METHODS:
        needed = 'delete' if method in {'delete_facture', 'delete_facture_payment'} else ('write' if method in _FACTURE_WRITE_METHODS else 'read')
        if not user['permissions'].get('Factures', {}).get(needed):
            return False, f"You don't have {needed} access to Factures"
        # Copying a Devis reads Sales data but never changes it.
        if method in ('create_facture_from_sale', 'get_facture_draft_from_sale', 'get_facture_draft_from_sales') and not user['permissions'].get('Sales', {}).get('read'):
            return False, "You don't have read access to Sales"
        return True, None

    if method == 'get_import_bl_number':
        # Read the persistent Bon de Livraison reference (allocating it on
        # first print for legacy imports). Gated by Imports read/write access.
        if not (user['permissions'].get('Imports', {}).get('read')
                or user['permissions'].get('Imports', {}).get('write')):
            return False, "You don't have read access to Imports"
        return True, None

    if method == 'get_next_bl_preview':
        # Read-only advisory Bon de Livraison proposal for the New Import
        # dialog. Gated by Imports read/write access like get_next_devis_preview.
        if not (user['permissions'].get('Imports', {}).get('read')
                or user['permissions'].get('Imports', {}).get('write')):
            return False, "You don't have read access to Imports"
        return True, None

    if method == 'cursor.execute':
        sql = args[0] if args else ''
        kind, table = classify_sql(sql)
        if kind == 'schema':
            return True, None
        # Case-insensitive, schema-qualifier-aware lookup: raw SQL call sites
        # across the codebase are inconsistent about writing 'sales' vs
        # 'Sales', and both name the same physical (lowercase-folded) table.
        section = UserManager.section_for_table(table) if table else None
        if not section:
            logger.warning(
                'permission_denied reason=unknown_table method=cursor.execute',
            )
            return False, f"No permission mapping for table '{table}' - contact your admin"
        if section == "Reports" and kind == "read":
            return False, "Reports must be read through the ownership-filtered API"
        needed = _ACTION_FOR_KIND[kind]
        if not user['permissions'].get(section, {}).get(needed):
            logger.warning(
                'permission_denied method=cursor.execute section=%s needed=%s',
                section, needed,
            )
            return False, f"You don't have {needed} access to {section}"
        if table and table.rsplit('.', 1)[-1].casefold() in ('sales', 'clients'):
            logger.info(
                'permission_granted method=cursor.execute section=%s needed=%s',
                section, needed,
            )
        return True, None

    if method == 'get_sale_catalog':
        # Not a single-section method (its first two positional args are
        # booleans, not a section name) - the generic _SECTION_METHODS path
        # below would misread args[0]/kwargs.get('section') and always deny
        # it. Gate each optional slice by its own section's read permission.
        def _flag(index, key, default):
            if len(args) > index:
                return bool(args[index])
            return bool(kwargs.get(key, default))
        requested = {
            'Products': _flag(0, 'include_products', True),
            'Services': _flag(1, 'include_services', True),
            'Clients': _flag(3, 'include_clients', False),
            'Suppliers': _flag(4, 'include_suppliers', False),
        }
        for section, wanted in requested.items():
            if wanted and not user['permissions'].get(section, {}).get('read'):
                return False, f"You don't have read access to {section}"
        return True, None

    if method in _SECTION_METHODS:
        kind, idx = _SECTION_METHODS[method]
        section = args[idx] if len(args) > idx else kwargs.get('section')
        # Attachment metadata sync mirrors the attachment permission model:
        # read access to Clients OR Sales grants the change-log stream.
        if method == "get_changes" and section == "attachments":
            if not any(
                user['permissions'].get(sec, {}).get('read')
                for sec in ('Clients', 'Sales')
            ):
                return False, "You don't have read access to Clients or Sales"
            return True, None
        mapped = SECTION_GROUP.get(section, section)
        needed = _ACTION_FOR_KIND[kind]
        if method == "get_items" and mapped == "Reports":
            return True, None
        if not user['permissions'].get(mapped, {}).get(needed):
            return False, f"You don't have {needed} access to {mapped}"
        return True, None

    if method in _CLIENT_ACCOUNT_METHODS:
        if not user['permissions'].get('Clients', {}).get('read'):
            logger.warning(
                'permission_denied method=%s needed=Clients:read', method,
            )
            return False, "You don't have read access to Clients"
        if (method in _CLIENT_PAYMENT_WRITE_METHODS
                and not user['permissions'].get('Sales', {}).get('write')):
            logger.warning(
                'permission_denied method=%s needed=Sales:write', method,
            )
            return False, "You don't have write access to Sales"
        logger.info(
            'permission_granted method=%s permission_filter=Clients:read-only', method,
        )
        return True, None

    if method in _SUPPLIER_ACCOUNT_METHODS:
        if not user['permissions'].get('Suppliers', {}).get('read'):
            logger.warning(
                'permission_denied method=%s needed=Suppliers:read', method,
            )
            return False, "You don't have read access to Suppliers"
        if (method in _SUPPLIER_PAYMENT_WRITE_METHODS
                and not user['permissions'].get('Imports', {}).get('write')):
            logger.warning(
                'permission_denied method=%s needed=Imports:write', method,
            )
            return False, "You don't have write access to Imports"
        logger.info(
            'permission_granted method=%s permission_filter=Suppliers:read-only', method,
        )
        return True, None

    if method in _ATTACHMENT_METHODS:
        kind, index = _ATTACHMENT_METHODS[method]
        if index is None:
            permitted = any(
                user['permissions'].get(section, {}).get(_ACTION_FOR_KIND[kind])
                for section in ('Clients', 'Sales')
            )
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

    def __init__(self, database, port=DEFAULT_PORT, *, max_request_bytes=None,
                 request_timeout=None, max_request_threads=None, max_inflight_body_bytes=None,
                 database_statement_timeout_ms=None):
        self.database = database
        self.port = port
        self.max_request_bytes = (max_request_bytes if max_request_bytes is not None else
                                  _positive_int_env('PYLOCALINVENTORY_MAX_REQUEST_MB',
                                                    (_DEFAULT_BODY_BYTES + 1024 * 1024 - 1) // (1024 * 1024)) * 1024 * 1024)
        self.request_timeout = (request_timeout if request_timeout is not None else
                                _positive_int_env('PYLOCALINVENTORY_HTTP_TIMEOUT_SECONDS', 30))
        self.max_request_threads = (max_request_threads if max_request_threads is not None else
                                    _positive_int_env('PYLOCALINVENTORY_MAX_HTTP_THREADS', 32))
        self.database_statement_timeout_ms = (
            database_statement_timeout_ms if database_statement_timeout_ms is not None else
            _positive_int_env('PYLOCALINVENTORY_DB_STATEMENT_TIMEOUT_MS', 8000)
        )
        self.max_inflight_body_bytes = (
            max_inflight_body_bytes if max_inflight_body_bytes is not None else
            _positive_int_env('PYLOCALINVENTORY_MAX_INFLIGHT_BODY_MB',
                              max(128, (2 * self.max_request_bytes + 1024 * 1024 - 1) // (1024 * 1024)))
            * 1024 * 1024
        )
        if min(
            self.max_request_bytes, self.request_timeout, self.max_request_threads,
            self.database_statement_timeout_ms,
        ) <= 0:
            raise ValueError("Server request limits must be positive")
        if self.max_inflight_body_bytes < self.max_request_bytes:
            raise ValueError('In-flight body budget must accommodate one maximum-size request')
        if self.max_request_bytes < (DEFAULT_MAX_BYTES * 4 + 2) // 3 + 1024 * 1024:
            logger.warning('http_body_limit_below_supported_attachment_size limit=%d',
                           self.max_request_bytes)
        self.sessions = _SessionStore()
        self.database_name = None
        self.schema_name = None
        self._pool = None
        self._httpd = None
        self._thread = None
        self._stopping = False
        self._pool_lock = threading.Lock()
        self._checked_out = 0
        self._pool_counts = {}
        self._checkout_times = {}
        self._body_lock = threading.Lock()
        self._body_inflight = 0
        # Lifecycle diagnostics are deliberately in-process only. They make the
        # Host state shown by the UI and written to app.log truthful without
        # adding a second persistent file that could itself fail.
        self._state_lock = threading.Lock()
        self._state = 'not_started'
        self._state_since = datetime.now().astimezone()
        self._state_reason = 'initial'
        self._previous_state = None
        self._previous_reason = None
        self._last_unhealthy_state = None
        self._last_unhealthy_reason = None
        self._last_unhealthy_at = None
        self._started_at = None
        self._last_error_category = None
        self._last_error_at = None
        self._monitor_stop = threading.Event()
        self._monitor_thread = None
        self._draining = 0
        self.heartbeat_seconds = 300

    def _ensure_lifecycle(self):
        # Tests and a few old call sites construct a server with __new__ and
        # inject only a pool; keep those objects diagnosable too.
        if not hasattr(self, '_state_lock'):
            self._state_lock = threading.Lock()
            self._state = 'not_started'
            self._state_since = datetime.now().astimezone()
            self._state_reason = 'initial'
            self._previous_state = None
            self._previous_reason = None
            self._last_unhealthy_state = None
            self._last_unhealthy_reason = None
            self._last_unhealthy_at = None
            self._started_at = None
            self._last_error_category = None
            self._last_error_at = None
            self._monitor_stop = threading.Event()
            self._monitor_thread = None
            self._draining = 0
            self.heartbeat_seconds = 300
        if not hasattr(self, '_body_lock'):
            self._body_lock = threading.Lock()
            self._body_inflight = 0
        if not hasattr(self, '_stopping'):
            self._stopping = False

    def _get_state(self):
        self._ensure_lifecycle()
        with self._state_lock:
            return self._state

    def _runtime_fields(self):
        self._ensure_pool_metrics()
        with self._pool_lock:
            checked_out = self._checked_out
        with self._body_lock:
            body_inflight = self._body_inflight
        httpd = getattr(self, '_httpd', None)
        try:
            active_requests = httpd.active_requests if httpd is not None else 0
        except Exception:
            active_requests = 0
        thread = getattr(self, '_thread', None)
        try:
            session_count = self.sessions.count()
        except Exception:
            session_count = 0
        return {
            'thread_alive': bool(thread and thread.is_alive()),
            'listener_available': self._listener_available(),
            'active_requests': active_requests,
            'checked_out': checked_out,
            'body_inflight': body_inflight,
            'sessions': session_count,
            'pool_drain_pending': int(getattr(self, '_draining', 0)),
        }

    def snapshot(self):
        """Return a privacy-safe, point-in-time Host state summary.

        Contains only state names, timestamps, counters and a sanitized error
        category - never credentials, SQL, parameters, usernames or row data.
        """
        self._ensure_lifecycle()
        with self._state_lock:
            state = self._state
            state_since = self._state_since
            reason = self._state_reason
            previous_state = self._previous_state
            previous_reason = self._previous_reason
            last_unhealthy_state = self._last_unhealthy_state
            last_unhealthy_reason = self._last_unhealthy_reason
            last_unhealthy_at = self._last_unhealthy_at
            started_at = self._started_at
            last_error_category = self._last_error_category
            last_error_at = self._last_error_at
        now = datetime.now().astimezone()
        result = {
            'state': state,
            'state_since': state_since.isoformat(timespec='seconds'),
            'reason': reason,
            'previous_state': previous_state,
            'previous_reason': previous_reason,
            'last_unhealthy_state': last_unhealthy_state,
            'last_unhealthy_reason': last_unhealthy_reason,
            'last_unhealthy_at': (
                last_unhealthy_at.isoformat(timespec='seconds')
                if last_unhealthy_at is not None else None
            ),
            'port': getattr(self, 'port', None),
            'pid': os.getpid(),
            'build_id': APP_BUILD_ID,
            'started_at': (
                started_at.isoformat(timespec='seconds') if started_at is not None else None
            ),
            'uptime_seconds': (
                round(max(0.0, (now - started_at).total_seconds()), 1)
                if started_at is not None else None
            ),
            'last_error_category': last_error_category,
            'last_error_at': (
                last_error_at.isoformat(timespec='seconds') if last_error_at is not None else None
            ),
        }
        result.update(self._runtime_fields())
        return result

    def _transition(self, new_state, reason, error_category=None, expected_state=None):
        self._ensure_lifecycle()
        now = datetime.now().astimezone()
        with self._state_lock:
            old_state = self._state
            if expected_state is not None and old_state != expected_state:
                return False
            if old_state == new_state:
                return False
            self._previous_state = old_state
            self._previous_reason = self._state_reason
            self._state = new_state
            self._state_since = now
            self._state_reason = reason
            if error_category:
                self._last_error_category = error_category
                self._last_error_at = now
            if new_state in ('thread_exited', 'listener_lost', 'failed'):
                self._last_unhealthy_state = new_state
                self._last_unhealthy_reason = reason
                self._last_unhealthy_at = now
            if new_state == 'running':
                self._started_at = now
                # A successful new run starts a fresh failure history.
                self._last_unhealthy_state = None
                self._last_unhealthy_reason = None
                self._last_unhealthy_at = None
        fields = self._runtime_fields()
        level = (
            logging.ERROR
            if new_state in ('failed', 'thread_exited', 'listener_lost')
            else logging.INFO
        )
        logger.log(
            level,
            'host_state from=%s to=%s reason=%s port=%s pid=%s build_id=%s '
            'thread_alive=%s listener=%s active_requests=%d checked_out=%d '
            'body_inflight=%d sessions=%d pool_drain_pending=%d error_category=%s',
            old_state, new_state, reason, getattr(self, 'port', None), os.getpid(),
            APP_BUILD_ID,
            fields['thread_alive'], fields['listener_available'],
            fields['active_requests'], fields['checked_out'],
            fields['body_inflight'], fields['sessions'],
            fields['pool_drain_pending'], error_category or 'none',
        )
        return True

    def _monitor_serving_thread(self, stop_event):
        """Detect a serving thread/listener that died outside stop().

        Also writes a low-frequency heartbeat, so a future incident can
        distinguish an orderly stop (``host_stop_requested``) from a process
        that disappeared without running any shutdown code (heartbeats end
        abruptly, followed by a new ``Application startup`` line).
        """
        heartbeat_seconds = max(1.0, float(getattr(self, 'heartbeat_seconds', 300)))
        last_heartbeat = time.monotonic()
        while not stop_event.wait(1.0):
            if self._stopping:
                return
            if self._get_state() != 'running':
                return
            thread = self._thread
            if thread is None or not thread.is_alive():
                self._transition('thread_exited', 'serving_thread_not_alive')
                return
            if not self._listener_available():
                self._transition('listener_lost', 'listener_unavailable')
                return
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_seconds:
                last_heartbeat = now
                try:
                    snapshot = self.snapshot()
                except Exception as error:
                    logger.warning('host_heartbeat_failed category=%s',
                                   type(error).__name__)
                    continue
                logger.info(
                    'host_heartbeat state=%s uptime_s=%s port=%s pid=%d build_id=%s '
                    'thread_alive=%s listener=%s active_requests=%d checked_out=%d '
                    'body_inflight=%d sessions=%d',
                    snapshot['state'], snapshot['uptime_seconds'], snapshot['port'],
                    snapshot['pid'], snapshot['build_id'], snapshot['thread_alive'],
                    snapshot['listener_available'], snapshot['active_requests'],
                    snapshot['checked_out'], snapshot['body_inflight'],
                    snapshot['sessions'],
                )

    def _start_monitor(self):
        self._monitor_stop = threading.Event()
        monitor = threading.Thread(
            target=self._monitor_serving_thread,
            args=(self._monitor_stop,),
            name='LANServerMonitor',
            daemon=True,
        )
        try:
            monitor.start()
        except Exception as error:
            # Diagnostics must never prevent hosting from starting.
            logger.warning('host_monitor_start_failed category=%s',
                           type(error).__name__)
            monitor = None
        self._monitor_thread = monitor

    def _stop_monitor(self):
        stop_event = getattr(self, '_monitor_stop', None)
        if stop_event is not None:
            stop_event.set()
        monitor = getattr(self, '_monitor_thread', None)
        if (monitor is not None and monitor.is_alive()
                and monitor is not threading.current_thread()):
            monitor.join(timeout=1.5)
            if monitor.is_alive():
                logger.warning('host_monitor_join_timeout')
        self._monitor_thread = None

    def _reserve_body(self, size):
        with self._body_lock:
            if self._body_inflight + size > self.max_inflight_body_bytes:
                logger.warning('http_body_capacity_exhausted in_flight=%d limit=%d',
                               self._body_inflight, self.max_inflight_body_bytes)
                raise _RequestBodyError(503, 'body_capacity', 'Server is busy')
            self._body_inflight += size

    def _release_body(self, size):
        with self._body_lock:
            self._body_inflight -= size

    @property
    def is_running(self):
        return bool(self._httpd and self._thread and self._thread.is_alive()
                    and self._listener_available())

    def _listener_available(self):
        try:
            httpd = self._httpd
            if httpd is None:
                return False
            sock = httpd.socket
            return (sock.fileno() >= 0 and
                    bool(sock.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)) and
                    sock.getsockname()[1] == self.port)
        except (AttributeError, OSError):
            return False

    def health_status(self, check_database=False):
        """In-process health; called without DB I/O by the hosting status UI.

        Authenticated /health calls this with check_database=True; an HTTP
        response itself proves that the handler is responsive.
        """
        status = {
            'gui_process_alive': True,
            'server_thread_alive': bool(self._thread and self._thread.is_alive()),
            'listener_available': self._listener_available(),
        }
        if check_database:
            try:
                request_db = self._borrow_database()
                try:
                    if request_db.cursor is None:
                        raise RuntimeError('Health probe has no database cursor')
                    # Transaction-local: this deadline cannot alter business SQL.
                    request_db.cursor.execute('SET LOCAL statement_timeout = 2000')
                    request_db.cursor.execute('SELECT 1')
                    status['database_accessible'] = request_db.cursor.fetchone() == (1,)
                finally:
                    self._return_database(request_db)
            except Exception as error:
                status['database_accessible'] = False
                logger.warning('health_database_unavailable category=%s', type(error).__name__)
        return status

    def _serve(self):
        logger.info('server_thread_started port=%d', self.port)
        httpd = self._httpd
        if httpd is None:
            logger.error('server_thread_started_without_listener port=%d', self.port)
            self._transition('failed', 'listener_missing')
            return
        try:
            httpd.serve_forever()
        except Exception as error:
            # This thread only runs socketserver's accept loop; the sanitized
            # stack keeps source lines and SQL text out of the log.
            logger.error('server_thread_failed port=%d category=%s stack=%s',
                         self.port, type(error).__name__, _safe_stack(error))
            if not self._stopping:
                if not self._transition(
                    'thread_exited', 'serving_thread_failed', type(error).__name__,
                    expected_state='running',
                ):
                    self._transition(
                        'thread_exited', 'serving_thread_failed', type(error).__name__,
                        expected_state='starting',
                    )
        finally:
            if not self._stopping:
                if self._get_state() == 'running':
                    self._transition('thread_exited', 'serving_thread_returned',
                                     expected_state='running')
                logger.error(
                    'server_thread_terminated_unexpectedly port=%d state=%s reason=%s',
                    self.port, self._get_state(), self._state_reason,
                )
                try:
                    httpd.server_close()
                except Exception as error:
                    logger.error('server_listener_close_failed category=%s stack=%s',
                                 type(error).__name__, _safe_stack(error))
                else:
                    logger.error(
                        'host_listener_closed port=%s trigger=unexpected_serving_thread_exit '
                        'state=%s reason=%s',
                        getattr(self, 'port', None), self._get_state(), self._state_reason,
                    )
            else:
                logger.info('server_thread_stopped port=%d', self.port)

    def start(self):
        self._ensure_lifecycle()
        if self.is_running:
            return
        if self._httpd or self._pool or (self._thread and self._thread.is_alive()):
            self.stop(reason='restart_before_start')

        self._stopping = False
        self._transition('starting', 'start_requested')
        logger.info('server_starting port=%d body_limit=%d inflight_limit=%d read_timeout=%ss thread_limit=%d db_statement_timeout_ms=%d',
                    self.port, self.max_request_bytes, self.max_inflight_body_bytes,
                self.request_timeout, self.max_request_threads,
                self.database_statement_timeout_ms)
        try:
            pg_config = load_server_config()
            selected_profile = self.database.profile_manager.selected_profile
            pool_args = dict(
                host=pg_config.get('host'), port=pg_config.get('port'),
                user=pg_config.get('user'), password=pg_config.get('password'),
                connect_timeout=5, application_name='PyLocalInventory-LAN',
            )
            if getattr(selected_profile, 'database_name', None):
                self.database_name = selected_profile.database_name
                self.schema_name = None
                pool_args['dbname'] = self.database_name
                pool_args['options'] = (
                    f'-c statement_timeout={self.database_statement_timeout_ms}'
                )
            else:
                self.schema_name = selected_profile.schema_name or Database._profile_schema_name(
                    selected_profile.get_value('company name') or selected_profile.name
                )
                self.database_name = None
                pool_args['dbname'] = pg_config.get('database')
                pool_args['options'] = (
                    f'-c search_path={self.schema_name} '
                    f'-c statement_timeout={self.database_statement_timeout_ms}'
                )
            self._pool = ThreadedConnectionPool(2, 10, **pool_args)
            with self._pool_lock:
                self._checked_out = 0
            self._httpd = _BoundedHTTPServer(('0.0.0.0', self.port), self._make_handler(),
                                             self.max_request_threads)
            self.port = self._httpd.server_port
            self._thread = threading.Thread(target=self._serve, name='LANServer', daemon=True)
            self._thread.start()
            self._start_monitor()
        except Exception as error:
            self._stop_monitor()
            logger.error('server_start_failed port=%d category=%s stack=%s',
                         self.port, type(error).__name__, _safe_stack(error))
            if self._httpd:
                try:
                    self._httpd.server_close()
                except Exception as cleanup_error:
                    logger.error('server_start_listener_cleanup_failed category=%s',
                                 type(cleanup_error).__name__)
            if self._pool:
                try:
                    self._pool.closeall()
                except Exception as cleanup_error:
                    logger.error('server_start_pool_cleanup_failed category=%s',
                                 type(cleanup_error).__name__)
            self._httpd = self._pool = self._thread = None
            self._transition('failed', 'start_failed', type(error).__name__)
            raise
        if self.is_running:
            self._transition('running', 'start_succeeded', expected_state='starting')
            logger.info('server_listening build_id=%s bind=0.0.0.0 port=%s state=%s',
                        APP_BUILD_ID, self.port, self._get_state())
        else:
            logger.warning('server_not_healthy_after_start port=%s state=%s',
                           self.port, self._get_state())
            self._transition('failed', 'start_unhealthy', expected_state='starting')

    def stop(self, reason='unspecified'):
        self._ensure_lifecycle()
        self._ensure_pool_metrics()
        logger.info(
            'host_stop_requested reason=%s port=%s pid=%d thread=%s caller=%s',
            reason, getattr(self, 'port', None), os.getpid(),
            threading.current_thread().name, _caller_stack(),
        )
        httpd = getattr(self, '_httpd', None)
        thread = getattr(self, '_thread', None)
        pool = getattr(self, '_pool', None)
        thread_alive = bool(thread and thread.is_alive())
        with self._state_lock:
            state_before = self._state
            draining = int(getattr(self, '_draining', 0))
        if httpd is None and pool is None and not thread_alive:
            if draining:
                logger.debug('server_stop_already_draining port=%d reason=%s draining=%d',
                             self.port, reason, draining)
                return
            if state_before not in ('stopped', 'failed', 'not_started',
                                    'thread_exited', 'listener_lost'):
                self._transition('stopped', 'already_stopped')
            logger.debug('server_stop_noop port=%d reason=%s state=%s',
                         self.port, reason, state_before)
            return

        self._stopping = True
        self._transition('stopping', reason)
        logger.info('server_stopping port=%d reason=%s', self.port, reason)
        failures = []

        def attempt(label, action):
            try:
                action()
            except Exception as error:
                failures.append((label, type(error).__name__))
                logger.error('host_stop_step_failed step=%s category=%s stack=%s',
                             label, type(error).__name__, _safe_stack(error))

        if httpd is not None:
            if thread_alive:
                attempt('listener_shutdown', httpd.shutdown)
            close_failures_before = len(failures)
            attempt('listener_close', httpd.server_close)
            if len(failures) == close_failures_before:
                logger.info('host_listener_closed port=%s trigger=stop reason=%s',
                            getattr(self, 'port', None), reason)
        if thread_alive:
            try:
                thread.join(timeout=2)
            except Exception as error:
                failures.append(('serving_thread_join', type(error).__name__))
                logger.error('host_stop_step_failed step=serving_thread_join category=%s stack=%s',
                             type(error).__name__, _safe_stack(error))
            if thread.is_alive():
                failures.append(('serving_thread_join', 'TimeoutError'))
                logger.warning('server_stop_thread_join_timeout port=%d', self.port)
        self._stop_monitor()
        self._httpd = None
        self._thread = None

        active_requests = 0
        if httpd is not None:
            try:
                active_requests = int(httpd.active_requests)
            except Exception:
                active_requests = 0
        if pool is not None:
            if active_requests:
                logger.warning('server_stop_waiting_for_requests active=%d', active_requests)
                # Never close connections while an accepted request is still
                # using them. Do not block the Qt event loop on long requests.
                with self._state_lock:
                    self._draining = int(getattr(self, '_draining', 0)) + 1
                self._pool = None
                active_httpd = httpd
                active_pool = pool
                had_cleanup_failures = bool(failures)
                first_cleanup_category = failures[0][1] if failures else None

                def close_when_drained():
                    while active_httpd.active_requests:
                        time.sleep(0.1)
                    close_error = None
                    try:
                        active_pool.closeall()
                    except Exception as error:
                        close_error = error
                        logger.error('server_pool_drain_close_failed category=%s stack=%s',
                                     type(error).__name__, _safe_stack(error))
                    else:
                        logger.info('server_pool_closed_after_drain')
                    with self._state_lock:
                        self._draining = max(0, int(getattr(self, '_draining', 0)) - 1)
                        still_draining = self._draining
                        current_state = self._state
                    if not still_draining and current_state == 'stopping':
                        if close_error is not None:
                            self._transition('failed', 'stop_pool_drain_failed',
                                             type(close_error).__name__)
                        elif had_cleanup_failures:
                            self._transition('failed', 'stop_cleanup_failed',
                                             first_cleanup_category)
                        else:
                            self._transition('stopped', 'stop_completed_after_drain')

                threading.Thread(target=close_when_drained, name='LANPoolDrain',
                                 daemon=True).start()
                logger.info('server_stopped_pending_pool_drain port=%d active=%d state=%s',
                            self.port, active_requests, self._get_state())
                return
            attempt('pool_close', pool.closeall)
        self._pool = None
        if failures:
            self._transition('failed', 'stop_cleanup_failed', failures[0][1])
        else:
            self._transition('stopped', 'stop_completed')
        logger.info('server_stopped port=%d reason=%s state=%s',
                    self.port, reason, self._get_state())

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
        self._ensure_pool_metrics()
        started = time.monotonic()
        pool = self._pool
        if pool is None:
            raise RuntimeError('LAN database pool is not running')
        try:
            conn = pool.getconn()
        except Exception as error:
            with self._pool_lock:
                in_use = self._pool_counts.get(pool, 0)
            logger.warning('db_checkout_failed category=%s in_use=%d capacity=10 stack=%s',
                           type(error).__name__, in_use, _safe_stack(error))
            raise
        with self._pool_lock:
            in_use = self._pool_counts.get(pool, 0) + 1
            self._pool_counts[pool] = in_use
            if self._pool is pool:
                self._checked_out = in_use
            self._checkout_times[id(conn)] = (started, pool)
        logger.info('db_checkout in_use=%d capacity=10 wait_ms=%.1f',
                    in_use, (time.monotonic() - started) * 1000)
        if in_use >= 8:
            logger.warning('db_pool_near_capacity in_use=%d capacity=10', in_use)
        try:
            request_db = Database(profile_manager=None)
            request_db.registered_classes = self.database.registered_classes
            request_db.database_name = self.database_name
            request_db.schema_name = self.schema_name
            request_db.conn = conn
            request_db.cursor = conn.cursor()
            return request_db
        except Exception as error:
            logger.error('db_request_init_failed category=%s stack=%s',
                         type(error).__name__, _safe_stack(error))
            self._release_connection(conn, discard=True, pool=pool)
            raise

    def _ensure_pool_metrics(self):
        # A few existing tests construct a server with __new__ and inject a
        # stand-in pool directly, without running the production constructor.
        if not hasattr(self, '_pool_lock'):
            self._pool_lock = threading.Lock()
            self._checked_out = 0
            self._pool_counts = {}
            self._checkout_times = {}

    def _release_connection(self, connection, discard=False, pool=None):
        self._ensure_pool_metrics()
        with self._pool_lock:
            checkout = self._checkout_times.get(id(connection))
        pool = pool or (checkout[1] if checkout else self._pool)
        if pool is None:
            raise RuntimeError('No pool owns this database connection')
        returned = False
        try:
            try:
                pool.putconn(connection, close=discard)
            except TypeError:
                # Preserve compatibility with pool stand-ins used by callers.
                pool.putconn(connection)
            returned = True
        except Exception as error:
            logger.error('db_return_failed category=%s stack=%s', type(error).__name__,
                         _safe_stack(error))
            raise
        finally:
            with self._pool_lock:
                checkout = self._checkout_times.get(id(connection))
                in_use = self._pool_counts.get(pool, 0)
                if returned:
                    self._checkout_times.pop(id(connection), None)
                    in_use = max(0, in_use - 1)
                    self._pool_counts[pool] = in_use
                    if self._pool is pool:
                        self._checked_out = in_use
            age_ms = (time.monotonic() - checkout[0]) * 1000 if checkout else 0
            logger.log(logging.WARNING if not returned or age_ms >= 10000 else logging.INFO,
                       'db_%s in_use=%d capacity=10 held_ms=%.1f',
                       'return_failed' if not returned else 'discard' if discard else 'return',
                       in_use, age_ms)

    def _return_database(self, request_db):
        connection = request_db.conn
        discard = bool(getattr(connection, 'closed', False))
        try:
            request_db.cursor.close()
        except Exception as error:
            logger.warning('db_cursor_close_failed category=%s', type(error).__name__)
            discard = True
        try:
            # PostgreSQL starts a transaction even for SELECT. Reset it before
            # returning the connection so it cannot remain idle in transaction.
            if connection and not discard:
                rollback = getattr(connection, "rollback", None)
                if callable(rollback):
                    rollback()
        except Exception as error:
            logger.warning('db_reset_failed category=%s stack=%s',
                           type(error).__name__, _safe_stack(error))
            discard = True
        try:
            self._release_connection(connection, discard=discard)
        except Exception:
            try:
                connection.close()
            except Exception as error:
                logger.error('db_connection_close_failed category=%s stack=%s',
                             type(error).__name__, _safe_stack(error))

    def _create_client_backup_archive(self, work_dir):
        """Create a verified host-side archive for an authenticated client."""
        bundle_dir = os.path.join(work_dir, "PyLocalInventory_Backup")
        os.makedirs(bundle_dir)
        if self.database_name:
            dump_file = pg_backup.backup_database(self.database_name, bundle_dir)
        else:
            dump_file = pg_backup.backup_schema(self.schema_name, bundle_dir)
        if not os.path.isfile(dump_file) or os.path.getsize(dump_file) <= 0:
            raise RuntimeError("The host created an invalid database backup")

        profile_manager = getattr(self.database, "profile_manager", None)
        profile = getattr(profile_manager, "selected_profile", None)
        profile_dir = (
            os.path.dirname(profile.config_path)
            if profile and getattr(profile, "config_path", None) else None
        )
        if profile_dir and os.path.isdir(profile_dir):
            for name in os.listdir(profile_dir):
                if name in ("backups", "attachments"):
                    continue
                source = os.path.join(profile_dir, name)
                destination = os.path.join(bundle_dir, name)
                if os.path.isfile(source):
                    shutil.copy2(source, destination)
                elif os.path.isdir(source):
                    shutil.copytree(source, destination)

        attachments = attachment_backup_root(self.database)
        if attachments.exists():
            shutil.copytree(
                attachments, os.path.join(bundle_dir, "attachments"),
                dirs_exist_ok=True,
            )

        archive_base = os.path.join(
            work_dir, f"PyLocalInventory_{datetime.now():%Y%m%d_%H%M%S}"
        )
        archive_path = shutil.make_archive(archive_base, "zip", bundle_dir)
        if not os.path.isfile(archive_path) or os.path.getsize(archive_path) <= 0:
            raise RuntimeError("The host created an empty backup archive")
        return archive_path

    def _dispatch(self, method, args, kwargs, user=None):
        request_db = self._borrow_database()
        try:
            cur = request_db.cursor
            conn = request_db.conn
            if cur is None or conn is None:
                raise RuntimeError('Pooled database has no cursor or connection')
            if method == 'cursor.execute':
                sql = args[0]
                params = args[1] if len(args) > 1 and args[1] else []
                cur.execute(sql, params)
                kind, _table = classify_sql(sql)
                # Each RPC borrows a different pooled connection, so leaving
                # DDL uncommitted and calling conn.commit in a later RPC cannot
                # commit the original transaction. Commit all mutating SQL in
                # the request that executed it.
                if kind in ('schema', 'write', 'delete'):
                    conn.commit()
                result = {'rowcount': cur.rowcount}
                if cur.description:
                    result['rows'] = cur.fetchall()
                    result['description'] = [d[0] for d in cur.description]
                return result

            if method == 'conn.commit':
                conn.commit()
                return None
            if method == 'conn.rollback':
                conn.rollback()
                return None

            if method == 'save_sale_with_items':
                return request_db.save_sale_with_items(*args, **kwargs, user=user)

            if method == 'get_next_devis_preview':
                return request_db.get_next_devis_preview(*args, **kwargs)

            if method in _FACTURE_METHODS:
                return getattr(request_db, method)(*args, **kwargs, user=user)

            if method == 'get_import_bl_number':
                return request_db.get_import_bl_number(*args, **kwargs)

            if method == 'get_next_bl_preview':
                return request_db.get_next_bl_preview(*args, **kwargs)

            if method == 'save_import_with_items':
                return request_db.save_import_with_items(*args, **kwargs, user=user)

            if method == 'save_product_with_opening_stock':
                return request_db.save_product_with_opening_stock(
                    *args, **kwargs, user=user
                )
            if method == 'update_product_with_stock':
                return request_db.update_product_with_stock(
                    *args, **kwargs, user=user
                )

            if method == 'get_reports':
                return request_db.get_reports(**kwargs)
            if method == 'list_report_users':
                return request_db.list_report_users()
            if method == 'save_report':
                return request_db.save_report_for_user(*args, user=user)
            if method == 'delete_report':
                return request_db.delete_report_for_user(*args, user=user)
            if method == 'get_product_stock_levels':
                return request_db.get_product_stock_levels()
            if method == 'get_dashboard_snapshot':
                snapshot = request_db.get_dashboard_snapshot()
                if not (user or {}).get("is_superadmin"):
                    permissions = (user or {}).get("permissions", {})
                    readable = lambda section: bool(
                        permissions.get(section, {}).get("read")
                    )
                    if not readable("Sales"):
                        snapshot["sales_total"] = "0"
                        snapshot["recent_activities"] = [
                            row for row in snapshot["recent_activities"]
                            if row.get("type") != "Sales"
                        ]
                        for row in snapshot["monthly"].values():
                            row["sales"] = "0"
                    if not readable("Imports"):
                        snapshot["imports_total"] = "0"
                        snapshot["recent_activities"] = [
                            row for row in snapshot["recent_activities"]
                            if row.get("type") != "Imports"
                        ]
                        for row in snapshot["monthly"].values():
                            row["imports"] = "0"
                    if not readable("Products"):
                        snapshot["products_count"] = 0
                        snapshot["low_stock_count"] = 0
                        snapshot["low_stock_products"] = []
                    if not readable("Clients"):
                        snapshot["clients_count"] = 0
                    if not readable("Suppliers"):
                        snapshot["suppliers_count"] = 0
                return snapshot
            if method in _CLIENT_ACCOUNT_METHODS:
                return getattr(request_db, method)(*args, **kwargs, user=user)
            if method in _SUPPLIER_ACCOUNT_METHODS:
                return getattr(request_db, method)(*args, **kwargs, user=user)

            if method == 'get_items' and args and args[0] in ('Sales', 'Sales_Items', 'Reports'):
                return request_db.get_items_for_user(
                    args[0], user, **kwargs
                )
            if method == 'get_operation_summary_items' and args and args[0] in ('Sales', 'Imports'):
                return request_db.get_operation_summary_items(
                    *args, user=user, **kwargs
                )
            if method == 'get_items_by_operation_id' and len(args) > 1:
                return request_db.get_operation_items_for_user(args[0], args[1], user)
            if method == 'get_items_by_operation_ids' and len(args) > 1:
                return request_db.get_items_by_operation_ids(args[0], args[1])
            if method == 'get_sale_catalog':
                return request_db.get_sale_catalog(*args, **kwargs)
            if method == 'get_attachment_thumbnail' and len(args) > 0:
                return request_db.get_attachment_thumbnail(args[0])
            if method == 'get_attachment_thumbnails_bulk' and len(args) > 0:
                return request_db.get_attachment_thumbnails_bulk(args[0])
            if method == 'add_item' and len(args) > 1 and args[1] == 'Reports':
                return request_db.save_report_for_user(None, args[0], user)
            if method == 'update_item' and len(args) > 2 and args[2] == 'Reports':
                return bool(request_db.save_report_for_user(args[0], args[1], user))
            if method == 'delete_item' and len(args) > 1 and args[1] == 'Reports':
                return request_db.delete_report_for_user(args[0], user)

            if (method in _SECTION_METHODS or method in _ATTACHMENT_METHODS
                    or method in _CLIENT_ACCOUNT_METHODS
                    or method in _SUPPLIER_ACCOUNT_METHODS
                    or method in _FACTURE_METHODS
                    or method in _REPORT_METHODS
                    or method in _PRODUCT_READ_METHODS or method in _ALWAYS_ALLOWED
                    or method in (
                        'save_product_with_opening_stock',
                        'update_product_with_stock',
                    )):
                return getattr(request_db, method)(*args, **kwargs)

            raise ValueError(f"Method not allowed over network: {method}")
        finally:
            self._return_database(request_db)

    def _make_handler(self):
        server_obj = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                self.request.settimeout(server_obj.request_timeout)
                super().setup()

            def handle(self):
                try:
                    super().handle()
                except (TimeoutError, socket.timeout):
                    logger.warning('http_header_timeout')
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    logger.info('http_peer_disconnected')

            def handle_one_request(self):
                # Socket timeouts alone are per read: a peer sending a byte
                # every few seconds could otherwise occupy a slot forever.
                self._headers_done = threading.Event()
                self._header_expired = False
                def expire_headers():
                    if not self._headers_done.is_set():
                        self._header_expired = True
                        logger.warning('http_header_deadline_exceeded')
                        try:
                            self.connection.shutdown(socket.SHUT_RD)
                        except OSError as error:
                            logger.info('http_header_shutdown_failed category=%s', type(error).__name__)
                self._header_timer = threading.Timer(server_obj.request_timeout, expire_headers)
                self._header_timer.daemon = True
                self._header_timer.start()
                try:
                    super().handle_one_request()
                finally:
                    self._headers_done.set()
                    self._header_timer.cancel()

            def parse_request(self):
                try:
                    parsed = super().parse_request()
                    if self._header_expired:
                        self.close_connection = True
                        return False
                    return parsed
                finally:
                    self._headers_done.set()
                    self._header_timer.cancel()

            def log_message(self, format, *log_args):
                pass  # keep the console output of the app clean

            def send_response(self, code, message=None):
                self._response_status = code
                super().send_response(code, message)

            def _send_json(self, status, payload):
                body = json.dumps(payload, default=str).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                if hasattr(self, '_request_id'):
                    self.send_header('X-Request-ID', self._request_id)
                self.end_headers()
                self.wfile.write(body)

            def _send_error(self, status, message):
                try:
                    self._send_json(status, {'error': message})
                except OSError as error:
                    self._error_category = 'peer_disconnected'
                    self.close_connection = True
                    logger.info('http_error_response_disconnected category=%s',
                                type(error).__name__)

            def _read_json(self):
                lengths = self.headers.get_all('Content-Length', [])
                if len(lengths) > 1:
                    raise _RequestBodyError(400, 'invalid_length', 'Invalid Content-Length')
                try:
                    length = int(lengths[0]) if lengths else 0
                except ValueError:
                    raise _RequestBodyError(400, 'invalid_length', 'Invalid Content-Length') from None
                if length < 0:
                    raise _RequestBodyError(400, 'invalid_length', 'Invalid Content-Length')
                if length > server_obj.max_request_bytes:
                    raise _RequestBodyError(413, 'body_too_large', 'Request body too large')
                server_obj._reserve_body(length)
                try:
                    chunks = []
                    remaining = length
                    # Allow slow but legitimate attachments, while bounding
                    # total upload time even when the sender trickles bytes.
                    deadline = time.monotonic() + max(server_obj.request_timeout,
                                                       length / (256 * 1024))
                    while remaining:
                        time_left = deadline - time.monotonic()
                        if time_left <= 0:
                            raise _RequestBodyError(408, 'read_timeout', 'Request body timed out')
                        self.connection.settimeout(min(server_obj.request_timeout, time_left))
                        try:
                            chunk = self.rfile.read(min(64 * 1024, remaining))
                        except (TimeoutError, socket.timeout):
                            raise _RequestBodyError(408, 'read_timeout', 'Request body timed out') from None
                        if not chunk:
                            raise _RequestBodyError(400, 'incomplete_body', 'Incomplete request body')
                        chunks.append(chunk)
                        remaining -= len(chunk)
                    raw = b''.join(chunks)
                finally:
                    server_obj._release_body(length)
                    # The last chunk may have used a short deadline-specific
                    # timeout. Do not carry that into writing the response.
                    try:
                        self.connection.settimeout(server_obj.request_timeout)
                    except OSError as error:
                        logger.info('http_socket_reset_failed category=%s', type(error).__name__)
                try:
                    result = json.loads(raw.decode('utf-8')) if raw else {}
                except (ValueError, UnicodeDecodeError):
                    raise _RequestBodyError(400, 'invalid_json', 'Invalid JSON body') from None
                if not isinstance(result, dict):
                    raise _RequestBodyError(400, 'invalid_json', 'Invalid JSON body')
                return result

            def _handle_request(self, endpoint, action):
                self._request_id = uuid.uuid4().hex[:16]
                self._response_status = 500
                self._error_category = 'none'
                started = time.perf_counter()
                httpd = server_obj._httpd
                logger.info('http_request_start id=%s endpoint=%s active=%d',
                            self._request_id, endpoint, httpd.active_requests if httpd else 0)
                try:
                    action()
                except _RequestBodyError as error:
                    self._error_category = error.category
                    self.close_connection = True
                    self._send_error(error.status, str(error))
                except PoolError:
                    self._error_category = 'database_pool'
                    self._send_error(503, 'Host database temporarily unavailable')
                except (TimeoutError, socket.timeout):
                    self._error_category = 'socket_timeout'
                    self.close_connection = True
                    self._send_error(408, 'Request timed out')
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    self._error_category = 'peer_disconnected'
                except Exception as error:
                    self._error_category = type(error).__name__
                    logger.error('http_request_failed id=%s endpoint=%s category=%s stack=%s',
                                 self._request_id, endpoint, type(error).__name__,
                                 _safe_stack(error))
                    self._send_error(500, 'Host request failed')
                finally:
                    logger.log(logging.WARNING if self._response_status >= 500 else logging.INFO,
                               'http_request_end id=%s endpoint=%s status=%d category=%s duration_ms=%.1f',
                               self._request_id, endpoint, self._response_status,
                               self._error_category, (time.perf_counter() - started) * 1000)

            def do_POST(self):
                endpoint = self.path if self.path in ('/login', '/rpc') else 'unknown'
                def action():
                    if endpoint == '/login':
                        return self._handle_login()
                    if endpoint == '/rpc':
                        return self._handle_rpc()
                    self._send_json(404, {'error': 'not found'})
                self._handle_request(endpoint, action)

            def do_GET(self):
                endpoint = self.path if self.path in ('/backup', '/health') else 'unknown'
                self._handle_request(endpoint, lambda: self._handle_get(endpoint))

            def _handle_get(self, endpoint):
                if endpoint not in ('/backup', '/health'):
                    return self._send_json(404, {'error': 'not found'})
                auth_header = self.headers.get("Authorization") or ""
                token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
                user = server_obj.sessions.get(token) if token else None
                if not user:
                    self._error_category = 'authentication'
                    return self._send_json(401, {"error": "Authentication required"})
                if endpoint == '/health':
                    health = server_obj.health_status(check_database=True)
                    health['http_responsive'] = True
                    status = 200 if all(health.values()) else 503
                    if status != 200:
                        self._error_category = 'health_unavailable'
                    return self._send_json(status, health)
                # A database backup contains every section plus account data.
                # Restrict it to the role that already administers the host.
                if not user.get("is_superadmin"):
                    self._error_category = 'permission'
                    return self._send_json(
                        403, {"error": "Only a Super Admin can create a full backup"}
                    )
                response_started = False
                try:
                    # A backup is streamed rather than buffered. Match the
                    # client's longer download timeout without weakening POSTs.
                    self.connection.settimeout(300)
                    with tempfile.TemporaryDirectory() as work_dir:
                        archive_path = server_obj._create_client_backup_archive(work_dir)
                        size = os.path.getsize(archive_path)
                        filename = os.path.basename(archive_path)
                        self.send_response(200)
                        self.send_header("Content-Type", "application/zip")
                        self.send_header("Content-Length", str(size))
                        self.send_header(
                            "Content-Disposition", f'attachment; filename="{filename}"'
                        )
                        self.end_headers()
                        response_started = True
                        with open(archive_path, "rb") as stream:
                            shutil.copyfileobj(stream, self.wfile, length=1024 * 1024)
                except Exception as error:
                    self._error_category = type(error).__name__
                    logger.error('backup_failed id=%s category=%s stack=%s',
                                 self._request_id, type(error).__name__,
                                 _safe_stack(error))
                    if not response_started:
                        self._send_error(500, str(error))

            def _handle_login(self):
                body = self._read_json()
                request_db = server_obj._borrow_database()
                catalog = {"products": [], "services": []}
                try:
                    user_manager = UserManager(request_db)
                    user = user_manager.verify_login(
                        body.get('username', ''), body.get('password', '')
                    )
                    if user:
                        permissions = user.get("permissions", {})
                        sales_access = (
                            permissions.get("Sales", {}).get("read")
                            or permissions.get("Sales", {}).get("write")
                        )
                        catalog = request_db.get_sale_catalog(
                            include_products=bool(
                                user.get("is_superadmin")
                                or sales_access
                                or permissions.get("Products", {}).get("read")
                            ),
                            include_services=bool(
                                user.get("is_superadmin")
                                or sales_access
                                or permissions.get("Services", {}).get("read")
                            ),
                            include_clients=bool(
                                user.get("is_superadmin")
                                or sales_access
                                or permissions.get("Clients", {}).get("read")
                            ),
                            include_suppliers=bool(
                                user.get("is_superadmin")
                                or permissions.get("Suppliers", {}).get("read")
                            ),
                        )
                finally:
                    server_obj._return_database(request_db)

                if not user:
                    self._error_category = 'authentication'
                    return self._send_json(401, {'error': 'Invalid username or password'})
                token = server_obj.sessions.create(user)
                selected_profile = getattr(
                    getattr(server_obj.database, "profile_manager", None),
                    "selected_profile", None,
                )
                profile_values = {}
                if selected_profile:
                    for key in (
                        "company name", "address", "email", "phone", "fax", "website",
                        "ice", "patente", "if number", "rc", "cnss", "bank name",
                        "bank account", "bank agency", "report footer", "currency",
                    ):
                        profile_values[key] = selected_profile.get_value(key)
                logger.info(
                    'login_accepted id=%s role_id=%s build_id=%s',
                    self._request_id, user.get('role_id'), APP_BUILD_ID,
                )
                self._send_json(200, {
                    'token': token,
                    'user_id': user['id'],
                    'username': user['username'],
                    'is_superadmin': user['is_superadmin'],
                    'permissions': user['permissions'],
                    'profile': profile_values,
                    'sale_catalog': catalog,
                    'build_id': APP_BUILD_ID,
                })

            def _handle_rpc(self):
                auth_header = self.headers.get('Authorization') or ''
                token = auth_header[7:] if auth_header.startswith('Bearer ') else ''
                user = server_obj.sessions.get(token) if token else None
                if not user:
                    self._error_category = 'authentication'
                    return self._send_json(401, {'error': 'Authentication required'})

                body = self._read_json()
                method = body.get('method', '')
                args = body.get('args', [])
                kwargs = body.get('kwargs', {})

                allowed, reason = _check_permission(user, method, args, kwargs)
                if not allowed:
                    self._error_category = 'permission'
                    return self._send_json(403, {'error': reason})

                try:
                    started = time.perf_counter()
                    result = server_obj._dispatch(method, args, kwargs, user=user)
                except PoolError:
                    self._error_category = 'database_pool'
                    return self._send_json(503, {'error': 'Host database temporarily unavailable'})
                except ValueError as e:
                    self._error_category = 'validation'
                    return self._send_json(400, {'error': str(e)})
                except Exception as e:
                    self._error_category = type(e).__name__
                    logger.error('rpc_failed id=%s method=%s category=%s stack=%s',
                                 self._request_id, _method_label(method), type(e).__name__,
                                 _safe_stack(e))
                    return self._send_json(500, {'error': str(e)})
                elapsed = time.perf_counter() - started
                logger.log(
                    logging.WARNING if elapsed >= 0.5 else logging.INFO,
                    'rpc_completed id=%s method=%s duration=%.3fs',
                    self._request_id, _method_label(method), elapsed,
                )
                self._send_json(200, {'result': result})

        return Handler
