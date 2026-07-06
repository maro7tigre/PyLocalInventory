"""
Shared types for the LAN client/server database link (core.network.server /
core.network.client). Transport is plain HTTP+JSON so both sides only need
the Python standard library.
"""
import re

DEFAULT_PORT = 8765


class RemoteError(Exception):
    """Base class for errors surfaced from the network database link."""


class AuthError(RemoteError):
    """Login failed, or the session token is missing/invalid/expired."""


class PermissionDeniedError(RemoteError):
    """The authenticated user's role does not allow the requested action."""


class ConnectionFailedError(RemoteError):
    """The host could not be reached at all (wrong host/port, offline, etc.)."""


_SCHEMA_VERBS = {'PRAGMA', 'CREATE', 'ALTER', 'DROP', 'BEGIN', 'COMMIT', 'ROLLBACK'}


def classify_sql(sql):
    """Classify a raw SQL statement for permission checking.

    Returns (kind, table_name) where kind is one of:
      - 'schema': PRAGMA/CREATE/ALTER/DROP/transaction control - always allowed,
        these are idempotent internal bookkeeping (e.g. lazy column migrations),
        not user-driven data changes.
      - 'read' / 'write' / 'delete': SELECT / INSERT+UPDATE / DELETE, with the
        best-effort table name extracted so the caller can map it to a section.
        table_name is None if it couldn't be determined (callers should treat
        that as "unknown, deny by default").
    """
    stripped = sql.strip()
    upper = stripped.upper()
    first_word = upper.split(None, 1)[0] if upper else ''

    if first_word in _SCHEMA_VERBS:
        return 'schema', None

    if first_word == 'SELECT':
        m = re.search(r'\bFROM\s+[\'"`]?(\w+)', stripped, re.IGNORECASE)
        return 'read', (m.group(1) if m else None)
    if first_word == 'INSERT':
        m = re.search(r'\bINTO\s+[\'"`]?(\w+)', stripped, re.IGNORECASE)
        return 'write', (m.group(1) if m else None)
    if first_word == 'UPDATE':
        m = re.search(r'\bUPDATE\s+[\'"`]?(\w+)', stripped, re.IGNORECASE)
        return 'write', (m.group(1) if m else None)
    if first_word == 'DELETE':
        m = re.search(r'\bFROM\s+[\'"`]?(\w+)', stripped, re.IGNORECASE)
        return 'delete', (m.group(1) if m else None)

    # Anything else unrecognized: treat as schema/internal rather than guessing
    # at a table-based permission we can't actually determine.
    return 'schema', None
