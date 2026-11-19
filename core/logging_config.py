"""Application-wide logging, crash hooks, and lightweight performance timing."""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from contextlib import contextmanager

from core.runtime_paths import app_path, user_data_root


_CONFIGURED = False
_LOG_PATH = None


def _choose_log_directory():
    candidates = (app_path("logs"), os.path.join(user_data_root(), "logs"))
    last_error = None
    for directory in candidates:
        try:
            os.makedirs(directory, exist_ok=True)
            probe = os.path.join(directory, ".write_test")
            with open(probe, "a", encoding="utf-8"):
                pass
            os.remove(probe)
            return directory
        except OSError as error:
            last_error = error
    raise OSError("No writable application log directory") from last_error


def setup_logging():
    """Configure the four diagnostic logs (app/crash/performance/threading),
    faulthandler, the Qt message handler, and the exception hooks.

    The heavy lifting lives in ``core.diagnostics``; everything here stays a
    stable facade so callers keep working unchanged."""
    global _CONFIGURED, _LOG_PATH
    if _CONFIGURED:
        return _LOG_PATH

    directory = _choose_log_directory()

    from core import diagnostics
    diagnostics.install(directory)
    _LOG_PATH = diagnostics.log_paths().get("app.log") or os.path.join(directory, "app.log")

    # Some Windows shells still expose a cp1252 stream.  Legacy diagnostic
    # prints contain Unicode symbols; make those non-fatal instead of allowing
    # a harmless status message to crash startup.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="replace")
            except (OSError, ValueError):
                pass
    _CONFIGURED = True
    install_exception_hooks()
    return _LOG_PATH


def log_path():
    return _LOG_PATH or setup_logging()


def install_exception_hooks():
    logger = logging.getLogger("crash")
    previous_sys_hook = sys.excepthook

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            previous_sys_hook(exc_type, exc_value, exc_traceback)
            return
        logger.critical(
            "Unhandled application exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        previous_sys_hook(exc_type, exc_value, exc_traceback)

    sys.excepthook = handle_exception

    if hasattr(threading, "excepthook"):
        previous_thread_hook = threading.excepthook

        def handle_thread_exception(args):
            logger.critical(
                "Unhandled worker-thread exception in %s",
                getattr(args.thread, "name", "unknown"),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
            previous_thread_hook(args)

        threading.excepthook = handle_thread_exception


@contextmanager
def timed_operation(name, *, logger=None, slow_seconds=0.5, **context):
    """Log completion and warn only when an operation crosses its threshold."""
    operation_logger = logger or logging.getLogger("performance")
    started = time.perf_counter()
    try:
        yield
    except Exception:
        elapsed = time.perf_counter() - started
        operation_logger.exception(
            "%s failed after %.3f seconds context=%s", name, elapsed, context
        )
        raise
    else:
        elapsed = time.perf_counter() - started
        level = logging.WARNING if elapsed >= slow_seconds else logging.INFO
        operation_logger.log(
            level, "%s completed in %.3f seconds context=%s",
            name, elapsed, context,
        )
