"""
Connection settings for the single, central PostgreSQL server that backs every
profile (one schema per profile in one shared database). Kept separate from
per-profile config.json since these settings are shared across all profiles,
not tied to any one of them.
"""
import json
import os
from core.runtime_paths import portable_dir

import psycopg2

CONFIG_PATH = os.getenv("PYLOCALINVENTORY_PG_CONFIG") or os.path.join(
    portable_dir("profiles"), "_server_config.json"
)

DEFAULT_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "maintenance_database": "postgres",
    "database": "lamidap",
    "user": "",
    "password": "",
    "postgres_bin_dir": "",
}


def _config_path():
    return os.getenv("PYLOCALINVENTORY_PG_CONFIG") or CONFIG_PATH


def load_server_config():
    """Load Postgres connection settings, creating a default file if absent."""
    path = _config_path()
    if not os.path.exists(path):
        save_server_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        config = dict(DEFAULT_CONFIG)
        config.update(data)
        protected = config.pop("password_dpapi", None)
        if protected is not None:
            from core.network.windows_service import unprotect_machine_secret
            config["password"] = unprotect_machine_secret(protected)
        return config
    except Exception as e:
        if os.getenv("PYLOCALINVENTORY_PG_CONFIG"):
            raise RuntimeError(
                "Unable to load the Windows Service PostgreSQL configuration"
            ) from e
        print(f"Failed to load Postgres server config, using defaults: {e}")
        return dict(DEFAULT_CONFIG)


def save_server_config(config):
    """Persist Postgres connection settings."""
    path = _config_path()
    if os.getenv("PYLOCALINVENTORY_PG_CONFIG"):
        raise RuntimeError("The Windows Service PostgreSQL configuration is read-only")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)


def test_connection(config):
    """Try connecting with the given settings. Returns (ok, message)."""
    try:
        conn = psycopg2.connect(
            host=config.get("host"),
            port=config.get("port"),
            dbname=config.get("maintenance_database") or config.get("database"),
            user=config.get("user"),
            password=config.get("password"),
            connect_timeout=5,
        )
        conn.close()
        return True, "Connection successful"
    except Exception as e:
        return False, str(e)
