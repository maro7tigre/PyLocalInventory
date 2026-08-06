# Antigravity Master Prompt — Stabilize PyLocalInventory

Read `PYLOCALINVENTORY_ANTIGRAVITY_CONTEXT.md` completely before changing code.

You are the senior PySide6/Qt, PostgreSQL, LAN RPC, threading, and application-stability engineer responsible for fixing the existing PyLocalInventory application.

The application freezes, shows Windows “Not Responding”, and sometimes crashes. Runtime logs now contain confirmed Python, SQL, Qt-thread, native, RPC, synchronization, and diagnostic failures.

Do not redesign the visible UI.

Do not change unrelated business logic.

Preserve Products, Services, Clients, Suppliers, Sales, Imports, stock, Historical Sales, Remise, Total HT, TVA, Total TTC, Payments, Client accounts, Reports, Devis, Invoices, PDF, printing, attachments, backups, roles, permissions, Host mode, and Client mode.

PostgreSQL on the Host must remain authoritative.

Do not claim success based only on compilation, unit tests, or one successful launch.

## Step 0 — Protect the repository and restore a clean baseline

1. Inspect Git status/history.
2. Identify:
   - Current commit
   - Last commit before SQLite-cache work
   - Last known stable commit
   - Files changed by cache/sync work
3. Preserve experimental cache work in:

```text
experiment/sqlite-local-cache
```

4. Create or continue:

```text
fix/runtime-stability
```

5. Set production defaults:

```python
ENABLE_SQLITE_CACHE = False
ENABLE_INCREMENTAL_SYNC = False
```

6. Prove that when disabled there is:
   - No CacheManager instance
   - No SQLite open/read/write
   - No cache/sync signal
   - No sync timer/coordinator
   - No `get_changes`
   - No hidden effect on `RemoteDatabase`

Do not delete experimental work before preserving it.

## Priority 1 — Fix shutdown and logger failure

Confirmed:

```text
ui/main_window.py
closeEvent()
NameError: name 'logger' is not defined
```

Required:

- Use the existing logging configuration.
- Define module logger correctly:

```python
logger = logging.getLogger(__name__)
```

- Make `closeEvent()` idempotent with a `_shutting_down` guard.
- Prevent new work after shutdown begins.
- Stop timers and sync scheduling.
- Invalidate request generations.
- Request cooperative worker cancellation.
- Wait for workers/QThreads with bounded timeouts.
- Stop Host server.
- Close network resources.
- Close PostgreSQL only after workers stop using it.
- Flush logs.
- Accept the event.
- Use robust `try/finally`.
- One cleanup failure must not skip the remaining cleanup.
- Logging must never prevent shutdown.
- Do not use arbitrary sleeps.
- Do not use `QThread.terminate()` normally.
- Calling close twice must be safe.

## Priority 2 — Fix Decimal parsing everywhere

Confirmed:

```text
ui/widgets/operations_table.py
_on_item_changed()
→ _update_row_subtotal()
decimal.InvalidOperation: ConversionSyntax
```

Create/reuse one authoritative parser that safely handles:

- Decimal
- int
- float
- numeric string
- None
- empty string
- normal/non-breaking spaces
- comma/dot decimals
- accepted thousands separators
- intermediate editing states: `-`, `.`, `,`, `-.`, `-,`

Support intentionally accepted formats such as:

```text
1500
1500.25
1500,25
1 500,25
1 500.25
1,500.25
1.500,25
```

Return explicit states:

```text
VALID
EMPTY
INTERMEDIATE
INVALID
```

Rules:

- Never silently turn invalid non-empty input into zero.
- Intermediate typing must not crash.
- Invalid final input must block Save through existing validation.
- Use `QSignalBlocker` or equivalent to prevent recursive `itemChanged`.
- Use Decimal for quantity, price, subtotal, Remise, TVA, Total HT, Total TTC.
- Convert float-origin values with `Decimal(str(value))`.
- Preserve existing formulas and rounding policy.
- Search for duplicated unsafe parsers and centralize them safely.

## Priority 3 — Fix Imports SQL using real schema evidence

Confirmed:

```text
core/database.py
get_operation_summary_items()
psycopg2.errors.UndefinedColumn:
column si.information does not exist
```

Required:

- Inspect actual Imports/Import Items schema, migrations, and aliases.
- Identify what `si` is.
- Replace/remove the invalid reference using a real existing column/expression.
- Do not invent a column without proof.
- Preserve Sales summary behavior.
- Roll back failed transactions before reusing a connection.
- Stop using this exception/fallback as normal flow.
- Add local and remote Imports tests.
- Verify no fallback and fixed small query count.

## Priority 4 — Remove all blocking LAN/SQL work from GUI thread

Audit every call to:

```text
RemoteDatabase._call
cursor.execute
get_items
get_items_by_operation_id
get_operation_summary_items
get_product_stock_levels_for_product_ids
get_changes
list_attachments
get_attachment_thumbnail
get_client_sales
get_reports
upload_attachment
```

No blocking RPC, PostgreSQL, filesystem, image, report, PDF, backup, or large loop may run on QApplication’s GUI thread.

Use one consistent worker pattern:

- Worker performs blocking operation.
- Worker returns plain Python data.
- GUI validates generation ID.
- GUI updates widgets/models.
- Worker never touches QWidget.
- Strong references are retained.
- Cleanup occurs on success/error/cancel/timeout.
- Old results are ignored.
- Deleted tabs cannot receive results.

Add development/test diagnostics that identify any blocking RPC attempted from the GUI thread.

## Priority 5 — Eliminate N+1 RPC/query patterns

Confirmed repeated calls include:

```text
get_items_by_operation_id
SELECT ID, name, unit_price FROM Products WHERE name = %s
```

Replace per-row calls with:

- One limited operation-summary page query
- One bulk aggregate query or small fixed set
- One bulk Product lookup for all required IDs/names
- In-memory maps
- Full detail only when the user opens one Sale/Import

Target:

```text
100 visible Sales/Imports
small fixed query/RPC count
0 per-row detail calls
0 per-row Product calls
```

No network/database call inside a Qt render loop.

Add query/RPC count regression tests.

## Priority 6 — Fix BaseTab request races and Clients first load

In `ui/tabs/base_tab.py` and subclasses:

- One identical active request per tab maximum.
- Monotonic generation ID.
- Track trigger source.
- Latest request wins.
- Keep old data visible while loading.
- Never clear before valid replacement.
- Reset in-flight state on success/error/timeout/cancel/close.
- Remove worker references after true completion.
- Connect persistent signals once.
- Prevent old results from clearing new results.

For Clients specifically:

- Trace automatic first request to final render.
- Log every rejection reason.
- Ensure first valid result renders without manual Refresh.
- One activation = one effective request.
- One Refresh click = one effective request.

## Priority 7 — Repair QThread/worker lifetime

Confirmed:

```text
Fatal Python error: Aborted
Windows fatal exception: access violation
QThreadStorage: entry destroyed before end of thread
```

Audit:

```text
ui/tabs/base_tab.py
tests/test_remote_table_worker.py
worker registries
tab destruction
application shutdown
sync/report/attachment workers
```

Required lifecycle:

```text
retain strong reference
start
cooperative cancel/invalidate
success/error signal
thread.quit()
worker.deleteLater()
thread.finished → thread.deleteLater()
remove reference after completion
```

Requirements:

- No QThread destroyed while running.
- No QObject used after deletion.
- No GUI access from worker.
- No test exits with active QThread.
- Test blocking Events released in `finally`.
- Shutdown waits with bounded timeouts.
- Dependencies close after workers.
- Add tests for app close/tab close/worker error/timeout/cancel/stale result.
- Verify no live QThread after every test.

After lifecycle fixes, reproduce the native access violation. If it remains:

- Record Python/PySide6/shiboken6/psycopg2 versions and architecture.
- Confirm PySide6 and shiboken6 match.
- Run in a clean supported virtual environment.
- Collect faulthandler and Windows crash-dump evidence.
- Identify use-after-delete, GUI-from-worker, native mismatch, or shutdown order.
- Do not call it fixed because it fails to reproduce once.

## Priority 8 — Fix attachment thumbnail loading

Replace sequential Main-Thread thumbnail RPC with:

- Background requests
- Concurrency limit 2–4
- Visible items only
- Cancellation on close/view change
- Deduplication by attachment ID/version
- Strict bounded LRU cache
- Placeholder while loading
- Plain bytes/raw data from worker
- GUI-thread-only final Qt image assignment
- No full-size image cache
- No unlimited queued requests

Preserve current attachment permissions and central Host storage.

## Priority 9 — Stop unsafe incremental synchronization

While stabilizing:

```python
ENABLE_INCREMENTAL_SYNC = False
```

must prevent every sync object/timer and every `get_changes` call.

Only re-enable after baseline passes, with:

- One coordinator
- One timer
- No overlap
- Entire network cycle outside GUI thread
- Consolidated request when possible
- Background sequential sections otherwise
- Failure backoff
- No recursive tab refresh
- Apply changed IDs only
- Clean shutdown

## Priority 10 — Correct diagnostics

### Memory

Use actual RSS, preferably:

```python
psutil.Process(os.getpid()).memory_info().rss
```

If unavailable, log `ram=unavailable`, not false `0.0MB`.

### Encoding

All file handlers must use UTF-8. Fix mojibake tab names.

### GUI watchdog

Use a queued GUI heartbeat/acknowledgement.

A functioning modal `dialog.exec()` must not be reported as a multi-hour freeze.

Rate-limit real stall reports and include last operation/request.

### Log separation

Use separate runtime/test logs, for example:

```text
logs/runtime/app.log
logs/runtime/crash.log
logs/runtime/performance.log
logs/runtime/threading.log
logs/tests/test.log
```

Tests must log `mode=test`. Intentional `boom:Products`/`boom:Clients` must not pollute runtime logs.

Add session ID and process start time.

## Priority 11 — Keep the architecture simple

Stable target:

```text
One Host PostgreSQL
+
Existing RPC
+
Server-side search/filter/sort/aggregation/pagination
+
One background request per tab
+
Small bounded RAM cache
+
QTableView/QAbstractTableModel only for measured heavy tables
+
No production SQLite sync until separately proven
```

Do not migrate all tables at once.

Only after confirmed crashes/thread/RPC/SQL problems are fixed, measure QTableWidget rendering. If still a major bottleneck, migrate Sales first behind:

```python
USE_SALES_TABLE_MODEL = False
```

Preserve visible UI and all actions.

## Mandatory data-integrity checks

Verify no regression in:

- Sale create/edit/delete
- Stock deduction/restoration
- Overselling prevention
- Historical Sale no-stock behavior
- Imports stock increase
- Payments
- Client balances
- Attachments
- Roles/permissions
- Remise
- Total HT
- TVA
- Total TTC
- Reports
- Devis/invoices
- PDF/printing
- Backups
- Host/Client consistency

One action must produce one transaction.

No duplicate Sale.

No double stock deduction.

## Required automated tests

Add/repair tests for:

### Decimal

- Decimal/int/float-origin/string/None/empty
- comma/dot
- spaces/non-breaking spaces
- accepted thousands formats
- intermediate states
- invalid final text
- recursive signal prevention
- Save blocked on invalid input

### Shutdown/threads

- Logger exists
- close once/twice
- cleanup component raises
- active fetch/sync/thumbnail during close
- no QThread alive
- process exits code 0

### Imports

- local/remote summary
- real schema columns
- no fallback
- rollback after SQL failure

### GUI-thread safety

- Remote fetch not on GUI thread
- thumbnail not on GUI thread
- sync not on GUI thread
- database query not on GUI thread

### N+1

- 100 Sales fixed small count
- 100 Imports fixed small count
- zero per-row Product/detail calls

### BaseTab/Clients

- first activation one request
- first valid result renders
- duplicate activation suppressed
- stale ignored
- newest accepted
- failed request resets state
- manual Refresh one request
- closed tab receives nothing

### Diagnostics

- real RAM or unavailable
- UTF-8 names
- modal dialog no false stall
- test logs isolated

Run the full suite in a fresh process.

It must exit 0 with no:

```text
Fatal Python error: Aborted
Windows access violation
QThread destroyed while running
QThreadStorage destroyed before end of thread
Unhandled Decimal exception
NameError during shutdown
UndefinedColumn si.information
```

## Required real runtime verification

Before testing:

1. Archive old logs.
2. Start clean logs.
3. Record dependency versions/architecture.
4. Verify Host and Client build IDs match.

Test both real Host and Client:

1. Open/close each 20 times.
2. Close during tab load.
3. Close during sync.
4. Close during thumbnail loading.
5. Open heavy tabs 50 times.
6. Rapid tab switching for at least 10 minutes.
7. Repeated search/sort/refresh.
8. Verify Clients first load.
9. Create/edit Sales.
10. Test locale and temporary numeric input.
11. Test Historical Sale.
12. Verify stock on Host and another Client.
13. Open many attachments.
14. Generate Report/PDF/Backup.
15. Disconnect/reconnect network.
16. Run extended normal workflow.
17. Confirm no remaining Python/Qt/server/worker process.

Measure actual:

- RAM
- workers
- threads
- connections
- queries
- RPC calls
- network time
- render time
- GUI heartbeat delay

Do not invent values.

## Completion gates

Do not continue unrelated work until:

### Gate A

- No Decimal crash
- No logger NameError
- No Imports UndefinedColumn
- Clean shutdown
- No QThread abort/access violation in required workflow

### Gate B

- No blocking RPC/SQL on Main Thread
- No synchronous thumbnail loop
- No Main-Thread sync

### Gate C

- Fixed small query/RPC count
- No per-row detail/Product lookup

### Gate D

- Clients renders automatically
- No duplicate effective request
- No stale overwrite
- No “Not Responding” during stress test

### Gate E

- No duplicate Sale
- No double stock deduction
- Correct Historical Sale and financial totals
- Host/Client data consistent

### Gate F

- Accurate RAM
- UTF-8 logs
- Correct watchdog
- Test/runtime logs separated
- Clean new crash log

## Final report

Provide:

1. Exact root cause of every confirmed failure
2. Git branches/commits
3. Modified files/functions
4. Imports schema evidence and fixed SQL
5. Decimal parser design
6. Shutdown sequence
7. Worker/QThread ownership model
8. Main-thread calls removed
9. Query/RPC counts before/after
10. Attachment design
11. Sync flags/behavior
12. Clients first-load cause
13. Diagnostic fixes
14. Automated tests and actual results
15. Runtime tests and actual results
16. RAM/thread/worker/connection/query/RPC/render measurements
17. Host results
18. Client results
19. Anything requiring physical multi-PC verification
20. Build/deployment/rollback instructions
21. Exact logs to collect after any future crash

Do not say “fixed forever”. State only what was reproduced, changed, measured, and verified.
