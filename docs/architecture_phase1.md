# Phase 1 — Architecture Documentation (as-built)

Goal of the hybrid local-first effort: keep PostgreSQL on the Host as the single
authoritative source, add a per-client on-disk SQLite cache plus a bounded RAM
cache and incremental sync, so remote Client PCs stop freezing/crashing from
repeated full re-downloads. This document captures the current architecture
*before* any of that code is written. Written at BUILD_ID
`sales-table-total-ht-ttc-2026-08-05-v1`. Baseline: 129 unit tests pass.

The caching/sync work (phases 3-14: incremental sync, offline read mode,
attachment metadata sync, Home dashboard cache, and filter-aware Reports
cache) shipped in BUILD_ID `sales-table-total-ht-ttc-2026-08-05-v2`; the full
suite is 229 unit tests (run with `QT_QPA_PLATFORM=offscreen`).

---

## 1. Entry point and startup flow

`main.py` → `setup_logging()` → `QApplication` → `apply_dark_theme()` →
`MainWindow()` → `window.show()` → `app.exec()`. The `--verify-report` flag
short-circuits into `core.report_verification.generate_verification_report()`.

`MainWindow.__init__` (`ui/main_window.py`):
1. Loads `QSettings` (geometry, profiles_path, language, warning toggles, tab
   visibility) and per-user settings (`core/user_settings.py`).
2. Creates `ProfileManager()` and `PasswordManager()`.
3. `connection_mode` is `'client'` if a remembered network connection exists,
   else `'standalone'`.
4. Creates a real `Database(self.profile_manager)` and registers all parameter
   classes (`register_parameter_classes()`).
5. Builds menus, then `refresh_app()` decides which screen to show.

`refresh_app()` screens:
- standalone, no profile / not validated → `setup_profile_selection()`
  (`WelcomeWidget`, signal `network_login_requested` → `start_network_login`).
- standalone, profile remembered → `setup_password_entry()` (`PasswordWidget`).
- client mode, not connected → `setup_network_unlock()` or `setup_login_entry()`
  (`LoginWidget`); `login_submitted(host, port, username, password, remember,
  startup)` → `attempt_network_login`.
- valid → `setup_main_tabs()`.

## 2. Network login (client side)

`attempt_network_login` (`ui/main_window.py:494`):
1. Validates port 1–65535.
2. Creates `RemoteDatabase(profile_manager, host, port, username, password)` and
   calls `.connect()` (`core/network/client.py:143`) → `POST /login`; on success
   stores token, permissions, is_superadmin, current_user_id, remote_profile,
   sale_catalog, host_build_id. Errors: `AuthError` / `ConnectionFailedError` /
   `RemoteError`.
3. Persists/clears remembered connection and startup registration.
4. Swaps `self.database = remote_db`, re-registers classes, warns on host/client
   BUILD_ID mismatch, calls `refresh_app()` → `setup_main_tabs()`.

## 3. Main tab construction and startup preload

`setup_main_tabs()` (`ui/main_window.py:559`):
- Standalone only: `self.database.connect()` (PostgreSQL handshake + schema
  creation/migrations).
- Builds a `QTabWidget`; Home tab plus entity tabs (Products, Services, Clients,
  Suppliers, Sales, Imports, Reports). An entity tab is only created when
  `self.database.has_permission(section, 'read')` is true.
- `currentChanged` → `on_tab_changed` → `tab.refresh_on_tab_switch()`.
- **Startup preload**: every readable tab gets `refresh_table()` called
  immediately. Each call spawns its own background `QThread` fetch, so on a
  remote client 6–8 full HTTP batch round-trips fire at login, one per tab.

## 4. Host / server startup

The Host is a normal instance (typically super-admin) with a real
`Database` connected to PostgreSQL. Hosting is toggled in
`NetworkDialog` (focus_tab=1), which starts `DatabaseServer.start()`
(`core/network/server.py:264`):
- Reads `core/pg_config.load_server_config()`.
- Builds a `psycopg2.pool.ThreadedConnectionPool(2, 10)` to the selected
  profile's database (`database_name`) or shared database with
  `options=-c search_path=<schema>`.
- Starts `ThreadingHTTPServer(('0.0.0.0', port))` serving:
  - `POST /login` — `UserManager.verify_login`, builds permission snapshot +
    sale catalog, issues a token (`_SessionStore`, in-memory).
  - `POST /rpc` — auth + `_check_permission` + `_dispatch`.
  - `GET /backup` — super-admin only, streams a host-generated archive.
- Each request: `_borrow_database()` checks out a pooled connection wrapped in a
  throwaway `Database(profile_manager=None)` that shares the host's
  `registered_classes`; `_return_database()` resets (rollback) and returns the
  connection. Per-request connections → MVCC concurrency, no shared cursor.

## 5. Client RPC surface (`core/network/client.py`)

`RemoteDatabase` is a drop-in for `Database`:
- Generic attribute proxy (`__getattr__`, client.py:376) forwards
  `add_item`, `update_item`, `get_items`, `get_items_by_operation_id`,
  `delete_item`, and the transaction trio to `_call()` → `POST /rpc` with a
  Bearer token.
- `RemoteCursor.execute()` and `RemoteConnection.commit()/rollback()` stand in
  for raw-SQL call sites (one round-trip per `.execute()`, returns
  rows/description/lastrowid/rowcount together).
- `has_permission()` reads the cached login permissions locally (no round-trip);
  the host re-validates every request.
- `_json_safe()` converts `Decimal` → `format(value, 'f')` (string) before JSON.
- Timeout 10 s per RPC; `save_sale_with_items` gets extra network logging to
  `logs/network_sales.log`.

## 6. RPC dispatch and permissions (`core/network/server.py`)

`_handle_rpc` → `_check_permission(user, method, args, kwargs)`:
- Super-admin bypasses everything.
- `_ALWAYS_ALLOWED`: transaction methods, `get_dashboard_snapshot`.
- `_SECTION_METHODS` map method → (kind, arg index holding the section):
  `add_item`/`update_item`/`delete_item`/`get_items`/
  `get_items_by_operation_id`/`get_operation_summary_items`.
- Raw SQL: `cursor.execute` parsed by `classify_sql(sql)` → (kind, table) →
  `UserManager.section_for_table(table)` → required action; `Reports` reads are
  denied through raw SQL.
- Dedicated handlers: `save_sale_with_items` (needs Sales write + write on any
  pending client/product/service entity), `save_import_with_items`,
  `save_product_with_opening_stock`, `update_product_with_stock`,
  `_REPORT_METHODS` (ownership-filtered), `_PRODUCT_READ_METHODS`,
  `_CLIENT_ACCOUNT_METHODS`, `_ATTACHMENT_METHODS`.
- Errors: 401 (auth), 403 (permission, JSON `{error: reason}`), 400 (ValueError),
  500 (exception). Success: `200 {'result': ...}` via `json.dumps(default=str)`.
- Ownership policy: Sales are company-wide (`get_items_for_user('Sales', ...)`
  just delegates to `get_items`); Reports are ownership-filtered.

## 7. PostgreSQL connection and schema (`core/database.py`)

`Database.connect()` (`database.py:129`):
- psycopg2 to the profile's own database (`database_name`) or shared database +
  `SET search_path TO <schema>`.
- `_create_all_tables()` from registered classes; `_ensure_meta_table()`,
  `_ensure_user_tables()` (Users/Roles/RolePermissions), `_ensure_attachment_tables()`,
  `_ensure_payments_table()`, `_run_one_time_migrations()`.
- `_ensure_additional_columns()` adds snapshot/audit columns (`database.py:350`):
  `created_by INTEGER`, `created_by_username TEXT`, `created_at TEXT` on most
  tables; `remise DOUBLE PRECISION` and `is_historical BOOLEAN` on sales;
  `operation_token TEXT` on sales/imports with unique partial indexes.
- **There is no `updated_at` and no per-row version column.** Incremental sync
  needs either new columns or a change-sequence in the meta table.

## 8. Read paths (the bottleneck)

Every tab read funnels through `BaseTab.background_fetcher()`
(`ui/tabs/base_tab.py:712`), which calls on `database`:
- Sales/Imports → `get_operation_summary_items(section, ...)`
  (`database.py:1980`): the heavy one — joins `sales_items`/`import_items` in an
  aggregate subquery computing `subtotal`, `total_price`, `total_ht`,
  `total_ttc`, `vat_amount`, `information`, `total_quantity`,
  `total_production`. Fallback to `get_items` when empty.
- Everything else → `get_items(section, ...)` (`database.py:1907`):
  `SELECT * FROM <section>` + search + keyset pagination + LIMIT.
- Products also fetch `get_product_stock_levels_for_product_ids(...)`.
- Home → `get_dashboard_snapshot()` (counts + recent activity).

All three go over the network on a remote client, and are re-executed on every
app start, every tab switch after 30 s, every search/sort change, and every
"Load more". SessionCache only survives the current process.

Keyset helpers (`database.py:1817–1906`): `_order_column_expression`,
`_date_sort_expression`, `_keyset_sort_value`, `_keyset_condition`,
`_summary_order_expression`.

## 9. Tab loading / refresh / cache (`ui/tabs/base_tab.py`)

- `refresh_table(force=False)` (`base_tab.py:384`): key = `_cache_key()` =
  `(search_text, order_combo_text)`. If `force`/`_needs_refresh` → full refresh;
  else if a non-empty cached entry exists → `_render_from_cache()` synchronously
  (no DB/network), and only start a background refresh if the entry is stale
  (> `DEFAULT_STALE_SECONDS` 30 s).
- `_start_full_refresh()` resets pagination; RemoteDatabase → `_start_remote_refresh`,
  otherwise `_start_local_refresh` which builds a dedicated worker
  `Database` connection (`_create_worker_database`).
- `_start_refresh()` spawns `QThread` + `_RemoteTableFetchWorker.run()` calling
  the captured `fetcher`; emits `finished(items, levels, metrics, started,
  refresh_id)` / `failed(error, started)`.
- `_apply_refresh_results()` (main thread): drops stale `refresh_id` results;
  converts raw records → object-class instances; append (Load more) or replace;
  advances keyset cursor; **writes the batch into SessionCache**; renders via
  `populate_table_with_items()` (row height measurement only up to 300 rows).
- `refresh_on_tab_switch()`: refreshes when not loaded / `_needs_refresh` /
  stale > 30 s. `mark_dirty()` sets `_needs_refresh` and clears the cache.
- `_wait_for_refresh_thread()` on `aboutToQuit`: clears cache, interrupts/quits
  the in-flight thread (waits up to 11 s).

## 10. RAM cache (`core/session_cache.py`)

- One `SessionCache` per tab, bounded: 32 entries, 2000 records/entry, 20 000
  total, LRU eviction; thread-safe (`RLock`).
- `CacheEntry`: records (raw dicts), levels, has_more, after_id, after_sort,
  last_fetched, last_access, batches. Stale after 30 s.
- Stores plain raw record dicts + stock-level dicts only — never Qt objects.
- **RAM-only.** Cleared on app shutdown (`_wait_for_refresh_thread`) and on every
  `mark_dirty()`. Nothing persists between app launches.

## 11. Worker threads

- BaseTab: one `QThread` at a time per tab for table fetches; local refreshes
  use their own worker `Database` connection, closed when the thread finishes.
- Dialogs/tabs have their own workers (reports generation runs on its own
  thread; payment/save operations run synchronously with host round-trips).
- All Qt updates happen on the main thread; the network fetch runs on the
  worker.

## 12. Pagination

- Keyset pagination everywhere (`after_id`, `after_sort`), `page_size = 100`
  (`limit = page_size + 1` probe row → `has_more`). "Load more" button and
  scroll-to-bottom (`_maybe_load_more_on_scroll`, 150 px threshold) append the
  next batch; `SessionCache.append_batch` keeps the cursor consistent.

## 13. Build / deploy

- `PyLocalInventory.spec`: one-file-onedir `COLLECT`, bundles `report/`
  templates, `logo.png`, Playwright Chromium headless-shell; excludes
  weasyprint/xhtml2pdf/pdfkit. Requires `PLAYWRIGHT_BROWSERS_PATH`.
- `build_windows.ps1`: venv bootstrap, pip installs, playwright chromium
  `--only-shell` install, `PyInstaller --noconfirm --clean`, then verifies
  bundled assets and the EXE. Output: `dist\PyLocalInventory\PyLocalInventory.exe`.
- **One EXE serves both Host and Client** — role is decided at runtime by
  connection mode, not by a separate build.

---

## Findings relevant to the hybrid local-first redesign

1. **No persistence today.** SessionCache is the only cache and lives and dies
   with the process. Remote clients re-download every tab on every launch —
   this is the root cause of the freeze/crash on the client PCs.
2. **Single integration point.** Every tab read already flows through
   `BaseTab.background_fetcher()` → `get_items` /
   `get_operation_summary_items` / stock-level methods. Wrapping that path (and
   the sync of the same data) is where the SQLite read layer belongs.
3. **Heaviest queries = largest tables.** Sales/Imports use aggregate-join
   summary queries; they are also the biggest tables. These benefit most from
   an on-disk cache.
4. **Write path stays as-is.** All writes already go Client → server → PostgreSQL
   (no writable PG on clients). The cache is display-only; a write must
   invalidate the affected cache entries after the authoritative commit.
5. **No `updated_at`/version columns.** A change-sequence for incremental sync
   requires either new columns or a meta-table-based sequence. `created_at`
   (TEXT) and `operation_token` (unique on sales/imports) exist and can anchor
   idempotent sync.
6. **Reuse the permission allow-list.** Any new sync endpoint on the server must
   go through `_check_permission` so it cannot bypass role filtering. Sales are
   company-wide; Reports are ownership-filtered.
7. **Data crosses the wire as JSON strings** (`_json_safe`, `default=str`). An
   on-disk cache can persist the exact same dict shapes without Decimal
   round-trip surprises.
8. **Startup preload spawns 6–8 concurrent HTTP fetches** at login on a remote
   client. With a disk cache these should render from SQLite instantly and sync
   in the background.
9. **Cache identity per client.** `RemoteDatabase` knows host/port/username; the
   cache database must be keyed by (host, port, username) so several client
   identities can coexist on one PC without cross-contaminating permissions or
   data.
