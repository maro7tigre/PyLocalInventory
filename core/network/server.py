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
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from psycopg2.pool import ThreadedConnectionPool

from core.database import Database
from core import pg_backup
from core.attachments import attachment_backup_root
from core.pg_config import load_server_config
from core.user_manager import UserManager, SECTION_GROUP
from core.network.protocol import classify_sql, DEFAULT_PORT
from core.runtime_paths import user_data_root
from core.build_info import APP_BUILD_ID

logger = logging.getLogger(__name__)

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
    'get_attachment': ('read', 1),              # get_attachment(attachment_id)
    'get_attachment_thumbnail': ('read', 1),    # get_attachment_thumbnail(attachment_id)
    'get_attachment_thumbnails_bulk': ('read', 1),  # get_attachment_thumbnails_bulk(attachment_ids)
    'update_attachment': ('write', 4),          # update_attachment(attachment_id, display_name, description, category),
    'list_attachments': ('read', 0),            # list_attachments(entity_type, entity_id)
    'upload_attachment': ('write', 0),          # upload_attachment(entity_type, entity_id, ...)
    'download_attachment': ('read', None),      # download_attachment(attachment_id) - no owner arg
    'delete_attachment': ('delete', None),      # delete_attachment(attachment_id) - no owner arg
}
_CLIENT_ACCOUNT_METHODS = {
    'get_client_account', 'get_client_sales', 'get_client_sale_summaries',
    'get_client_sale_items', 'add_client_payment', 'update_client_payment',
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
_PRODUCT_READ_METHODS = {
    'get_product_stock_levels', 'get_product_stock_levels_for_product_ids',
    'get_product_stock_history',
}
# Internal financial analytics: revenue needs Sales read, purchase costs are
# Imports data - seeing COGS/profit requires both. Enforced here so an
# unauthorized client cannot even request the data (the backend filters the
# snapshot per-metric as a second layer).
_FINANCIAL_ANALYTICS_METHODS = {'get_sale_profitability', 'get_analytics_snapshot'}

# Charges / Operating Expenses
_CHARGE_METHODS = {
    'get_charge_categories', 'add_charge_category', 'update_charge_category',
    'delete_charge_category', 'get_charges', 'get_charge', 'save_charge',
    'delete_charge', 'get_recurring_templates', 'get_due_recurring_charges',
    'confirm_recurring_charge', 'save_recurring_template', 'delete_recurring_template',
    'get_charge_summary',
}
_ALWAYS_ALLOWED = {
    'begin_transaction', 'commit_transaction', 'rollback_transaction',
    'get_dashboard_snapshot',
}
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

    if method in _FINANCIAL_ANALYTICS_METHODS:
        if method == 'get_sale_profitability':
            # Internal per-sale cost/profit view: revenue is Sales data,
            # purchase costs are Imports data. Both reads are required.
            if not user['permissions'].get('Sales', {}).get('read'):
                return False, "You don't have read access to Sales"
            if not user['permissions'].get('Imports', {}).get('read'):
                return False, "You don't have read access to Imports"
            return True, None
        # get_analytics_snapshot is callable by any authenticated user; the
        # backend strips every metric group the caller's role may not read
        # (same model as get_dashboard_snapshot), so the response only ever
        # contains permitted data.
        return True, None

    if method in _CHARGE_METHODS:
        # Charges/Operating Expenses: revenue is Sales data, purchase costs are
        # Imports data, charges are Charges data. For write operations, both
        # Sales and Charges write are required; for read, Charges read is minimum.
        if method in ('get_charges', 'get_charge', 'get_charge_summary',
                      'get_recurring_templates', 'get_due_recurring_charges',
                      'get_charge_categories'):
            if not user['permissions'].get('Charges', {}).get('read'):
                return False, "You don't have read access to Charges"
            return True, None
        if method in ('delete_charge', 'delete_recurring_template',
                      'delete_charge_category'):
            if not (user['permissions'].get('Charges', {}).get('read')
                    and user['permissions'].get('Charges', {}).get('delete')):
                return False, "You don't have delete access to Charges"
            return True, None
        if method in ('save_charge', 'confirm_recurring_charge',
                      'save_recurring_template', 'add_charge_category',
                      'update_charge_category'):
            if not (user['permissions'].get('Charges', {}).get('read')
                    and user['permissions'].get('Charges', {}).get('write')):
                return False, "You don't have write access to Charges"
            return True, None
        # get_charge_summary and get_recurring_templates also need Charges read
        if not user['permissions'].get('Charges', {}).get('read'):
            return False, "You don't have read access to Charges"
        return True, None

    if method == 'get_next_devis_preview':
        # Read-only advisory Devis proposal; gated by Sales read/write access.
        if not (user['permissions'].get('Sales', {}).get('read')
                or user['permissions'].get('Sales', {}).get('write')):
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
                "Permission denied (no section mapping): build_id=%s user_id=%s role_id=%s "
                "is_superadmin=%s method=%s table=%r normalized_section=%s mode=remote",
                APP_BUILD_ID, user.get('id'), user.get('role_id'), user.get('is_superadmin'),
                method, table, section,
            )
            return False, f"No permission mapping for table '{table}' - contact your admin"
        if section == "Reports" and kind == "read":
            return False, "Reports must be read through the ownership-filtered API"
        needed = _ACTION_FOR_KIND[kind]
        if not user['permissions'].get(section, {}).get(needed):
            logger.warning(
                "Permission denied (insufficient access): build_id=%s user_id=%s role_id=%s "
                "is_superadmin=%s method=%s table=%r normalized_section=%s needed=%s mode=remote",
                APP_BUILD_ID, user.get('id'), user.get('role_id'), user.get('is_superadmin'),
                method, table, section, needed,
            )
            return False, f"You don't have {needed} access to {section}"
        if table and table.rsplit('.', 1)[-1].casefold() in ('sales', 'clients'):
            logger.info(
                "Permission granted: build_id=%s user_id=%s method=%s table=%r "
                "normalized_section=%s needed=%s mode=remote",
                APP_BUILD_ID, user.get('id'), method, table, section, needed,
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
            workflow_section = 'Imports' if section == 'Suppliers' else 'Sales'
            workflow_allowed = (
                user['permissions'].get(workflow_section, {}).get('read')
                or user['permissions'].get(workflow_section, {}).get('write')
            )
            if (wanted and not user['permissions'].get(section, {}).get('read')
                    and not workflow_allowed):
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
        client_id = args[0] if args else None
        if not user['permissions'].get('Clients', {}).get('read'):
            logger.warning(
                "Permission denied (client account): build_id=%s user_id=%s role_id=%s "
                "method=%s client_id=%s needed=Clients:read mode=remote",
                APP_BUILD_ID, user.get('id'), user.get('role_id'), method, client_id,
            )
            return False, "You don't have read access to Clients"
        if (method in _CLIENT_PAYMENT_WRITE_METHODS
                and not user['permissions'].get('Sales', {}).get('write')):
            logger.warning(
                "Permission denied (client account): build_id=%s user_id=%s role_id=%s "
                "method=%s client_id=%s needed=Sales:write mode=remote",
                APP_BUILD_ID, user.get('id'), user.get('role_id'), method, client_id,
            )
            return False, "You don't have write access to Sales"
        logger.info(
            "Permission granted (client account): build_id=%s user_id=%s role_id=%s "
            "method=%s client_id=%s permission_filter=Clients:read-only "
            "(no created_by ownership filter applied) mode=remote",
            APP_BUILD_ID, user.get('id'), user.get('role_id'), method, client_id,
        )
        return True, None

    if method in _SUPPLIER_ACCOUNT_METHODS:
        supplier_id = args[0] if args else None
        if not user['permissions'].get('Suppliers', {}).get('read'):
            logger.warning(
                "Permission denied (supplier account): build_id=%s user_id=%s role_id=%s "
                "method=%s supplier_id=%s needed=Suppliers:read mode=remote",
                APP_BUILD_ID, user.get('id'), user.get('role_id'), method, supplier_id,
            )
            return False, "You don't have read access to Suppliers"
        if (method in _SUPPLIER_PAYMENT_WRITE_METHODS
                and not user['permissions'].get('Imports', {}).get('write')):
            logger.warning(
                "Permission denied (supplier account): build_id=%s user_id=%s role_id=%s "
                "method=%s supplier_id=%s needed=Imports:write mode=remote",
                APP_BUILD_ID, user.get('id'), user.get('role_id'), method, supplier_id,
            )
            return False, "You don't have write access to Imports"
        logger.info(
            "Permission granted (supplier account): build_id=%s user_id=%s role_id=%s "
            "method=%s supplier_id=%s permission_filter=Suppliers:read-only "
            "(no created_by ownership filter applied) mode=remote",
            APP_BUILD_ID, user.get('id'), user.get('role_id'), method, supplier_id,
        )
        return True, None

    if method in _ATTACHMENT_METHODS:
        kind, index = _ATTACHMENT_METHODS[method]
        if index is None:
            permitted = any(
                user['permissions'].get(section, {}).get(_ACTION_FOR_KIND[kind])
                for section in ('Clients', 'Sales', 'Charges')
            )
        else:
            entity = args[index] if len(args) > index else ''
            section = {
                'client': 'Clients', 'sale': 'Sales', 'charge': 'Charges'
            }.get(entity)
            permitted = bool(section and user['permissions'].get(section, {}).get(_ACTION_FOR_KIND[kind]))
        if not permitted:
            return False, "You don't have permission to manage these attachments"
        return True, None

    return False, f"Method '{method}' is not permitted over the network"


# Bounded lock waits for pooled RPC connections (mirrors
# core.database._CONNECTION_OPTIONS): a blocked query must fail with an
# error the client can display, never hang a host session forever.
_POOL_CONNECTION_OPTIONS = "-c lock_timeout=8000"


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
                connect_timeout=5,
                options=_POOL_CONNECTION_OPTIONS,
                application_name="PyLocalInventory-LAN",
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
                options=f'-c search_path={schema_name} '
                        f'{_POOL_CONNECTION_OPTIONS}',
                connect_timeout=5,
                application_name="PyLocalInventory-LAN",
            )

        self._httpd = ThreadingHTTPServer(('0.0.0.0', self.port), self._make_handler())
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        logger.info(
            "LAN server started: build_id=%s port=%s database_name=%s schema_name=%s",
            APP_BUILD_ID, self.port, self.database_name, self.schema_name,
        )

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
        try:
            request_db = Database(profile_manager=None)
            request_db.registered_classes = self.database.registered_classes
            request_db.database_name = self.database_name
            request_db.schema_name = self.schema_name
            request_db.conn = conn
            request_db.cursor = conn.cursor()
            return request_db
        except Exception:
            logger.exception("Failed to initialize pooled request database")
            try:
                self._pool.putconn(conn, close=True)
            except Exception:
                logger.exception("Failed to discard unusable pooled connection")
            raise

    def _return_database(self, request_db):
        connection = request_db.conn
        try:
            request_db.cursor.close()
        except Exception:
            logger.exception("Failed to close pooled request cursor")
        try:
            # PostgreSQL starts a transaction even for SELECT. Reset it before
            # returning the connection so it cannot remain idle in transaction.
            if connection and not getattr(connection, "closed", False):
                rollback = getattr(connection, "rollback", None)
                if callable(rollback):
                    rollback()
                self._pool.putconn(connection)
            else:
                try:
                    self._pool.putconn(connection, close=True)
                except TypeError:
                    self._pool.putconn(connection)
        except Exception:
            logger.exception("Failed to reset pooled database connection")
            try:
                try:
                    self._pool.putconn(connection, close=True)
                except TypeError:
                    self._pool.putconn(connection)
            except Exception:
                logger.exception("Failed to discard broken pooled connection")

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

            if method == 'get_next_devis_preview':
                return request_db.get_next_devis_preview(*args, **kwargs)

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
            if method == 'get_product_stock_history':
                return request_db.get_product_stock_history(*args, **kwargs)
            if method == 'get_sale_profitability':
                return request_db.get_sale_profitability(*args, **kwargs, user=user)
            if method == 'get_analytics_snapshot':
                return request_db.get_analytics_snapshot(*args, **kwargs, user=user)
            if method == 'get_dashboard_snapshot':
                snapshot = request_db.get_dashboard_snapshot()
                if not user.get("is_superadmin"):
                    permissions = user.get("permissions", {})
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

            # Charges / Operating Expenses
            if method in _CHARGE_METHODS:
                return getattr(request_db, method)(*args, **kwargs, user=user)

            if (method in _SECTION_METHODS or method in _ATTACHMENT_METHODS
                    or method in _CLIENT_ACCOUNT_METHODS
                    or method in _SUPPLIER_ACCOUNT_METHODS
                    or method in _REPORT_METHODS
                    or method in _PRODUCT_READ_METHODS or method in _ALWAYS_ALLOWED
                    or method in _CHARGE_METHODS
                    or method in (
                        'save_product_with_opening_stock',
                        'update_product_with_stock',
                    )):
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
            logger.exception("Could not write server sale diagnostic log")

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

            def do_GET(self):
                if self.path != "/backup":
                    return self._send_json(404, {"error": "not found"})
                auth_header = self.headers.get("Authorization") or ""
                token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
                user = server_obj.sessions.get(token) if token else None
                if not user:
                    return self._send_json(401, {"error": "Authentication required"})
                # A database backup contains every section plus account data.
                # Restrict it to the role that already administers the host.
                if not user.get("is_superadmin"):
                    return self._send_json(
                        403, {"error": "Only a Super Admin can create a full backup"}
                    )
                response_started = False
                try:
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
                    if not response_started:
                        self._send_json(500, {"error": str(error)})

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
                    return self._send_json(401, {'error': 'Invalid username or password'})
                token = server_obj.sessions.create(user)
                selected_profile = getattr(
                    getattr(server_obj.database, "profile_manager", None),
                    "selected_profile", None,
                )
                profile_values = {}
                if selected_profile:
                    for key in (
                        "company name", "address", "email", "phone",
                        "report footer", "currency",
                    ):
                        profile_values[key] = selected_profile.get_value(key)
                logger.info(
                    "Login accepted: user_id=%s username=%s role_id=%s is_superadmin=%s "
                    "build_id=%s remote_addr=%s",
                    user['id'], user['username'], user.get('role_id'), user['is_superadmin'],
                    APP_BUILD_ID, self.client_address[0] if self.client_address else None,
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
                    return self._send_json(401, {'error': 'Authentication required'})

                body = self._read_json()
                method = body.get('method', '')
                args = body.get('args', [])
                kwargs = body.get('kwargs', {})
                is_save_call = method in ('save_sale_with_items', 'save_import_with_items')
                if is_save_call:
                    # TEMPORARY Sale Save freeze diagnostic - see core/sale_save_diagnostics.py.
                    from core import sale_save_diagnostics
                    sale_save_diagnostics.event(
                        "RPC_REQUEST_RECEIVED", method=method, user=user.get('username'),
                    )

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
                    if is_save_call:
                        sale_save_diagnostics.event(
                            "RPC_REQUEST_END", method=method, result="permission_denied", reason=reason,
                        )
                    return self._send_json(403, {'error': reason})

                try:
                    started = time.perf_counter()
                    if is_save_call:
                        sale_save_diagnostics.event("SERVER_DISPATCH_START", method=method)
                    result = server_obj._dispatch(method, args, kwargs, user=user)
                    if is_save_call:
                        sale_save_diagnostics.event("SERVER_DISPATCH_END", method=method, result="ok")
                except ValueError as e:
                    if method == 'save_sale_with_items':
                        server_obj._write_sales_log(f"validation=failed transaction=rollback error={e}")
                    if is_save_call:
                        sale_save_diagnostics.event(
                            "SERVER_DISPATCH_END", method=method, result="value_error", error=str(e),
                        )
                    return self._send_json(400, {'error': str(e)})
                except Exception as e:
                    if method == 'save_sale_with_items':
                        server_obj._write_sales_log(f"validation_or_transaction=rollback error={e}")
                    if is_save_call:
                        sale_save_diagnostics.event(
                            "SERVER_DISPATCH_END", method=method, result="exception", error=str(e),
                        )
                    logger.exception(
                        "LAN RPC failed method=%s user=%s",
                        method, user.get("username"),
                    )
                    return self._send_json(500, {'error': str(e)})
                elapsed = time.perf_counter() - started
                logger.log(
                    logging.WARNING if elapsed >= 0.5 else logging.INFO,
                    "LAN RPC method=%s user=%s duration=%.3fs",
                    method, user.get("username"), elapsed,
                )
                if method == 'save_sale_with_items':
                    server_obj._write_sales_log(f"validation=ok transaction=commit result={result}")
                if is_save_call:
                    sale_save_diagnostics.event(
                        "RPC_REQUEST_END", method=method, result="ok", elapsed_ms=round(elapsed * 1000, 1),
                    )
                self._send_json(200, {'result': result})

        return Handler
