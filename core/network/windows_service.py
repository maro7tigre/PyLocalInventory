"""Windows SCM service wrapper for the PyLocalInventory LAN host."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import sys
import time

# pythonservice.exe loads this module by absolute path; ensure project imports
# work even though a boot-start service has no repository working directory.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

SERVICE_NAME = "PyLocalInventoryLAN"
SERVICE_DISPLAY_NAME = "PyLocalInventory LAN Server"
SERVICE_DESCRIPTION = "Hosts PyLocalInventory securely for LAN clients."


def machine_root() -> Path:
    base = os.getenv("PROGRAMDATA") or r"C:\ProgramData"
    return Path(base) / "PyLocalInventory" / "LANService"


def service_config_path() -> Path:
    return machine_root() / "service.json"


def profile_config_path() -> Path:
    return machine_root() / "profile.json"


def postgres_config_path() -> Path:
    return machine_root() / "postgres.json"


def status_path() -> Path:
    return machine_root() / "runtime" / "status.json"


def public_config_path() -> Path:
    return machine_root() / "runtime" / "public.json"


def _atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def protect_machine_secret(value: str) -> str:
    """Protect a secret with Windows DPAPI machine scope.

    Access is additionally restricted by the ProgramData ACL installed by the
    administrator script. The plaintext is never written to disk.
    """
    import win32crypt
    protected = win32crypt.CryptProtectData(
        str(value or "").encode("utf-8"),
        "PyLocalInventory PostgreSQL",
        None, None, None,
        0x4,  # CRYPTPROTECT_LOCAL_MACHINE
    )
    return base64.b64encode(protected).decode("ascii")


def unprotect_machine_secret(value: str) -> str:
    import win32crypt
    raw = base64.b64decode(str(value).encode("ascii"), validate=True)
    _description, plaintext = win32crypt.CryptUnprotectData(raw, None, None, None, 0)
    return plaintext.decode("utf-8")


def load_service_configuration() -> dict:
    try:
        value = json.loads(service_config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(
            "The LAN service is not configured. Run install_lan_service.ps1 as Administrator."
        ) from error
    if not isinstance(value, dict):
        raise RuntimeError("Invalid LAN service configuration")
    required = ("profile", "port", "project_root", "python_executable")
    if any(not value.get(key) for key in required):
        raise RuntimeError("Incomplete LAN service configuration")
    return value


def configure_machine(profile_name: str, port: int):
    """Copy only service-required configuration into secured ProgramData."""
    from core.pg_config import load_server_config
    from core.profiles import ProfileManager
    from core.runtime_paths import app_root

    manager = ProfileManager()
    if not manager.load_profile(profile_name):
        raise RuntimeError(f"Profile {profile_name!r} does not exist for this Windows user")
    source = Path(manager.selected_profile.config_path)
    profile_data = json.loads(source.read_text(encoding="utf-8"))
    # The desktop unlock verifier is neither needed nor usable by LocalSystem.
    profile_data.pop("encrypted_phrase", None)
    profile_data["service_profile_name"] = profile_name

    postgres = load_server_config()
    password = postgres.pop("password", "")
    postgres["password_dpapi"] = protect_machine_secret(password)

    root = machine_root()
    root.mkdir(parents=True, exist_ok=True)
    _atomic_json(profile_config_path(), profile_data)
    _atomic_json(postgres_config_path(), postgres)
    _atomic_json(service_config_path(), {
        "profile": profile_name,
        "port": int(port),
        "project_root": os.path.abspath(app_root()),
        "python_executable": os.path.abspath(sys.executable),
        "configured_by": os.getenv("USERNAME") or "unknown",
    })
    _atomic_json(public_config_path(), {"profile": profile_name, "port": int(port)})
    return root


def repair_machine_runtime(python_executable: str, project_root: str):
    """Update only runtime locations, preserving all service business data."""
    config = load_service_configuration()
    python_path = Path(python_executable).resolve()
    project_path = Path(project_root).resolve()
    if not python_path.is_file():
        raise RuntimeError(f"Service Python does not exist: {python_path}")
    if not (project_path / "main.py").is_file():
        raise RuntimeError(f"Project entry point does not exist: {project_path / 'main.py'}")
    config["python_executable"] = str(python_path)
    config["project_root"] = str(project_path)
    _atomic_json(service_config_path(), config)
    return machine_root()


class ServiceProfileManager:
    """Minimal ProfileManager surface backed by the ProgramData profile copy."""

    def __init__(self, profile_name):
        from core.profiles import ProfileClass
        profile = ProfileClass(str(profile_name))
        profile.config_path = str(profile_config_path())
        profile.preview_path = ""
        profile.load_config_data()
        self.selected_profile = profile
        self.available_profiles = {profile.name: profile}


def load_service_profile_manager(profile_name):
    return ServiceProfileManager(profile_name)


def _query_scm():
    import pywintypes
    import win32service
    scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
    try:
        try:
            service = win32service.OpenService(
                scm, SERVICE_NAME,
                win32service.SERVICE_QUERY_STATUS | win32service.SERVICE_QUERY_CONFIG,
            )
        except pywintypes.error as error:
            if error.winerror == 1060:
                return None
            raise
        try:
            status = win32service.QueryServiceStatusEx(service)
            config = win32service.QueryServiceConfig(service)
            return {"state_code": status["CurrentState"], "start_type": config[1]}
        finally:
            win32service.CloseServiceHandle(service)
    finally:
        win32service.CloseServiceHandle(scm)


class WindowsServiceController:
    """GUI-side SCM status and control surface."""

    @staticmethod
    def installed():
        return _query_scm() is not None

    @staticmethod
    def configuration():
        try:
            value = json.loads(public_config_path().read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def status():
        import win32service
        scm = _query_scm()
        if scm is None:
            return None
        try:
            snapshot = json.loads(status_path().read_text(encoding="utf-8"))
            if not isinstance(snapshot, dict):
                snapshot = {}
        except (OSError, ValueError):
            snapshot = {}
        state_code = scm["state_code"]
        scm_running = state_code == win32service.SERVICE_RUNNING
        scm_pending = state_code in (
            win32service.SERVICE_START_PENDING, win32service.SERVICE_STOP_PENDING,
        )
        snapshot.update({
            "service_installed": True,
            "service_state_code": state_code,
            "service_running": scm_running,
            "process_alive": scm_running or scm_pending,
            "startup_automatic": scm["start_type"] in (
                win32service.SERVICE_AUTO_START,
                getattr(win32service, "SERVICE_AUTO_START", 2),
            ),
        })
        fresh = False
        try:
            from datetime import datetime, timezone
            updated = datetime.fromisoformat(snapshot["supervisor_updated_at"])
            fresh = (datetime.now(timezone.utc).astimezone() - updated).total_seconds() <= 15
        except (KeyError, TypeError, ValueError):
            pass
        snapshot["status_fresh"] = fresh
        snapshot["is_running"] = bool(
            scm_running and fresh and snapshot.get("state") == "running"
            and snapshot.get("thread_alive") and snapshot.get("listener_available")
        )
        if not snapshot.get("profile"):
            snapshot.update(WindowsServiceController.configuration())
        return snapshot

    @staticmethod
    def _wait(target_state, timeout=30):
        import win32service
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = _query_scm()
            if state and state["state_code"] == target_state:
                return True
            time.sleep(0.25)
        return False

    @staticmethod
    def start(*_args, **_kwargs):
        import win32service
        import win32serviceutil
        if not WindowsServiceController.installed():
            raise RuntimeError("The PyLocalInventory LAN Windows Service is not installed")
        win32serviceutil.StartService(SERVICE_NAME)
        if not WindowsServiceController._wait(win32service.SERVICE_RUNNING):
            raise RuntimeError("Windows did not report the LAN service as running")
        return True

    @staticmethod
    def stop():
        import win32service
        import win32serviceutil
        if not WindowsServiceController.installed():
            return False
        win32serviceutil.StopService(SERVICE_NAME)
        if not WindowsServiceController._wait(win32service.SERVICE_STOPPED, timeout=45):
            raise RuntimeError("Windows did not report the LAN service as stopped")
        return True

    @staticmethod
    def startup_enabled():
        import win32service
        state = _query_scm()
        return bool(state and state["start_type"] == win32service.SERVICE_AUTO_START)


def _prepare_service_environment(config):
    root = machine_root()
    os.environ["PYLOCALINVENTORY_HOST_DIR"] = str(root / "runtime")
    os.environ["PYLOCALINVENTORY_PG_CONFIG"] = str(postgres_config_path())
    os.environ["PYLOCALINVENTORY_SERVICE_PROFILE"] = str(profile_config_path())
    os.environ["PYLOCALINVENTORY_LOG_DIR"] = str(root / "logs")
    os.environ["PYLOCALINVENTORY_SHARED_DATA_ROOT"] = str(root / "data")
    os.environ["PYLOCALINVENTORY_PYTHON_EXE"] = config["python_executable"]
    os.environ["PYLOCALINVENTORY_ENTRYPOINT"] = str(
        Path(config["project_root"]) / "main.py"
    )


import servicemanager
import win32event
import win32service
import win32serviceutil


class PyLocalInventoryLANService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESCRIPTION

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=40000)
        try:
            config = load_service_configuration()
            _prepare_service_environment(config)
            from core.network import host_process
            host_process._atomic_json(
                host_process.STOP_PATH,
                {"requested_at": time.time(), "requested_by": "SCM"},
            )
        finally:
            win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        config = load_service_configuration()
        _prepare_service_environment(config)
        servicemanager.LogInfoMsg(
            f"{SERVICE_DISPLAY_NAME} starting profile={config['profile']} port={config['port']}"
        )
        from core.network import host_process
        # Clear only a marker left by a previous abnormal shutdown. If SCM
        # concurrently requests a stop, SvcStop signals stop_event and writes
        # the marker again after this point, so the administrative stop wins.
        try:
            host_process.STOP_PATH.unlink()
        except FileNotFoundError:
            pass
        if win32event.WaitForSingleObject(self.stop_event, 0) == win32event.WAIT_OBJECT_0:
            host_process._atomic_json(
                host_process.STOP_PATH,
                {"requested_at": time.time(), "requested_by": "SCM"},
            )
        result = host_process.run_supervisor(
            config["profile"], int(config["port"]), clear_stop_request=False
        )
        servicemanager.LogInfoMsg(
            f"{SERVICE_DISPLAY_NAME} stopped result={result}"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command", nargs="?")
    parser.add_argument("--profile")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--python-executable")
    parser.add_argument("--project-root")
    known, _unknown = parser.parse_known_args(argv)
    if known.command == "configure":
        if not known.profile:
            raise SystemExit("--profile is required")
        root = configure_machine(known.profile, known.port)
        print(f"Configured LAN service under {root}")
        return 0
    if known.command == "repair-runtime":
        if not known.python_executable or not known.project_root:
            raise SystemExit("--python-executable and --project-root are required")
        root = repair_machine_runtime(
            known.python_executable, known.project_root
        )
        print(f"Updated LAN service runtime paths under {root}")
        return 0

    # HandleCommandLine reads sys.argv so preserve standard pywin32 service
    # install/update/start/stop/remove command compatibility.
    win32serviceutil.HandleCommandLine(PyLocalInventoryLANService)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
