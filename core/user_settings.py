"""Per-user application settings and Windows startup support."""
import json
import os
import sys

try:
    import winreg
except ImportError:  # Non-Windows or unavailable winreg
    winreg = None

APP_NAME = "PyLocalInventory"
SETTINGS_FILENAME = "settings.json"
STARTUP_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REG_NAME = "PyLocalInventory"

DEFAULT_SETTINGS = {
    "remember_profile": False,
    "remembered_profile_id": "",
    "start_with_windows": False,
}


def settings_dir() -> str:
    """Return the per-user settings directory path."""
    local_appdata = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
    if not local_appdata:
        local_appdata = os.path.expanduser("~")
    path = os.path.join(local_appdata, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def settings_path() -> str:
    """Return the full settings file path."""
    return os.path.join(settings_dir(), SETTINGS_FILENAME)


def load_settings() -> dict:
    """Load settings from the per-user JSON settings file."""
    path = settings_path()
    if not os.path.exists(path):
        return dict(DEFAULT_SETTINGS)

    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if not isinstance(data, dict):
                return dict(DEFAULT_SETTINGS)
            settings = dict(DEFAULT_SETTINGS)
            settings.update(data)
            return settings
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Warning: Could not load settings file: {exc}")
        return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> dict:
    """Save settings atomically to the per-user JSON settings file."""
    settings = dict(DEFAULT_SETTINGS, **(settings or {}))
    path = settings_path()
    temp_path = f"{path}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except OSError as exc:
        print(f"Error saving settings file: {exc}")
        raise
    return settings


def get_remembered_profile_id(settings: dict = None) -> str:
    settings = settings or load_settings()
    if not settings.get("remember_profile"):
        return ""
    return str(settings.get("remembered_profile_id") or "")


def remember_profile_enabled(settings: dict = None) -> bool:
    settings = settings or load_settings()
    return bool(settings.get("remember_profile"))


def set_remembered_profile(settings: dict, profile_id: str) -> dict:
    settings = dict(settings or load_settings())
    settings["remember_profile"] = True
    settings["remembered_profile_id"] = str(profile_id or "")
    return save_settings(settings)


def clear_remembered_profile(settings: dict) -> dict:
    settings = dict(settings or load_settings())
    settings["remember_profile"] = False
    settings["remembered_profile_id"] = ""
    return save_settings(settings)


def _is_windows() -> bool:
    return sys.platform.startswith("win") and winreg is not None


def _startup_command() -> str:
    """Build the startup command for the current runtime."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'

    python_exe = sys.executable
    lower = python_exe.lower()
    if lower.endswith("python.exe"):
        pythonw = python_exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(pythonw):
            python_exe = pythonw

    script_path = os.path.abspath(sys.argv[0])
    return f'"{python_exe}" "{script_path}"'


def is_startup_enabled() -> bool:
    """Return True when the Windows startup entry exists and is valid."""
    if not _is_windows():
        return False

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_PATH, 0, winreg.KEY_READ) as reg_key:
            value, _ = winreg.QueryValueEx(reg_key, STARTUP_REG_NAME)
            if value:
                current = _startup_command()
                if value != current:
                    enable_startup()
                return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        print(f"Warning: Could not read startup registry value: {exc}")
    return False


def enable_startup() -> bool:
    """Register the application to start with the current Windows user session."""
    if not _is_windows():
        raise RuntimeError("Windows startup registration is only supported on Windows.")

    command = _startup_command()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_PATH, 0, winreg.KEY_SET_VALUE) as reg_key:
            winreg.SetValueEx(reg_key, STARTUP_REG_NAME, 0, winreg.REG_SZ, command)
        return True
    except OSError as exc:
        raise RuntimeError(f"Failed to register startup: {exc}")


def disable_startup() -> bool:
    """Remove the application from Windows startup."""
    if not _is_windows():
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_PATH, 0, winreg.KEY_SET_VALUE) as reg_key:
            winreg.DeleteValue(reg_key, STARTUP_REG_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RuntimeError(f"Failed to remove startup entry: {exc}")


def set_startup_enabled(enabled: bool) -> bool:
    """Enable or disable the startup entry and return the actual state."""
    if enabled:
        success = enable_startup()
    else:
        success = disable_startup()
    settings = load_settings()
    settings["start_with_windows"] = enabled
    save_settings(settings)
    return success
