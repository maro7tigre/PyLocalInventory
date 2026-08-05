"""
Client-side drop-in stand-in for core.database.Database, backed by a network
connection to a host running core.network.server.DatabaseServer.

Exposes the same attribute surface used throughout the app - add_item,
update_item, get_items, get_items_by_operation_id, delete_item, transactions,
plus .cursor/.conn proxies for the raw-SQL call sites - so MainWindow can set
self.database to either a real Database or a RemoteDatabase and every tab/
dialog/domain class keeps working unmodified.
"""
import json
import socket
import urllib.error
import urllib.request
import time
import os
import zipfile
import logging
from decimal import Decimal
from datetime import datetime
from core.runtime_paths import user_data_root

from core.network.protocol import (
    AuthError, ConnectionFailedError, PermissionDeniedError, RemoteError, DEFAULT_PORT
)
from core.user_manager import SECTION_GROUP
from core.build_info import APP_BUILD_ID

logger = logging.getLogger(__name__)

_ATTACHMENT_RPC_METHODS = {
    'list_attachments', 'upload_attachment', 'download_attachment',
    'get_attachment_thumbnail', 'update_attachment', 'delete_attachment',
}

class RemoteProfile:
    """Read-only report branding supplied by the connected host."""

    def __init__(self, values=None):
        self._values = dict(values or {})

    def get_value(self, key):
        return self._values.get(key)


class RemoteCursor:
    """Stands in for sqlite3.Cursor. Each .execute() is one round-trip that
    returns rows/lastrowid/rowcount together, since a real network round-trip
    per fetchone()/fetchall() call would be far too chatty."""

    def __init__(self, remote_db):
        self._remote_db = remote_db
        self._rows = []
        self._description = None
        self.lastrowid = None
        self.rowcount = -1

    def execute(self, sql, params=None):
        result = self._remote_db._call('cursor.execute', [sql, list(params) if params else []])
        rows = result.get('rows') or []
        self._rows = [tuple(r) for r in rows]
        description = result.get('description')
        self._description = [(name,) for name in description] if description else None
        self.lastrowid = result.get('lastrowid')
        self.rowcount = result.get('rowcount', -1)
        return self

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    @property
    def description(self):
        return self._description


class RemoteConnection:
    """Stands in for sqlite3.Connection - just commit()/rollback()."""

    def __init__(self, remote_db):
        self._remote_db = remote_db

    def commit(self):
        self._remote_db._call('conn.commit', [])

    def rollback(self):
        self._remote_db._call('conn.rollback', [])


class RemoteDatabase:
    """Talks to a DatabaseServer over HTTP+JSON. Every write/read is checked
    against the logged-in user's role permissions on the host - a permission
    error surfaces here as PermissionDeniedError.
    """

    def __init__(self, profile_manager, host, port, username, password):
        self.profile_manager = profile_manager
        self.host = host
        self.port = port or DEFAULT_PORT
        self.username = username
        self._password = password

        self.registered_classes = {}
        self.language = 'en'
        self._token = None
        self.permissions = {}
        self.is_superadmin = False
        self.current_user_id = None
        self.remote_profile = None
        # ``None`` means an older host did not provide a login snapshot, so
        # callers can retain the legacy RPC fallback for compatibility.
        self.sale_catalog = None
        # ``None`` means the host we connected to is running a build from
        # before build-id reporting existed - i.e. it predates this fix.
        self.host_build_id = None

        # On-disk SQLite cache of fetched records, keyed by this client
        # identity (host|port|username). Created on a successful login so it is
        # never shared across users on a shared PC. Falls back to None if the
        # cache cannot be opened - the cache is display-only, never critical.
        self.cache = None

        # Offline/read-only flag: set by the background sync when the host is
        # unreachable so tabs stop firing network refreshes that hang on a
        # dead connection and just render what the cache already holds.
        self.offline = False

        self.cursor = RemoteCursor(self)
        self.conn = RemoteConnection(self)

    def has_permission(self, section, action='read'):
        """Check the logged-in user's role permissions for a section (or a
        child table that rolls up into one, e.g. 'Sales_Items' -> 'Sales'),
        without making a network round-trip."""
        if self.is_superadmin:
            return True
        mapped = SECTION_GROUP.get(section, section)
        return bool(self.permissions.get(mapped, {}).get(action, False))

    def register_class(self, cls):
        """Mirrors Database.register_class - only needs the section name
        locally, the real table already exists on the host."""
        try:
            temp_obj = cls(0, None)
            self.registered_classes[temp_obj.section] = cls
            return True
        except Exception as e:
            print(f"✗ Failed to register {cls.__name__}: {e}")
            return False

    def connect(self):
        """Performs the login handshake. Raises AuthError / ConnectionFailedError
        / RemoteError on failure so the caller can show a clear message."""
        url = f"http://{self.host}:{self.port}/login"
        body = json.dumps({'username': self.username, 'password': self._password}).encode('utf-8')
        req = urllib.request.Request(
            url, data=body, headers={'Content-Type': 'application/json'}, method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise AuthError("Invalid username or password")
            raise RemoteError(f"Host rejected the connection ({e.code})")
        except (TimeoutError, socket.timeout):
            logger.warning("Login timed out host=%s port=%s", self.host, self.port)
            raise ConnectionFailedError("Connection timed out")
        except urllib.error.URLError as e:
            logger.warning(
                "Login connection failure host=%s port=%s error=%s",
                self.host, self.port, getattr(e, "reason", e),
            )
            reason = getattr(e, "reason", None)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise ConnectionFailedError("Connection timed out")
            if isinstance(reason, ConnectionRefusedError):
                raise ConnectionFailedError("Server unavailable")
            raise ConnectionFailedError("Unable to reach host")
        except (json.JSONDecodeError, KeyError):
            raise RemoteError("Server returned an invalid response")
        except Exception:
            logger.exception(
                "Unexpected login network error host=%s port=%s",
                self.host, self.port,
            )
            raise ConnectionFailedError("Network error")

        self._token = data['token']
        self._password = None
        self.permissions = data.get('permissions', {})
        self.is_superadmin = data.get('is_superadmin', False)
        self.current_user_id = data.get('user_id')
        self.username = data.get('username') or self.username
        self.remote_profile = RemoteProfile(data.get("profile") or {})
        self.sale_catalog = data.get("sale_catalog")
        # Absent on a host running a build from before build-id reporting -
        # i.e. that host has not been redeployed with this fix.
        self.host_build_id = data.get('build_id')
        self._open_cache()
        if self.host_build_id != APP_BUILD_ID:
            logger.warning(
                "Build mismatch: this client build_id=%s host=%s port=%s reports "
                "host_build_id=%s user=%s - if a fix isn't taking effect, redeploy "
                "the host and/or this client to matching builds.",
                APP_BUILD_ID, self.host, self.port, self.host_build_id, self.username,
            )
        else:
            logger.info(
                "Build match: client and host=%s:%s both on build_id=%s user=%s",
                self.host, self.port, APP_BUILD_ID, self.username,
            )
        return True

    def _call(self, method, args=None, kwargs=None, timeout=10):
        if not self._token:
            raise AuthError("Not connected")

        url = f"http://{self.host}:{self.port}/rpc"
        safe_args = self._json_safe(args or [])
        safe_kwargs = self._json_safe(kwargs or {})
        payload = json.dumps({'method': method, 'args': safe_args, 'kwargs': safe_kwargs}).encode('utf-8')
        if method == 'save_sale_with_items':
            sale_data = safe_args[0] if safe_args else {}
            items = safe_args[1] if len(safe_args) > 1 else []
            self._write_network_log(
                f"request_url={url} method={method} sale_id={safe_args[2] if len(safe_args) > 2 else None} "
                f"client_id={sale_data.get('client_id')} client_identifier={sale_data.get('client_username')} date={sale_data.get('date')} "
                f"vat={sale_data.get('tva')} notes_present={bool(sale_data.get('notes'))} "
                f"items_sent={len(items)} items={items}"
            )
        req = urllib.request.Request(
            url, data=payload,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {self._token}'},
            method='POST'
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                http_status = resp.status
                data = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            try:
                message = json.loads(e.read().decode('utf-8')).get('error', str(e))
            except Exception:
                message = str(e)
            if method == 'save_sale_with_items':
                self._write_network_log(
                    f"response_url={url} http_status={e.code} validation=failed error={message}"
                )
            if e.code == 401:
                raise AuthError(message)
            if e.code == 403:
                raise PermissionDeniedError(message)
            raise RemoteError(message)
        except (AuthError, PermissionDeniedError, RemoteError):
            raise
        except Exception as e:
            logger.warning(
                "LAN RPC connection failure method=%s host=%s port=%s error=%s",
                method, self.host, self.port, e,
            )
            if method == 'save_sale_with_items':
                self._write_network_log(
                    f"response_url={url} http_status=unavailable connection_error={e}"
                )
            raise ConnectionFailedError(f"Could not reach {self.host}:{self.port}: {e}")

        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.log(
            logging.WARNING if elapsed_ms >= 500 else logging.INFO,
            "LAN RPC method=%s host=%s port=%s duration_ms=%.1f build_id=%s host_build_id=%s",
            method, self.host, self.port, elapsed_ms, APP_BUILD_ID, self.host_build_id,
        )
        if method in _ATTACHMENT_RPC_METHODS or method == 'cursor.execute':
            # Extra trace for the exact operation family the sale->client
            # attachment mirror error comes from - entity/table context
            # without ever logging the base64 file payload itself.
            if method == 'cursor.execute':
                sql_preview = (str(safe_args[0]) if safe_args else '')[:160]
                detail = f"sql={sql_preview!r}"
            else:
                entity_type = safe_args[0] if len(safe_args) > 0 else None
                entity_id = safe_args[1] if len(safe_args) > 1 else None
                detail = f"entity_type={entity_type} entity_id={entity_id}"
            logger.info(
                "Attachment-path RPC detail: method=%s user=%s user_id=%s build_id=%s host_build_id=%s %s",
                method, self.username, self.current_user_id, APP_BUILD_ID, self.host_build_id, detail,
            )
        result = data.get('result')
        if method == 'save_sale_with_items':
            self._write_network_log(
                f"response_url={url} http_status={http_status} validation=ok result={self._json_safe(result)}"
            )
        return result

    def download_backup(self, destination):
        """Stream a host-generated backup to this PC using an atomic rename."""
        if not self._token:
            raise AuthError("Not connected")
        destination = os.path.abspath(os.fspath(destination))
        parent = os.path.dirname(destination)
        if not os.path.isdir(parent):
            raise ValueError("Choose an existing destination folder")
        partial = destination + ".part"
        req = urllib.request.Request(
            f"http://{self.host}:{self.port}/backup",
            headers={"Authorization": f"Bearer {self._token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as response:
                with open(partial, "wb") as stream:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        stream.write(chunk)
            if not os.path.isfile(partial) or os.path.getsize(partial) <= 0:
                raise RuntimeError("The host returned an empty backup")
            if not zipfile.is_zipfile(partial):
                raise RuntimeError("The downloaded backup archive is invalid")
            with zipfile.ZipFile(partial) as archive:
                dumps = [
                    item for item in archive.infolist()
                    if item.filename.lower().endswith((".backup", ".dump"))
                    and item.file_size > 0
                ]
                if not dumps:
                    raise RuntimeError(
                        "The downloaded archive does not contain a database backup"
                    )
                bad_member = archive.testzip()
                if bad_member:
                    raise RuntimeError(
                        f"The downloaded backup is corrupted at {bad_member}"
                    )
            os.replace(partial, destination)
            return destination
        except urllib.error.HTTPError as error:
            try:
                message = json.loads(error.read().decode("utf-8")).get(
                    "error", str(error)
                )
            except Exception:
                message = str(error)
            if error.code == 401:
                raise AuthError(message)
            if error.code == 403:
                raise PermissionDeniedError(message)
            raise RemoteError(message)
        except (AuthError, PermissionDeniedError, RemoteError):
            raise
        except Exception:
            if os.path.exists(partial):
                try:
                    os.remove(partial)
                except OSError:
                    pass
            raise

    @classmethod
    def _json_safe(cls, value):
        """Convert database/UI values to JSON primitives without losing decimals."""
        if isinstance(value, Decimal):
            return format(value, 'f')
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_safe(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _write_network_log(message):
        try:
            log_dir = os.path.join(user_data_root(), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, 'network_sales.log'), 'a', encoding='utf-8') as stream:
                stream.write(f"[{datetime.now().isoformat(timespec='seconds')}] client {message}\n")
        except OSError:
            logger.exception("Could not write network sale diagnostic log")

    def __getattr__(self, name):
        # Reached only for attributes not set in __init__: add_item, update_item,
        # get_items, get_items_by_operation_id, delete_item, begin_transaction,
        # commit_transaction, rollback_transaction - forwarded generically so the
        # server-side allow-list is the single source of truth for what's exposed.
        def _proxy(*args, **kwargs):
            return self._call(name, list(args), kwargs)
        return _proxy

    def list_attachments(self, entity_type, entity_id):
        """Return attachment metadata for one entity.

        Online: asks the host (authoritative) exactly like before. Offline:
        renders from the synced local cache so the attachment panel still
        works - rows carry only metadata (id, names, size, mime, relative
        path), never file bytes or absolute paths.
        """
        entity_id = int(entity_id)
        if bool(getattr(self, 'offline', False)):
            cache = getattr(self, 'cache', None)
            if cache is not None:
                records = cache.get_records('attachments') or {}
                return [
                    record for record in records.values()
                    if record.get('entity_type') == entity_type
                    and int(record.get('entity_id')) == entity_id
                ]
        return self._call('list_attachments', [entity_type, entity_id])

    def get_changes(self, section, since_seq=0, limit=500, timeout=4):
        """Fetch incremental changes for ``section`` since sequence
        ``since_seq``. Returns {'changes': [...], 'last_seq': N}."""
        return self._call(
            'get_changes', [section],
            {'since_seq': since_seq, 'limit': limit},
            timeout=timeout,
        )

    def sync_section(self, section, limit=500, timeout=4):
        """Pull and apply incremental changes for one section into the local
        SQLite cache, advancing the stored sync cursor.

        Returns None when the on-disk cache is unavailable. Otherwise returns
        {'applied': n, 'last_seq': m, 'has_more': bool} where ``has_more``
        means the caller should loop with the returned ``last_seq`` until it
        is False.
        """
        cache = self.cache
        if cache is None:
            return None
        since_seq = cache.get_sync_state(section) or 0
        data = self.get_changes(
            section, since_seq=since_seq, limit=limit, timeout=timeout
        )
        changes = data.get('changes') or []
        upserts = []
        deletes = []
        for change in changes:
            row_id = change.get('row_id')
            if row_id is None:
                continue
            if change.get('operation') == 'delete':
                deletes.append(row_id)
            elif change.get('payload'):
                upserts.append(change['payload'])
        if deletes:
            cache.delete_records(section, deletes)
        if upserts:
            cache.store_records(section, upserts)
        if deletes or upserts:
            cache.invalidate_views(section)
        last_seq = data.get('last_seq', since_seq)
        if last_seq != since_seq:
            cache.set_sync_state(section, last_seq)
        return {
            'applied': len(changes),
            'last_seq': last_seq,
            'has_more': len(changes) >= limit,
        }

    def _open_cache(self):
        from core.cache_manager import CacheManager
        try:
            self.cache = CacheManager(
                host=self.host, port=self.port, username=self.username
            )
        except Exception:
            logger.exception(
                "Failed to open local cache host=%s port=%s user=%s",
                self.host, self.port, self.username,
            )
            self.cache = None

    def close(self):
        if self.cache is not None:
            try:
                self.cache.close()
            except Exception:
                logger.exception("Failed to close local cache")
            self.cache = None
        self._token = None
