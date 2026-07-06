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
import urllib.error
import urllib.request

from core.network.protocol import (
    AuthError, ConnectionFailedError, PermissionDeniedError, RemoteError, DEFAULT_PORT
)


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

        self.cursor = RemoteCursor(self)
        self.conn = RemoteConnection(self)

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
        except Exception as e:
            raise ConnectionFailedError(f"Could not reach {self.host}:{self.port}: {e}")

        self._token = data['token']
        self.permissions = data.get('permissions', {})
        self.is_superadmin = data.get('is_superadmin', False)
        return True

    def _call(self, method, args=None, kwargs=None):
        if not self._token:
            raise AuthError("Not connected")

        url = f"http://{self.host}:{self.port}/rpc"
        payload = json.dumps({'method': method, 'args': args or [], 'kwargs': kwargs or {}}).encode('utf-8')
        req = urllib.request.Request(
            url, data=payload,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {self._token}'},
            method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            try:
                message = json.loads(e.read().decode('utf-8')).get('error', str(e))
            except Exception:
                message = str(e)
            if e.code == 401:
                raise AuthError(message)
            if e.code == 403:
                raise PermissionDeniedError(message)
            raise RemoteError(message)
        except (AuthError, PermissionDeniedError, RemoteError):
            raise
        except Exception as e:
            raise ConnectionFailedError(f"Could not reach {self.host}:{self.port}: {e}")

        return data.get('result')

    def __getattr__(self, name):
        # Reached only for attributes not set in __init__: add_item, update_item,
        # get_items, get_items_by_operation_id, delete_item, begin_transaction,
        # commit_transaction, rollback_transaction - forwarded generically so the
        # server-side allow-list is the single source of truth for what's exposed.
        def _proxy(*args, **kwargs):
            return self._call(name, list(args), kwargs)
        return _proxy

    def close(self):
        self._token = None
