"""
Postgres-schema-level backup/restore for a single profile.

Replaces the old approach of just copying the profile's SQLite .db file, which
no longer exists now that data lives in one shared Postgres database. Prefers
the pg_dump/pg_restore CLI tools when available on PATH (full fidelity - data,
sequences, constraints), and falls back to a pure-psycopg2 per-table COPY dump
when those client tools aren't installed on this machine.
"""
import json
import os
import shutil
import subprocess
import tempfile

import psycopg2

from core.pg_config import load_server_config


def _pg_dump_available():
    return shutil.which('pg_dump') is not None and shutil.which('pg_restore') is not None


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
            cur.execute(f"CREATE DATABASE {database_name}")
    finally:
        conn.close()


def _drop_database(database_name):
    config, _ = _connection_and_env()
    conn = _connect_admin(config)
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (database_name,))
        cur.execute(f"DROP DATABASE IF EXISTS {database_name}")
    finally:
        conn.close()


def backup_database(database_name, dest_dir):
    """Write a full database backup into `dest_dir`."""
    os.makedirs(dest_dir, exist_ok=True)
    config, env = _connection_and_env()
    if shutil.which('pg_dump') is None or shutil.which('pg_restore') is None:
        raise RuntimeError("pg_dump/pg_restore are required for real database backups")

    dump_file = os.path.join(dest_dir, "database.dump")
    cmd = [
        'pg_dump', '-h', str(config.get('host')), '-p', str(config.get('port')),
        '-U', str(config.get('user')), '-d', database_name, '-Fc', '-f', dump_file,
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {result.stderr}")


def restore_database(database_name, source_dir):
    """Restore a full database backup previously written by backup_database()."""
    dump_file = os.path.join(source_dir, "database.dump")
    if not os.path.exists(dump_file):
        raise RuntimeError("No database dump found (database.dump missing)")
    if shutil.which('pg_dump') is None or shutil.which('pg_restore') is None:
        raise RuntimeError("pg_dump/pg_restore are required for real database restores")

    config, env = _connection_and_env()
    _drop_database(database_name)
    _ensure_database_exists(database_name)

    cmd = [
        'pg_restore', '-h', str(config.get('host')), '-p', str(config.get('port')),
        '-U', str(config.get('user')), '-d', database_name, '--no-owner', dump_file,
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"pg_restore failed: {result.stderr}")


def clone_database(source_database, dest_database):
    """Clone one profile database into another."""
    with tempfile.TemporaryDirectory() as temp_dir:
        backup_database(source_database, temp_dir)
        restore_database(dest_database, temp_dir)


def backup_schema(schema_name, dest_dir):
    """Write a backup of `schema_name` into `dest_dir` (caller ensures it exists)."""
    os.makedirs(dest_dir, exist_ok=True)
    if _pg_dump_available():
        _backup_with_pg_dump(schema_name, dest_dir)
    else:
        _backup_with_copy(schema_name, dest_dir)


def restore_schema(schema_name, source_dir):
    """Restore `schema_name` from a backup previously written by backup_schema()."""
    dump_file = os.path.join(source_dir, "schema.dump")
    if os.path.exists(dump_file) and _pg_dump_available():
        _restore_with_pg_restore(schema_name, dump_file)
    else:
        _restore_with_copy(schema_name, source_dir)


def _backup_with_pg_dump(schema_name, dest_dir):
    config, env = _connection_and_env()
    dump_file = os.path.join(dest_dir, "schema.dump")
    cmd = [
        'pg_dump', '-h', str(config.get('host')), '-p', str(config.get('port')),
        '-U', str(config.get('user')), '-d', str(config.get('database')),
        '-n', schema_name, '-Fc', '-f', dump_file,
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {result.stderr}")


def _restore_with_pg_restore(schema_name, dump_file):
    config, env = _connection_and_env()
    # Drop and recreate the schema first so restore starts from a clean slate
    conn = _connect(config)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
    cur.execute(f"CREATE SCHEMA {schema_name}")
    conn.close()

    cmd = [
        'pg_restore', '-h', str(config.get('host')), '-p', str(config.get('port')),
        '-U', str(config.get('user')), '-d', str(config.get('database')),
        '--no-owner', dump_file,
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"pg_restore failed: {result.stderr}")


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
