"""
Connection settings for the single, central PostgreSQL server that backs every
profile (one schema per profile in one shared database). Kept separate from
per-profile config.json since these settings are shared across all profiles,
not tied to any one of them.
"""
import json
import os

import psycopg2

CONFIG_PATH = os.path.join("profiles", "_server_config.json")

DEFAULT_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "maintenance_database": "postgres",
    "database": "lamidap",
    "user": "",
    "password": "",
}


def load_server_config():
    """Load Postgres connection settings, creating a default file if absent."""
    if not os.path.exists(CONFIG_PATH):
        save_server_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)

    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        config = dict(DEFAULT_CONFIG)
        config.update(data)
        return config
    except Exception as e:
        print(f"Failed to load Postgres server config, using defaults: {e}")
        return dict(DEFAULT_CONFIG)


def save_server_config(config):
    """Persist Postgres connection settings."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
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
