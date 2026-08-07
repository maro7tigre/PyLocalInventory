"""TEMPORARY diagnostic mode for the Sale Save freeze investigation.

This module adds NO behavior changes to save/DB/thread/RPC architecture -
it only observes and logs. Delete this module and its call sites
(grep for `sale_save_diagnostics`) once the freeze has been root-caused
from captured evidence.

Writes to <logs>/sale_save_hang_diagnostic.log:
  - A full Python thread-stack dump (via faulthandler) every 5 seconds,
    for the lifetime of the process.
  - Timestamped trace markers around the real Sale Save flow (GUI, worker
    thread, RPC client, RPC server, DB transaction).

`start()` must be called once, early, from main.py. Every other function
here is a no-op until `start()` has run (so importing this module is safe
even before startup).
"""
from __future__ import annotations

import faulthandler
import os
import threading
import time

from core.runtime_paths import app_path, user_data_root

_FILENAME = "sale_save_hang_diagnostic.log"
_DUMP_INTERVAL_SECONDS = 5

_lock = threading.Lock()
_log_file = None
_log_path = None
_started = False


def _resolve_log_path():
    candidates = (app_path("logs"), os.path.join(user_data_root(), "logs"))
    last_error = None
    for directory in candidates:
        try:
            os.makedirs(directory, exist_ok=True)
            probe = os.path.join(directory, ".write_test")
            with open(probe, "a", encoding="utf-8"):
                pass
            os.remove(probe)
            return os.path.join(directory, _FILENAME)
        except OSError as error:
            last_error = error
    raise OSError("No writable logs directory for sale_save_hang_diagnostic.log") from last_error


def _timestamp():
    now = time.time()
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)) + f".{int(now % 1 * 1000):03d}"


def _write_line(line):
    with _lock:
        if _log_file is None:
            return
        _log_file.write(line)
        _log_file.flush()


def event(marker, **fields):
    """Write one timestamped trace marker: thread name/id + any extra fields."""
    if _log_file is None:
        return
    t = threading.current_thread()
    extra = " ".join(f"{k}={v!r}" for k, v in fields.items())
    _write_line(f"{_timestamp()} | {marker} | thread={t.name}(id={t.ident}) | {extra}\n")


def _dump_all_thread_stacks(reason):
    if _log_file is None:
        return
    with _lock:
        _log_file.write(f"\n===== THREAD DUMP ({reason}) {_timestamp()} =====\n")
        try:
            faulthandler.dump_traceback(file=_log_file, all_threads=True)
        except Exception as exc:  # never let diagnostics crash the app
            _log_file.write(f"[dump_traceback failed: {exc!r}]\n")
        _log_file.write("===== END THREAD DUMP =====\n\n")
        _log_file.flush()


def _periodic_dump_loop():
    while True:
        time.sleep(_DUMP_INTERVAL_SECONDS)
        _dump_all_thread_stacks("periodic")


def start():
    """Enable faulthandler, open the diagnostic log, and start the periodic
    all-threads stack dumper. Safe to call more than once (only the first
    call does anything). Returns the absolute path to the diagnostic log."""
    global _log_file, _log_path, _started
    if _started:
        return _log_path
    _log_path = _resolve_log_path()
    _log_file = open(_log_path, "a", encoding="utf-8", buffering=1)
    faulthandler.enable(file=_log_file, all_threads=True)
    _write_line(f"{_timestamp()} | DIAGNOSTIC_START | pid={os.getpid()} | log={_log_path}\n")
    thread = threading.Thread(
        target=_periodic_dump_loop, name="SaleSaveHangDiagnosticDumper", daemon=True
    )
    thread.start()
    _started = True
    return _log_path


def log_path():
    return _log_path
