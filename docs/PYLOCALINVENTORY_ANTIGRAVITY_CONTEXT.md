# PyLocalInventory — Deep Context for Antigravity

Read this file completely before editing the repository.

## 1. What the application is

**PyLocalInventory** is a Windows desktop business application built with:

- Python
- PySide6 / Qt
- PostgreSQL
- One Host PC
- Multiple Client PCs connected over the local network

The Host PC runs the authoritative PostgreSQL database and the existing LAN server/RPC layer. Client PCs connect through the existing remote database/client layer.

PostgreSQL on the Host must remain the only authoritative data source.

Do not create an independently writable PostgreSQL database on each PC. Do not implement multi-master replication.

## 2. Main modules

The application includes:

- Products
- Services
- Clients
- Suppliers
- Sales and Sale Items
- Imports/Purchases and Import Items
- Product stock
- Historical Sales
- Payments
- Client balances/accounts
- Reports
- Devis and invoices
- PDF generation
- Printing
- Attachments
- Backup/restore
- Users, roles, and permissions
- Host mode and remote Client mode

Do not remove or disable existing features merely to make the application look stable.

## 3. Important business rules

### Host authority

All sensitive writes must be validated and committed on the Host:

- Sales
- Sale Items
- Stock deduction/restoration
- Imports
- Product quantities
- Payments
- Client balances
- Attachments
- Users, roles, and permissions

### Stock integrity

One user action must create one authoritative transaction.

The application must prevent:

- Duplicate Sales
- Double stock deduction
- Partial Sales
- Sale Items without a Sale
- Overselling
- Stale Client-side stock becoming authoritative

### Historical Sales

The existing Historical Sale option must continue to avoid changing current stock.

### Financial formulas

Preserve exactly:

```text
Original Subtotal = sum(quantity × unit price)
Total HT = Original Subtotal - Remise
TVA = Total HT × VAT rate
Total TTC = Total HT + TVA
```

Use `decimal.Decimal` consistently. Never mix `Decimal` and `float`.

## 4. Known architecture and files

Important areas include:

```text
main.py
core/database.py
core/network/client.py
core/network/server.py
core/sync.py
core/cache_manager.py
core/diagnostics.py
ui/main_window.py
ui/tabs/base_tab.py
ui/tabs/home_tab.py
ui/widgets/operations_table.py
ui/dialogs/reports_dialog.py
tests/test_remote_table_worker.py
tests/test_sync_coordinator.py
```

Known architecture:

- PostgreSQL on Host
- Existing `ThreadingHTTPServer`
- Existing connection pool
- `RemoteDatabase`
- JSON-safe LAN RPC
- Permission allow-list
- Build-ID compatibility checks
- `BaseTab` table loading
- PySide6 worker threads
- `QTableWidget` in existing heavy tables
- Session RAM caching
- Recent SQLite cache/incremental-sync experiment

## 5. Recent cache experiment

Recent work added a local SQLite cache and incremental synchronization, including:

- `core/cache_manager.py`
- Per-Host/per-user cache identity
- Row-addressable cache entries
- WAL
- Cache schema versioning
- Sync state/change sequence
- Disk-first render experiments

The application was estimated around 80–90% stable before this experiment and around 50–60% stable after it.

Until separately proven stable, production defaults should be:

```python
ENABLE_SQLITE_CACHE = False
ENABLE_INCREMENTAL_SYNC = False
```

When disabled, the app must not:

- Instantiate the cache manager
- Open SQLite
- Start cache/sync workers
- Connect cache/sync signals
- Call `get_changes`
- Read/write the disk cache
- Alter normal `RemoteDatabase` behavior

Preserve experimental work in a separate Git branch instead of deleting it.

## 6. Confirmed failures from runtime logs

These are confirmed by logs, not guesses.

### A. Decimal parsing crash

File:

```text
ui/widgets/operations_table.py
```

Path:

```text
_on_item_changed()
→ _update_row_subtotal()
```

Exception:

```text
decimal.InvalidOperation: [<class 'decimal.ConversionSyntax'>]
```

Unsafe behavior:

```python
Decimal(str(price_item.text()).replace(" ", "").replace(",", "."))
```

Temporary or locale-formatted input can crash the GUI.

### B. Shutdown crash

File:

```text
ui/main_window.py
```

Function:

```text
closeEvent()
```

Exception:

```text
NameError: name 'logger' is not defined
```

This happened repeatedly in Host and Client modes. Because it occurs during shutdown, it can prevent thread, server, timer, sync, network, and database cleanup.

### C. QThread/native lifetime failure

Observed:

```text
Fatal Python error: Aborted
Windows fatal exception: access violation
QThreadStorage: entry 0 destroyed before end of thread
```

Relevant paths include:

```text
ui/tabs/base_tab.py
tests/test_remote_table_worker.py
main.py
```

This indicates unsafe worker/QThread lifetime or shutdown ordering.

### D. Broken Imports summary SQL

File:

```text
core/database.py
```

Function:

```text
get_operation_summary_items()
```

Exception:

```text
psycopg2.errors.UndefinedColumn:
column si.information does not exist
```

It occurs in local and remote Imports loading. The application logs the exception and falls back to another query, creating extra load and slower startup.

Inspect the actual Imports/Import Items schema before changing the query. Do not guess the replacement column.

### E. LAN RPC and SQL work on the Qt Main Thread

Logs show calls such as:

```text
MainThread | LAN RPC method=cursor.execute
MainThread | LAN RPC method=get_items_by_operation_id
MainThread | LAN RPC method=get_attachment_thumbnail
MainThread | LAN RPC method=get_changes
```

This is a confirmed source of freezing and Windows “Not Responding”.

No LAN RPC, PostgreSQL query, file I/O, image decoding, PDF preparation, backup work, or large data loop may block the Qt GUI thread.

### F. N+1 RPC/query pattern

Repeated sequences include:

```text
get_items_by_operation_id
SELECT ID, name, unit_price FROM Products WHERE name = %s
get_items_by_operation_id
SELECT ID, name, unit_price FROM Products WHERE name = %s
...
```

Operation rows are causing per-row detail and Product lookup calls.

A visible page must use bulk queries and a fixed small RPC/query count.

### G. Synchronous thumbnails

Many `get_attachment_thumbnail` requests run sequentially on `MainThread`, each taking tens or hundreds of milliseconds.

Thumbnail loading must be background, cancellable, limited to visible items, and bounded in concurrency/cache size.

### H. Incremental sync on Main Thread

Logs show bursts of `MainThread | get_changes`.

There must be one background coordinator, one timer, no overlapping cycle, and zero calls when sync is disabled.

### I. Clients tab can be empty until manual Refresh

On a remote Client PC, the Clients tab can appear empty until Refresh.

Investigate:

- Duplicate startup requests
- Stale-result rejection
- Incorrect generation ID
- In-flight state not reset
- Clearing before replacement
- Visibility checks
- Duplicate signal connections
- Cache/network race

The first valid result must render automatically.

### J. Diagnostics are inaccurate

Problems include:

```text
ram=0.0MB
```

Mojibake tab names such as:

```text
ðŸ’° Sales
ðŸ‘¥ Clients
ðŸ“¥ Imports
```

The GUI watchdog also reported multi-hour stalls while inside normal `app.exec()` or modal `dialog.exec()` event loops.

Test fixture errors such as `boom:Products` and `boom:Clients` are mixed into runtime logs.

## 7. Required stable target architecture

Prefer this production architecture:

```text
One authoritative PostgreSQL database on Host
+
Existing Host RPC/API
+
Server-side search/filter/sort/aggregation/pagination
+
One controlled background request per tab
+
Latest-request-wins generation IDs
+
Small bounded RAM result cache
+
QTableView + QAbstractTableModel only for confirmed heavy tables
+
No production SQLite sync until separately proven
+
No full-table download
+
No full-table render
+
No network or SQL on GUI thread
```

Do not migrate all tabs at once.

## 8. Threading rules

Allowed on workers:

- PostgreSQL reads
- LAN RPC
- Bulk aggregation
- JSON serialization
- Report data preparation
- Backup/PDF subprocess orchestration
- Image file reading and decoding to plain data

Required on GUI thread:

- QWidget/model updates
- Final Qt image assignment
- Dialog display
- Final render

Every worker needs:

- Strong owner reference
- Request ID
- Generation ID
- Cooperative cancellation/invalidation
- Success/error/timeout cleanup
- Shutdown cleanup

Older results must never overwrite newer results.

## 9. Query/RPC rules

For 50–100 visible rows:

- Small fixed query/RPC count
- Zero detail call per row
- Zero Product lookup per row
- Zero network call in render loops
- Server-side search over the complete authorized dataset
- Parameterized SQL
- ORDER BY allow-list
- No full-table scan/download

## 10. Safe shutdown order

Recommended order:

1. Set `shutting_down = True`
2. Prevent new work
3. Stop timers
4. Stop sync scheduling
5. Invalidate pending generations
6. Request cooperative cancellation
7. Wait for active workers/QThreads with bounded timeouts
8. Stop Host server
9. Close Client network resources
10. Close PostgreSQL resources
11. Flush logs
12. Accept close event
13. Exit QApplication

Logging failure must never stop cleanup.

## 11. Definition of done

The app is not fixed merely because it compiles or unit tests pass.

Required evidence:

- No Decimal crash
- No logger shutdown exception
- No Imports UndefinedColumn
- No QThread abort/access violation in the required stress workflow
- No blocking RPC/SQL on GUI thread
- No per-row operation/Product queries
- No synchronous thumbnail loop
- No duplicate sync coordinator
- Clients renders on first valid automatic load
- Accurate RAM metrics
- UTF-8 logs
- Correct watchdog
- Test logs separated from runtime logs
- Host and Client open/close 20 times
- Rapid tab switching without “Not Responding”
- Correct Sales, stock, Historical Sale, Remise, TVA, Total HT, and Total TTC
- No duplicate Sale or double stock deduction
- No unbounded memory growth

Do not guess. Reproduce, measure, fix, and report what remains unverified on physical PCs.
