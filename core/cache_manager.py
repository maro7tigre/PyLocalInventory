"""
Per-client on-disk SQLite cache of raw record dicts.

Purpose
-------
The session RAM cache (core/session_cache.py) only lives for the current
process, so a remote client re-downloads every tab from the host on every
launch. This module adds a persistent, row-addressable SQLite mirror of the
records fetched from the host so tabs can render instantly from disk and only
changed rows need to be re-fetched (incremental sync comes in a later phase).

Storage model
-------------
A single database file (pylocalinventory_cache.db under user_data_root/cache)
holds several client identities side by side. ``identity`` is
"<host>|<port>|<username>", so users sharing one PC never read each other's
cached rows or cursors.

* One physical table per section, created on demand from a sanitized section
  name (e.g. cache_Products), keyed by (identity, row_id). Each row stores the
  full record dict returned by get_items/get_operation_summary_items as JSON,
  preserving calculated values (e.g. total_ht/total_ttc) exactly as the UI
  expects them.
* ``views`` persists, per identity+section+view-key, the ordered list of row
  ids and the keyset cursor so "Load more" can resume from disk.
* ``stock`` persists product stock levels keyed by product id.
* ``sync_state`` records the last synchronized sequence per identity+section
  for the incremental-sync protocol.
* ``PRAGMA user_version`` holds the schema version; a mismatched version drops
  and rebuilds the cache because it is disposable display data, never the
  source of truth.

Rules (never violated)
---------------------
* Only raw record dicts, stock dicts and cursor metadata are stored. Never
  QWidgets, pixmaps, connections or worker threads.
* PostgreSQL on the host remains the only source of truth. The cache is
  optimistic display data, refreshed from the source in the background.
* Payloads are persisted with json.dumps(default=str) - the same Decimal-to-
  string convention the network layer already uses on the wire.
* This disk layer is the durable mirror; the per-tab hot view cache lives in
  core/session_cache.py. The bounds for both layers are defined together in
  core/cache_policies.py and are strictly nested (RAM per-view cap < disk
  per-section cap).
"""

import json
import logging
import os
import re
import sqlite3
import threading
import time

from core.cache_policies import (
    DISK_MAX_ROWS_PER_SECTION,
    DISK_MAX_STOCK_ROWS,
    DISK_MAX_VIEW_AGE_SECONDS,
    DISK_MAX_RECORD_AGE_SECONDS,
    DISK_MAX_VIEWS_PER_IDENTITY,
    DISK_VACUUM_MIN_DB_BYTES,
)
from core.runtime_paths import user_data_root

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

DEFAULT_MAX_ROWS_PER_SECTION = DISK_MAX_ROWS_PER_SECTION
DEFAULT_MAX_VIEWS_PER_IDENTITY = DISK_MAX_VIEWS_PER_IDENTITY
DEFAULT_MAX_STOCK_ROWS = DISK_MAX_STOCK_ROWS
DEFAULT_MAX_VIEW_AGE_SECONDS = DISK_MAX_VIEW_AGE_SECONDS
DEFAULT_MAX_RECORD_AGE_SECONDS = DISK_MAX_RECORD_AGE_SECONDS
DEFAULT_VACUUM_MIN_DB_BYTES = DISK_VACUUM_MIN_DB_BYTES


def _safe_table_name(section):
    """Map a section name to a stable, identifier-safe table name."""
    name = re.sub(r'[^A-Za-z0-9_]', '_', str(section))
    if not name or not re.match(r'^[A-Za-z_]', name):
        name = 'Section'
    return f"cache_{name}"


class CacheManager:
    """Thread-safe SQLite cache of raw record dicts, one file for all
    identities on this PC, row-addressable per section."""

    def __init__(
        self,
        host='',
        port='',
        username='',
        db_path=None,
        max_rows_per_section=DEFAULT_MAX_ROWS_PER_SECTION,
        max_views_per_identity=DEFAULT_MAX_VIEWS_PER_IDENTITY,
        max_stock_rows=DEFAULT_MAX_STOCK_ROWS,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.identity = f"{host}|{port}|{username}"
        self.max_rows_per_section = int(max_rows_per_section)
        self.max_views_per_identity = int(max_views_per_identity)
        self.max_stock_rows = int(max_stock_rows)
        self.db_path = db_path or os.path.join(
            user_data_root(), 'cache', 'pylocalinventory_cache.db'
        )
        self._conn = None
        self._lock = threading.RLock()
        self._opened = False
        self.open()

    # --------------------------------------------------------------- lifecycle

    def open(self):
        """Open (or create) the cache database and bring it to this schema."""
        try:
            parent = os.path.dirname(self.db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            conn = sqlite3.connect(
                self.db_path, check_same_thread=False, timeout=10
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._conn = conn
            with self._lock:
                self._migrate_or_create()
                self._opened = True
            # Sweep expired display data once per launch; bounded work with the
            # section/views indexes, runs before any tab needs the cache.
            self.cleanup_expired()
            return True
        except sqlite3.Error:
            logger.exception("SQLite cache could not be opened at %s", self.db_path)
            self._conn = None
            self._opened = False
            return False

    def _migrate_or_create(self):
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            if version != 0:
                logger.warning(
                    "SQLite cache schema version %s != expected %s - rebuilding cache",
                    version, SCHEMA_VERSION,
                )
            self._drop_all()
            self._create_schema()
            self._conn.execute(f"PRAGMA user_version={int(SCHEMA_VERSION)}")
            self._conn.commit()

    def _drop_all(self):
        tables = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (table,) in tables:
            self._conn.execute(f"DROP TABLE IF EXISTS {table}")

    def _create_schema(self):
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS views("
            " identity TEXT NOT NULL,"
            " section TEXT NOT NULL,"
            " search TEXT NOT NULL,"
            " order_key TEXT NOT NULL,"
            " record_ids TEXT NOT NULL,"
            " has_more INTEGER NOT NULL,"
            " after_id INTEGER,"
            " after_sort TEXT,"
            " stored_at REAL NOT NULL,"
            " PRIMARY KEY(identity, section, search, order_key))"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS stock("
            " identity TEXT NOT NULL,"
            " product_id INTEGER NOT NULL,"
            " quantity REAL NOT NULL,"
            " stored_at REAL NOT NULL,"
            " PRIMARY KEY(identity, product_id))"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS sync_state("
            " identity TEXT NOT NULL,"
            " section TEXT NOT NULL,"
            " last_seq INTEGER NOT NULL DEFAULT 0,"
            " last_sync_at REAL NOT NULL,"
            " PRIMARY KEY(identity, section))"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS dashboard("
            " identity TEXT NOT NULL,"
            " payload TEXT NOT NULL,"
            " stored_at REAL NOT NULL,"
            " PRIMARY KEY(identity))"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS views_section_idx ON views(identity, section)"
        )

    def _ensure_section_table(self, section):
        table = _safe_table_name(section)
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS {table}("
            " identity TEXT NOT NULL,"
            " row_id INTEGER NOT NULL,"
            " payload TEXT NOT NULL,"
            " stored_at REAL NOT NULL,"
            " PRIMARY KEY(identity, row_id))"
        )
        return table

    @property
    def opened(self):
        """True when the database connection is open and usable."""
        return bool(self._opened)

    def close(self):
        """Commit, shrink if needed, and close the database connection."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.commit()
                except sqlite3.Error:
                    logger.exception("SQLite cache commit failed on close")
                self.vacuum()
                try:
                    self._conn.close()
                except sqlite3.Error:
                    logger.exception("SQLite cache close failed")
                self._conn = None
            self._opened = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    # ----------------------------------------------------------------- records

    def store_records(self, section, records):
        """Upsert a batch of raw record dicts for a section, then trim the
        section to its row cap. Returns the number of rows stored."""
        records = list(records or [])
        if not records:
            return 0
        with self._lock:
            if not self._opened:
                return 0
            table = self._ensure_section_table(section)
            now = time.time()
            try:
                for record in records:
                    row_id = record.get('ID', record.get('id'))
                    if row_id is None:
                        continue
                    self._conn.execute(
                        f"INSERT OR REPLACE INTO {table}"
                        "(identity, row_id, payload, stored_at) VALUES (?,?,?,?)",
                        (self.identity, int(row_id), json.dumps(record, default=str), now),
                    )
                self._conn.commit()
            except sqlite3.Error:
                logger.exception("SQLite cache store_records failed section=%s", section)
                return 0
            self._trim_section(section, table)
            return len(records)

    def get_records(self, section, row_ids=None):
        """Return a {row_id: record_dict} map for the requested rows (or all
        rows of this section for this identity when row_ids is None)."""
        with self._lock:
            if not self._opened:
                return {}
            table = self._ensure_section_table(section)
            try:
                if row_ids is None:
                    rows = self._conn.execute(
                        f"SELECT row_id, payload FROM {table} WHERE identity=?",
                        (self.identity,),
                    ).fetchall()
                else:
                    ids = [int(i) for i in row_ids if i is not None]
                    if not ids:
                        return {}
                    placeholders = ','.join('?' * len(ids))
                    rows = self._conn.execute(
                        f"SELECT row_id, payload FROM {table} "
                        f"WHERE identity=? AND row_id IN ({placeholders})",
                        [self.identity] + ids,
                    ).fetchall()
            except sqlite3.Error:
                logger.exception("SQLite cache get_records failed section=%s", section)
                return {}
            result = {}
            for row_id, payload in rows:
                try:
                    result[int(row_id)] = json.loads(payload)
                except (ValueError, TypeError):
                    logger.warning(
                        "SQLite cache dropped malformed payload section=%s row_id=%s",
                        section, row_id,
                    )
            return result

    def has_record(self, section, row_id):
        with self._lock:
            if not self._opened:
                return False
            table = self._ensure_section_table(section)
            try:
                row = self._conn.execute(
                    f"SELECT 1 FROM {table} WHERE identity=? AND row_id=?",
                    (self.identity, int(row_id)),
                ).fetchone()
                return row is not None
            except sqlite3.Error:
                logger.exception("SQLite cache has_record failed section=%s", section)
                return False

    def count_records(self, section):
        with self._lock:
            if not self._opened:
                return 0
            table = self._ensure_section_table(section)
            try:
                row = self._conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE identity=?",
                    (self.identity,),
                ).fetchone()
                return int(row[0]) if row else 0
            except sqlite3.Error:
                logger.exception("SQLite cache count_records failed section=%s", section)
                return 0

    def all_record_ids(self, section):
        with self._lock:
            if not self._opened:
                return []
            table = self._ensure_section_table(section)
            try:
                rows = self._conn.execute(
                    f"SELECT row_id FROM {table} WHERE identity=? ORDER BY row_id",
                    (self.identity,),
                ).fetchall()
                return [int(row[0]) for row in rows]
            except sqlite3.Error:
                logger.exception("SQLite cache all_record_ids failed section=%s", section)
                return []

    def _trim_section(self, section, table):
        try:
            count = self._conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE identity=?",
                (self.identity,),
            ).fetchone()[0]
            excess = int(count) - self.max_rows_per_section
            if excess > 0:
                self._conn.execute(
                    f"DELETE FROM {table} WHERE identity=? AND row_id IN ("
                    f"SELECT row_id FROM {table} WHERE identity=? "
                    f"ORDER BY stored_at ASC LIMIT ?)",
                    (self.identity, self.identity, excess),
                )
                self._conn.commit()
        except sqlite3.Error:
            logger.exception("SQLite cache trim failed section=%s", section)

    def delete_records(self, section, row_ids):
        """Remove specific cached rows for a section (incremental delete)."""
        ids = [int(i) for i in (row_ids or []) if i is not None]
        if not ids:
            return 0
        with self._lock:
            if not self._opened:
                return 0
            table = self._ensure_section_table(section)
            placeholders = ','.join('?' * len(ids))
            try:
                self._conn.execute(
                    f"DELETE FROM {table} WHERE identity=? AND row_id IN ({placeholders})",
                    [self.identity] + ids,
                )
                self._conn.commit()
                return len(ids)
            except sqlite3.Error:
                logger.exception("SQLite cache delete_records failed section=%s", section)
                return 0

    def invalidate_views(self, section):
        """Drop this identity's cached views for a section when its rows
        change, so the next tab refresh renders fresh data instead of a
        stale snapshot."""
        with self._lock:
            if not self._opened:
                return 0
            try:
                cursor = self._conn.execute(
                    "DELETE FROM views WHERE identity=? AND section=?",
                    (self.identity, section),
                )
                count = cursor.rowcount
                self._conn.commit()
                return int(count)
            except sqlite3.Error:
                logger.exception("SQLite cache invalidate_views failed section=%s", section)
                return 0

    def drop_section(self, section):
        """Delete this identity's cached rows and views for one section."""
        with self._lock:
            if not self._opened:
                return False
            table = self._ensure_section_table(section)
            try:
                self._conn.execute(
                    f"DELETE FROM {table} WHERE identity=?", (self.identity,)
                )
                self._conn.execute(
                    "DELETE FROM views WHERE identity=? AND section=?",
                    (self.identity, section),
                )
                self._conn.commit()
                return True
            except sqlite3.Error:
                logger.exception("SQLite cache drop_section failed section=%s", section)
                return False

    # ------------------------------------------------------------------- views

    def store_view(self, section, search, order_key, record_ids,
                   has_more=False, after_id=None, after_sort=None):
        """Persist one view entry (ordered row ids + keyset cursor)."""
        with self._lock:
            if not self._opened:
                return False
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO views"
                    "(identity, section, search, order_key, record_ids, "
                    "has_more, after_id, after_sort, stored_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        self.identity, section, search, order_key,
                        json.dumps([int(i) for i in record_ids]),
                        1 if has_more else 0, after_id, after_sort, time.time(),
                    ),
                )
                self._conn.commit()
            except sqlite3.Error:
                logger.exception(
                    "SQLite cache store_view failed section=%s order_key=%s",
                    section, order_key,
                )
                return False
            self._trim_views()
            return True

    def get_view(self, section, search, order_key):
        """Return (record_ids, has_more, after_id, after_sort, stored_at) or
        None when the view is not cached."""
        with self._lock:
            if not self._opened:
                return None
            try:
                row = self._conn.execute(
                    "SELECT record_ids, has_more, after_id, after_sort, stored_at "
                    "FROM views WHERE identity=? AND section=? AND search=? AND order_key=?",
                    (self.identity, section, search, order_key),
                ).fetchone()
            except sqlite3.Error:
                logger.exception(
                    "SQLite cache get_view failed section=%s order_key=%s",
                    section, order_key,
                )
                return None
            if row is None:
                return None
            try:
                record_ids = json.loads(row[0])
            except (ValueError, TypeError):
                record_ids = []
            return record_ids, bool(row[1]), row[2], row[3], float(row[4])

    def _trim_views(self):
        try:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM views WHERE identity=?",
                (self.identity,),
            ).fetchone()[0]
            excess = int(count) - self.max_views_per_identity
            if excess > 0:
                self._conn.execute(
                    "DELETE FROM views WHERE identity=? AND (identity, section, "
                    "search, order_key) IN ("
                    "SELECT identity, section, search, order_key FROM views "
                    "WHERE identity=? ORDER BY stored_at ASC LIMIT ?)",
                    (self.identity, self.identity, excess),
                )
                self._conn.commit()
        except sqlite3.Error:
            logger.exception("SQLite cache view trim failed")

    # ------------------------------------------------------------------- stock

    def store_stock(self, levels):
        """Upsert a {product_id: quantity} map for this identity."""
        levels = levels or {}
        if not levels:
            return 0
        with self._lock:
            if not self._opened:
                return 0
            now = time.time()
            try:
                for product_id, quantity in levels.items():
                    self._conn.execute(
                        "INSERT OR REPLACE INTO stock"
                        "(identity, product_id, quantity, stored_at) VALUES (?,?,?,?)",
                        (self.identity, int(product_id), float(quantity), now),
                    )
                self._conn.commit()
            except (sqlite3.Error, ValueError, TypeError):
                logger.exception("SQLite cache store_stock failed")
                return 0
            self._trim_stock()
            return len(levels)

    def get_stock(self, product_ids=None):
        """Return {product_id: quantity}; None means all rows for identity."""
        with self._lock:
            if not self._opened:
                return {}
            try:
                if product_ids is None:
                    rows = self._conn.execute(
                        "SELECT product_id, quantity FROM stock WHERE identity=?",
                        (self.identity,),
                    ).fetchall()
                else:
                    ids = [int(i) for i in product_ids if i is not None]
                    if not ids:
                        return {}
                    placeholders = ','.join('?' * len(ids))
                    rows = self._conn.execute(
                        f"SELECT product_id, quantity FROM stock "
                        f"WHERE identity=? AND product_id IN ({placeholders})",
                        [self.identity] + ids,
                    ).fetchall()
            except sqlite3.Error:
                logger.exception("SQLite cache get_stock failed")
                return {}
            return {int(pid): float(q) for pid, q in rows}

    def _trim_stock(self):
        try:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM stock WHERE identity=?",
                (self.identity,),
            ).fetchone()[0]
            excess = int(count) - self.max_stock_rows
            if excess > 0:
                self._conn.execute(
                    "DELETE FROM stock WHERE identity=? AND product_id IN ("
                    "SELECT product_id FROM stock WHERE identity=? "
                    "ORDER BY stored_at ASC LIMIT ?)",
                    (self.identity, self.identity, excess),
                )
                self._conn.commit()
        except sqlite3.Error:
            logger.exception("SQLite cache stock trim failed")

    # ------------------------------------------------------------- sync state

    def set_sync_state(self, section, last_seq):
        with self._lock:
            if not self._opened:
                return False
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO sync_state"
                    "(identity, section, last_seq, last_sync_at) VALUES (?,?,?,?)",
                    (self.identity, section, int(last_seq), time.time()),
                )
                self._conn.commit()
                return True
            except sqlite3.Error:
                logger.exception("SQLite cache set_sync_state failed section=%s", section)
                return False

    def get_sync_state(self, section):
        with self._lock:
            if not self._opened:
                return None
            try:
                row = self._conn.execute(
                    "SELECT last_seq FROM sync_state "
                    "WHERE identity=? AND section=?",
                    (self.identity, section),
                ).fetchone()
                return int(row[0]) if row else None
            except sqlite3.Error:
                logger.exception("SQLite cache get_sync_state failed section=%s", section)
                return None

    # ------------------------------------------------------------- dashboard

    def store_dashboard(self, snapshot):
        """Persist the latest dashboard snapshot for this identity so an
        offline client can still render the Home tab. ``snapshot`` is a plain
        dict of JSON-safe values; returns True on success."""
        with self._lock:
            if not self._opened:
                return False
            try:
                self._conn.execute(
                    "INSERT INTO dashboard(identity, payload, stored_at) "
                    "VALUES (?,?,?) "
                    "ON CONFLICT(identity) DO UPDATE SET "
                    "payload=excluded.payload, stored_at=excluded.stored_at",
                    (self.identity, json.dumps(snapshot or {}, default=str), time.time()),
                )
                self._conn.commit()
                return True
            except sqlite3.Error:
                logger.exception("SQLite cache store_dashboard failed")
                return False

    def get_dashboard(self):
        """Return (snapshot, stored_at) for this identity, or (None, None)
        when nothing has been cached yet or the cache is unavailable."""
        with self._lock:
            if not self._opened:
                return None, None
            try:
                row = self._conn.execute(
                    "SELECT payload, stored_at FROM dashboard WHERE identity=?",
                    (self.identity,),
                ).fetchone()
            except sqlite3.Error:
                logger.exception("SQLite cache get_dashboard failed")
                return None, None
            if row is None:
                return None, None
            try:
                return json.loads(row[0]), row[1]
            except (ValueError, TypeError):
                return None, None

    # -------------------------------------------------------------- accounting

    def clear_identity(self):
        """Remove every cached row, view, stock entry and sync cursor for this
        identity (used when the user logs out or switches connection)."""
        with self._lock:
            if not self._opened:
                return False
            try:
                sections = self._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name LIKE 'cache\\_%' ESCAPE '\\'"
                ).fetchall()
                for (table,) in sections:
                    self._conn.execute(
                        f"DELETE FROM {table} WHERE identity=?", (self.identity,)
                    )
                self._conn.execute(
                    "DELETE FROM views WHERE identity=?", (self.identity,)
                )
                self._conn.execute(
                    "DELETE FROM stock WHERE identity=?", (self.identity,)
                )
                self._conn.execute(
                    "DELETE FROM sync_state WHERE identity=?", (self.identity,)
                )
                self._conn.execute(
                    "DELETE FROM dashboard WHERE identity=?", (self.identity,)
                )
                self._conn.commit()
                return True
            except sqlite3.Error:
                logger.exception("SQLite cache clear_identity failed")
                return False

    def stats(self):
        """Snapshot of cached row/view/stock counts for this identity."""
        with self._lock:
            if not self._opened:
                return {'opened': False, 'db_path': self.db_path}
            sections = []
            for (table,) in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name LIKE 'cache\\_%' ESCAPE '\\'"
            ).fetchall():
                try:
                    count = self._conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE identity=?",
                        (self.identity,),
                    ).fetchone()[0]
                except sqlite3.Error:
                    count = 0
                if count:
                    sections.append({'section': table, 'rows': int(count)})
            views = self._conn.execute(
                "SELECT COUNT(*) FROM views WHERE identity=?",
                (self.identity,),
            ).fetchone()[0]
            stock = self._conn.execute(
                "SELECT COUNT(*) FROM stock WHERE identity=?",
                (self.identity,),
            ).fetchone()[0]
            size = 0
            try:
                size = os.path.getsize(self.db_path)
            except OSError:
                pass
            return {
                'opened': True,
                'db_path': self.db_path,
                'identity': self.identity,
                'sections': sections,
                'views': int(views),
                'stock_rows': int(stock),
                'db_bytes': size,
            }

    # --------------------------------------------------------------- hygiene

    def cleanup_expired(self, view_max_age=DEFAULT_MAX_VIEW_AGE_SECONDS,
                        record_max_age=DEFAULT_MAX_RECORD_AGE_SECONDS):
        """TTL sweep for this identity: drop views and stock older than
        ``view_max_age`` seconds and record rows older than ``record_max_age``.

        Returns the total number of rows removed. Best-effort - never raises,
        and a failure only skips the sweep.
        """
        removed = 0
        with self._lock:
            if not self._opened:
                return 0
            now = time.time()
            try:
                view_cutoff = now - view_max_age
                record_cutoff = now - record_max_age
                removed += self._conn.execute(
                    "DELETE FROM views WHERE identity=? AND stored_at < ?",
                    (self.identity, view_cutoff),
                ).rowcount
                removed += self._conn.execute(
                    "DELETE FROM stock WHERE identity=? AND stored_at < ?",
                    (self.identity, view_cutoff),
                ).rowcount
                for (table,) in self._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name LIKE 'cache\\_%' ESCAPE '\\'"
                ).fetchall():
                    removed += self._conn.execute(
                        f"DELETE FROM {table} WHERE identity=? AND stored_at < ?",
                        (self.identity, record_cutoff),
                    ).rowcount
                self._conn.commit()
            except sqlite3.Error:
                logger.exception("SQLite cache cleanup_expired failed")
                return 0
        return removed

    def vacuum(self, min_db_bytes=DEFAULT_VACUUM_MIN_DB_BYTES):
        """Shrink the SQLite file with VACUUM, but only when the file is at
        least ``min_db_bytes`` so small caches never pay the rewrite cost.

        Returns bytes freed, or 0 when skipped or failed. Never raises.
        """
        with self._lock:
            if not self._opened:
                return 0
            try:
                size = os.path.getsize(self.db_path)
            except OSError:
                return 0
            if size < min_db_bytes:
                return 0
            try:
                self._conn.execute("VACUUM")
            except sqlite3.Error:
                logger.exception("SQLite cache vacuum failed")
                return 0
            try:
                after = os.path.getsize(self.db_path)
            except OSError:
                after = size
            return max(0, size - after)

    def hygiene(self, view_max_age=DEFAULT_MAX_VIEW_AGE_SECONDS,
                record_max_age=DEFAULT_MAX_RECORD_AGE_SECONDS,
                vacuum=True, min_db_bytes=DEFAULT_VACUUM_MIN_DB_BYTES):
        """Run the TTL sweep and (optionally) an opportunistic vacuum.

        Returns {'removed': rows_swept, 'vacuum_freed_bytes': bytes_freed}.
        Best-effort - never raises.
        """
        removed = self.cleanup_expired(view_max_age, record_max_age)
        freed = self.vacuum(min_db_bytes=min_db_bytes) if vacuum else 0
        return {'removed': removed, 'vacuum_freed_bytes': freed}
