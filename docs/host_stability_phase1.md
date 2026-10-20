# Host service diagnostics (Phase 1)

The Host is started and stopped from **Network Config → Hosting** as before.
The status shown there checks the serving thread and the bound, listening
socket every two seconds while that dialog is open. A window being open alone
does not mean hosting is healthy.

## What the Hosting status means

- **Hosting**: this application process owns a Host object whose serving
  thread is alive and whose listener socket is bound and accepting on the
  configured port.
- **Server unavailable**: the Host object still exists in this process, but the
  serving thread and/or listener is no longer healthy. The detail line names
  the last lifecycle state, reason and error category.
- **Not hosting**: this application process has no Host object at all. This is
  the normal state immediately after the application starts because hosting is
  **not resumed automatically**, and it is also the state after the operator
  stops hosting (or after a failed start is cleared). The detail line
  distinguishes those cases and shows the last recorded state when available.

The detail line is diagnostic only. It does not restart hosting and does not
perform database I/O.

## Lifecycle states and logs

`DatabaseServer` records one of: `not_started`, `starting`, `running`,
`thread_exited`, `listener_lost`, `stopping`, `stopped`, `failed`. Unhappy
states are detected by the serving thread itself and by a lightweight
`LANServerMonitor` thread; neither one auto-restarts hosting.

Every change writes one line to `app.log`:

```
host_state from=<old> to=<new> reason=<reason> port=<port> pid=<pid>
build_id=<id> thread_alive=<bool> listener=<bool> active_requests=<n>
checked_out=<n> body_inflight=<n> sessions=<n> pool_drain_pending=<n>
error_category=<class|none>
```

Each running Host also writes a `host_heartbeat` record every five minutes with
the same state/listener/request/pool counters. A heartbeat that stops abruptly
without a preceding `host_stop_requested` means the process disappeared or was
killed before any shutdown code ran; a matching later `Application startup`
record with a new PID then proves an application restart. A long gap caused by
machine sleep/suspend is not a stop: after resume the same PID continues and
heartbeats resume. This is different from a serving-thread failure, which leaves
the process alive and writes `server_thread_failed` / `host_state ...
to=thread_exited`.

Every `stop()` invocation writes `host_stop_requested` *before* cleanup with the
reason, thread name and a privacy-safe caller chain (file basename, line,
function). Known reasons are `operator_stop` and `stale_server_cleanup` from the
Hosting dialog, `application_shutdown` from the main window, and
`restart_before_start` from `start()`. Any other caller appears as
`unspecified`, making an unexpected stop path visible. Listener closure writes
`host_listener_closed`; stop cleanup steps write `host_stop_step_failed`. The
Hosting dialog also logs `host_ui_status` only when its displayed status
changes, `host_toggle_requested` for every button activation, and
`host_reference_cleared` when the application drops its Host object reference.

The detail line shows the running build ID and PID. This matters because an
older packaged Host can have the exact same code paths but none of these
records: commit `73c5a44` changed Host lifecycle behavior without changing
`APP_BUILD_ID`, which remained `sales-table-total-ht-ttc-2026-08-05-v2` for both
the old and new behavior. Older builds also used the default `WARNING` root
level, so their `Application startup` INFO line was dropped; only the PID in
each log prefix is reliable there. Always compare the Host's `Application
startup build_id=...`, the detail line, and `host_state` records before
interpreting `Status: Not hosting`. Deploy the same build to the Host and every
Client: clients intentionally report a build mismatch when the Host build
differs, and that warning identifies a stale deployment rather than a Host
failure.

Typical reasons are `start_requested`, `start_succeeded`, `start_failed`,
`serving_thread_failed`, `serving_thread_not_alive`, `listener_unavailable`,
`operator_stop`, `stale_server_cleanup`, `application_shutdown`,
`stop_completed`, and `stop_cleanup_failed`. A failed start or stop is also
reported by `server_start_failed`, `host_stop_step_failed`, and
`server_thread_failed` records. The in-process snapshot retains the previous
state and the last unhealthy state/reason/time, so a later cleanup stop does
not erase why the Host failed. Stacks in these records contain only the file
basename, line number and function name; exception messages and source lines
are intentionally omitted so credentials, SQL and customer values cannot leak.

## Limits and health

- `PYLOCALINVENTORY_MAX_REQUEST_MB`: maximum POST JSON body in MiB. The default
  is at least 64 MiB and grows with `PYLOCALINVENTORY_MAX_ATTACHMENT_MB` (25 MiB
  by default) to allow one maximum-size base64 attachment plus JSON overhead.
- `PYLOCALINVENTORY_MAX_INFLIGHT_BODY_MB`: total simultaneous POST-body budget
  in MiB; default at least 128 MiB or twice the per-request limit. A request
  exceeding the per-request limit receives HTTP 413. When the concurrent body
  budget is full, an otherwise valid request receives HTTP 503.
- `PYLOCALINVENTORY_HTTP_TIMEOUT_SECONDS`: accepted-socket and complete-header
  deadline, default 30 seconds. A POST body also has a total upload deadline
  that scales with its length. Backup downloads remain streamed and use a
  longer (300-second) socket timeout.
- `PYLOCALINVENTORY_DB_STATEMENT_TIMEOUT_MS`: maximum duration of one SQL
   statement on a Host RPC connection, default 8000 ms. PostgreSQL cancels an
   overlong statement, and the Host rolls back and returns that connection to
   the pool; this prevents lock waits from occupying all pool connections.
- `PYLOCALINVENTORY_MAX_HTTP_THREADS`: simultaneous HTTP handler limit,
  default 32; the listen backlog is 16. Excess connections are closed and
  recorded as `http_capacity_exhausted`. These values do not change the
  PostgreSQL pool's existing 2–10 connections.

Set environment variables **before starting the Host**; no database setting
or schema is changed. A non-positive or malformed environment value falls
back to its default; an in-flight budget smaller than one allowed request is
rejected on start.

`GET /health` requires an existing login Bearer token. A successful response
reports `gui_process_alive`, `server_thread_alive`, `listener_available`,
`http_responsive`, and `database_accessible` as booleans. Database access is a
read-only `SELECT 1` using a pooled connection with a transaction-local
two-second SQL statement deadline. HTTP 503 with `database_accessible: false`
means the handler responded but its database probe failed. An unauthenticated
request receives HTTP 401 without any diagnostic fields; even that response
confirms the HTTP service answered. A refused or timed-out TCP connection
cannot reach this endpoint. Keep session tokens out of console history,
screenshots, and shared logs.

## Evidence to capture **before** restarting a failed Host

1. Note Host and Client clocks, port, build IDs, last successful request and
   exact time/wording of the failure. Check whether the Host GUI responds and
   reopen Network Config → Hosting to inspect thread/listener status and the
   detail line. Record whether the status is **Hosting**, **Server
   unavailable**, or **Not hosting**. The last case means the application
   process has no Host object; check whether the application was restarted,
   hosting was stopped, or a start failed and was cleared.
2. On the Host, run `Get-NetTCPConnection -LocalPort 8765 -State Listen`
   (substitute the configured port). Check an unauthenticated
   `http://127.0.0.1:8765/health` request for HTTP 401. Check the same Host LAN
   IP and port from the Client with `Test-NetConnection` or an HTTP probe.
   Record separately **refused**, **connect timeout**, **HTTP/read timeout**,
   **HTTP 401/403**, **HTTP 500/503**, and **HTTP success**.
3. If a logged-in Client already has a session, perform an authenticated
   `GET /health` without exposing its token; capture only its status/boolean
   fields. HTTP responsiveness and database accessibility are distinct.
4. Preserve `app.log` and its rotated siblings, `threading.log`, and
   `crash.log` from the directory printed at Host startup (usually `logs/`
   beside the app, with per-user storage as fallback). Correlate the last
   `host_state` transition with `host_stop_requested` (reason + caller),
   `host_heartbeat`, `host_listener_closed`, `host_ui_status`,
   `host_toggle_requested`, `host_reference_cleared`, `server_thread_*`,
   `server_start_failed`, `host_stop_step_failed`, `http_request_start/end`
   (using `X-Request-ID`), `db_checkout/return/discard`, and capacity warnings.
   Preserve thread and socket counts and Host memory at the same times. For a
   database wait, use authorized **read-only** `pg_stat_activity`
   state/wait-event counts, without exporting SQL text or customer rows.
5. Record the process identity: `Application startup build_id=... pid=...` and
   the PID/build shown in the Hosting detail line. If the PID changed, the Host
   application restarted; if the PID is unchanged and there is no
   `host_stop_requested`, capture the complete log snippet before doing
   anything else. Do not overwrite the logs by restarting immediately.

New Host request diagnostics omit bodies, credentials, tokens, usernames,
customer identifiers, SQL parameter values, and sale payloads. **Old log
files may still contain sensitive entries from earlier versions**; review and
redact them before sharing. The live serving thread, pool use and listener
must be observed during a recurrence before assigning the incident a cause.
