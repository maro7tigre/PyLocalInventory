"""
Session-scoped RAM cache of lightweight raw record dicts.

Purpose
-------
Tab switches and repeated filter/sort searches should not repeat identical
database/network requests. This module keeps the *display data* of each tab
(raw dicts returned by ``get_items``/``get_operation_summary_items``) in a
bounded, thread-safe, in-memory cache for the lifetime of the app session.

Rules (never violated)
----------------------
* Only plain dicts (raw model records), stock-level dicts and scalar cursor
  values are stored. Never QTableWidgetItems, QWidgets, connections, worker
  threads or full-size pixmaps.
* The PostgreSQL database remains the only source of truth. Cached rows are
  optimistic display data refreshed from the source in the background.
* Keyset cursors are cached per view so "Load more" can keep appending without
  re-fetching earlier pages.
* Every cache entry is bounded and the whole cache is LRU-evicted, so memory
  stays flat no matter how many searches the user runs.
"""

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Entries evicted by age before re-render (seconds); mirrors BaseTab staleness.
DEFAULT_STALE_SECONDS = 30.0


@dataclass
class CacheEntry:
    """One fully-materialized keyset-loaded view (a single search+sort key)."""

    #: Displayed raw records, in fetch order (never the probe row).
    records: List[Dict[str, Any]] = field(default_factory=list)
    #: Product stock levels for the records (None when not applicable).
    levels: Optional[Dict[int, int]] = None
    #: Whether more keyset batches exist after ``records``.
    has_more: bool = False
    #: Keyset cursor pointing after the last displayed record.
    after_id: Optional[int] = None
    after_sort: Optional[Any] = None
    #: time.monotonic() of the last source fetch that touched this entry.
    last_fetched: float = 0.0
    #: time.monotonic() of the last read/write (LRU ordering).
    last_access: float = 0.0
    #: Number of keyset batches appended so far.
    batches: int = 0

    def is_stale(self, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.monotonic()
        return now - self.last_fetched >= DEFAULT_STALE_SECONDS


class SessionCache:
    """Bounded, thread-safe cache of raw record lists keyed by view.

    One :class:`SessionCache` is owned by each tab (sections never share a
    tab), so a per-tab cache is effectively a per-section cache. All methods
    are safe to call from worker threads; critical sections are tiny.
    """

    def __init__(
        self,
        max_entries: int = 32,
        max_records_per_entry: int = 2000,
        max_total_records: int = 20000,
    ):
        self._max_entries = max_entries
        self._max_records_per_entry = max_records_per_entry
        self._max_total_records = max_total_records
        self._entries: "OrderedDict[Any, CacheEntry]" = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------ reads

    def get(self, key: Any) -> Optional[CacheEntry]:
        """Return the cached entry for ``key`` or None (touching LRU order)."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            entry.last_access = time.monotonic()
            self._entries.move_to_end(key)
            self._hits += 1
            return entry

    def __contains__(self, key: Any) -> bool:
        with self._lock:
            return key in self._entries

    # ---------------------------------------------------------------- writes

    def set_first_batch(
        self,
        key: Any,
        records: List[Dict[str, Any]],
        levels: Optional[Dict[int, int]] = None,
        has_more: bool = False,
        after_id: Optional[int] = None,
        after_sort: Optional[Any] = None,
    ) -> CacheEntry:
        """Replace the entry for ``key`` with a fresh first batch."""
        records = records[: self._max_records_per_entry]
        with self._lock:
            self._evict_if_needed(len(records))
            now = time.monotonic()
            entry = CacheEntry(
                records=list(records),
                levels=levels,
                has_more=has_more,
                after_id=after_id,
                after_sort=after_sort,
                last_fetched=now,
                last_access=now,
                batches=1,
            )
            self._entries[key] = entry
            self._entries.move_to_end(key)
            return entry

    def append_batch(
        self,
        key: Any,
        records: List[Dict[str, Any]],
        levels: Optional[Dict[int, int]] = None,
        has_more: bool = False,
        after_id: Optional[int] = None,
        after_sort: Optional[Any] = None,
    ) -> CacheEntry:
        """Extend the entry for ``key`` with the next keyset batch.

        The entry must normally already exist; if it does not (e.g. the cache
        was invalidated mid-load), a fresh entry is created from the batch so
        subsequent "Load more" calls keep a consistent cursor.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                logger.info("session_cache append on missing key=%s (created fresh)", key)
                return self.set_first_batch(
                    key, records, levels, has_more, after_id, after_sort
                )
            room = self._max_records_per_entry - len(entry.records)
            take = max(0, min(len(records), room))
            if take:
                entry.records.extend(records[:take])
            entry.has_more = has_more and len(records) <= room
            if after_id is not None:
                entry.after_id = after_id
                entry.after_sort = after_sort
            if levels is not None:
                entry.levels = levels
            entry.last_fetched = time.monotonic()
            entry.last_access = entry.last_fetched
            entry.batches += 1
            self._entries.move_to_end(key)
            return entry

    def invalidate(self, key: Optional[Any] = None) -> None:
        """Drop one view entry, or every entry when ``key`` is None."""
        with self._lock:
            if key is None:
                self._entries.clear()
            else:
                self._entries.pop(key, None)

    def clear(self) -> None:
        """Drop every entry (tab mutation, page-size change, shutdown)."""
        with self._lock:
            self._entries.clear()

    # ------------------------------------------------------------- accounting

    def _evict_if_needed(self, incoming: int) -> None:
        """Evict least-recently-used entries to honour the memory bounds."""
        while len(self._entries) >= self._max_entries:
            _oldest_key, _oldest = self._entries.popitem(last=False)
            logger.debug(
                "session_cache evicted key=%s records=%d",
                _oldest_key, len(_oldest.records),
            )
        total = incoming + sum(len(e.records) for e in self._entries.values())
        while total > self._max_total_records and self._entries:
            _oldest_key, oldest = self._entries.popitem(last=False)
            total -= len(oldest.records)
            logger.debug(
                "session_cache byte-budget eviction key=%s records=%d",
                _oldest_key, len(oldest.records),
            )

    def stats(self) -> Dict[str, Any]:
        """Snapshot of cache state for diagnostics."""
        with self._lock:
            return {
                'entries': len(self._entries),
                'records': sum(len(e.records) for e in self._entries.values()),
                'hits': self._hits,
                'misses': self._misses,
                'max_entries': self._max_entries,
                'max_records_per_entry': self._max_records_per_entry,
                'max_total_records': self._max_total_records,
            }

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
