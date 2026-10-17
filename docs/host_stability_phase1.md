# Host service diagnostics (Phase 1)

The Host is started and stopped from **Network Config → Hosting** as before.
The status shown there checks the serving thread and the bound, listening
socket every two seconds while that dialog is open. A window being open alone
does not mean hosting is healthy.

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
   reopen Network Config → Hosting to inspect thread/listener status.
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
   beside the app, with per-user storage as fallback). Correlate
   `server_thread_*`, `http_request_start/end` (using `X-Request-ID`),
   `db_checkout/return/discard`, and capacity warnings. Preserve thread and
   socket counts and Host memory at the same times. For a database wait, use
   authorized **read-only** `pg_stat_activity` state/wait-event counts, without
   exporting SQL text or customer rows.

New Host request diagnostics omit bodies, credentials, tokens, usernames,
customer identifiers, SQL parameter values, and sale payloads. **Old log
files may still contain sensitive entries from earlier versions**; review and
redact them before sharing. The live serving thread, pool use and listener
must be observed during a recurrence before assigning the incident a cause.
