"""
Database System - PostgreSQL backed, supports multi-item operations with foreign keys.

Each profile gets its own schema in one shared Postgres database (schema-per-tenant),
selected via `SET search_path`. All identifiers created here are left UNQUOTED so
Postgres folds them to lowercase - this matches the many raw-SQL call sites elsewhere
in the app (classes/*.py, ui/**/*.py) that already reference table/column names
unquoted, so they keep working unchanged against the folded lowercase names.
"""
import re
from datetime import datetime

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
                self._ensure_attachment_tables()
                self._ensure_payments_table()
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
            self._ensure_attachment_tables()
            self._ensure_payments_table()
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
        if param_type == 'decimal':
            return "NUMERIC(15, 3)"
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
            'clients': {
                'ice': 'TEXT', 'created_by': 'INTEGER',
                'created_by_username': 'TEXT', 'created_at': 'TEXT',
            },
            'products': {
                'created_by': 'INTEGER', 'created_by_username': 'TEXT', 'created_at': 'TEXT',
            },
            'services': {
                'unit_price': 'DOUBLE PRECISION', 'created_by': 'INTEGER',
                'created_by_username': 'TEXT', 'created_at': 'TEXT',
            },
            'sales': {
                'client_id': 'INTEGER', 'client_name': 'TEXT', 'state': 'TEXT',
                'created_by': 'INTEGER', 'created_by_username': 'TEXT',
                'created_at': 'TEXT', 'operation_token': 'TEXT',
            },
            'imports': {
                'supplier_name': 'TEXT', 'supplier_id': 'INTEGER',
                'created_by': 'INTEGER', 'created_by_username': 'TEXT',
                'created_at': 'TEXT', 'operation_token': 'TEXT',
            },
            'reports': {
                'report_type': 'TEXT', 'created_by': 'INTEGER',
                'created_by_username': 'TEXT', 'created_at': 'TEXT',
            },
            'sales_items': {
                'product_name': 'TEXT', 'service_id': 'INTEGER', 'item_type': 'TEXT',
            },
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
                            print(f"Added missing column '{col}' to {table}")
                        except Exception as e_add:
                            self.conn.rollback()
                            print(f"Warning: could not add column {col} to {table}: {e_add}")
            except Exception as e_tab:
                self.conn.rollback()
                print(f"Warning: snapshot column check failed for {table}: {e_tab}")

        try:
            index_statements = (
                "CREATE INDEX IF NOT EXISTS sales_created_by_idx ON sales(created_by)",
                "CREATE INDEX IF NOT EXISTS imports_created_by_idx ON imports(created_by)",
                "CREATE INDEX IF NOT EXISTS reports_created_by_idx ON reports(created_by)",
                "CREATE INDEX IF NOT EXISTS reports_report_type_idx ON reports(report_type)",
                "CREATE INDEX IF NOT EXISTS sales_items_sales_id_idx ON sales_items(sales_id)",
                "CREATE INDEX IF NOT EXISTS sales_items_service_id_idx ON sales_items(service_id)",
                "CREATE INDEX IF NOT EXISTS import_items_import_id_idx ON import_items(import_id)",
                "CREATE INDEX IF NOT EXISTS import_items_product_id_idx ON import_items(product_id)",
                "CREATE INDEX IF NOT EXISTS sales_items_product_id_idx ON sales_items(product_id)",
                "CREATE INDEX IF NOT EXISTS imports_supplier_id_idx ON imports(supplier_id)",
                "CREATE INDEX IF NOT EXISTS products_normalized_name_idx "
                "ON products (LOWER(REGEXP_REPLACE(BTRIM(name), '\\s+', ' ', 'g')))",
                "CREATE INDEX IF NOT EXISTS products_normalized_username_idx "
                "ON products (LOWER(REGEXP_REPLACE(BTRIM(username), '\\s+', ' ', 'g')))",
                "CREATE INDEX IF NOT EXISTS services_normalized_name_idx "
                "ON services (LOWER(REGEXP_REPLACE(BTRIM(name), '\\s+', ' ', 'g')))",
                "CREATE INDEX IF NOT EXISTS clients_normalized_username_idx "
                "ON clients (LOWER(REGEXP_REPLACE(BTRIM(username), '\\s+', ' ', 'g')))",
                "CREATE INDEX IF NOT EXISTS clients_normalized_name_idx "
                "ON clients (LOWER(REGEXP_REPLACE(BTRIM(name), '\\s+', ' ', 'g')))",
                "CREATE INDEX IF NOT EXISTS suppliers_normalized_username_idx "
                "ON suppliers (LOWER(REGEXP_REPLACE(BTRIM(username), '\\s+', ' ', 'g')))",
                "CREATE INDEX IF NOT EXISTS suppliers_normalized_name_idx "
                "ON suppliers (LOWER(REGEXP_REPLACE(BTRIM(name), '\\s+', ' ', 'g')))",
                "CREATE UNIQUE INDEX IF NOT EXISTS sales_operation_token_uidx "
                "ON sales(operation_token) WHERE operation_token IS NOT NULL AND operation_token <> ''",
                "CREATE UNIQUE INDEX IF NOT EXISTS imports_operation_token_uidx "
                "ON imports(operation_token) WHERE operation_token IS NOT NULL AND operation_token <> ''",
            )
            for statement in index_statements:
                self.cursor.execute(statement)
            self.conn.commit()
        except Exception as exc:
            self.conn.rollback()
            print(f"Warning: could not create workflow indexes: {exc}")

        # Existing installations created this column as INTEGER. PostgreSQL's
        # cast keeps all old values intact. Check first to avoid taking an
        # unnecessary table lock every time another LAN client starts.
        try:
            self.cursor.execute(
                "SELECT data_type, numeric_precision, numeric_scale "
                "FROM information_schema.columns WHERE table_schema=current_schema() "
                "AND table_name='sales_items' AND column_name='quantity'"
            )
            column = self.cursor.fetchone()
            if column and column != ('numeric', 15, 3):
                self.cursor.execute(
                    "ALTER TABLE sales_items ALTER COLUMN quantity TYPE NUMERIC(15, 3) "
                    "USING quantity::NUMERIC(15, 3)"
                )
            self.conn.commit()
        except Exception as exc:
            self.conn.rollback()
            print(f"Warning: could not migrate sales_items.quantity to decimal: {exc}")

        # Client IDs were historically only resolved in memory. Backfill the
        # stable relation from usernames once, then index it for client views.
        try:
            self.cursor.execute(
                "UPDATE sales s SET client_id=c.id FROM clients c "
                "WHERE s.client_id IS NULL AND s.client_username=c.username"
            )
            self.cursor.execute("CREATE INDEX IF NOT EXISTS sales_client_id_idx ON sales(client_id)")
            self.conn.commit()
        except Exception as exc:
            self.conn.rollback()
            print(f"Warning: could not backfill sales.client_id: {exc}")

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

    def _ensure_attachment_tables(self):
        """Create generic attachment metadata; document bytes are disk-backed."""
        try:
            from core.attachments import AttachmentService
            AttachmentService(self).ensure_tables()
        except Exception as e:
            self.conn.rollback()
            print(f"Warning: could not create attachment tables: {e}")

    def _ensure_payments_table(self):
        """Create the client-account payment table during trusted host startup."""
        try:
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    sale_id INTEGER,
                    sales_item_id INTEGER,
                    amount DOUBLE PRECISION,
                    date TEXT,
                    FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE,
                    FOREIGN KEY (sales_item_id) REFERENCES sales_items(id) ON DELETE CASCADE
                )
                """
            )
            self.cursor.execute(
                "ALTER TABLE payments ADD COLUMN IF NOT EXISTS sales_item_id INTEGER"
            )
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            print(f"Warning: could not create Payments table: {e}")

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

    @staticmethod
    def _sale_decimal(value, field, minimum=None):
        from decimal import Decimal, InvalidOperation
        try:
            number = Decimal(str(value if value not in (None, '') else 0).replace(' ', '').replace(',', '.'))
        except (InvalidOperation, ValueError):
            raise ValueError(f"Invalid numeric value for {field}: {value!r}")
        if minimum is not None and number < Decimal(str(minimum)):
            raise ValueError(f"{field} must be at least {minimum}")
        return number

    @staticmethod
    def _normalize_exact(value):
        return " ".join(str(value or "").split()).casefold()

    def _find_named_record(self, table, name, record_id=None):
        if record_id not in (None, "", 0, "0"):
            self.cursor.execute(f"SELECT id, name FROM {table} WHERE id = %s", (int(record_id),))
            row = self.cursor.fetchone()
            if row:
                return int(row[0]), row[1]
        self.cursor.execute(
            f"SELECT id, name FROM {table} "
            "WHERE LOWER(REGEXP_REPLACE(BTRIM(name), '\\s+', ' ', 'g')) = %s "
            "ORDER BY id LIMIT 1",
            (self._normalize_exact(name),),
        )
        row = self.cursor.fetchone()
        return (int(row[0]), row[1]) if row else (None, None)

    @staticmethod
    def _actor_fields(user):
        user = user or {}
        return {
            "created_by": user.get("id"),
            "created_by_username": user.get("username") or "Local Admin",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _create_pending_sale_entities(self, pending_entities, user):
        resolved = {}
        actor = self._actor_fields(user)
        for entity in pending_entities or []:
            if not isinstance(entity, dict):
                raise ValueError("Pending entity data must be an object")
            kind = str(entity.get("type") or "").strip().casefold()
            name = " ".join(str(entity.get("name") or "").split())
            if kind not in ("client", "product", "service") or not name:
                raise ValueError("Pending entity type and name are required")
            key = (kind, self._normalize_exact(name))
            if key in resolved:
                continue
            self.cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"{kind}:{self._normalize_exact(name)}",),
            )

            if kind == "client":
                username = " ".join(str(entity.get("username") or name).split())
                self.cursor.execute(
                    "SELECT id, name FROM clients "
                    "WHERE LOWER(REGEXP_REPLACE(BTRIM(username), '\\s+', ' ', 'g')) = %s "
                    "OR LOWER(REGEXP_REPLACE(BTRIM(name), '\\s+', ' ', 'g')) = %s "
                    "ORDER BY id LIMIT 1",
                    (self._normalize_exact(username), self._normalize_exact(name)),
                )
                row = self.cursor.fetchone()
                if row:
                    resolved[key] = int(row[0])
                    continue
                self.cursor.execute(
                    "INSERT INTO clients "
                    "(username, name, client_type, created_by, created_by_username, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        username, name, entity.get("client_type") or "individual",
                        actor["created_by"], actor["created_by_username"], actor["created_at"],
                    ),
                )
                resolved[key] = int(self.cursor.fetchone()[0])
                resolved[("client", self._normalize_exact(username))] = resolved[key]
                continue

            table = "products" if kind == "product" else "services"
            record_id, _ = self._find_named_record(table, name)
            if record_id:
                resolved[key] = record_id
                continue

            sale_price = self._sale_decimal(
                entity.get("sale_price", entity.get("unit_price")),
                f"{kind} {name} price",
                "0",
            )
            if kind == "product":
                purchase_price = self._sale_decimal(
                    entity.get("purchase_price", 0), f"product {name} purchase price", "0"
                )
                self.cursor.execute(
                    "INSERT INTO products "
                    "(name, username, unit_price, sale_price, category, description, "
                    "created_by, created_by_username, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        name, str(entity.get("sku") or name), purchase_price, sale_price,
                        str(entity.get("category") or ""), str(entity.get("description") or ""),
                        actor["created_by"], actor["created_by_username"], actor["created_at"],
                    ),
                )
                product_id = int(self.cursor.fetchone()[0])
                initial_quantity = self._sale_decimal(
                    entity.get("initial_quantity", 0),
                    f"product {name} initial quantity",
                    "0",
                )
                if initial_quantity:
                    self.cursor.execute(
                        "INSERT INTO imports "
                        "(supplier_username, supplier_name, date, tva, notes, "
                        "created_by, created_by_username, created_at) "
                        "VALUES ('', 'Opening Stock', %s, 0, %s, %s, %s, %s) RETURNING id",
                        (
                            datetime.now().strftime("%Y-%m-%d"),
                            f"Opening stock for {name}",
                            actor["created_by"], actor["created_by_username"], actor["created_at"],
                        ),
                    )
                    opening_import_id = int(self.cursor.fetchone()[0])
                    self.cursor.execute(
                        "INSERT INTO import_items "
                        "(import_id, product_id, product_name, quantity, unit_price) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (opening_import_id, product_id, name, initial_quantity, purchase_price),
                    )
                resolved[key] = product_id
            else:
                self.cursor.execute(
                    "INSERT INTO services "
                    "(service_type, name, unit_price, description, keywords, "
                    "created_by, created_by_username, created_at) "
                    "VALUES ('Custom Service', %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        name, sale_price, str(entity.get("description") or ""),
                        str(entity.get("keywords") or ""), actor["created_by"],
                        actor["created_by_username"], actor["created_at"],
                    ),
                )
                resolved[key] = int(self.cursor.fetchone()[0])
        return resolved

    def save_sale_with_items(
        self, sale_data, items, sale_id=None, visible_row_count=None,
        pending_entities=None, user=None,
    ):
        """Atomically save one sale header and its complete visible line set."""
        if not isinstance(sale_data, dict):
            raise ValueError("sale_data must be an object")
        if not isinstance(items, list):
            raise ValueError("items must be an array")
        visible_count = int(visible_row_count if visible_row_count is not None else len(items))
        if visible_count > 0 and not items:
            raise ValueError(
                f"Sale was not saved: {visible_count} visible items were found, but the server received 0 valid items."
            )

        validated = []
        for index, raw in enumerate(items, start=1):
            if not isinstance(raw, dict):
                raise ValueError(f"Item {index} must be an object")
            name = str(raw.get('product_name') or raw.get('designation') or '').strip()
            if not name:
                raise ValueError(f"Item {index}: designation is required")
            quantity = self._sale_decimal(raw.get('quantity'), f"item {index} quantity", '0.001')
            unit_price = self._sale_decimal(raw.get('unit_price'), f"item {index} unit price", '0')
            item_id = raw.get('id')
            product_id = raw.get('product_id')
            service_id = raw.get('service_id')
            try:
                item_id = int(item_id) if item_id not in (None, '', 0, '0') else None
                product_id = int(product_id) if product_id not in (None, '', 0, '0') else None
                service_id = int(service_id) if service_id not in (None, '', 0, '0') else None
            except (TypeError, ValueError):
                raise ValueError(f"Item {index}: IDs must be integers when present")

            requested_type = str(raw.get("item_type") or "").strip().casefold()
            if requested_type not in ("product", "service", "manual"):
                requested_type = "product" if product_id else ("service" if service_id else "")
            validated.append({
                'id': item_id,
                'product_id': product_id,
                'service_id': service_id,
                'product_name': name,
                'information': str(raw.get('information') or '').strip(),
                'quantity': quantity,
                'unit_price': unit_price,
                'production': int(raw.get('production') or 0),
                'item_type': requested_type,
            })

        try:
            header_token = str(sale_data.get("operation_token") or "").strip()
            if not sale_id and header_token:
                self.cursor.execute(
                    "SELECT id FROM sales WHERE operation_token = %s", (header_token,)
                )
                duplicate = self.cursor.fetchone()
                if duplicate:
                    self.cursor.execute(
                        "SELECT COUNT(*) FROM sales_items WHERE sales_id = %s",
                        (int(duplicate[0]),),
                    )
                    return {
                        "sale_id": int(duplicate[0]), "saved": int(self.cursor.fetchone()[0]),
                        "inserted": 0, "updated": 0, "deleted": 0,
                        "items": [], "transaction": "committed", "duplicate": True,
                    }

            resolved_pending = self._create_pending_sale_entities(pending_entities, user)

            # Resolve only in the explicitly selected catalog.
            for item in validated:
                kind = item["item_type"]
                if not kind:
                    product_match = self._find_named_record(
                        "products", item["product_name"], item["product_id"]
                    )
                    service_match = self._find_named_record(
                        "services", item["product_name"], item["service_id"]
                    )
                    if product_match[0] and service_match[0]:
                        raise ValueError(
                            f"Choose Product or Service for '{item['product_name']}'"
                        )
                    if product_match[0]:
                        kind = item["item_type"] = "product"
                        item["product_id"] = product_match[0]
                    elif service_match[0]:
                        kind = item["item_type"] = "service"
                        item["service_id"] = service_match[0]
                    elif item["id"] is not None:
                        kind = item["item_type"] = "manual"
                    else:
                        raise ValueError(
                            f"Choose Product or Service for '{item['product_name']}'"
                        )
                if kind == "manual":
                    # Legacy manual lines remain editable, but new lines must
                    # explicitly select Product or Service.
                    if item["id"] is None:
                        raise ValueError(
                            f"Choose Product or Service for '{item['product_name']}'"
                        )
                    continue
                table = "products" if kind == "product" else "services"
                selected_id = item["product_id"] if kind == "product" else item["service_id"]
                record_id, canonical_name = self._find_named_record(
                    table, item["product_name"], selected_id
                )
                if not record_id:
                    record_id = resolved_pending.get(
                        (kind, self._normalize_exact(item["product_name"]))
                    )
                if not record_id:
                    raise ValueError(
                        f"{kind.title()} '{item['product_name']}' does not exist"
                    )
                item["product_id"] = record_id if kind == "product" else None
                item["service_id"] = record_id if kind == "service" else None
                if canonical_name:
                    item["product_name"] = canonical_name

            sale_cls = self.registered_classes['Sales']
            sale_obj = sale_cls(0, None)
            header = {
                key: sale_data[key]
                for key in sale_obj.get_visible_parameters('database')
                if key in sale_data and not sale_obj.is_parameter_calculated(key)
            }
            if not header:
                raise ValueError("Sale header contains no storable fields")
            if sale_id:
                for protected in (
                    "created_by", "created_by_username", "created_at", "operation_token"
                ):
                    header.pop(protected, None)

            # Resolve the relational client ID server-side for every create and
            # edit. The name remains a historical snapshot, but all client-sale
            # views filter exclusively on this immutable database ID.
            username = " ".join(str(header.get('client_username') or '').split())
            if username:
                self.cursor.execute(
                    "SELECT id, name, username FROM clients "
                    "WHERE LOWER(REGEXP_REPLACE(BTRIM(username), '\\s+', ' ', 'g')) = %s "
                    "OR LOWER(REGEXP_REPLACE(BTRIM(name), '\\s+', ' ', 'g')) = %s "
                    "ORDER BY id LIMIT 1",
                    (self._normalize_exact(username), self._normalize_exact(username)),
                )
                client_row = self.cursor.fetchone()
                if not client_row:
                    pending_id = resolved_pending.get(("client", self._normalize_exact(username)))
                    if pending_id:
                        self.cursor.execute(
                            "SELECT id, name, username FROM clients WHERE id=%s", (pending_id,)
                        )
                        client_row = self.cursor.fetchone()
                if not client_row:
                    raise ValueError(f"Client '{username}' does not exist")
                header['client_id'] = int(client_row[0])
                header['client_username'] = client_row[2] or username
                if client_row:
                    header['client_name'] = client_row[1] or username
            else:
                raise ValueError("Client is required")

            actor = self._actor_fields(user)
            if not sale_id:
                header.update(actor)

            if sale_id:
                sale_id = int(sale_id)
                if user and not user.get("is_superadmin"):
                    self.cursor.execute(
                        "SELECT 1 FROM sales WHERE id=%s AND created_by=%s",
                        (sale_id, int(user.get("id") or 0)),
                    )
                    if not self.cursor.fetchone():
                        raise PermissionError("This sale belongs to another user")
                assignments = ', '.join(f"{key} = %s" for key in header)
                self.cursor.execute(
                    f"UPDATE sales SET {assignments} WHERE id = %s",
                    [*header.values(), sale_id],
                )
                if self.cursor.rowcount != 1:
                    raise ValueError(f"Sale {sale_id} does not exist")
            else:
                columns = ', '.join(header)
                placeholders = ', '.join('%s' for _ in header)
                self.cursor.execute(
                    f"INSERT INTO sales ({columns}) VALUES ({placeholders}) RETURNING id",
                    list(header.values()),
                )
                row = self.cursor.fetchone()
                if not row:
                    raise RuntimeError("Host database did not return the new sale ID")
                sale_id = int(row[0])

            self.cursor.execute("SELECT id FROM sales_items WHERE sales_id = %s", (sale_id,))
            existing_ids = {int(row[0]) for row in self.cursor.fetchall()}
            retained_ids = set()
            inserted = updated = 0
            for item in validated:
                values = (
                    item['product_id'], item['service_id'], item['item_type'],
                    item['product_name'], item['information'],
                    item['quantity'], item['unit_price'], item['production'],
                )
                if item['id'] is not None:
                    if item['id'] not in existing_ids:
                        raise ValueError(f"Item ID {item['id']} does not belong to sale {sale_id}")
                    self.cursor.execute(
                        "UPDATE sales_items SET product_id=%s, service_id=%s, item_type=%s, "
                        "product_name=%s, information=%s, quantity=%s, unit_price=%s, "
                        "production=%s WHERE id=%s AND sales_id=%s",
                        (*values, item['id'], sale_id),
                    )
                    retained_ids.add(item['id'])
                    updated += 1
                else:
                    self.cursor.execute(
                        "INSERT INTO sales_items "
                        "(sales_id, product_id, service_id, item_type, product_name, "
                        "information, quantity, unit_price, production) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                        (sale_id, *values),
                    )
                    row = self.cursor.fetchone()
                    if not row:
                        raise RuntimeError(f"Item {item['product_name']!r} was not inserted")
                    retained_ids.add(int(row[0]))
                    inserted += 1

            delete_ids = existing_ids - retained_ids
            if delete_ids:
                self.cursor.execute(
                    "DELETE FROM sales_items WHERE sales_id = %s AND id = ANY(%s)",
                    (sale_id, list(delete_ids)),
                )
            deleted = len(delete_ids)

            if str(header.get("state") or "pending") != "on_hold":
                requested_by_product = {}
                for item in validated:
                    if item["item_type"] == "product":
                        requested_by_product[item["product_id"]] = (
                            requested_by_product.get(item["product_id"], 0) + item["quantity"]
                        )
                for product_id, requested in requested_by_product.items():
                    self.cursor.execute(
                        "SELECT COALESCE(SUM(quantity), 0) FROM import_items WHERE product_id=%s",
                        (product_id,),
                    )
                    imported = self.cursor.fetchone()[0] or 0
                    self.cursor.execute(
                        """
                        SELECT COALESCE(SUM(si.quantity), 0)
                        FROM sales_items si JOIN sales s ON s.id=si.sales_id
                        WHERE si.product_id=%s AND si.sales_id<>%s
                          AND (s.state IS NULL OR s.state<>'on_hold')
                        """,
                        (product_id, sale_id),
                    )
                    sold_elsewhere = self.cursor.fetchone()[0] or 0
                    if requested > imported - sold_elsewhere:
                        raise ValueError(
                            f"Insufficient stock for product ID {product_id}: "
                            f"requested {requested}, available {imported - sold_elsewhere}"
                        )
            self.conn.commit()
            return {
                'sale_id': sale_id,
                'saved': len(validated),
                'inserted': inserted,
                'updated': updated,
                'deleted': deleted,
                'items': [
                    {'item_type': item['item_type'], 'product_id': item['product_id'],
                     'service_id': item['service_id'], 'designation': item['product_name']}
                    for item in validated
                ],
                'transaction': 'committed',
            }
        except Exception:
            self.conn.rollback()
            raise

    def save_import_with_items(
        self, import_data, items, import_id=None, visible_row_count=None, user=None
    ):
        """Atomically save a supplier purchase and its stock ledger entries."""
        if not isinstance(import_data, dict) or not isinstance(items, list):
            raise ValueError("Import header and items must be objects")
        visible_count = int(
            visible_row_count if visible_row_count is not None else len(items)
        )
        if visible_count > 0 and not items:
            raise ValueError(
                f"Import was not saved: {visible_count} visible items were found, "
                "but the server received 0 valid items."
            )

        validated = []
        for index, raw in enumerate(items, start=1):
            if not isinstance(raw, dict):
                raise ValueError(f"Item {index} must be an object")
            name = " ".join(str(raw.get("product_name") or "").split())
            if not name:
                raise ValueError(f"Item {index}: product name is required")
            quantity = self._sale_decimal(
                raw.get("quantity"), f"item {index} quantity", "0.001"
            )
            unit_price = self._sale_decimal(
                raw.get("unit_price"), f"item {index} unit price", "0"
            )
            try:
                item_id = int(raw["id"]) if raw.get("id") not in (None, "", 0, "0") else None
                product_id = (
                    int(raw["product_id"])
                    if raw.get("product_id") not in (None, "", 0, "0") else None
                )
            except (TypeError, ValueError):
                raise ValueError(f"Item {index}: IDs must be integers when present")
            validated.append({
                "id": item_id, "product_id": product_id, "product_name": name,
                "quantity": quantity, "unit_price": unit_price,
                "category": str(raw.get("category") or ""),
                "description": str(raw.get("description") or ""),
                "sku": str(raw.get("sku") or raw.get("reference") or ""),
            })

        try:
            token = str(import_data.get("operation_token") or "").strip()
            if not import_id and token:
                self.cursor.execute(
                    "SELECT id FROM imports WHERE operation_token=%s", (token,)
                )
                duplicate = self.cursor.fetchone()
                if duplicate:
                    self.cursor.execute(
                        "SELECT COUNT(*) FROM import_items WHERE import_id=%s",
                        (int(duplicate[0]),),
                    )
                    return {
                        "import_id": int(duplicate[0]),
                        "saved": int(self.cursor.fetchone()[0]),
                        "inserted": 0, "updated": 0, "deleted": 0,
                        "created_products": 0, "transaction": "committed",
                        "duplicate": True,
                    }

            actor = self._actor_fields(user)
            created_products = 0
            for item in validated:
                product_id = canonical = None
                if item["product_id"]:
                    product_id, canonical = self._find_named_record(
                        "products", item["product_name"], item["product_id"]
                    )
                if not product_id and item["sku"]:
                    self.cursor.execute(
                        "SELECT id, name FROM products "
                        "WHERE LOWER(REGEXP_REPLACE(BTRIM(username), '\\s+', ' ', 'g'))=%s "
                        "ORDER BY id LIMIT 1",
                        (self._normalize_exact(item["sku"]),),
                    )
                    row = self.cursor.fetchone()
                    if row:
                        product_id, canonical = int(row[0]), row[1]
                if not product_id:
                    product_id, canonical = self._find_named_record(
                        "products", item["product_name"]
                    )
                if not product_id:
                    self.cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (
                            f"product-sku:{self._normalize_exact(item['sku'])}"
                            if item["sku"]
                            else f"product-name:{self._normalize_exact(item['product_name'])}",
                        ),
                    )
                    if item["sku"]:
                        self.cursor.execute(
                            "SELECT id, name FROM products "
                            "WHERE LOWER(REGEXP_REPLACE(BTRIM(username), '\\s+', ' ', 'g'))=%s "
                            "ORDER BY id LIMIT 1",
                            (self._normalize_exact(item["sku"]),),
                        )
                        row = self.cursor.fetchone()
                        if row:
                            product_id, canonical = int(row[0]), row[1]
                if not product_id:
                    product_id, canonical = self._find_named_record(
                        "products", item["product_name"]
                    )
                if not product_id:
                    self.cursor.execute(
                        "INSERT INTO products "
                        "(name, username, unit_price, sale_price, category, description, "
                        "created_by, created_by_username, created_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                        (
                            item["product_name"], item["sku"] or item["product_name"],
                            item["unit_price"], item["unit_price"], item["category"],
                            item["description"], actor["created_by"],
                            actor["created_by_username"], actor["created_at"],
                        ),
                    )
                    product_id = int(self.cursor.fetchone()[0])
                    canonical = item["product_name"]
                    created_products += 1
                else:
                    # Purchase price follows the latest supplier transaction;
                    # preserve sale price and all unrelated product fields.
                    self.cursor.execute(
                        "UPDATE products SET unit_price=%s WHERE id=%s",
                        (item["unit_price"], product_id),
                    )
                item["product_id"] = product_id
                item["product_name"] = canonical or item["product_name"]

            import_cls = self.registered_classes["Imports"]
            import_obj = import_cls(0, None)
            header = {
                key: import_data[key]
                for key in import_obj.get_visible_parameters("database")
                if key in import_data and not import_obj.is_parameter_calculated(key)
            }
            supplier_username = " ".join(
                str(header.get("supplier_username") or "").split()
            )
            if not supplier_username:
                raise ValueError("Supplier is required")
            self.cursor.execute(
                "SELECT id, name, username FROM suppliers "
                "WHERE LOWER(REGEXP_REPLACE(BTRIM(username), '\\s+', ' ', 'g'))=%s "
                "OR LOWER(REGEXP_REPLACE(BTRIM(name), '\\s+', ' ', 'g'))=%s "
                "ORDER BY id LIMIT 1",
                (
                    self._normalize_exact(supplier_username),
                    self._normalize_exact(supplier_username),
                ),
            )
            supplier = self.cursor.fetchone()
            if not supplier:
                raise ValueError(f"Supplier '{supplier_username}' does not exist")
            header["supplier_id"] = int(supplier[0])
            header["supplier_name"] = supplier[1] or supplier_username
            header["supplier_username"] = supplier[2] or supplier_username

            if import_id:
                import_id = int(import_id)
                if user and not user.get("is_superadmin"):
                    self.cursor.execute(
                        "SELECT 1 FROM imports WHERE id=%s AND created_by=%s",
                        (import_id, int(user.get("id") or 0)),
                    )
                    if not self.cursor.fetchone():
                        raise PermissionError("This import belongs to another user")
                for protected in (
                    "created_by", "created_by_username", "created_at", "operation_token"
                ):
                    header.pop(protected, None)
                assignments = ", ".join(f"{key}=%s" for key in header)
                self.cursor.execute(
                    f"UPDATE imports SET {assignments} WHERE id=%s",
                    [*header.values(), import_id],
                )
                if self.cursor.rowcount != 1:
                    raise ValueError(f"Import {import_id} does not exist")
            else:
                header.update(actor)
                columns = ", ".join(header)
                placeholders = ", ".join("%s" for _ in header)
                self.cursor.execute(
                    f"INSERT INTO imports ({columns}) VALUES ({placeholders}) RETURNING id",
                    list(header.values()),
                )
                import_id = int(self.cursor.fetchone()[0])

            self.cursor.execute(
                "SELECT id FROM import_items WHERE import_id=%s", (import_id,)
            )
            existing_ids = {int(row[0]) for row in self.cursor.fetchall()}
            retained_ids = set()
            inserted = updated = 0
            for item in validated:
                values = (
                    item["product_id"], item["product_name"],
                    item["quantity"], item["unit_price"],
                )
                if item["id"] is not None:
                    if item["id"] not in existing_ids:
                        raise ValueError(
                            f"Item ID {item['id']} does not belong to import {import_id}"
                        )
                    self.cursor.execute(
                        "UPDATE import_items SET product_id=%s, product_name=%s, "
                        "quantity=%s, unit_price=%s WHERE id=%s AND import_id=%s",
                        (*values, item["id"], import_id),
                    )
                    retained_ids.add(item["id"])
                    updated += 1
                else:
                    self.cursor.execute(
                        "INSERT INTO import_items "
                        "(import_id, product_id, product_name, quantity, unit_price) "
                        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (import_id, *values),
                    )
                    retained_ids.add(int(self.cursor.fetchone()[0]))
                    inserted += 1
            delete_ids = existing_ids - retained_ids
            if delete_ids:
                self.cursor.execute(
                    "DELETE FROM import_items WHERE import_id=%s AND id=ANY(%s)",
                    (import_id, list(delete_ids)),
                )
            self.conn.commit()
            return {
                "import_id": import_id, "saved": len(validated),
                "inserted": inserted, "updated": updated, "deleted": len(delete_ids),
                "created_products": created_products, "transaction": "committed",
            }
        except Exception:
            self.conn.rollback()
            raise

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

    def get_items_for_user(
        self, section, user, owner_id=None, date_from=None, date_to=None,
        report_type=None,
    ):
        """Return ownership-filtered Sales or Reports rows.

        Regular users are always pinned to their authenticated session ID.
        Super admins may request one owner or leave it empty for all rows.
        Legacy rows with no owner remain visible only in the all-user admin view.
        """
        if section == "Sales_Items":
            user = user or {}
            if user.get("is_superadmin"):
                return self.get_items(section)
            self.cursor.execute(
                "SELECT si.* FROM sales_items si JOIN sales s ON s.id=si.sales_id "
                "WHERE s.created_by=%s ORDER BY si.id",
                (int(user.get("id") or 0),),
            )
            rows = self.cursor.fetchall()
            columns = [description[0] for description in self.cursor.description]
            if columns and columns[0].lower() == "id":
                columns[0] = "ID"
            return [dict(zip(columns, row)) for row in rows]
        if section not in ("Sales", "Reports"):
            return self.get_items(section)
        user = user or {}
        is_superadmin = bool(user.get("is_superadmin"))
        effective_owner = owner_id if is_superadmin else user.get("id")
        if not is_superadmin and effective_owner is None:
            return []
        query = f"SELECT * FROM {section}"
        params = []
        if effective_owner not in (None, "", "all"):
            query += " WHERE created_by=%s"
            params.append(int(effective_owner))
        conditions = []
        if section == "Reports":
            if report_type not in (None, "", "all"):
                conditions.append("COALESCE(NULLIF(report_type, ''), 'General')=%s")
                params.append(str(report_type))
            date_expression = (
                "CASE "
                "WHEN date ~ '^\\d{2}-\\d{2}-\\d{4}$' THEN TO_DATE(date, 'DD-MM-YYYY') "
                "WHEN date ~ '^\\d{4}-\\d{2}-\\d{2}$' THEN TO_DATE(date, 'YYYY-MM-DD') "
                "WHEN date ~ '^\\d{2}/\\d{2}/\\d{4}$' THEN TO_DATE(date, 'DD/MM/YYYY') "
                "ELSE NULL END"
            )
            if date_from:
                conditions.append(f"{date_expression}>=%s::date")
                params.append(str(date_from))
            if date_to:
                conditions.append(f"{date_expression}<=%s::date")
                params.append(str(date_to))
        if conditions:
            query += (" AND " if " WHERE " in query else " WHERE ") + " AND ".join(conditions)
        query += " ORDER BY id"
        self.cursor.execute(query, params)
        rows = self.cursor.fetchall()
        columns = [description[0] for description in self.cursor.description]
        if columns and columns[0].lower() == "id":
            columns[0] = "ID"
        return [dict(zip(columns, row)) for row in rows]

    def get_product_stock_levels(self):
        self.cursor.execute(
            """
            SELECT p.id,
                   COALESCE(imported.quantity, 0) - COALESCE(sold.quantity, 0)
            FROM products p
            LEFT JOIN (
                SELECT product_id, SUM(quantity) AS quantity
                FROM import_items GROUP BY product_id
            ) imported ON imported.product_id=p.id
            LEFT JOIN (
                SELECT si.product_id, SUM(si.quantity) AS quantity
                FROM sales_items si
                JOIN sales s ON s.id=si.sales_id
                WHERE s.state IS NULL OR s.state<>'on_hold'
                GROUP BY si.product_id
            ) sold ON sold.product_id=p.id
            """
        )
        return {int(row[0]): row[1] or 0 for row in self.cursor.fetchall()}

    def get_operation_items_for_user(self, operation_id, section, user):
        if section != "Sales_Items" or (user or {}).get("is_superadmin"):
            return self.get_items_by_operation_id(operation_id, section)
        self.cursor.execute(
            "SELECT 1 FROM sales WHERE id=%s AND created_by=%s",
            (int(operation_id), int((user or {}).get("id") or 0)),
        )
        if not self.cursor.fetchone():
            raise PermissionError("This sale belongs to another user")
        return self.get_items_by_operation_id(operation_id, section)

    def list_report_users(self):
        self.cursor.execute(
            "SELECT id, username FROM users ORDER BY LOWER(username), id"
        )
        return [{"id": int(row[0]), "username": row[1]} for row in self.cursor.fetchall()]

    def get_reports(
        self, owner_id=None, date_from=None, date_to=None, report_type=None
    ):
        return self.get_items_for_user(
            "Reports", {"is_superadmin": True, "username": "Local Admin"}, owner_id,
            date_from, date_to, report_type,
        )

    def save_report(self, report_id, data):
        return self.save_report_for_user(
            report_id, data, {"is_superadmin": True, "username": "Local Admin"}
        )

    def delete_report(self, report_id):
        return self.delete_report_for_user(
            report_id, {"is_superadmin": True, "username": "Local Admin"}
        )

    def save_report_for_user(self, report_id, data, user):
        user = user or {}
        actor = self._actor_fields(user)
        payload = {
            "department": actor["created_by_username"],
            "date": str(data.get("date") or ""),
            "report_type": str(data.get("report_type") or "General"),
            "report": str(data.get("report") or "").strip(),
        }
        if not payload["date"] or not payload["report"]:
            raise ValueError("Report date and text are required")
        try:
            if report_id:
                params = [
                    payload["department"], payload["date"], payload["report_type"],
                    payload["report"], int(report_id),
                ]
                query = (
                    "UPDATE reports SET department=%s, date=%s, report_type=%s, "
                    "report=%s WHERE id=%s"
                )
                if not user.get("is_superadmin"):
                    query += " AND created_by=%s"
                    params.append(int(user.get("id") or 0))
                self.cursor.execute(query, params)
                if self.cursor.rowcount != 1:
                    raise PermissionError("Report not found or belongs to another user")
                saved_id = int(report_id)
            else:
                self.cursor.execute(
                    "INSERT INTO reports "
                    "(department, date, report_type, report, created_by, "
                    "created_by_username, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        payload["department"], payload["date"], payload["report_type"],
                        payload["report"], actor["created_by"],
                        actor["created_by_username"], actor["created_at"],
                    ),
                )
                saved_id = int(self.cursor.fetchone()[0])
            self.conn.commit()
            return saved_id
        except Exception:
            self.conn.rollback()
            raise

    def delete_report_for_user(self, report_id, user):
        params = [int(report_id)]
        query = "DELETE FROM reports WHERE id=%s"
        if not (user or {}).get("is_superadmin"):
            query += " AND created_by=%s"
            params.append(int((user or {}).get("id") or 0))
        self.cursor.execute(query, params)
        if self.cursor.rowcount != 1:
            self.conn.rollback()
            raise PermissionError("Report not found or belongs to another user")
        self.conn.commit()
        return True

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

    def get_client_account(self, client_id, user=None):
        """Return client account rows through one permission-gated backend API.

        The LAN server exposes this method under Clients/read. This lets a user
        view a client's account without granting broad Sales table access.
        """
        client_id = int(client_id)
        self.cursor.execute("SELECT id FROM clients WHERE id = %s", (client_id,))
        if not self.cursor.fetchone():
            raise ValueError(f"Client {client_id} does not exist")

        owner_clause = ""
        owner_params = []
        if user and not user.get("is_superadmin"):
            owner_clause = " AND s.created_by = %s"
            owner_params.append(int(user.get("id") or 0))
        self.cursor.execute(
            f"""
            SELECT
                s.id,
                COALESCE(s.date, ''),
                COALESCE(s.state, 'pending'),
                si.id,
                COALESCE(si.product_name, ''),
                COALESCE(si.quantity, 0),
                COALESCE(si.unit_price, 0),
                COALESCE(s.tva, 0)
            FROM sales s
            JOIN sales_items si ON si.sales_id = s.id
            WHERE s.client_id = %s{owner_clause}
            ORDER BY s.id, si.id
            """,
            (client_id, *owner_params),
        )
        purchase_rows = self.cursor.fetchall()
        sale_ids = sorted({row[0] for row in purchase_rows})
        payment_rows = []
        if sale_ids:
            self.cursor.execute(
                """
                SELECT p.id, p.sale_id, p.sales_item_id, p.date, p.amount
                FROM payments p
                WHERE p.sale_id = ANY(%s)
                ORDER BY p.id DESC
                """,
                (sale_ids,),
            )
            payment_rows = self.cursor.fetchall()

        return {
            "purchases": [list(row) for row in purchase_rows],
            "payments": [list(row) for row in payment_rows],
        }

    def add_client_payment(
        self, client_id, sale_id, sales_item_id, amount, date, user=None
    ):
        """Record a payment after verifying it belongs to the requested client."""
        client_id = int(client_id)
        sale_id = int(sale_id)
        sales_item_id = int(sales_item_id)
        amount = float(amount)
        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero")

        try:
            owner_clause = ""
            owner_params = []
            if user and not user.get("is_superadmin"):
                owner_clause = " AND s.created_by = %s"
                owner_params.append(int(user.get("id") or 0))
            self.cursor.execute(
                f"""
                SELECT 1
                FROM sales s
                JOIN sales_items si ON si.sales_id = s.id
                WHERE s.id = %s AND si.id = %s AND s.client_id = %s{owner_clause}
                """,
                (sale_id, sales_item_id, client_id, *owner_params),
            )
            if not self.cursor.fetchone():
                raise ValueError("The selected purchase does not belong to this client")
            self.cursor.execute(
                """
                INSERT INTO payments (sale_id, sales_item_id, amount, date)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (sale_id, sales_item_id, amount, str(date)),
            )
            payment_id = self.cursor.fetchone()[0]
            self.conn.commit()
            return int(payment_id)
        except Exception:
            self.conn.rollback()
            raise

    def delete_item(self, item_id, section):
        """Delete item from section"""
        if not self.cursor or section not in self.registered_classes:
            return False

        try:
            if section in ('Clients', 'Sales'):
                from core.attachments import AttachmentService
                AttachmentService(self).delete_owner(
                    'client' if section == 'Clients' else 'sale', int(item_id)
                )
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

    # Attachment operations transfer bytes as base64 over LAN RPC. The host's
    # data directory is never returned to a workstation.
    def list_attachments(self, entity_type, entity_id):
        from core.attachments import AttachmentService
        return AttachmentService(self).list(entity_type, int(entity_id))

    def upload_attachment(self, entity_type, entity_id, filename, content_b64, description='', category=''):
        from core.attachments import AttachmentService
        return AttachmentService(self).upload(entity_type, int(entity_id), filename, content_b64, description, category)

    def download_attachment(self, attachment_id):
        from core.attachments import AttachmentService
        return AttachmentService(self).download(int(attachment_id))

    def get_attachment_thumbnail(self, attachment_id):
        from core.attachments import AttachmentService
        return AttachmentService(self).thumbnail(int(attachment_id))

    def update_attachment(self, attachment_id, display_name=None, description=None, category=None):
        from core.attachments import AttachmentService
        return AttachmentService(self).update(int(attachment_id), display_name, description, category)

    def delete_attachment(self, attachment_id):
        from core.attachments import AttachmentService
        return AttachmentService(self).delete(int(attachment_id))

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None
