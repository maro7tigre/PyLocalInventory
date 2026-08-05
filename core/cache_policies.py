"""
Single source of truth for the local caching bounds.

The client keeps two bounded cache layers (PostgreSQL on the host is the only
source of truth; both layers are optimistic display data):

* RAM session layer (core/session_cache.py) - per-tab hot view cache. It holds
  the records of the views the user is actively looking at so tab switches and
  filter/sort repeats render instantly. Because it is keyed per tab and
  evicted by LRU, its bounds are the smallest.
* Disk layer (core/cache_manager.py) - one SQLite file per PC, keyed by
  identity ("host|port|username"). It mirrors every section the client has
  fetched so tabs can render from disk on launch and only changed rows need
  re-fetching.

Invariants (asserted by tests/test_cache_policies.py)
-----------------------------------------------------
* The RAM per-view record cap and the per-tab total are both strictly below
  the disk per-section row cap: the RAM layer is a strict subset view of what
  a single section can hold on disk, so a RAM-cached view never tries to hold
  more rows than the disk layer is allowed to mirror.
* The RAM view cap (views per tab) stays below the disk view cap (views per
  identity): many tabs/identities share one SQLite file.
* DEFAULT_STALE_SECONDS (30 s) mirrors the tab-switch staleness throttle so a
  cached RAM view and the tab's refresh logic agree on when data is stale.
"""

# Master kill switch for the on-disk SQLite cache layer.
#
# The disk cache and its background incremental sync are EXPERIMENTAL. The
# full rollout dropped app stability on remote clients (GUI-thread blocking
# from the sync coordinator's synchronous per-section network calls and
# GUI-thread SQLite writes), so the layer is disabled by default until the
# regression is isolated and a controlled one-tab rollout proves it stable.
#
# When False:
#   * RemoteDatabase never opens its SQLite cache (self.cache stays None).
#   * The background SyncCoordinator is not started by MainWindow.
#   * BaseTab never reads/writes the disk cache (RAM session cache still works).
#   * HomeTab never persists or renders the dashboard from disk.
#
# All the cache code is intentionally kept in the repo behind this flag so the
# experiment can be re-enabled without rewriting anything.
ENABLE_SQLITE_CACHE = False

# RAM session layer (per tab).
RAM_MAX_VIEWS_PER_TAB = 32
RAM_MAX_RECORDS_PER_VIEW = 2000
RAM_MAX_TOTAL_RECORDS_PER_TAB = 20000

# Disk layer (per identity in the shared SQLite file).
DISK_MAX_ROWS_PER_SECTION = 100_000
DISK_MAX_VIEWS_PER_IDENTITY = 512
DISK_MAX_STOCK_ROWS = 100_000

# Cache hygiene: how long mirrored display data may live on disk before it is
# swept. Views and stock are cheap to re-fetch, so their TTL is short; record
# snapshots stay longer because a client may legitimately go weeks offline.
# Synchronized sections keep refreshing stored_at on every upsert, so actively
# synced rows are never swept.
DISK_MAX_VIEW_AGE_SECONDS = 7 * 24 * 3600
DISK_MAX_RECORD_AGE_SECONDS = 30 * 24 * 3600

# Only shrink the SQLite file (VACUUM) when it is at least this big, so small
# caches never pay the rewrite cost.
DISK_VACUUM_MIN_DB_BYTES = 16 * 1024 * 1024

# How old a cached view can be (seconds) before a background refresh starts;
# mirrors BaseTab's 30-second tab-switch refresh throttle.
DEFAULT_STALE_SECONDS = 30.0
