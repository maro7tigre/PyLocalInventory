"""Detached LAN host process and its lightweight GUI-side controller.

The packaged application re-enters its own executable with ``--lan-server``.
In source runs the controller starts this module with the current interpreter.
The host owns no Qt widgets and survives the desktop window closing.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time

from core.build_info import APP_BUILD_ID
from core.runtime_paths import app_root, user_data_root

logger = logging.getLogger(__name__)

HOST_DIR = Path(user_data_root()) / "lan-host"
STATUS_PATH = HOST_DIR / "status.json"
STOP_PATH = HOST_DIR / "stop.request"
LOCK_PATH = HOST_DIR / "supervisor.lock"
WORKER_LOCK_PATH = HOST_DIR / "worker.lock"
START_LOCK_PATH = HOST_DIR / "start.lock"
STARTUP_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REG_NAME = "PyLocalInventory LAN Host"
_STALE_STATUS_SECONDS = 12


def _now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _atomic_json(path: Path, payload: dict):
    HOST_DIR.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, default=str), encoding="utf-8")
    os.replace(temporary, path)


def _publish_status(payload):
    """Best-effort diagnostics must never take a healthy listener offline."""
    try:
        _atomic_json(STATUS_PATH, payload)
    except OSError as error:
        logger.warning("Could not publish LAN host status: %s", type(error).__name__)


def _read_json(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _status_is_fresh(status):
    try:
        updated = datetime.fromisoformat(status["supervisor_updated_at"])
        return (datetime.now(timezone.utc).astimezone() - updated).total_seconds() <= _STALE_STATUS_SECONDS
    except (KeyError, TypeError, ValueError):
        return False


def _host_command(profile_name, port):
    arguments = ["--lan-server", "--profile", profile_name, "--port", str(int(port))]
    if getattr(sys, "frozen", False):
        return [sys.executable, *arguments]
    # Use an absolute entry-point path so an HKCU Run launch works even when
    # Windows supplies System32 (rather than the repository) as the cwd.
    return [sys.executable, os.path.join(app_root(), "main.py"), *arguments]


def _worker_command(profile_name, port, supervisor_pid):
    command = _host_command(profile_name, port)
    return [*command, "--worker", "--supervisor-pid", str(int(supervisor_pid))]


class HostProcessController:
    """Read status and start/stop the detached supervisor process."""

    @staticmethod
    def status():
        status = _read_json(STATUS_PATH)
        if not status:
            return None
        alive = _pid_alive(status.get("pid"))
        fresh = _status_is_fresh(status)
        status["process_alive"] = alive
        status["status_fresh"] = fresh
        status["is_running"] = bool(
            alive and fresh and status.get("state") == "running"
            and status.get("thread_alive") and status.get("listener_available")
        )
        if not alive and status.get("state") not in ("stopped", "not_started"):
            status["reason"] = "supervisor_process_not_alive"
        elif alive and not fresh:
            status["reason"] = "supervisor_status_stale"
        return status

    @staticmethod
    def start(profile_name, port):
        start_lock = _acquire_file_lock(START_LOCK_PATH)
        if start_lock is None:
            raise RuntimeError("Another LAN host start is already in progress")
        try:
            current = HostProcessController.status()
            if _lock_is_held(LOCK_PATH) or (
                    current and current.get("process_alive") and current.get("status_fresh")):
                raise RuntimeError("A LAN host process is already running")
            HOST_DIR.mkdir(parents=True, exist_ok=True)
            try:
                STOP_PATH.unlink()
            except FileNotFoundError:
                pass
            command = _host_command(str(profile_name), int(port))
            creationflags = 0
            startupinfo = None
            if sys.platform.startswith("win"):
                creationflags = (
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    | subprocess.DETACHED_PROCESS
                    | subprocess.CREATE_NO_WINDOW
                )
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            process = subprocess.Popen(
                command,
                cwd=app_root(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creationflags,
                startupinfo=startupinfo,
            )
            _publish_status({
                "state": "starting", "reason": "process_launched",
                "pid": process.pid, "profile": str(profile_name), "port": int(port),
                "build_id": APP_BUILD_ID, "supervisor_updated_at": _now(),
                "thread_alive": False, "listener_available": False,
            })
            return process.pid
        finally:
            start_lock.close()

    @staticmethod
    def stop():
        current = HostProcessController.status()
        if not _lock_is_held(LOCK_PATH) and (
                not current or not current.get("process_alive")):
            return False
        _atomic_json(STOP_PATH, {"requested_at": _now(), "requested_by": os.getpid()})
        return True

    @staticmethod
    def startup_enabled():
        if not sys.platform.startswith("win"):
            return False
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_PATH) as key:
                winreg.QueryValueEx(key, STARTUP_REG_NAME)
            return True
        except OSError:
            return False

    @staticmethod
    def configure_startup(enabled, profile_name, port):
        if not sys.platform.startswith("win"):
            raise RuntimeError("Automatic host startup is supported only on Windows")
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_PATH) as key:
            if enabled:
                command = subprocess.list2cmdline(_host_command(str(profile_name), int(port)))
                winreg.SetValueEx(key, STARTUP_REG_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, STARTUP_REG_NAME)
                except FileNotFoundError:
                    pass


def _acquire_file_lock(path):
    HOST_DIR.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    if os.fstat(handle.fileno()).st_size == 0:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
    if sys.platform.startswith("win"):
        import msvcrt
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            handle.close()
            return None
    else:
        import fcntl
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return None
    return handle


def _lock_is_held(path):
    handle = _acquire_file_lock(path)
    if handle is None:
        return True
    handle.close()
    return False


def _register_classes(database):
    from classes.product_class import ProductClass
    from classes.service_class import ServiceClass
    from classes.door_type_class import DoorTypeClass
    from classes.wood_type_class import WoodTypeClass
    from classes.client_class import ClientClass
    from classes.supplier_class import SupplierClass
    from classes.sales_class import SalesClass
    from classes.sales_item_class import SalesItemClass
    from classes.import_class import ImportClass
    from classes.import_item_class import ImportItemClass
    from classes.reports_class import ReportsClass
    for cls in (
        ProductClass, ServiceClass, DoorTypeClass, WoodTypeClass, ClientClass,
        SupplierClass, SalesClass, SalesItemClass, ImportClass, ImportItemClass,
        ReportsClass,
    ):
        database.register_class(cls)


def _run_server_worker(profile_name, port, supervisor_pid):
    """Own the listener and recover failed listener/DB initialization."""
    from core.database import Database
    from core.logging_config import setup_logging
    from core.network.server import DatabaseServer
    from core.profiles import ProfileManager

    setup_logging()
    started_at = _now()
    failures = 0
    restart_count = 0
    server = None
    worker_lock = _acquire_file_lock(WORKER_LOCK_PATH)
    if worker_lock is None:
        logger.error("A LAN server worker is already running")
        return 3
    try:
        while True:
            if STOP_PATH.exists():
                break
            try:
                manager = ProfileManager()
                if not manager.load_profile(profile_name):
                    raise RuntimeError("Configured profile is not available")
                database = Database(manager)
                _register_classes(database)
                if not database.connect(initialize_schema=True):
                    raise RuntimeError("PostgreSQL initialization failed")
                database.close()
                server = DatabaseServer(database, port=int(port))
                server.start()
                healthy_since = time.monotonic()
                while not STOP_PATH.exists() and server.is_running:
                    # A genuinely stable run clears the consecutive-failure
                    # backoff; a listener that repeatedly dies just after
                    # binding continues to back off instead of tight-looping.
                    if failures and time.monotonic() - healthy_since >= 60:
                        failures = 0
                    snapshot = server.snapshot()
                    snapshot.update({
                        "profile": profile_name, "pid": supervisor_pid,
                        "worker_pid": os.getpid(),
                        "supervisor_started_at": started_at,
                        "supervisor_updated_at": _now(), "restart_count": restart_count,
                    })
                    _publish_status(snapshot)
                    time.sleep(2)
                if STOP_PATH.exists():
                    break
                raise RuntimeError("LAN serving thread stopped unexpectedly")
            except Exception as error:
                failures += 1
                restart_count += 1
                if server is not None:
                    try:
                        server.stop(reason="supervisor_recovery")
                    except Exception:
                        logger.exception("Could not clean up failed LAN server")
                    server = None
                delay = min(30, 2 ** min(failures - 1, 5))
                _publish_status({
                    "state": "recovering", "reason": type(error).__name__,
                    "pid": supervisor_pid, "worker_pid": os.getpid(),
                    "profile": profile_name, "port": int(port),
                    "build_id": APP_BUILD_ID, "supervisor_started_at": started_at,
                    "supervisor_updated_at": _now(), "restart_count": restart_count,
                    "retry_in_seconds": delay, "thread_alive": False,
                    "listener_available": False,
                })
                logger.exception("LAN host failed; retrying in %ss", delay)
                deadline = time.monotonic() + delay
                while time.monotonic() < deadline and not STOP_PATH.exists():
                    time.sleep(0.25)
        if server is not None:
            server.stop(reason="operator_stop")
            deadline = time.monotonic() + 30
            while server.snapshot().get("state") == "stopping" and time.monotonic() < deadline:
                time.sleep(0.1)
        _publish_status({
            "state": "stopped", "reason": "operator_stop", "pid": supervisor_pid,
            "worker_pid": os.getpid(),
            "profile": profile_name, "port": int(port), "build_id": APP_BUILD_ID,
            "supervisor_started_at": started_at, "supervisor_updated_at": _now(),
            "thread_alive": False, "listener_available": False,
        })
        return 0
    finally:
        worker_lock.close()


def run_supervisor(profile_name, port):
    """Supervise the server worker process until an explicit stop request.

    Keeping supervision in a separate process means an unhandled worker
    exception or native crash does not permanently take hosting offline.
    """
    from core.logging_config import setup_logging

    setup_logging()
    lock = _acquire_file_lock(LOCK_PATH)
    if lock is None:
        logger.error("LAN host supervisor is already running")
        return 2
    try:
        try:
            STOP_PATH.unlink()
        except FileNotFoundError:
            pass
        failure_streak = 0
        restart_count = 0
        while not STOP_PATH.exists():
            command = _worker_command(profile_name, port, os.getpid())
            worker = subprocess.Popen(
                command, cwd=app_root(), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0),
            )
            worker_started = time.monotonic()
            while worker.poll() is None and not STOP_PATH.exists():
                time.sleep(0.5)
            if STOP_PATH.exists():
                try:
                    worker.wait(timeout=35)
                except subprocess.TimeoutExpired:
                    logger.error("LAN worker ignored graceful stop; terminating")
                    worker.terminate()
                    try:
                        worker.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        logger.error("LAN worker did not terminate; killing")
                        worker.kill()
                        worker.wait(timeout=5)
                break
            stable_seconds = time.monotonic() - worker_started
            failure_streak = 1 if stable_seconds >= 60 else failure_streak + 1
            restart_count += 1
            delay = min(30, 2 ** min(failure_streak - 1, 5))
            _publish_status({
                "state": "recovering", "reason": "worker_process_exited",
                "pid": os.getpid(), "worker_pid": worker.pid,
                "profile": profile_name, "port": int(port),
                "build_id": APP_BUILD_ID, "supervisor_updated_at": _now(),
                "restart_count": restart_count, "retry_in_seconds": delay,
                "thread_alive": False, "listener_available": False,
            })
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline and not STOP_PATH.exists():
                time.sleep(0.25)
        # The worker normally writes the final stopped record. Ensure one is
        # present even if it had to be terminated.
        _publish_status({
            "state": "stopped", "reason": "operator_stop", "pid": os.getpid(),
            "profile": profile_name, "port": int(port), "build_id": APP_BUILD_ID,
            "supervisor_updated_at": _now(), "thread_alive": False,
            "listener_available": False,
        })
        try:
            STOP_PATH.unlink()
        except FileNotFoundError:
            pass
        return 0
    finally:
        lock.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--supervisor-pid", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        return _run_server_worker(
            args.profile, args.port, args.supervisor_pid or os.getppid()
        )
    return run_supervisor(args.profile, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
