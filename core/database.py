"""
Database System - PostgreSQL backed, supports multi-item operations with foreign keys.

Each profile gets its own schema in one shared Postgres database (schema-per-tenant),
selected via `SET search_path`. All identifiers created here are left UNQUOTED so
Postgres folds them to lowercase - this matches the many raw-SQL call sites elsewhere
in the app (classes/*.py, ui/**/*.py) that already reference table/column names
unquoted, so they keep working unchanged against the folded lowercase names.
"""
import re

import psycopg2
from psycopg2 import OperationalError

from core.pg_config import load_server_config


class Database:
    """Database that integrates with parameter class system"""

    def __init__(self, profile_manager=None):
        self.profile_manager = profile_manager
        self.registered_classes = {}  # section_name -> class
        self.conn = None
        self.cursor = None
        self.database_name = None
        self.schema_name = None
        self.last_error = None
        # Current UI language; allows parameter classes to localize display names
        self.language = 'en'

    def has_permission(self, section, action='read'):
        """Local database - this is the host's own data, always fully accessible.
        Only RemoteDatabase (network clients) is actually gated by role permissions."""
        return True

    def register_class(self, cls):
        """Register a parameter class with the database"""
        try:
            # Create temporary instance to get metadata
            temp_obj = cls(0, None)  # Pass None for database to avoid circular dependency
            section_name = temp_obj.section

            self.registered_classes[section_name] = cls

            # Create/update database table for this class if connected
            if self.cursor:
                self._create_table_for_class(cls, section_name)

            print(f"✓ Registered parameter class: {section_name}")
            return True

        except Exception as e:
            print(f"✗ Failed to register {cls.__name__}: {e}")
            return False

    @staticmethod
    def _sanitize_schema_name(name):
        """Turn a free-text profile name into a safe, unquoted Postgres identifier."""
        sanitized = re.sub(r'[^a-z0-9_]', '_', (name or '').lower())
        if not sanitized or sanitized[0].isdigit():
            sanitized = f"p_{sanitized}"
        return sanitized

    @staticmethod
    def _profile_schema_name(company_name):
        """Build the per-profile schema name from the company name."""
        return Database._sanitize_schema_name(f"DB_{company_name or ''}")

    @staticmethod
    def _profile_database_name(company_name):
        """Build the per-profile database name from the company name."""
        return Database._sanitize_schema_name(f"DB_{company_name or ''}")

    @staticmethod
    def _maintenance_database_name(pg_config):
        return pg_config.get('maintenance_database') or pg_config.get('database') or 'postgres'

    def _connect_admin(self, pg_config):
        return psycopg2.connect(
            host=pg_config.get('host'),
            port=pg_config.get('port'),
            dbname=self._maintenance_database_name(pg_config),
            user=pg_config.get('user'),
            password=pg_config.get('password'),
        )

    def _ensure_profile_database(self, pg_config, database_name):
        """Create the profile database if it does not already exist."""
        admin_conn = self._connect_admin(pg_config)
        admin_conn.autocommit = True
        try:
            admin_cur = admin_conn.cursor()
            admin_cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database_name,))
            if not admin_cur.fetchone():
                admin_cur.execute(f"CREATE DATABASE {database_name}")
        finally:
            admin_conn.close()

    def connect(self):
        """Establish database connection for the selected profile."""
        self.last_error = None
        if not self.profile_manager or not self.profile_manager.selected_profile:
            self.last_error = "No profile selected, cannot connect to database"
            print(self.last_error)
            return False

        # Close existing connection
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None

        try:
            pg_config = load_server_config()
            profile = self.profile_manager.selected_profile
            database_name = profile.database_name or self._profile_database_name(
                profile.get_value('company name') or profile.name
            )

            if profile.database_name or not profile.schema_name:
                profile.database_name = database_name
                self._ensure_profile_database(pg_config, database_name)
                self.conn = psycopg2.connect(
                    host=pg_config.get('host'),
                    port=pg_config.get('port'),
                    dbname=database_name,
                    user=pg_config.get('user'),
                    password=pg_config.get('password'),
                )
                self.cursor = self.conn.cursor()
                self.database_name = database_name
                self.schema_name = None

                # Create tables for all registered classes
                self._create_all_tables()

                # Ensure meta/migrations and run one-time tasks
                self._ensure_meta_table()
                self._ensure_user_tables()
                self._run_one_time_migrations()

                print(f"✓ Connected to database: {database_name}")
                return True

            schema_name = profile.schema_name or self._profile_schema_name(
                profile.get_value('company name') or profile.name
            )
            profile.schema_name = schema_name

            self.conn = psycopg2.connect(
                host=pg_config.get('host'),
                port=pg_config.get('port'),
                dbname=pg_config.get('database'),
                user=pg_config.get('user'),
                password=pg_config.get('password'),
            )
            self.cursor = self.conn.cursor()

            self.cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")
            self.conn.commit()
            self.cursor.execute(f"SET search_path TO {schema_name}")
            self.database_name = None
            self.schema_name = schema_name

            # Create tables for all registered classes
            self._create_all_tables()

            # Ensure meta/migrations and run one-time tasks
            self._ensure_meta_table()
            self._ensure_user_tables()
            self._run_one_time_migrations()

            print(f"✓ Connected to database schema: {schema_name}")
            return True

        except OperationalError as e:
            self.last_error = str(e)
            print(f"✗ Failed to connect to database: {e}")
            return False
        except Exception as e:
            self.last_error = str(e)
            print(f"✗ Failed to connect to database: {e}")
            return False

    @staticmethod
    def _sql_type_for(param_type):
        """Map a parameter's declared 'type' to a Postgres column type.

        'bool' is deliberately mapped to a numeric type, not TEXT: the only
        two 'bool'-typed parameters in this app (Sales/Imports 'tva') are
        numeric percentage toggles (true_value/false_value are floats like
        20.0/0.0), not genuine True/False text - raw SQL elsewhere does
        arithmetic on them (e.g. `s.tva/100`), which Postgres (unlike SQLite)
        refuses to do implicitly against a TEXT column.
        """
        if param_type == 'int':
            return "INTEGER"
        if param_type in ('float', 'bool'):
            return "DOUBLE PRECISION"
        return "TEXT"  # string, image, date, text

    def _create_table_for_class(self, cls, section_name):
        """Create database table for a parameter class with foreign key support"""
        try:
            # Create temporary instance to get parameter info
            temp_obj = cls(0, None)

            # Get parameters that should be stored in database
            db_params = temp_obj.get_visible_parameters("database")

            if not db_params:
                print(f"No database parameters defined for {section_name}")
                return

            # Build column definitions
            columns = ["id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"]
            foreign_keys = []

            for param_key in db_params:
                if param_key in temp_obj.parameters:
                    param_info = temp_obj.parameters[param_key]

                    # Skip calculated parameters (they're computed, not stored)
                    if temp_obj.is_parameter_calculated(param_key):
                        continue

                    # Determine SQL type based on parameter type
                    sql_type = self._sql_type_for(param_info.get('type', 'string'))

                    # Add column (unquoted - folds to lowercase)
                    columns.append(f"{param_key} {sql_type}")

                    # Add foreign key constraints for ID fields
                    if param_key.endswith('_id') and param_key != 'id':
                        # Only enforce cascading on child item links; allow deletion of base entities freely
                        if param_key == 'sales_id':
                            foreign_keys.append(f"FOREIGN KEY ({param_key}) REFERENCES sales(id) ON DELETE CASCADE")
                        elif param_key == 'import_id':
                            foreign_keys.append(f"FOREIGN KEY ({param_key}) REFERENCES imports(id) ON DELETE CASCADE")

            # Combine columns and foreign keys
            all_constraints = columns + foreign_keys
            constraints_str = ",\n    ".join(all_constraints)

            # Create table if not exists
            sql = f"""
                CREATE TABLE IF NOT EXISTS {section_name} (
                    {constraints_str}
                )
            """
            self.cursor.execute(sql)
            self.conn.commit()

            # --- Migration: ensure all expected columns exist (add missing) ---
            try:
                self.cursor.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = %s",
                    (section_name.lower(),)
                )
                existing_cols = {row[0] for row in self.cursor.fetchall()}
                for param_key in db_params:
                    if param_key in temp_obj.parameters and param_key not in existing_cols:
                        pinfo = temp_obj.parameters[param_key]
                        if temp_obj.is_parameter_calculated(param_key):
                            continue
                        sql_type = self._sql_type_for(pinfo.get('type', 'string'))
                        try:
                            self.cursor.execute(f"ALTER TABLE {section_name} ADD COLUMN {param_key} {sql_type}")
                            self.conn.commit()
                            print(f"✓ Added missing column '{param_key}' to {section_name}")
                        except Exception as mig_e:
                            self.conn.rollback()
                            print(f"⚠️ Failed adding column {param_key} to {section_name}: {mig_e}")
            except Exception as e_cols:
                self.conn.rollback()
                print(f"⚠️ Column migration check failed for {section_name}: {e_cols}")

            print(f"✓ Created/verified table: {section_name}")

        except Exception as e:
            self.conn.rollback()
            print(f"✗ Error creating table for {section_name}: {e}")

    def _create_all_tables(self):
        """Create tables for all registered classes in proper order"""
        # Create tables in order to respect foreign key dependencies
        creation_order = [
            'Products', 'Clients', 'Suppliers',  # Base tables first
            'Sales', 'Imports',                   # Operation tables
            'Sales_Items', 'Import_Items'         # Item tables last
        ]

        # Create tables in order if they exist in registered classes
        for section_name in creation_order:
            if section_name in self.registered_classes:
                cls = self.registered_classes[section_name]
                self._create_table_for_class(cls, section_name)

        # Create any remaining tables not in the order list
        for section_name, cls in self.registered_classes.items():
            if section_name not in creation_order:
                self._create_table_for_class(cls, section_name)

        # Ensure new snapshot columns exist (idempotent)
        self._ensure_additional_columns()

    def _ensure_additional_columns(self):
        """Ensure newly introduced snapshot columns exist in existing databases."""
        required = {
            'sales': {'client_name': 'TEXT', 'state': 'TEXT'},
            'imports': {'supplier_name': 'TEXT'},
            'sales_items': {'product_name': 'TEXT'},
            'import_items': {'product_name': 'TEXT'}
        }
        for table, cols in required.items():
            try:
                self.cursor.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = %s",
                    (table,)
                )
                existing = {r[0] for r in self.cursor.fetchall()}
                for col, ctype in cols.items():
                    if col not in existing:
                        try:
                            self.cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ctype}")
                            self.conn.commit()
                            print(f"✓ Added missing column '{col}' to {table}")
                        except Exception as e_add:
                            self.conn.rollback()
                            print(f"⚠️ Could not add column {col} to {table}: {e_add}")
            except Exception as e_tab:
                self.conn.rollback()
                print(f"⚠️ Snapshot column check failed for {table}: {e_tab}")

    def _ensure_user_tables(self):
        """Create the Users/Roles/RolePermissions tables used for LAN network access.

        Kept separate from the registered-class table system since accounts/roles
        aren't a display-parameter class - they're used by core.user_manager and
        core.network.server, not by any UI tab.
        """
        try:
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS roles (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL
                )
            """)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS rolepermissions (
                    role_id INTEGER NOT NULL,
                    section TEXT NOT NULL,
                    can_read INTEGER NOT NULL DEFAULT 0,
                    can_write INTEGER NOT NULL DEFAULT 0,
                    can_delete INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(role_id, section),
                    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
                )
            """)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role_id INTEGER,
                    is_superadmin INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE SET NULL
                )
            """)
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            print(f"Warning: could not create user/role tables: {e}")

    # ---------------- Migration & Meta Helpers -----------------
    def _ensure_meta_table(self):
        try:
            self.cursor.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            print(f"Warning: could not create Meta table: {e}")

    def _get_meta(self, key, default=None):
        try:
            self.cursor.execute("SELECT value FROM meta WHERE key=%s", (key,))
            row = self.cursor.fetchone()
            return row[0] if row else default
        except Exception:
            self.conn.rollback()
            return default

    def _set_meta(self, key, value):
        try:
            self.cursor.execute(
                "INSERT INTO meta(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value))
            )
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            print(f"Warning: could not set meta {key}: {e}")

    def _run_one_time_migrations(self):
        """Run gated migrations using Meta flags so they execute only once per schema.

        Multi-instance safety: a Postgres advisory lock scoped to this schema is
        acquired before checking flags so that only one app instance can run
        migrations at a time. A second instance blocks on the lock, then
        re-checks - finding flags already set and skipping without doing any work.
        """
        # Fast path: if both flags are already set, nothing to do (no lock needed)
        if (self._get_meta('fk_relaxed', '0') == '1' and
                self._get_meta('backfill_product_name_done', '0') == '1'):
            return

        lock_target = self.database_name or self.schema_name
        lock_key = f"lamidap_migrate_{lock_target}"
        try:
            self.cursor.execute("SELECT pg_advisory_lock(hashtext(%s))", (lock_key,))
        except Exception as e:
            print(f"Migration: could not acquire advisory lock ({e}), skipping this session")
            return

        try:
            # Re-read flags inside the lock (another instance may have finished while we waited)
            try:
                self.cursor.execute(
                    "SELECT key, value FROM meta WHERE key IN ('fk_relaxed','backfill_product_name_done')"
                )
                flags = {row[0]: row[1] for row in self.cursor.fetchall()}
            except Exception as e:
                self.conn.rollback()
                print(f"Migration: could not read Meta flags: {e}")
                return

            fk_done = flags.get('fk_relaxed', '0') == '1'
            backfill_done = flags.get('backfill_product_name_done', '0') == '1'

            # 1) Legacy product_id FK relaxation: fresh Postgres schemas are
            # created without that FK to begin with (see _create_table_for_class),
            # so there's nothing to relax here - just mark it done.
            if not fk_done:
                self._set_meta('fk_relaxed', '1')

            # 2) Backfill missing product_name where product_id still exists
            if not backfill_done:
                try:
                    self.cursor.execute("""
                        UPDATE sales_items
                        SET product_name = (
                            SELECT name FROM products p WHERE p.id = sales_items.product_id
                        )
                        WHERE (product_name IS NULL OR product_name = '') AND product_id IS NOT NULL
                    """)
                    self.cursor.execute("""
                        UPDATE import_items
                        SET product_name = (
                            SELECT name FROM products p WHERE p.id = import_items.product_id
                        )
                        WHERE (product_name IS NULL OR product_name = '') AND product_id IS NOT NULL
                    """)
                    self.conn.commit()
                    self._set_meta('backfill_product_name_done', '1')
                    print("✓ Backfilled missing product_name snapshots where possible")
                except Exception as e:
                    self.conn.rollback()
                    print(f"Backfill product_name migration failed: {e}")
        finally:
            try:
                self.cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", (lock_key,))
            except Exception:
                pass

    def save(self, obj):
        """Save any parameter object to database"""
        if not self.cursor:
            print("Database not connected")
            return False

        try:
            # Use the object's built-in save method
            if hasattr(obj, 'save_to_database'):
                return obj.save_to_database()

            # Fallback: manual save
            return self._manual_save(obj)

        except Exception as e:
            print(f"Error saving {obj.section} object: {e}")
            return False

    def _manual_save(self, obj):
        """Manual save implementation as fallback"""
        section_name = obj.section
        data = obj.get_value(destination="database")

        # Filter out calculated parameters
        filtered_data = {}
        for key, value in data.items():
            if not obj.is_parameter_calculated(key):
                filtered_data[key] = value

        if hasattr(obj, 'id') and obj.id and obj.id > 0:
            # Update existing
            return self.update_item(obj.id, filtered_data, section_name)
        else:
            # Insert new and update object's ID
            new_id = self.add_item(filtered_data, section_name)
            if new_id:
                obj.id = new_id
                obj.set_value('id', new_id)
                return True
            return False

    def load(self, cls, obj_id):
        """Load and return a parameter object"""
        if not self.cursor:
            print("Database not connected")
            return None

        try:
            # Create new instance
            obj = cls(obj_id, self)

            # Use the object's built-in load method
            if hasattr(obj, 'load_database_data'):
                if obj.load_database_data():
                    return obj
                else:
                    return None

            return None

        except Exception as e:
            print(f"Error loading {cls.__name__} with ID {obj_id}: {e}")
            return None

    def delete(self, cls_or_obj, obj_id=None):
        """Delete an object and its related items (cascading)"""
        if not self.cursor:
            print("Database not connected")
            return False

        try:
            if obj_id is None:
                # Object instance passed
                obj = cls_or_obj
                section_name = obj.section
                obj_id = obj.id
            else:
                # Class and ID passed
                cls = cls_or_obj
                temp_obj = cls(0, None)
                section_name = temp_obj.section

            # Pre-delete handling for base entities referenced by items
            try:
                if section_name == 'Products':
                    # Nullify references in item tables to allow deletion while keeping name snapshots
                    self.cursor.execute("UPDATE sales_items SET product_id = NULL WHERE product_id = %s", (obj_id,))
                    self.cursor.execute("UPDATE import_items SET product_id = NULL WHERE product_id = %s", (obj_id,))
                # (Clients/Suppliers not stored via *_id in operations currently)
            except Exception as pre_e:
                print(f"Warning: pre-delete reference cleanup failed: {pre_e}")

            # Delete from database (foreign key constraints will handle cascading for child ops)
            self.cursor.execute(f"DELETE FROM {section_name} WHERE id = %s", (obj_id,))

            # Commit transaction
            self.conn.commit()

            return self.cursor.rowcount > 0

        except Exception as e:
            # Rollback on error
            self.conn.rollback()
            print(f"Error deleting object: {e}")
            return False

    def begin_transaction(self):
        """No-op under psycopg2 - a transaction is already implicitly open
        after connect()/commit(); kept for interface parity with callers."""
        pass

    def commit_transaction(self):
        """Commit the current transaction"""
        if self.conn:
            self.conn.commit()

    def rollback_transaction(self):
        """Rollback the current transaction"""
        if self.conn:
            self.conn.rollback()

    def query(self, cls, **filters):
        """Query objects with optional filters"""
        if not self.cursor:
            print("Database not connected")
            return []

        try:
            temp_obj = cls(0, None)
            section_name = temp_obj.section

            # Build query
            if filters:
                where_clause = " AND ".join([f"{k} = %s" for k in filters.keys()])
                sql = f"SELECT * FROM {section_name} WHERE {where_clause}"
                params = list(filters.values())
            else:
                sql = f"SELECT * FROM {section_name}"
                params = []

            # Execute query
            self.cursor.execute(sql, params)
            rows = self.cursor.fetchall()

            # Convert to objects
            objects = []
            for row in rows:
                obj_id = row[0]  # ID is always first column
                obj = self.load(cls, obj_id)
                if obj:
                    objects.append(obj)

            return objects

        except Exception as e:
            self.conn.rollback()
            print(f"Error querying {cls.__name__}: {e}")
            return []

    def get_all(self, cls):
        """Get all objects of a given class"""
        return self.query(cls)

    # Updated legacy methods for backward compatibility
    def add_item(self, data, section):
        """Add item to database and return the new ID"""
        if not self.cursor or section not in self.registered_classes:
            return None

        try:
            # Get parameters that should be stored
            cls = self.registered_classes[section]
            temp_obj = cls(0, None)
            db_params = temp_obj.get_visible_parameters("database")

            # Filter data to only include storable parameters
            filtered_data = {}
            for key in db_params:
                if (key in data and
                        not temp_obj.is_parameter_calculated(key)):
                    filtered_data[key] = data[key]

            if not filtered_data:
                return None

            # Build INSERT query
            columns = list(filtered_data.keys())
            placeholders = ['%s' for _ in columns]
            columns_str = ", ".join(columns)
            placeholders_str = ", ".join(placeholders)

            sql = f"INSERT INTO {section} ({columns_str}) VALUES ({placeholders_str}) RETURNING id"
            values = list(filtered_data.values())

            self.cursor.execute(sql, values)
            self.conn.commit()

            # Return the ID of the inserted record
            row = self.cursor.fetchone()
            return row[0] if row else None

        except Exception as e:
            self.conn.rollback()
            print(f"Error adding item to {section}: {e}")
            return None

    def update_item(self, item_id, data, section):
        """Update item in database"""
        if not self.cursor or section not in self.registered_classes:
            return False

        try:
            # Get parameters that should be stored
            cls = self.registered_classes[section]
            temp_obj = cls(0, None)
            db_params = temp_obj.get_visible_parameters("database")

            # Filter data to only include storable parameters
            filtered_data = {}
            for key in db_params:
                if (key in data and
                        not temp_obj.is_parameter_calculated(key)):
                    filtered_data[key] = data[key]

            if not filtered_data:
                return False

            # Build UPDATE query
            set_clauses = [f"{key} = %s" for key in filtered_data.keys()]
            set_clause = ", ".join(set_clauses)
            values = list(filtered_data.values())
            values.append(item_id)

            sql = f"UPDATE {section} SET {set_clause} WHERE id = %s"

            self.cursor.execute(sql, values)
            self.conn.commit()
            return True

        except Exception as e:
            self.conn.rollback()
            print(f"Error updating item in {section}: {e}")
            return False

    def get_items(self, section):
        """Get all items from section"""
        if not self.cursor or section not in self.registered_classes:
            return []

        try:
            self.cursor.execute(f"SELECT * FROM {section}")
            rows = self.cursor.fetchall()

            # Get column names - Postgres folds unquoted columns to lowercase,
            # so restore the PK's original 'ID' casing that callers throughout
            # the app expect (classes/base_class.py etc. do item.get('ID')).
            columns = [description[0] for description in self.cursor.description]
            if columns and columns[0].lower() == 'id':
                columns[0] = 'ID'

            # Convert to list of dictionaries
            return [dict(zip(columns, row)) for row in rows]

        except Exception as e:
            self.conn.rollback()
            print(f"Error getting items from {section}: {e}")
            return []

    def get_items_by_operation_id(self, operation_id, section):
        """Get items for a specific operation (Sales_Items or Import_Items)"""
        if not self.cursor or section not in self.registered_classes:
            return []

        try:
            # Determine the foreign key column name based on section
            if section == 'Sales_Items':
                fk_column = 'sales_id'
            elif section == 'Import_Items':
                fk_column = 'import_id'
            else:
                print(f"Unknown item section: {section}")
                return []

            self.cursor.execute(f"SELECT * FROM {section} WHERE {fk_column} = %s", (operation_id,))
            rows = self.cursor.fetchall()

            # Get column names (see get_items() for why 'ID' is restored)
            columns = [description[0] for description in self.cursor.description]
            if columns and columns[0].lower() == 'id':
                columns[0] = 'ID'

            # Convert to list of dictionaries
            return [dict(zip(columns, row)) for row in rows]

        except Exception as e:
            self.conn.rollback()
            print(f"Error getting items from {section} for operation {operation_id}: {e}")
            return []

    def delete_item(self, item_id, section):
        """Delete item from section"""
        if not self.cursor or section not in self.registered_classes:
            return False

        try:
            # Pre-clean references if deleting a product
            if section == 'Products':
                try:
                    self.cursor.execute("UPDATE sales_items SET product_id = NULL WHERE product_id = %s", (item_id,))
                    self.cursor.execute("UPDATE import_items SET product_id = NULL WHERE product_id = %s", (item_id,))
                except Exception as e_clean:
                    self.conn.rollback()
                    print(f"Warning: could not nullify product references before deletion: {e_clean}")
            self.cursor.execute(f"DELETE FROM {section} WHERE id = %s", (item_id,))
            self.conn.commit()
            return self.cursor.rowcount > 0
        except Exception as e:
            self.conn.rollback()
            print(f"Error deleting item from {section}: {e}")
            return False

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None
