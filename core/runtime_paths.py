"""Runtime path helpers for source and PyInstaller builds."""
import os
import shutil
import sys


def is_frozen():
    return getattr(sys, "frozen", False)


def app_root():
    """Return the writable application root."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundled_root():
    """Return the location of bundled read-only resources."""
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return app_root()


def resource_path(*parts):
    return os.path.join(bundled_root(), *parts)


def app_path(*parts):
    return os.path.join(app_root(), *parts)


def user_data_root():
    """Return a per-user directory that is writable even during Startup."""
    base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or os.path.expanduser("~")
    root = os.path.join(base, "PyLocalInventory")
    os.makedirs(root, exist_ok=True)
    return root


def portable_dir(name):
    """Return writable per-user storage, seeding existing/bundled data once."""
    target = os.path.join(user_data_root(), name)
    if not os.path.exists(target):
        # Prefer data beside the executable for migration from older builds.
        candidates = (app_path(name), resource_path(name))
        source = next(
            (path for path in candidates if os.path.abspath(path) != os.path.abspath(target) and os.path.isdir(path)),
            None,
        )
        if source:
            shutil.copytree(source, target)
        else:
            os.makedirs(target, exist_ok=True)
    return target
