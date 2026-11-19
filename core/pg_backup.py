"""
PostgreSQL custom-format backup/restore for a single profile.
"""
from datetime import datetime
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

import psycopg2
from psycopg2 import sql

from core.pg_config import load_server_config

LOGGER = logging.getLogger(__name__)
_TOOL_ENV_VARS = ("POSTGRES_BIN", "POSTGRESQL_BIN", "PG_BIN")


def _version_key(path):
    match = re.search(r"PostgreSQL[\\/](\d+(?:\.\d+)*)[\\/]bin", path, re.IGNORECASE)
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def discover_postgres_tool(tool_name, config=None):
    """Return ``(executable_path, searched_locations)`` in priority order."""
    config = config or load_server_config()
    executable = f"{tool_name}.exe" if os.name == "nt" else tool_name
    candidates = []

    for key in ("postgres_bin_dir", "pg_bin_dir", "postgresql_bin_dir"):
        configured = str(config.get(key) or "").strip()
        if configured:
            candidates.append(os.path.join(configured, executable))

    for variable in _TOOL_ENV_VARS:
        directory = os.environ.get(variable, "").strip()
        if directory:
            candidates.append(os.path.join(directory, executable))
    pg_home = os.environ.get("PGHOME", "").strip()
    if pg_home:
        candidates.append(os.path.join(pg_home, "bin", executable))

    searched = list(candidates)
    for candidate in candidates:
        if os.path.isfile(candidate):
            resolved = os.path.abspath(candidate)
            LOGGER.info("PostgreSQL tool %s found: %s", tool_name, resolved)
            return resolved, searched

    path_match = shutil.which(tool_name)
    searched.append(f"PATH ({tool_name})")
    if path_match:
        LOGGER.info("PostgreSQL tool %s found on PATH: %s", tool_name, path_match)
        return os.path.abspath(path_match), searched

    if os.name == "nt":
        roots = []
        for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            root = os.environ.get(variable)
            if root:
                roots.append(os.path.join(root, "PostgreSQL"))
        common = []
        for root in dict.fromkeys(roots):
            if not os.path.isdir(root):
                searched.append(os.path.join(root, "<version>", "bin", executable))
                continue
            for version in os.listdir(root):
                common.append(os.path.join(root, version, "bin", executable))
        common.sort(key=_version_key, reverse=True)
        candidates = common

    for candidate in candidates:
        if candidate not in searched:
            searched.append(candidate)
        if os.path.isfile(candidate):
            resolved = os.path.abspath(candidate)
            LOGGER.info("PostgreSQL tool %s found: %s", tool_name, resolved)
            return resolved, searched

    LOGGER.warning("PostgreSQL tool %s was not found; searched: %s", tool_name, searched)
    return None, searched


def _require_tool(tool_name, config):
    path, searched = discover_postgres_tool(tool_name, config)
    if path:
        return path
    configured = str(config.get("postgres_bin_dir") or "").strip() or "(not configured)"
    locations = "\n".join(f"- {location}" for location in searched)
    raise RuntimeError(
        f"{tool_name} was not found.\n"
        f"Configured PostgreSQL Bin Directory: {configured}\n"
        f"Searched locations:\n{locations}\n"
        "Set 'PostgreSQL Bin Directory' in Network & Users > Database Server "
        "to the folder containing the PostgreSQL command-line tools."
    )


def _run_tool(command, env, config, tool_name):
    LOGGER.info("Running %s: %s", tool_name, " ".join(command))
    result = subprocess.run(
        command,
        env=env,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "No error output").strip()
        password = str(config.get("password") or "")
        if password:
            detail = detail.replace(password, "[REDACTED]")
        raise RuntimeError(f"{tool_name} failed (exit code {result.returncode}): {detail}")
    return result


def _safe_name(value):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "database")).strip("._")
    return cleaned or "database"


def _new_dump_path(dest_dir, database_name):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(dest_dir, f"{_safe_name(database_name)}_{stamp}.backup")


def _find_dump(source_dir, legacy_name):
    legacy = os.path.join(source_dir, legacy_name)
    if os.path.isfile(legacy) and os.path.getsize(legacy) > 0:
        return legacy
    backups = [
        os.path.join(source_dir, name)
        for name in os.listdir(source_dir)
        if name.lower().endswith(".backup")
        and os.path.isfile(os.path.join(source_dir, name))
        and os.path.getsize(os.path.join(source_dir, name)) > 0
    ]
    if not backups:
        raise RuntimeError(f"No valid PostgreSQL custom-format backup found in {source_dir}")
    return max(backups, key=os.path.getmtime)


def _verify_dump(dump_file):
    if not os.path.isfile(dump_file):
        raise RuntimeError("PostgreSQL reported success but did not create the backup file")
    if os.path.getsize(dump_file) <= 0:
        raise RuntimeError("PostgreSQL created an empty backup file")


def _connection_and_env():
    config = load_server_config()
    env = os.environ.copy()
    env['PGPASSWORD'] = config.get('password') or ''
    return config, env


def _maintenance_database_name(config):
    return config.get('maintenance_database') or config.get('database') or 'postgres'


def _connect(config):
    return psycopg2.connect(
        host=config.get('host'), port=config.get('port'), dbname=config.get('database'),
        user=config.get('user'), password=config.get('password'),
    )


def _connect_admin(config):
    return psycopg2.connect(
        host=config.get('host'),
        port=config.get('port'),
        dbname=_maintenance_database_name(config),
        user=config.get('user'),
        password=config.get('password'),
    )


def _ensure_database_exists(database_name):
    config, _ = _connection_and_env()
    conn = _connect_admin(config)
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database_name,))
        if not cur.fetchone():
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    finally:
        conn.close()


def _drop_database(database_name):
    config, _ = _connection_and_env()
    conn = _connect_admin(config)
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (database_name,))
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))
    finally:
        conn.close()


def backup_database(database_name, dest_dir):
    """Write a full database backup into `dest_dir`."""
    os.makedirs(dest_dir, exist_ok=True)
    config, env = _connection_and_env()
    pg_dump = _require_tool("pg_dump", config)

    dump_file = _new_dump_path(dest_dir, database_name)
    cmd = [
        pg_dump, '--host', str(config.get('host')), '--port', str(config.get('port')),
        '--username', str(config.get('user')), '--dbname', database_name,
        '--format=custom', '--file', dump_file,
    ]
    try:
        _run_tool(cmd, env, config, "pg_dump")
        _verify_dump(dump_file)
        return dump_file
    except Exception:
        if os.path.exists(dump_file):
            try:
                os.remove(dump_file)
            except OSError as cleanup_error:
                LOGGER.warning("Could not remove failed backup %s: %s", dump_file, cleanup_error)
        raise


def restore_database(database_name, source_dir):
    """Restore a full database backup previously written by backup_database()."""
    dump_file = _find_dump(source_dir, "database.dump")
    config, env = _connection_and_env()
    pg_restore = _require_tool("pg_restore", config)
    _drop_database(database_name)
    _ensure_database_exists(database_name)

    cmd = [
        pg_restore, '--host', str(config.get('host')), '--port', str(config.get('port')),
        '--username', str(config.get('user')), '--dbname', database_name,
        '--no-owner', dump_file,
    ]
    _run_tool(cmd, env, config, "pg_restore")


def clone_database(source_database, dest_database):
    """Clone one profile database into another."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backup_database(source_database, temp_dir)
        restore_database(dest_database, temp_dir)


def backup_schema(schema_name, dest_dir):
    """Write a backup of `schema_name` into `dest_dir` (caller ensures it exists)."""
    os.makedirs(dest_dir, exist_ok=True)
    return _backup_with_pg_dump(schema_name, dest_dir)


def restore_schema(schema_name, source_dir):
    """Restore `schema_name` from a backup previously written by backup_schema()."""
    try:
        dump_file = _find_dump(source_dir, "schema.dump")
    except RuntimeError:
        # Retain restore compatibility for backups made by older releases.
        _restore_with_copy(schema_name, source_dir)
        return
    _restore_with_pg_restore(schema_name, dump_file)


def _backup_with_pg_dump(schema_name, dest_dir):
    config, env = _connection_and_env()
    pg_dump = _require_tool("pg_dump", config)
    dump_file = _new_dump_path(dest_dir, schema_name)
    cmd = [
        pg_dump, '--host', str(config.get('host')), '--port', str(config.get('port')),
        '--username', str(config.get('user')), '--dbname', str(config.get('database')),
        '--schema', schema_name, '--format=custom', '--file', dump_file,
    ]
    try:
        _run_tool(cmd, env, config, "pg_dump")
        _verify_dump(dump_file)
        return dump_file
    except Exception:
        if os.path.exists(dump_file):
            try:
                os.remove(dump_file)
            except OSError as cleanup_error:
                LOGGER.warning("Could not remove failed backup %s: %s", dump_file, cleanup_error)
        raise


def _restore_with_pg_restore(schema_name, dump_file):
    config, env = _connection_and_env()
    pg_restore = _require_tool("pg_restore", config)
    # Drop and recreate the schema first so restore starts from a clean slate
    conn = _connect(config)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
    cur.execute(f"CREATE SCHEMA {schema_name}")
    conn.close()

    cmd = [
        pg_restore, '--host', str(config.get('host')), '--port', str(config.get('port')),
        '--username', str(config.get('user')), '--dbname', str(config.get('database')),
        '--no-owner', dump_file,
    ]
    _run_tool(cmd, env, config, "pg_restore")


def _backup_with_copy(schema_name, dest_dir):
    config, _ = _connection_and_env()
    conn = _connect(config)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            (schema_name,)
        )
        tables = [r[0] for r in cur.fetchall()]

        with open(os.path.join(dest_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"tables": tables}, f)

        for table in tables:
            csv_path = os.path.join(dest_dir, f"{table}.csv")
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                cur.copy_expert(f"COPY {schema_name}.{table} TO STDOUT WITH CSV HEADER", f)
    finally:
        conn.close()


def _restore_with_copy(schema_name, source_dir):
    manifest_path = os.path.join(source_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        raise RuntimeError("No backup data found (manifest.json missing)")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    config, _ = _connection_and_env()
    conn = _connect(config)
    try:
        cur = conn.cursor()
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")
        conn.commit()

        # Only tables that already exist in the (freshly reconnected) schema -
        # an older backup might list tables from a since-removed feature.
        existing_tables = []
        for table in manifest["tables"]:
            if not os.path.exists(os.path.join(source_dir, f"{table}.csv")):
                continue
            cur.execute("SELECT to_regclass(%s)", (f"{schema_name}.{table}",))
            if cur.fetchone()[0]:
                existing_tables.append(table)

        if existing_tables:
            # Truncate every affected table together in one statement so
            # CASCADE (e.g. Products -> Sales_Items) can't wipe out data this
            # loop already restored into an earlier table.
            table_list = ", ".join(f"{schema_name}.{t}" for t in existing_tables)
            cur.execute(f"TRUNCATE {table_list} RESTART IDENTITY CASCADE")

        for table in existing_tables:
            csv_path = os.path.join(source_dir, f"{table}.csv")
            with open(csv_path, "r", newline="", encoding="utf-8") as f:
                cur.copy_expert(f"COPY {schema_name}.{table} FROM STDIN WITH CSV HEADER", f)

            # Not every table has an identity 'id' column (e.g. Meta's PK is
            # 'key', RolePermissions has no single-column PK at all) - only
            # bump the sequence for tables that actually have one.
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s AND column_name = 'id'",
                (schema_name, table)
            )
            if cur.fetchone():
                cur.execute(f"SELECT MAX(id) FROM {schema_name}.{table}")
                max_id = cur.fetchone()[0]
                if max_id is not None:
                    cur.execute(
                        "SELECT setval(pg_get_serial_sequence(%s, 'id'), %s)",
                        (f"{schema_name}.{table}", max_id)
                    )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
