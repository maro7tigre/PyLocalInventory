"""Phase 1 runtime diagnostics: crash, thread, memory, and freeze telemetry.

Installs (all diagnostic-only, never kill/restart, never change behavior):

* four rotating log files - ``app.log`` (everything), ``crash.log`` (fatal
  exceptions and Qt fatal messages), ``performance.log`` (heavy operations),
  ``threading.log`` (worker/thread lifecycle and GUI stalls);
* per-record context enrichment so every serious line carries build id, host
  or client mode, process id, thread name/id, active tab, current operation
  and request id, active worker / database-connection counts, session query
  and network call counters, and live process RAM;
* Python ``faulthandler`` writing native-stack dumps to ``crash.log``;
* a Qt message handler (``qInstallMessageHandler``) that routes Qt warnings
  and fatal messages into the logs;
* a GUI event-loop watchdog: when the Qt main thread stalls for more than
  ``GUI_STALL_SECONDS`` a warning is logged with the main thread's Python
  stack. It never terminates the application.

Never log passwords, tokens, credentials, or attachment contents.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler

import faulthandler

from core.build_info import APP_BUILD_ID
from core.memory_utils import process_memory_mb

# Diagnostics must stay importable and usable before Qt is created, so Qt is
# imported lazily inside the pieces that need it (Qt handler, GUI watchdog).
_QT_IMPORT_ATTEMPTED = False
_QT_MSG_HANDLER_INSTALLED = False

logger = logging.getLogger("diagnostics")
crash_logger = logging.getLogger("crash")
performance_logger = logging.getLogger("performance")
threading_logger = logging.getLogger("threading")

INSTALLED = False
_LOG_PATHS = {}
_HANDLERS = []

GUI_STALL_SECONDS = 2.0
_WATCH_INTERVAL_SECONDS = 0.5
_RAM_SAMPLE_INTERVAL_SECONDS = 1.0


class _AppContext:
    """Thread-safe runtime context sampled into every log record."""

    def __init__(self):
        self._lock = threading.Lock()
        self.mode = "unknown"            # host | client | unknown
        self.active_tab = ""
        self.active_workers = 0
        self.db_connections = 0
        self.db_queries = 0
        self.network_calls = 0
        self._local = threading.local()

    # --- global fields -------------------------------------------------
    def set_mode(self, mode):
        with self._lock:
            self.mode = str(mode)

    def set_tab(self, tab):
        with self._lock:
            self.active_tab = str(tab or "")

    def worker_started(self):
        with self._lock:
            self.active_workers += 1

    def worker_finished(self):
        with self._lock:
            self.active_workers = max(0, self.active_workers - 1)

    def db_opened(self):
        with self._lock:
            self.db_connections += 1

    def db_closed(self):
        with self._lock:
            self.db_connections = max(0, self.db_connections - 1)

    def inc_queries(self, count=1):
        with self._lock:
            self.db_queries += count

    def inc_network(self, count=1):
        with self._lock:
            self.network_calls += count

    # --- thread-local fields --------------------------------------------
    def set_operation(self, operation):
        self._local.operation = str(operation)

    def operation(self):
        return getattr(self._local, "operation", None)

    def set_request(self, request_id):
        self._local.request_id = str(request_id)

    def request(self):
        return getattr(self._local, "request_id", None)


_context = _AppContext()

_LAST_RAM_AT = 0.0
_LAST_RAM = 0.0


def _sample_ram():
    """Live RAM sampled at most once per second (per-record would be too hot)."""
    global _LAST_RAM_AT, _LAST_RAM
    now = time.monotonic()
    if now - _LAST_RAM_AT >= _RAM_SAMPLE_INTERVAL_SECONDS:
        try:
            _LAST_RAM = process_memory_mb(refresh=True)
        except Exception:
            _LAST_RAM = 0.0
        _LAST_RAM_AT = now
    return _LAST_RAM


def set_mode(mode):
    """Record whether the current process is a host, a remote client, or both."""
    _context.set_mode(mode)


def set_active_tab(tab):
    _context.set_tab(tab)


@contextmanager
def operation(name, **ctx):
    """Time a heavy operation on the current thread, logging start/finish to
    the performance log. Never raises."""
    previous = _context.operation()
    _context.set_operation(name)
    started = time.perf_counter()
    try:
        yield
    except Exception:
        elapsed = (time.perf_counter() - started) * 1000
        performance_logger.exception(
            "operation_failed name=%s elapsed_ms=%.1f context=%s",
            name, elapsed, ctx,
        )
        raise
    else:
        elapsed = (time.perf_counter() - started) * 1000
        performance_logger.log(
            logging.WARNING if elapsed >= 500 else logging.INFO,
            "operation_done name=%s elapsed_ms=%.1f context=%s",
            name, elapsed, ctx,
        )
    finally:
        _context.set_operation(previous)


@contextmanager
def request(request_id):
    """Tag every log line emitted on this thread with a request id (e.g. a
    tab refresh generation) until the request completes."""
    previous = _context.request()
    _context.set_request(request_id)
    try:
        yield
    finally:
        _context.set_request(previous)


# ------------------------------------------------------------------- workers

def worker_started(kind, section="", worker_id=""):
    _context.worker_started()
    threading_logger.info(
        "worker_started kind=%s section=%s worker_id=%s",
        kind, section, worker_id,
    )


def worker_finished(kind, section="", worker_id=""):
    _context.worker_finished()
    threading_logger.info(
        "worker_finished kind=%s section=%s worker_id=%s",
        kind, section, worker_id,
    )


def worker_failed(kind, section="", worker_id=""):
    _context.worker_finished()
    threading_logger.error(
        "worker_failed kind=%s section=%s worker_id=%s",
        kind, section, worker_id,
    )


def worker_cleanup(kind, section="", worker_id=""):
    threading_logger.info(
        "worker_cleanup kind=%s section=%s worker_id=%s",
        kind, section, worker_id,
    )


# ------------------------------------------------------------ db/query tools

class QueryTrackedCursor:
    """Thin proxy over a psycopg2 cursor that counts queries and their total
    duration for the diagnostics context. Everything else delegates to the
    real cursor, so existing call sites keep working unchanged."""

    def __init__(self, cursor):
        object.__setattr__(self, "_cursor", cursor)

    def execute(self, sql, params=None):
        _context.inc_queries()
        started = time.perf_counter()
        try:
            if params is None:
                return self._cursor.execute(sql)
            return self._cursor.execute(sql, params)
        finally:
            object.__setattr__(
                self, "_last_query_ms", (time.perf_counter() - started) * 1000
            )

    def executemany(self, sql, seq_of_params):
        _context.inc_queries()
        started = time.perf_counter()
        try:
            return self._cursor.executemany(sql, seq_of_params)
        finally:
            object.__setattr__(
                self, "_last_query_ms", (time.perf_counter() - started) * 1000
            )

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __setattr__(self, name, value):
        setattr(self._cursor, name, value)

    def __getitem__(self, key):
        return self._cursor[key]


def track_cursor(cursor):
    """Wrap a database cursor so every query is counted and timed."""
    try:
        return QueryTrackedCursor(cursor)
    except Exception:
        crash_logger.exception("Could not wrap cursor for diagnostics")
        return cursor


def db_connection_opened(kind="local"):
    _context.db_opened()
    threading_logger.info("db_connection_opened kind=%s", kind)


def db_connection_closed(kind="local"):
    _context.db_closed()
    threading_logger.info("db_connection_closed kind=%s", kind)


def network_call(method=""):
    """Count a remote RPC (client mode)."""
    _context.inc_network()
    if method:
        logger.debug("network_call method=%s", method)


# ------------------------------------------------------------ log plumbing

def _context_filter(record):
    record.build_id = APP_BUILD_ID
    record.app_mode = _context.mode
    record.active_tab = _context.active_tab or "-"
    record.current_operation = _context.operation() or "-"
    record.current_request = _context.request() or "-"
    record.active_workers = _context.active_workers
    record.db_connections = _context.db_connections
    record.db_queries = _context.db_queries
    record.network_calls = _context.network_calls
    record.thread_id = threading.get_ident()
    record.ram_mb = _sample_ram()
    return True


_STANDARD_FORMAT = (
    "%(asctime)s | %(levelname)s | build=%(build_id)s | mode=%(app_mode)s | "
    "pid=%(process)d | thread=%(threadName)s[%(thread_id)s] | tab=%(active_tab)s | "
    "op=%(current_operation)s | req=%(current_request)s | "
    "workers=%(active_workers)d | conns=%(db_connections)d | "
    "queries=%(db_queries)d | net=%(network_calls)d | ram=%(ram_mb).1fMB | "
    "%(name)s | %(funcName)s | %(message)s"
)


class _NameFilter(logging.Filter):
    def __init__(self, names=(), min_level=None):
        super().__init__()
        self.names = set(names)
        self.min_level = min_level

    def filter(self, record):
        if not self.names and self.min_level is None:
            return True
        if self.min_level is not None and record.levelno >= self.min_level:
            return True
        return record.name in self.names


class _MultiProcessRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that never drops records when rotation is
    temporarily blocked by another process holding the log open.

    On Windows, ``os.rename`` in the stock ``doRollover`` fails with
    PermissionError whenever any other process has the log file open
    without FILE_SHARE_DELETE.  That exception used to be swallowed by
    ``handleError``, silently discarding the record being logged.  This
    handler instead falls back to appending the record and retries the
    rotation on the next emit.  It also opens its streams with
    FILE_SHARE_DELETE so rotation can succeed once all instances run the
    new code."""

    def _open(self):
        if os.name == "nt":
            try:
                return _open_log_stream_share_delete(
                    self.baseFilename, self.encoding
                )
            except OSError:
                pass
        return super()._open()

    def emit(self, record):
        try:
            if self.shouldRollover(record):
                try:
                    self.doRollover()
                except OSError:
                    # Rotation is not possible right now (another process is
                    # holding the log open).  doRollover already closed our
                    # stream, so reopen it and append the record instead of
                    # dropping it; rotation is retried on the next emit.
                    if self.stream is None:
                        self.stream = self._open()
            logging.FileHandler.emit(self, record)
        except Exception:
            self.handleError(record)


def _open_log_stream_share_delete(path, encoding):
    """Open ``path`` in append mode with FILE_SHARE_DELETE so other
    processes may rename/rotate it while this stream stays open."""
    import ctypes
    import msvcrt

    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    OPEN_ALWAYS = 4
    FILE_ATTRIBUTE_ARCHIVE = 0x20

    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.restype = ctypes.c_void_p
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]

    handle = create_file(
        os.fspath(path),
        GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_ALWAYS,
        FILE_ATTRIBUTE_ARCHIVE,
        None,
    )
    if not handle or handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError()

    fd = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_APPEND)
    if fd < 0:
        raise OSError("msvcrt.open_osfhandle failed")
    return os.fdopen(fd, "a", encoding=encoding)


def _add_rotating_handler(log_dir, filename, filter_rule):
    path = os.path.join(log_dir, filename)
    _LOG_PATHS[filename] = path
    handler = _MultiProcessRotatingFileHandler(
        path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(_STANDARD_FORMAT))
    handler.addFilter(filter_rule)
    _HANDLERS.append(handler)
    return handler


def log_paths():
    """Return {filename: absolute path} for the four diagnostic logs."""
    return dict(_LOG_PATHS)


def install(log_dir):
    """Add the four rotating handlers, faulthandler, and the Qt handler.

    Called from ``core.logging_config.setup_logging`` before QApplication is
    created. Idempotent."""
    global INSTALLED
    if INSTALLED:
        return
    try:
        os.makedirs(log_dir, exist_ok=True)
        root = logging.getLogger()
        _add_rotating_handler(log_dir, "app.log", _NameFilter())
        _add_rotating_handler(log_dir, "crash.log", _NameFilter(["crash"], logging.CRITICAL))
        _add_rotating_handler(log_dir, "performance.log", _NameFilter(["performance"]))
        _add_rotating_handler(log_dir, "threading.log", _NameFilter(["threading"]))
        for handler in _HANDLERS:
            # Handler-level filters run on every record that reaches the
            # handler, including records that only propagated up from child
            # loggers.  A root-logger filter would not, so the context fields
            # the formatter needs would be missing and every record would be
            # dropped by a formatting error.
            handler.addFilter(_context_filter)
            root.addHandler(handler)
    except Exception:
        # Diagnostics must never break application startup.
        logger.exception("Failed to install diagnostics logging")
    _install_faulthandler(os.path.join(log_dir, "crash.log"))
    _install_qt_message_handler()
    INSTALLED = True


def _install_faulthandler(crash_path):
    try:
        stream = open(crash_path, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=stream, all_threads=True)
    except Exception:
        logger.exception("Could not enable faulthandler")


def _install_qt_message_handler():
    global _QT_MSG_HANDLER_INSTALLED
    if _QT_MSG_HANDLER_INSTALLED:
        return
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception:
        return

    level_map = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
        QtMsgType.QtInfoMsg: logging.INFO,
    }

    def handler(qt_type, context, message):
        try:
            level = level_map.get(qt_type, logging.WARNING)
            location = ""
            try:
                location = "%s:%d (%s)" % (
                    getattr(context, "file", "") or "",
                    getattr(context, "line", 0) or 0,
                    getattr(context, "function", "") or "",
                )
            except Exception:
                location = ""
            logging.getLogger("qt").log(
                level, "Qt message: %s %s", message, location
            )
        except Exception:
            pass

    try:
        qInstallMessageHandler(handler)
        _QT_MSG_HANDLER_INSTALLED = True
    except Exception:
        logger.exception("Could not install Qt message handler")


# --------------------------------------------------------------- watchdog

class GuiWatchdog:
    """Log-only watchdog for GUI-thread stalls.

    A GUI-thread QTimer refreshes a heartbeat every ``_WATCH_INTERVAL_SECONDS``.
    A daemon thread watches that heartbeat and, when it is older than
    ``GUI_STALL_SECONDS``, logs a warning with the main thread's Python stack.
    It never kills, restarts, or modifies the application.

    Created only by ``main.py`` after ``QApplication`` exists.
    """

    def __init__(self, parent=None):
        from PySide6.QtCore import QTimer
        self._heartbeat = time.monotonic()
        self._reporting = False
        self._timer = QTimer(parent)
        self._timer.setInterval(int(_WATCH_INTERVAL_SECONDS * 1000))
        self._timer.timeout.connect(self._beat)
        self._timer.start()
        self._thread = threading.Thread(
            target=self._watch, name="GuiWatchdog", daemon=True
        )
        self._thread.start()

    def _beat(self):
        self._heartbeat = time.monotonic()
        self._reporting = False

    def _watch(self):
        main_ident = threading.main_thread().ident
        while True:
            time.sleep(_WATCH_INTERVAL_SECONDS)
            stalled = time.monotonic() - self._heartbeat
            if stalled < GUI_STALL_SECONDS or self._reporting:
                continue
            self._reporting = True
            frame = sys._current_frames().get(main_ident)
            if frame:
                frames_list = traceback.format_stack(frame)
                if frames_list:
                    last_frame = frames_list[-1]
                    if ".exec(" in last_frame or ".exec_(" in last_frame:
                        self._reporting = False
                        continue
                stack = "".join(frames_list)
            else:
                stack = "(no main-thread frame)"
            try:
                threading_logger.warning(
                    "gui_stall seconds=%.1f tab=%s op=%s req=%s workers=%d "
                    "conns=%d ram=%.1fMB main_stack:\n%s",
                    stalled,
                    _context.active_tab or "-",
                    _context.operation() or "-",
                    _context.request() or "-",
                    _context.active_workers,
                    _context.db_connections,
                    _sample_ram(),
                    stack,
                )
            except Exception:
                pass
