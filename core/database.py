"""
Database System - PostgreSQL backed, supports multi-item operations with foreign keys.

Each profile gets its own schema in one shared Postgres database (schema-per-tenant),
selected via `SET search_path`. All identifiers created here are left UNQUOTED so
Postgres folds them to lowercase - this matches the many raw-SQL call sites elsewhere
in the app (classes/*.py, ui/**/*.py) that already reference table/column names
unquoted, so they keep working unchanged against the folded lowercase names.
"""
import re
import json
import logging
from datetime import datetime
from decimal import Decimal
# haitam
import psycopg2
from psycopg2 import OperationalError

from core.pg_config import load_server_config
from core import diagnostics

logger = logging.getLogger(__name__)

# Session options applied to every connection this application opens.
#
# lock_timeout converts the historical unrecoverable freeze into a catchable
# error: several UI paths run synchronous queries on the GUI thread, and
# PostgreSQL by default waits FOREVER when another session holds a conflicting
# lock (e.g. another PC mid-sale-save). A bounded 8s wait lets those paths
# surface an error message instead of hanging the window indefinitely.
_CONNECTION_OPTIONS = "-c lock_timeout=8000"

# Sort columns allowed to appear directly in ORDER BY / keyset WHERE clauses.
# UI-generated text must be validated against this set before it ever reaches
# SQL - never interpolate arbitrary user input into ORDER BY.
_ORDER_COLUMNS = {
    'id', 'username', 'name', 'description', 'keywords', 'client_username',
    'client_name', 'supplier_username', 'supplier_name', 'date',
    'unit_price', 'sale_price', 'quantity', 'category', 'ice',
    'subtotal', 'total', 'information', 'total_quantity',
    'total_production', 'department', 'report_type', 'created_by',
    'created_at', 'report', 'is_historical', 'state', 'notes',
}

# Subset of _ORDER_COLUMNS whose values are numeric. Sort expressions for
# these are wrapped in COALESCE(..., 0) (text columns in COALESCE(..., ''))
# so the composite keyset row comparison (sort_expr, id) never hits NULL,
# which would silently drop rows sharing a NULL sort value.
_ORDER_NUMERIC_COLUMNS = {
    'id', 'unit_price', 'sale_price', 'quantity', 'ice', 'subtotal',
    'total', 'total_quantity', 'total_production', 'created_by',
}

# Canonical Client Account schema.
#
# get_client_account() joins Sales + Sales_Items and returns every field as a
# named value. Every layer that consumes a client account - the LAN RPC server,
# the RemoteDatabase client, the ClientDetailsDialog worker, the Purchases /
# Payment History tables and the print workers - must use these exact names.
# Never let a consumer unpack these rows by position; the column count has
# grown before and the fragile positional unpacking is what crashed View
# Client ("too many values to unpack (expected 9, got 14)").
CLIENT_ACCOUNT_PURCHASE_FIELDS = (
    "sale_id", "date", "state", "item_id", "product", "quantity",
    "unit_price", "vat", "remise", "information", "production",
    "notes", "is_historical", "created_by_username",
)
CLIENT_ACCOUNT_PAYMENT_FIELDS = (
    "payment_id", "sale_id", "item_id", "date", "amount",
)

# Canonical Supplier Account schemas - the single data contract shared by the
# host GUI, the LAN RPC layer and the View Supplier dialog / statement report.
# Mirrors the Client Account fields so the same widget pipeline can render
# either side. One row per Import x Import_Items join in the "imports" view
# and one row per payment in the "payments" view.
SUPPLIER_ACCOUNT_IMPORT_FIELDS = (
    "import_id", "date", "item_id", "product", "quantity",
    "unit_price", "vat", "notes", "is_historical", "created_by_username",
)
SUPPLIER_ACCOUNT_PAYMENT_FIELDS = (
    "payment_id", "import_id", "item_id", "date", "amount",
)
# Canonical per-Import summary schema returned by
# get_supplier_import_summaries(). One row per Import (never one per item).
SUPPLIER_ACCOUNT_IMPORT_SUMMARY_FIELDS = (
    "import_id", "date", "bl_number", "is_historical", "total", "paid",
    "remaining",
)

# Canonical per-Sale summary schema returned by get_client_sale_summaries().
# One row per Sale (never one per item) so the Sales History table never needs
# to download every Sale Item. ``devis`` is the display string DE-YEAR-N.
CLIENT_ACCOUNT_SALE_FIELDS = (
    "sale_id", "date", "state", "is_historical", "devis", "total", "paid",
    "remaining",
)

# Year a Devis number is scoped to: the first 4-digit group in the sale date,
# falling back to created_at, then 0. Kept as a single SQL expression so the
# per-year backfill and the summaries query always agree on the same year.
_DEVIS_YEAR_EXPR = (
    "COALESCE("
    "NULLIF(SUBSTRING(COALESCE(s.date, '') FROM '\\d{4}'), ''), "
    "NULLIF(SUBSTRING(COALESCE(s.created_at::text, '') FROM '\\d{4}'), ''), "
    "'0')"
)

# Maximum length of the canonical Devis reference (e.g. "DE-2026-525-A").
# The GUI and the host-side resolver both enforce this bound.
DEVIS_MAX_LENGTH = 40

# Year a Bon de Livraison number is scoped to: the first 4-digit group in the
# import date, falling back to created_at, then 0. Mirrors _DEVIS_YEAR_EXPR
# (the importing alias is "s", matching the backfill/allocator call sites).
_BL_YEAR_EXPR = (
    "COALESCE("
    "NULLIF(SUBSTRING(COALESCE(s.date, '') FROM '\\d{4}'), ''), "
    "NULLIF(SUBSTRING(COALESCE(s.created_at::text, '') FROM '\\d{4}'), ''), "
    "'0')"
)

# Maximum length of the persistent Bon de Livraison reference (BL-YEAR-N).
# Enforced by the host-side resolver only - the value is never user-editable.
BL_MAX_LENGTH = 40


def normalize_client_sale_summaries(sale_rows, payment_rows):
    """Convert raw summaries/payment rows to the sale-level account contract.

    ``sale_rows`` follow ``CLIENT_ACCOUNT_SALE_FIELDS`` and ``payment_rows``
    follow ``CLIENT_ACCOUNT_PAYMENT_FIELDS`` (both are already in the named
    order used by the dialog and the report workers).
    """
    sales = [dict(zip(CLIENT_ACCOUNT_SALE_FIELDS, row)) for row in sale_rows]
    payments = [
        dict(zip(CLIENT_ACCOUNT_PAYMENT_FIELDS, row)) for row in payment_rows
    ]
    return {"sales": sales, "payments": payments}


def normalize_client_account(purchase_rows, payment_rows):
    """Convert raw Sales/Sales_Items and Payments rows to canonical dicts.

    ``purchase_rows`` follow ``CLIENT_ACCOUNT_PURCHASE_FIELDS`` (the 14-column
    Sales x Sales_Items join) and ``payment_rows`` follow
    ``CLIENT_ACCOUNT_PAYMENT_FIELDS``. The returned structure is the single
    Client Account data contract shared by the host GUI, the LAN RPC layer and
    the View Client dialog / reports.
    """
    purchases = [
        dict(zip(CLIENT_ACCOUNT_PURCHASE_FIELDS, row)) for row in purchase_rows
    ]
    payments = [
        dict(zip(CLIENT_ACCOUNT_PAYMENT_FIELDS, row)) for row in payment_rows
    ]
    return {"purchases": purchases, "payments": payments}


def normalize_supplier_account(import_rows, payment_rows):
    """Convert raw Imports/Import_Items and Payments rows to canonical dicts.

    ``import_rows`` follow ``SUPPLIER_ACCOUNT_IMPORT_FIELDS`` and
    ``payment_rows`` follow ``SUPPLIER_ACCOUNT_PAYMENT_FIELDS``. The returned
    structure is the single Supplier Account data contract shared by the host
    GUI, the LAN RPC layer and the View Supplier dialog / reports.
    """
    imports = [
        dict(zip(SUPPLIER_ACCOUNT_IMPORT_FIELDS, row)) for row in import_rows
    ]
    payments = [
        dict(zip(SUPPLIER_ACCOUNT_PAYMENT_FIELDS, row)) for row in payment_rows
    ]
    return {"imports": imports, "payments": payments}


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

            print(f"[OK] Registered parameter class: {section_name}")
            return True

        except Exception as e:
            print(f"[FAIL] Failed to register {cls.__name__}: {e}")
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
            connect_timeout=5,
            application_name="PyLocalInventory",
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

    def connect(self, verify_schema=True):
        """Establish database connection for the selected profile.
        
        Args:
            verify_schema: If True (default), run full table creation and migrations.
                          If False, only establish connection and set search_path.
                          Should be False for worker connections to avoid repeated DDL.
        """
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

        def _trace(step):
            import os as _os, time as _time
            if _os.environ.get("PYLI_TRACE"):
                print(
                    f"[TRACE t={_time.monotonic():.3f}] Database.connect "
                    f"db={self.database_name!r} step={step}",
                    flush=True,
                )

        try:
            pg_config = load_server_config()
            profile = self.profile_manager.selected_profile
            database_name = profile.database_name or self._profile_database_name(
                profile.get_value('company name') or profile.name
            )
            _trace("config-loaded")

            if profile.database_name or not profile.schema_name:
                profile.database_name = database_name
                self._ensure_profile_database(pg_config, database_name)
                _trace("profile-db-ensured")
                self.conn = psycopg2.connect(
                    host=pg_config.get('host'),
                    port=pg_config.get('port'),
                    dbname=database_name,
                    user=pg_config.get('user'),
                    password=pg_config.get('password'),
                    connect_timeout=5,
                    options=_CONNECTION_OPTIONS,
                    application_name="PyLocalInventory",
                )
                _trace("psycopg2-connected")
                self.cursor = diagnostics.track_cursor(self.conn.cursor())
                self.database_name = database_name
                self.schema_name = None

                if verify_schema:
                    # Create tables for all registered classes
                    self._create_all_tables()
                    _trace("tables-created")

                    # Ensure meta/migrations and run one-time tasks
                    self._ensure_meta_table()
                    self._ensure_user_tables()
                    self._ensure_attachment_tables()
                    self._ensure_payments_table()
                    self._ensure_change_log_table()
                    self._ensure_charges_tables()
                    self._run_one_time_migrations()
                    _trace("migrations-done")

                print(f"[OK] Connected to database: {database_name}")
                diagnostics.db_connection_opened(kind="local")
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
                connect_timeout=5,
                options=_CONNECTION_OPTIONS,
                application_name="PyLocalInventory",
            )
            self.cursor = diagnostics.track_cursor(self.conn.cursor())

            self.cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")
            self.conn.commit()
            self.cursor.execute(f"SET search_path TO {schema_name}")
            self.database_name = None
            self.schema_name = schema_name

            if verify_schema:
                # Create tables for all registered classes
                self._create_all_tables()

                # Ensure meta/migrations and run one-time tasks
                self._ensure_meta_table()
                self._ensure_user_tables()
                self._ensure_attachment_tables()
                self._ensure_payments_table()
                self._ensure_change_log_table()
                self._ensure_charges_tables()
                self._run_one_time_migrations()

            print(f"[OK] Connected to database schema: {schema_name}")
            diagnostics.db_connection_opened(kind="local")
            return True

        except OperationalError as e:
            self.last_error = str(e)
            logger.exception("PostgreSQL connection failed")
            print(f"[FAIL] Failed to connect to database: {e}")
            return False
        except Exception as e:
            self.last_error = str(e)
            logger.exception("Database initialization failed")
            print(f"[FAIL] Failed to connect to database: {e}")
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
                            print(f"[OK] Added missing column '{param_key}' to {section_name}")
                        except Exception as mig_e:
                            self.conn.rollback()
                            print(f"⚠️ Failed adding column {param_key} to {section_name}: {mig_e}")
            except Exception as e_cols:
                self.conn.rollback()
                print(f"⚠️ Column migration check failed for {section_name}: {e_cols}")

            print(f"[OK] Created/verified table: {section_name}")

        except Exception as e:
            self.conn.rollback()
            print(f"[FAIL] Error creating table for {section_name}: {e}")

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

        # Persist the per-year Devis reference for any sale that still lacks
        # one (legacy data and sales created since the last startup). Runs on
        # the trusted host only - never part of Sale Save logic.
        self._ensure_devis_numbers()
        # Persist the canonical TEXT reference for rows that only have a number.
        self._ensure_devis_text()

        # Persist per-year Bon de Livraison references for any import that
        # still lacks one (legacy data and imports created since the last
        # startup). Idempotent - allocated numbers are never renumbered.
        self._ensure_bl_numbers()

    def _ensure_additional_columns(self):
        """Ensure newly introduced snapshot columns exist in existing databases."""
        required = {
            'clients': {
                'ice': 'TEXT', 'created_by': 'INTEGER',
                'created_by_username': 'TEXT', 'created_at': 'TEXT',
            },
            'products': {
                'created_by': 'INTEGER', 'created_by_username': 'TEXT', 'created_at': 'TEXT',
                # Read by get_dashboard_snapshot()'s low-stock query - used to
                # live only behind HomeTab's local-refresh code path, so a
                # database that never ran that exact path could hit it as an
                # undefined column.
                'stock_alert': 'INTEGER',
            },
            'services': {
                'unit_price': 'DOUBLE PRECISION', 'created_by': 'INTEGER',
                'created_by_username': 'TEXT', 'created_at': 'TEXT',
            },
            'sales': {
                'client_id': 'INTEGER', 'client_name': 'TEXT', 'state': 'TEXT',
                'created_by': 'INTEGER', 'created_by_username': 'TEXT',
                'created_at': 'TEXT', 'operation_token': 'TEXT',
                # Historical sales are books-only: they never touch stock.
                # Default FALSE so every existing sale stays a normal sale.
                'is_historical': 'BOOLEAN NOT NULL DEFAULT FALSE',
                'remise': 'DOUBLE PRECISION',
                # Persistent per-year sequential Devis reference (DE-YEAR-N).
                # NULL until the one-time/on-read backfill assigns it - see
                # _ensure_devis_numbers(). Never part of Sale Save logic.
                'devis_number': 'INTEGER',
                # Canonical, user-editable Devis reference (e.g. DE-2026-525-A).
                # Backfilled once from devis_number for legacy rows, then this
                # TEXT is authoritative: manual values are stored verbatim and
                # never silently renumbered. Enforced unique by
                # sales_devis_uidx; the host allocates/validates on save.
                'devis': 'TEXT',
            },
            'imports': {
                'supplier_name': 'TEXT', 'supplier_id': 'INTEGER',
                'created_by': 'INTEGER', 'created_by_username': 'TEXT',
                'created_at': 'TEXT', 'operation_token': 'TEXT',
                # Persistent per-year sequential Bon de Livraison reference
                # (BL-YEAR-N). NULL until backfilled or allocated on first
                # print/save. Allocated by the host only - never part of the
                # client Import payload. Enforced unique by imports_bl_uidx.
                'bl_number': 'TEXT',
                # Historical imports are books-only: they never touch stock.
                # Mirrors sales.is_historical above. Also the canonical creation
                # path when the column is absent - the class-driven migration
                # loop would otherwise add it as DOUBLE PRECISION (see the
                # type-normalization block below).
                'is_historical': 'BOOLEAN NOT NULL DEFAULT FALSE',
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

        # imports.is_historical must be BOOLEAN, not DOUBLE PRECISION. Databases
        # that added the column through the class-driven migration loop before
        # this fix got it as DOUBLE PRECISION because _sql_type_for maps the
        # 'bool' type to DOUBLE PRECISION (deliberate for the numeric tva
        # toggle). sales.is_historical is never affected - it is intentionally
        # absent from SalesClass's "database" section, so it is only ever
        # created here as BOOLEAN. Normalize the type so every consumer works:
        # COALESCE(i.is_historical, FALSE) and NOT i.is_historical both require
        # a boolean. Existing values are preserved - NULL stays NULL, 0 becomes
        # FALSE, any other number becomes TRUE. Idempotent: skipped once the
        # column is already BOOLEAN.
        for col_table in ("imports", "sales"):
            try:
                self.cursor.execute(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = %s "
                    "AND column_name = 'is_historical'",
                    (col_table,),
                )
                type_row = self.cursor.fetchone()
                if type_row and type_row[0] != "boolean":
                    self.cursor.execute(
                        f"ALTER TABLE {col_table} ALTER COLUMN is_historical "
                        "TYPE BOOLEAN USING (is_historical <> 0)"
                    )
                    self.conn.commit()
                    print(f"[OK] Normalized {col_table}.is_historical to BOOLEAN")
            except Exception as e_type:
                self.conn.rollback()
                print(
                    f"Warning: could not normalize {col_table}.is_historical "
                    f"to BOOLEAN: {e_type}"
                )

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
                "CREATE UNIQUE INDEX IF NOT EXISTS sales_devis_uidx "
                "ON sales (LOWER(BTRIM(devis))) "
                "WHERE devis IS NOT NULL AND BTRIM(devis) <> ''",
                "CREATE UNIQUE INDEX IF NOT EXISTS imports_bl_uidx "
                "ON imports (LOWER(BTRIM(bl_number))) "
                "WHERE bl_number IS NOT NULL AND BTRIM(bl_number) <> ''",
                "CREATE UNIQUE INDEX IF NOT EXISTS imports_operation_token_uidx "
                "ON imports(operation_token) WHERE operation_token IS NOT NULL AND operation_token <> ''",
            )
            for statement in index_statements:
                self.cursor.execute(statement)
            self.conn.commit()
        except Exception as exc:
            self.conn.rollback()
            print(f"Warning: could not create workflow indexes: {exc}")

        # Existing installations created these columns as INTEGER.
        # PostgreSQL's cast keeps all old values intact. Check first to avoid
        # taking an unnecessary table lock on every startup.
        for table in ("sales_items", "import_items"):
            try:
                self.cursor.execute(
                    "SELECT data_type, numeric_precision, numeric_scale "
                    "FROM information_schema.columns WHERE table_schema=current_schema() "
                    "AND table_name=%s AND column_name='quantity'",
                    (table,),
                )
                column = self.cursor.fetchone()
                if column and column != ('numeric', 15, 3):
                    self.cursor.execute(
                        f"ALTER TABLE {table} ALTER COLUMN quantity "
                        "TYPE NUMERIC(15, 3) USING quantity::NUMERIC(15, 3)"
                    )
                self.conn.commit()
            except Exception as exc:
                self.conn.rollback()
                print(
                    f"Warning: could not migrate {table}.quantity to decimal: {exc}"
                )

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
        """Create the client/supplier-account payment table during trusted host startup."""
        try:
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    sale_id INTEGER,
                    sales_item_id INTEGER,
                    import_id INTEGER,
                    import_item_id INTEGER,
                    amount DOUBLE PRECISION,
                    date TEXT,
                    FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE,
                    FOREIGN KEY (sales_item_id) REFERENCES sales_items(id) ON DELETE CASCADE,
                    FOREIGN KEY (import_id) REFERENCES imports(id) ON DELETE CASCADE,
                    FOREIGN KEY (import_item_id) REFERENCES import_items(id) ON DELETE CASCADE
                )
                """
            )
            self.cursor.execute(
                "ALTER TABLE payments ADD COLUMN IF NOT EXISTS sales_item_id INTEGER"
            )
            # Supplier side of the same table: an Import-level payment recorded
            # against a supplier account. Idempotent for legacy databases.
            self.cursor.execute(
                "ALTER TABLE payments ADD COLUMN IF NOT EXISTS import_id INTEGER"
            )
            self.cursor.execute(
                "ALTER TABLE payments ADD COLUMN IF NOT EXISTS import_item_id INTEGER"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS payments_import_id_idx "
                "ON payments(import_id) WHERE import_id IS NOT NULL"
            )
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            print(f"Warning: could not create Payments table: {e}")

    def _ensure_devis_numbers(self, sale_ids=None):
        """Assign persistent per-year Devis numbers (DE-YEAR-N) to sales.

        The number is stored on ``sales.devis_number`` so it is stable across
        restarts, refreshes, other PCs and report printing. Legacy sales and
        sales created since the last host startup are backfilled in ascending
        ``sales.id`` order within each year, starting after the highest number
        already assigned for that year. Already-assigned rows are never
        touched, so the backfill is idempotent and renumbering never happens.

        ``sale_ids`` optionally restricts the backfill to a subset (used by the
        read path when a sale is about to be displayed but has no number yet).
        When ``sale_ids`` is omitted every missing number is assigned in one
        statement.

        Returns the number of sales that were assigned a Devis number.
        """
        try:
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS sales_devis_number_idx ON sales(devis_number)"
            )
            extra = ""
            params = []
            if sale_ids:
                extra = "AND s.id = ANY(%s)"
                params.append([int(sale_id) for sale_id in sale_ids])
            sql = f"""
                WITH year_map AS (
                    SELECT s.id AS sale_id,
                           {_DEVIS_YEAR_EXPR} AS y
                    FROM sales s
                    WHERE s.devis_number IS NULL {extra}
                ),
                grouped AS (
                    SELECT ym.sale_id, ym.y,
                           ROW_NUMBER() OVER (PARTITION BY ym.y ORDER BY ym.sale_id) AS rn
                    FROM year_map ym
                ),
                base AS (
                    SELECT COALESCE(NULLIF(SUBSTRING(COALESCE(s.date, '') FROM '\\d{{4}}'), ''),
                                    NULLIF(SUBSTRING(COALESCE(s.created_at::text, '') FROM '\\d{{4}}'), ''),
                                    '0') AS y,
                           MAX(s.devis_number) AS m
                    FROM sales s
                    WHERE s.devis_number IS NOT NULL
                    GROUP BY 1
                )
                UPDATE sales s
                SET devis_number = g.rn + COALESCE(b.m, 0)
                FROM grouped g
                LEFT JOIN base b ON b.y = g.y
                WHERE s.id = g.sale_id
            """
            self.cursor.execute(sql, tuple(params))
            assigned = self.cursor.rowcount
            self.conn.commit()
            if assigned:
                logger.info(
                    "Devis backfill assigned=%s restricted=%s",
                    assigned, bool(sale_ids),
                )
            return assigned or 0
        except Exception as exc:
            self.conn.rollback()
            logger.warning("Devis backfill failed: %s", exc)
            return 0

    def _ensure_devis_text(self, sale_ids=None):
        """Persist the canonical ``sales.devis`` TEXT reference from the
        per-year ``devis_number`` for any sale that has a number but no text.

        Legacy rows and rows created before the TEXT column existed get
        ``DE-YEAR-N`` written once; afterwards the text is authoritative and
        the backfill never touches a non-empty value. ``sale_ids`` optionally
        restricts the backfill (read path). Returns rows updated.
        """
        try:
            extra = ""
            params = []
            if sale_ids:
                extra = "AND s.id = ANY(%s)"
                params.append([int(sale_id) for sale_id in sale_ids])
            sql = f"""
                UPDATE sales s
                SET devis = 'DE-' || {_DEVIS_YEAR_EXPR} || '-' || s.devis_number
                WHERE (s.devis IS NULL OR BTRIM(s.devis) = '')
                  AND s.devis_number IS NOT NULL {extra}
            """
            self.cursor.execute(sql, tuple(params))
            assigned = self.cursor.rowcount
            self.conn.commit()
            if assigned:
                logger.info(
                    "Devis text backfill assigned=%s restricted=%s",
                    assigned, bool(sale_ids),
                )
            return assigned or 0
        except Exception as exc:
            self.conn.rollback()
            logger.warning("Devis text backfill failed: %s", exc)
            return 0

    @staticmethod
    def _devis_year_from_date(date_value):
        """First 4-digit group of a date string, else the current year."""
        if date_value:
            match = re.search(r"\d{4}", str(date_value))
            if match:
                return match.group(0)
        return str(datetime.now().year)

    def _allocate_devis_number(self, sale_id, header):
        """Allocate the next per-year Devis number and store it on ``header``.

        Runs inside the sale-save transaction on the host - never on a GUI
        thread - so two clients cannot race a SELECT MAX+1. The unique index
        ``sales_devis_uidx`` remains the hard backstop.
        """
        year = self._devis_year_from_date(header.get("date"))
        self.cursor.execute(
            "SELECT COALESCE(MAX(devis_number), 0) + 1 FROM ("
            f"SELECT s.devis_number, {_DEVIS_YEAR_EXPR} AS devis_year "
            "FROM sales s) sub WHERE sub.devis_year = %s",
            (year,),
        )
        row = self.cursor.fetchone()
        next_num = int(row[0]) if row else 1
        header["devis"] = f"DE-{year}-{next_num}"
        header["devis_number"] = next_num

    def _resolve_sale_devis(self, sale_id, header):
        """Host-side Devis resolution for creates and edits.

        Mutates ``header`` with the authoritative ``devis`` (and
        ``devis_number`` when one was allocated). Rules:

        * A provided reference is stored verbatim (never silently changed)
          and must be unique (case-insensitive) among all other sales.
        * An empty reference on a create allocates the next per-year number.
        * An empty reference on an edit preserves the stored reference, or
          allocates one for legacy rows that have none yet.

        Raises ValueError for over-length or duplicate references.
        """
        raw_devis = ""
        if "devis" in header:
            raw_devis = " ".join(str(header["devis"] or "").split())
        if len(raw_devis) > DEVIS_MAX_LENGTH:
            raise ValueError(
                f"Devis must be at most {DEVIS_MAX_LENGTH} characters"
            )
        if raw_devis:
            header["devis"] = raw_devis
            dup_params = [self._normalize_exact(raw_devis)]
            dup_sql = (
                "SELECT id FROM sales WHERE LOWER(BTRIM(devis)) = %s "
                "AND devis IS NOT NULL AND BTRIM(devis) <> ''"
            )
            if sale_id:
                dup_sql += " AND id != %s"
                dup_params.append(int(sale_id))
            self.cursor.execute(dup_sql, dup_params)
            if self.cursor.fetchone():
                raise ValueError(
                    f"Devis '{raw_devis}' is already used by another sale"
                )
        elif sale_id:
            self.cursor.execute(
                "SELECT devis FROM sales WHERE id = %s", (int(sale_id),)
            )
            stored_row = self.cursor.fetchone()
            stored_devis = (stored_row[0] or "").strip() if stored_row else ""
            if stored_devis:
                header["devis"] = stored_devis
            else:
                self._allocate_devis_number(sale_id, header)
        else:
            self._allocate_devis_number(None, header)
        return header

    def get_next_devis_preview(self, date=None):
        """Propose the next per-year Devis reference (DE-YEAR-N) for the UI.

        Read-only and advisory: the definitive allocation/validation happens in
        ``_resolve_sale_devis`` inside ``save_sale_with_items`` at commit time.
        """
        year = self._devis_year_from_date(date)
        self.cursor.execute(
            "SELECT COALESCE(MAX(devis_number), 0) + 1 FROM ("
            f"SELECT s.devis_number, {_DEVIS_YEAR_EXPR} AS devis_year "
            "FROM sales s) sub WHERE sub.devis_year = %s",
            (year,),
        )
        row = self.cursor.fetchone()
        next_num = int(row[0]) if row else 1
        return f"DE-{year}-{next_num}"

    def _ensure_bl_numbers(self, import_ids=None):
        """Assign persistent per-year Bon de Livraison references (BL-YEAR-N).

        Backfills ``imports.bl_number`` for any import that still has none, in
        ascending ``imports.id`` order within each year, starting after the
        highest number already assigned for that year. Already-assigned rows
        are never touched, so the backfill is idempotent and renumbering never
        happens. ``import_ids`` optionally restricts the backfill (read path).

        Returns the number of imports that were assigned a BL reference.
        """
        try:
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS imports_bl_number_idx ON imports(bl_number)"
            )
            extra = ""
            params = []
            if import_ids:
                extra = "AND s.id = ANY(%s)"
                params.append([int(import_id) for import_id in import_ids])
            sql = f"""
                WITH year_map AS (
                    SELECT s.id AS import_id,
                           {_BL_YEAR_EXPR} AS y
                    FROM imports s
                    WHERE (s.bl_number IS NULL OR BTRIM(s.bl_number) = '') {extra}
                ),
                grouped AS (
                    SELECT ym.import_id, ym.y,
                           ROW_NUMBER() OVER (PARTITION BY ym.y ORDER BY ym.import_id) AS rn
                    FROM year_map ym
                ),
                base AS (
                    SELECT COALESCE(NULLIF(SUBSTRING(COALESCE(s.date, '') FROM '\\d{{4}}'), ''),
                                    NULLIF(SUBSTRING(COALESCE(s.created_at::text, '') FROM '\\d{{4}}'), ''),
                                    '0') AS y,
                           MAX(CAST(SUBSTRING(s.bl_number FROM 'BL-\\d{{4}}-(\\d+)') AS INTEGER)) AS m
                    FROM imports s
                    WHERE s.bl_number IS NOT NULL
                      AND BTRIM(s.bl_number) <> ''
                      AND s.bl_number ~ '^BL-\\d{{4}}-\\d+$'
                    GROUP BY 1
                )
                UPDATE imports s
                SET bl_number = 'BL-' || g.y || '-' || (g.rn + COALESCE(b.m, 0))
                FROM grouped g
                LEFT JOIN base b ON b.y = g.y
                WHERE s.id = g.import_id
            """
            self.cursor.execute(sql, tuple(params))
            assigned = self.cursor.rowcount
            self.conn.commit()
            if assigned:
                logger.info(
                    "BL backfill assigned=%s restricted=%s",
                    assigned, bool(import_ids),
                )
            return assigned or 0
        except Exception as exc:
            self.conn.rollback()
            logger.warning("BL backfill failed: %s", exc)
            return 0

    def _allocate_bl_number(self, import_id, header):
        """Allocate the next per-year Bon de Livraison number and store it on
        ``header``.

        Runs inside the import-save transaction on the host - never on a GUI
        thread - so two clients cannot race a SELECT MAX+1. The unique index
        ``imports_bl_uidx`` remains the hard backstop.
        """
        year = self._devis_year_from_date(header.get("date"))
        self.cursor.execute(
            "SELECT COALESCE(MAX(CAST(SUBSTRING(s.bl_number FROM 'BL-\\d{4}-(\\d+)') "
            "AS INTEGER)), 0) + 1 FROM ("
            f"SELECT s.bl_number, {_BL_YEAR_EXPR} AS bl_year "
            "FROM imports s) s WHERE s.bl_year = %s",
            (year,),
        )
        row = self.cursor.fetchone()
        next_num = int(row[0]) if row else 1
        header["bl_number"] = f"BL-{year}-{next_num}"

    def _resolve_import_bl(self, import_id, header):
        """Host-side Bon de Livraison reference resolution for creates/edits.

        Mutates ``header`` with the authoritative ``bl_number``. Rules:

        * A provided reference is stored verbatim (never silently changed)
          and must be unique (case-insensitive) among all other imports.
        * An empty reference on a create allocates the next per-year number.
        * An empty reference on an edit preserves the stored reference, or
          allocates one for legacy rows that have none yet.

        Raises ValueError for over-length or duplicate references.
        """
        raw_bl = ""
        if "bl_number" in header:
            raw_bl = " ".join(str(header["bl_number"] or "").split())
        if len(raw_bl) > BL_MAX_LENGTH:
            raise ValueError(
                f"Bon de livraison must be at most {BL_MAX_LENGTH} characters"
            )
        if raw_bl:
            header["bl_number"] = raw_bl
            dup_params = [self._normalize_exact(raw_bl)]
            dup_sql = (
                "SELECT id FROM imports WHERE LOWER(BTRIM(bl_number)) = %s "
                "AND bl_number IS NOT NULL AND BTRIM(bl_number) <> ''"
            )
            if import_id:
                dup_sql += " AND id != %s"
                dup_params.append(int(import_id))
            self.cursor.execute(dup_sql, dup_params)
            if self.cursor.fetchone():
                raise ValueError(
                    f"Bon de livraison '{raw_bl}' is already used by another import"
                )
        elif import_id:
            self.cursor.execute(
                "SELECT bl_number FROM imports WHERE id = %s", (int(import_id),)
            )
            stored_row = self.cursor.fetchone()
            stored_bl = (stored_row[0] or "").strip() if stored_row else ""
            if stored_bl:
                header["bl_number"] = stored_bl
            else:
                self._allocate_bl_number(import_id, header)
        else:
            self._allocate_bl_number(None, header)
        return header

    def get_next_bl_preview(self, date=None):
        """Propose the next per-year Bon de Livraison reference (BL-YEAR-N).

        Read-only and advisory: the definitive allocation/validation happens in
        ``_resolve_import_bl`` inside ``save_import_with_items`` at commit time.
        """
        year = self._devis_year_from_date(date)
        self.cursor.execute(
            "SELECT COALESCE(MAX(CAST(SUBSTRING(s.bl_number FROM 'BL-\\d{4}-(\\d+)') "
            "AS INTEGER)), 0) + 1 FROM ("
            f"SELECT s.bl_number, {_BL_YEAR_EXPR} AS bl_year "
            "FROM imports s) s WHERE s.bl_year = %s",
            (year,),
        )
        row = self.cursor.fetchone()
        next_num = int(row[0]) if row else 1
        return f"BL-{year}-{next_num}"

    def get_import_bl_number(self, import_id):
        """Return the persistent Bon de Livraison reference for an import.

        Allocates and persists ``BL-YEAR-N`` on first access for legacy rows,
        so reprinting the same import always keeps the same number. Host-side
        only (never runs in the GUI thread); the unique index
        ``imports_bl_uidx`` remains the concurrency backstop.
        """
        import_id = int(import_id)
        self.cursor.execute(
            "SELECT bl_number FROM imports WHERE id = %s", (import_id,)
        )
        row = self.cursor.fetchone()
        if row is None:
            raise ValueError(f"Import {import_id} does not exist")
        stored = (row[0] or "").strip()
        if stored:
            return stored
        self.cursor.execute(
            "SELECT date FROM imports WHERE id = %s", (import_id,)
        )
        date_row = self.cursor.fetchone()
        header = {"date": date_row[0] if date_row else None}
        self._allocate_bl_number(import_id, header)
        self.cursor.execute(
            "UPDATE imports SET bl_number = %s WHERE id = %s",
            (header["bl_number"], import_id),
        )
        self.conn.commit()
        return header["bl_number"]

    # ---------------- Migration & Meta Helpers -----------------
    def _ensure_meta_table(self):
        try:
            self.cursor.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            print(f"Warning: could not create Meta table: {e}")

    def _ensure_charges_tables(self):
        """Create the Charges (operating expenses) tables during host startup.

        Charges are business expenses (rent, salaries, electricity...) and are
        deliberately SEPARATE from Imports: product purchases are already
        represented in COGS, so subtracting them again as charges would
        double-count. Opening Stock / Stock Adjustment imports are stock
        ledger entries, never charges.

        Occurrence idempotency for recurring templates is enforced by a
        partial UNIQUE index: one charge per (template, expense_date).
        """
        try:
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS charge_categories (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    active BOOLEAN NOT NULL DEFAULT TRUE
                )
            """)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS charge_recurring_templates (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    name TEXT NOT NULL,
                    category_id INTEGER REFERENCES charge_categories(id),
                    default_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
                    frequency TEXT NOT NULL DEFAULT 'monthly',
                    next_due_date TEXT NOT NULL,
                    payment_method TEXT NOT NULL DEFAULT 'Cash',
                    reference_template TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    created_by INTEGER,
                    created_by_username TEXT,
                    created_at TEXT
                )
            """)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS charges (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    expense_date TEXT NOT NULL,
                    category_id INTEGER REFERENCES charge_categories(id),
                    description TEXT NOT NULL DEFAULT '',
                    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
                    payment_method TEXT NOT NULL DEFAULT 'Cash',
                    reference TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    recurring_template_id INTEGER
                        REFERENCES charge_recurring_templates(id)
                        ON DELETE SET NULL,
                    created_by INTEGER,
                    created_by_username TEXT,
                    created_at TEXT,
                    updated_by INTEGER,
                    updated_by_username TEXT,
                    updated_at TEXT
                )
            """)
            self.cursor.execute(
                "ALTER TABLE charge_recurring_templates "
                "ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE"
            )
            # Legacy databases created these flag columns as INTEGER 0/1,
            # which breaks SQL predicates like `WHERE rt.enabled AND ...`
            # (argument of AND must be type boolean). Normalize the type so
            # schema, queries and Python values agree everywhere. Values are
            # preserved: 0 becomes FALSE, any other number becomes TRUE.
            # Idempotent: skipped once the column is already BOOLEAN (same
            # pattern as the imports.is_historical normalization).
            for flag_table, flag_column in (
                ("charge_categories", "active"),
                ("charge_recurring_templates", "enabled"),
            ):
                try:
                    self.cursor.execute(
                        "SELECT data_type FROM information_schema.columns "
                        "WHERE table_schema = current_schema() "
                        "AND table_name = %s AND column_name = %s",
                        (flag_table, flag_column),
                    )
                    type_row = self.cursor.fetchone()
                    if type_row and type_row[0] != "boolean":
                        # Legacy columns carry an INTEGER default (e.g.
                        # DEFAULT 1), which PostgreSQL refuses to auto-cast
                        # during TYPE conversion. Drop it first, convert the
                        # stored values, then install the BOOLEAN default.
                        self.cursor.execute(
                            f"ALTER TABLE {flag_table} ALTER COLUMN "
                            f"{flag_column} DROP DEFAULT"
                        )
                        self.cursor.execute(
                            f"ALTER TABLE {flag_table} ALTER COLUMN "
                            f"{flag_column} TYPE BOOLEAN "
                            f"USING ({flag_column} <> 0)"
                        )
                        self.cursor.execute(
                            f"ALTER TABLE {flag_table} ALTER COLUMN "
                            f"{flag_column} SET DEFAULT TRUE"
                        )
                        print(
                            f"[OK] Normalized {flag_table}.{flag_column} "
                            "to BOOLEAN"
                        )
                except Exception as e_flag:
                    self.conn.rollback()
                    print(
                        f"Warning: could not normalize {flag_table}."
                        f"{flag_column} to BOOLEAN: {e_flag}"
                    )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS charges_expense_date_idx "
                "ON charges(expense_date)"
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS charges_category_idx "
                "ON charges(category_id)"
            )
            self.cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS charges_template_occurrence_uidx "
                "ON charges(recurring_template_id, expense_date) "
                "WHERE recurring_template_id IS NOT NULL"
            )
            # Seed the default category set once; user-created categories are
            # never touched afterwards.
            default_categories = [
                "Rent", "Salaries", "Electricity", "Water", "Internet / Phone",
                "Transport", "Fuel", "Maintenance", "Equipment",
                "Office Supplies", "Bank Fees", "Taxes", "Insurance",
                "Software / Subscriptions", "Marketing",
                "Professional Services", "Other",
            ]
            for name in default_categories:
                self.cursor.execute(
                    "INSERT INTO charge_categories (name) VALUES (%s) "
                    "ON CONFLICT (name) DO NOTHING",
                    (name,),
                )
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            print(f"Warning: could not create Charges tables: {e}")

    def _ensure_change_log_table(self):
        """Create the per-schema change log used for incremental client sync.

        Every write path that a remote client should hear about calls
        ``record_change`` after committing; clients poll ``get_changes`` with
        their stored ``last_seq`` and apply only the new rows to their local
        SQLite cache. The log is display-data metadata, never the source of
        truth - PostgreSQL tables remain authoritative.
        """
        try:
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS change_log (
                    seq BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    section TEXT NOT NULL,
                    row_id INTEGER NOT NULL,
                    operation TEXT NOT NULL,
                    payload TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS change_log_section_seq_idx "
                "ON change_log(section, seq)"
            )
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            print(f"Warning: could not create change log table: {e}")

    def record_change(self, section, row_id, operation, payload=None):
        """Append one row to the change log for a committed write.

        ``operation`` is 'upsert' (create or update) or 'delete'. ``payload``
        is the full record dict for upserts so clients can replace their
        cached row without re-fetching. Returns the new sequence number, or
        None if the write failed (never raises - sync is best-effort).
        """
        try:
            payload_json = None
            if payload is not None:
                payload_json = json.dumps(payload, default=str)
            self.cursor.execute(
                "INSERT INTO change_log (section, row_id, operation, payload) "
                "VALUES (%s, %s, %s, %s) RETURNING seq",
                (str(section), int(row_id), operation, payload_json),
            )
            seq = self.cursor.fetchone()[0]
            self.conn.commit()
            return int(seq)
        except Exception:
            self.conn.rollback()
            logger.exception("record_change failed section=%s row_id=%s", section, row_id)
            return None

    def get_changes(self, section, since_seq=0, limit=500):
        """Return incremental changes for ``section`` with seq > ``since_seq``.

        Result: {'changes': [{seq, row_id, operation, payload}], 'last_seq': N}.
        Payloads are None for deletes; upserts carry the full record dict. The
        host's own window is unaffected - this is only for remote clients.
        """
        try:
            self.cursor.execute(
                "SELECT seq, row_id, operation, payload FROM change_log "
                "WHERE section=%s AND seq > %s ORDER BY seq LIMIT %s",
                (str(section), int(since_seq), int(limit)),
            )
            rows = self.cursor.fetchall()
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            logger.exception("get_changes failed section=%s", section)
            return {'changes': [], 'last_seq': int(since_seq)}
        changes = []
        last_seq = int(since_seq)
        for seq, row_id, operation, payload in rows:
            last_seq = max(last_seq, int(seq))
            try:
                parsed_payload = json.loads(payload) if payload else None
            except (ValueError, TypeError):
                parsed_payload = None
            changes.append({
                'seq': int(seq),
                'row_id': int(row_id),
                'operation': operation,
                'payload': parsed_payload,
            })
        return {'changes': changes, 'last_seq': last_seq}

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
                    print("[OK] Backfilled missing product_name snapshots where possible")
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
        from decimal import Decimal
        from core.calculations import to_decimal
        try:
            number = to_decimal(value)
        except Exception:
            raise ValueError(f"Invalid numeric value for {field}: {value!r}")
        if minimum is not None and number < Decimal(str(minimum)):
            raise ValueError(f"{field} must be at least {minimum}")
        return number

    @staticmethod
    def _normalize_exact(value):
        return " ".join(str(value or "").split()).casefold()

    @staticmethod
    def _parse_bool_flag(value):
        """Interpret a boolean flag that may arrive as bool, 0/1, or a string."""
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in ("1", "true", "yes", "on", "y", "t")

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

    def save_product_with_opening_stock(self, product_data, initial_quantity=0, user=None):
        """Create a product and its opening-stock ledger entry atomically."""
        if not isinstance(product_data, dict):
            raise ValueError("Product data must be an object")

        quantity = self._sale_decimal(
            initial_quantity, "initial product quantity", "0"
        )
        product_cls = self.registered_classes.get("Products")
        if product_cls is None:
            raise ValueError("Products are not registered")

        product_obj = product_cls(0, None)
        allowed = product_obj.get_visible_parameters("database")
        data = {
            key: product_data[key]
            for key in allowed
            if key in product_data and not product_obj.is_parameter_calculated(key)
        }
        name = " ".join(str(data.get("name") or "").split())
        username = " ".join(str(data.get("username") or name).split())
        if not name:
            raise ValueError("Product name is required")
        if not username:
            raise ValueError("Product username is required")
        data["name"] = name
        data["username"] = username

        try:
            self.cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"product-username:{self._normalize_exact(username)}",),
            )
            self.cursor.execute(
                "SELECT 1 FROM products "
                "WHERE LOWER(REGEXP_REPLACE(BTRIM(username), '\\s+', ' ', 'g'))=%s "
                "LIMIT 1",
                (self._normalize_exact(username),),
            )
            if self.cursor.fetchone():
                raise ValueError(f"Product username '{username}' already exists")

            actor = self._actor_fields(user)
            for key, value in actor.items():
                if key in allowed and not data.get(key):
                    data[key] = value

            columns = list(data)
            self.cursor.execute(
                f"INSERT INTO products ({', '.join(columns)}) "
                f"VALUES ({', '.join('%s' for _ in columns)}) RETURNING id",
                list(data.values()),
            )
            product_id = int(self.cursor.fetchone()[0])

            if quantity > 0:
                self.cursor.execute(
                    "INSERT INTO imports "
                    "(supplier_username, supplier_name, date, notes, "
                    "created_by, created_by_username, created_at) "
                    "VALUES ('', 'Opening Stock', %s, %s, %s, %s, %s) RETURNING id",
                    (
                        datetime.now().strftime("%Y-%m-%d"),
                        f"Opening stock for {name}",
                        actor["created_by"], actor["created_by_username"],
                        actor["created_at"],
                    ),
                )
                opening_import_id = int(self.cursor.fetchone()[0])
                self.cursor.execute(
                    "INSERT INTO import_items "
                    "(import_id, product_id, product_name, quantity, unit_price) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        opening_import_id, product_id, name, quantity,
                        self._sale_decimal(data.get("unit_price"), "unit price", "0"),
                    ),
                )

            self.conn.commit()
            return {
                "product_id": product_id,
                "opening_quantity": str(quantity),
                "transaction": "committed",
            }
        except Exception:
            self.conn.rollback()
            raise

    def update_product_with_stock(self, product_id, product_data, target_quantity, user=None):
        """Update a product and set its ledger-derived stock in one transaction.

        Product stock is intentionally not duplicated in ``products``.  A
        stock-adjustment import records only the difference between the
        requested quantity and the current imports-minus-sales balance.
        """
        if not isinstance(product_data, dict):
            raise ValueError("Product data must be an object")
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            raise ValueError("Product ID must be an integer")
        quantity = self._sale_decimal(
            target_quantity, "product stock quantity", "0"
        )

        product_cls = self.registered_classes.get("Products")
        if product_cls is None:
            raise ValueError("Products are not registered")
        product_obj = product_cls(0, None)
        allowed = product_obj.get_visible_parameters("database")
        data = {
            key: product_data[key]
            for key in allowed
            if key in product_data and not product_obj.is_parameter_calculated(key)
        }
        name = " ".join(str(data.get("name") or "").split())
        username = " ".join(str(data.get("username") or name).split())
        if not name:
            raise ValueError("Product name is required")
        if not username:
            raise ValueError("Product username is required")
        data["name"] = name
        data["username"] = username

        try:
            # This row lock serializes quantity edits with concurrent sales,
            # whose stock validation locks the same product rows below.
            self.cursor.execute(
                "SELECT id FROM products WHERE id=%s FOR UPDATE", (product_id,)
            )
            if not self.cursor.fetchone():
                raise ValueError(f"Product {product_id} does not exist")
            self.cursor.execute(
                "SELECT 1 FROM products "
                "WHERE LOWER(REGEXP_REPLACE(BTRIM(username), '\\s+', ' ', 'g'))=%s "
                "AND id<>%s LIMIT 1",
                (self._normalize_exact(username), product_id),
            )
            if self.cursor.fetchone():
                raise ValueError(f"Product username '{username}' already exists")

            assignments = ", ".join(f"{key}=%s" for key in data)
            self.cursor.execute(
                f"UPDATE products SET {assignments} WHERE id=%s",
                [*data.values(), product_id],
            )
            if self.cursor.rowcount != 1:
                raise ValueError(f"Product {product_id} does not exist")

            self.cursor.execute(
                "SELECT COALESCE(SUM(ii.quantity), 0) "
                "FROM import_items ii "
                "JOIN imports i ON i.id = ii.import_id "
                "WHERE ii.product_id=%s "
                "  AND (i.is_historical IS NULL OR NOT i.is_historical)",
                (product_id,),
            )
            imported = self.cursor.fetchone()[0] or 0
            self.cursor.execute(
                """
                SELECT COALESCE(SUM(si.quantity), 0)
                FROM sales_items si
                JOIN sales s ON s.id=si.sales_id
                WHERE si.product_id=%s
                  AND (s.state IS NULL OR s.state<>'on_hold')
                  AND (s.is_historical IS NULL OR NOT s.is_historical)
                """,
                (product_id,),
            )
            sold = self.cursor.fetchone()[0] or 0
            current = imported - sold
            adjustment = quantity - current

            if adjustment:
                actor = self._actor_fields(user)
                self.cursor.execute(
                    "INSERT INTO imports "
                    "(supplier_username, supplier_name, date, tva, notes, "
                    "created_by, created_by_username, created_at) "
                    "VALUES ('', 'Stock Adjustment', %s, 0, %s, %s, %s, %s) "
                    "RETURNING id",
                    (
                        datetime.now().strftime("%Y-%m-%d"),
                        f"Stock adjusted from {current} to {quantity} for {name}",
                        actor["created_by"], actor["created_by_username"],
                        actor["created_at"],
                    ),
                )
                adjustment_import_id = int(self.cursor.fetchone()[0])
                self.cursor.execute(
                    "INSERT INTO import_items "
                    "(import_id, product_id, product_name, quantity, unit_price) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        adjustment_import_id, product_id, name, adjustment,
                        self._sale_decimal(data.get("unit_price"), "unit price", "0"),
                    ),
                )

            self.conn.commit()
            return {
                "product_id": product_id,
                "previous_quantity": str(current),
                "quantity": str(quantity),
                "adjustment": str(adjustment),
                "transaction": "committed",
            }
        except Exception:
            self.conn.rollback()
            raise

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

        # TEMPORARY Sale Save freeze diagnostic - see core/sale_save_diagnostics.py.
        from core import sale_save_diagnostics
        sale_save_diagnostics.event(
            "DB_TRANSACTION_START", sale_id=sale_id, item_count=len(validated),
        )
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
                    sale_save_diagnostics.event(
                        "DB_TRANSACTION_END", result="duplicate_token", sale_id=int(duplicate[0]),
                    )
                    return {
                        "sale_id": int(duplicate[0]), "saved": int(self.cursor.fetchone()[0]),
                        "inserted": 0, "updated": 0, "deleted": 0,
                        "items": [], "transaction": "committed", "duplicate": True,
                    }

            is_historical = self._parse_bool_flag(sale_data.get("is_historical"))

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
                    # Snapshot-only line ("Keep only in this Sale"): the typed
                    # name is stored with no Product/Service link and never
                    # affects stock. New lines are allowed as well.
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
            # is_historical lives on a real BOOLEAN column that is not managed
            # by the parameter-class schema builder; inject it explicitly so
            # creates and edits persist (and can switch) the flag.
            if "is_historical" in sale_data:
                header["is_historical"] = self._parse_bool_flag(sale_data["is_historical"])
            if sale_id:
                for protected in (
                    "created_by", "created_by_username", "created_at", "operation_token"
                ):
                    header.pop(protected, None)

            # Host-side Devis resolution (create & edit): validates or allocates
            # the canonical per-sale reference before anything is written.
            self._resolve_sale_devis(sale_id, header)

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

            if not is_historical and str(header.get("state") or "pending") != "on_hold":
                requested_by_product = {}
                for item in validated:
                    if item["item_type"] == "product":
                        requested_by_product[item["product_id"]] = (
                            requested_by_product.get(item["product_id"], 0) + item["quantity"]
                        )
                # Stable lock order prevents two multi-product sales from
                # deadlocking when their line order differs.
                for product_id in sorted(requested_by_product):
                    requested = requested_by_product[product_id]
                    # Serialize stock checks for the same product. Without this
                    # lock, two client PCs could both validate against the same
                    # pre-sale balance and oversell it.
                    self.cursor.execute(
                        "SELECT id FROM products WHERE id=%s FOR UPDATE",
                        (product_id,),
                    )
                    if not self.cursor.fetchone():
                        raise ValueError(f"Product {product_id} does not exist")
                    self.cursor.execute(
                        "SELECT COALESCE(SUM(ii.quantity), 0) "
                        "FROM import_items ii "
                        "JOIN imports i ON i.id = ii.import_id "
                        "WHERE ii.product_id=%s "
                        "  AND (i.is_historical IS NULL OR NOT i.is_historical)",
                        (product_id,),
                    )
                    imported = self.cursor.fetchone()[0] or 0
                    self.cursor.execute(
                        """
                        SELECT COALESCE(SUM(si.quantity), 0)
                        FROM sales_items si JOIN sales s ON s.id=si.sales_id
                        WHERE si.product_id=%s AND si.sales_id<>%s
                          AND (s.state IS NULL OR s.state<>'on_hold')
                          AND (s.is_historical IS NULL OR NOT s.is_historical)
                        """,
                        (product_id, sale_id),
                    )
                    sold_elsewhere = self.cursor.fetchone()[0] or 0
                    if requested > imported - sold_elsewhere:
                        raise ValueError(
                            f"Insufficient stock for product ID {product_id}: "
                            f"requested {requested}, available {imported - sold_elsewhere}"
                        )
            sale_save_diagnostics.event("DB_TRANSACTION_END", result="committing", sale_id=sale_id)
            self.conn.commit()
            sale_save_diagnostics.event("DB_TRANSACTION_END", result="committed", sale_id=sale_id)
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
        except Exception as e:
            sale_save_diagnostics.event(
                "DB_TRANSACTION_END", result="rolling_back", sale_id=sale_id, error=str(e),
            )
            self.conn.rollback()
            sale_save_diagnostics.event("DB_TRANSACTION_END", result="rolled_back", sale_id=sale_id)
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
            # is_historical lives on a real BOOLEAN column. Normalize here so the
            # INSERT/UPDATE always sends Python True/False regardless of whether
            # the payload arrives as bool, 0/1 or a string (mirrors the Sale
            # save path). Never persists 1/0 into the boolean column.
            if "is_historical" in header:
                header["is_historical"] = self._parse_bool_flag(header["is_historical"])
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

            # Allocate/preserve the persistent Bon de Livraison reference on
            # the host inside this transaction (never in the GUI thread).
            self._resolve_import_bl(import_id, header)

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
            new_id = row[0] if row else None
            if new_id is not None:
                self.record_change(
                    section, int(new_id), 'upsert',
                    self._row_snapshot(section, new_id),
                )
            return new_id

        except Exception as e:
            self.conn.rollback()
            print(f"Error adding item to {section}: {e}")
            return None

    def _row_snapshot(self, section, item_id):
        """Return the full row for ``item_id`` as a dict, or None on error."""
        try:
            self.cursor.execute(f"SELECT * FROM {section} WHERE id = %s", (item_id,))
            col_names = (
                [d[0] for d in self.cursor.description]
                if self.cursor.description else []
            )
            row = self.cursor.fetchone()
            if row is None:
                return None
            return dict(zip(col_names, row))
        except Exception:
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
            self.record_change(
                section, int(item_id), 'upsert',
                self._row_snapshot(section, item_id),
            )
            return True

        except Exception as e:
            self.conn.rollback()
            print(f"Error updating item in {section}: {e}")
            return False

    @staticmethod
    def _order_column_expression(order_by, prefix=''):
        """Resolve a validated sort column to a SQL expression (None for id).

        ``prefix`` scopes a plain column name for join-based queries (e.g. 's.'
        for sales) but the date sort is special-cased to a CASE expression.
        Returned expressions are NULL-safe so composite keyset comparisons
        never evaluate against a NULL sort value.
        """
        if not order_by or str(order_by).casefold() == 'id':
            return None
        column = str(order_by)
        if column not in _ORDER_COLUMNS:
            return None
        if column == 'date':
            return Database._date_sort_expression(prefix)
        expr = f"{prefix}{column}"
        if column in _ORDER_NUMERIC_COLUMNS:
            return f"COALESCE({expr}, 0)"
        return f"COALESCE({expr}, '')"

    @staticmethod
    def _date_sort_expression(prefix=''):
        """Order expression parsing the dd-mm-yyyy / yyyy-mm-dd date text stored
        in the ``date`` column into a real Postgres date for correct ordering.
        Unparseable/empty dates sort to 1900-01-01 so the keyset cursor value
        stays type-compatible with the comparison expression."""
        col = f"{prefix}date"
        return (
            "CASE "
            f"WHEN {col} ~ '^\\d{{2}}-\\d{{2}}-\\d{{4}}$' THEN TO_DATE({col}, 'DD-MM-YYYY') "
            f"WHEN {col} ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}$' THEN TO_DATE({col}, 'YYYY-MM-DD') "
            f"WHEN {col} ~ '^\\d{{2}}/\\d{{2}}/\\d{{4}}$' THEN TO_DATE({col}, 'DD/MM/YYYY') "
            "ELSE DATE '1900-01-01' END"
        )

    @staticmethod
    def _keyset_sort_value(order_by, after_sort):
        """Normalize a keyset cursor value so it can be cast to the same type as
        the ORDER BY expression (dates are stored as display text)."""
        if order_by != 'date' or after_sort is None:
            return after_sort
        text = str(after_sort).strip()
        for fmt in ('%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y'):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
        return '1900-01-01'

    @staticmethod
    def _keyset_condition(order_expr, direction, after_id, after_sort):
        """Build (sql_fragment, params) for keyset pagination on (order_expr, id).

        Uses a composite row comparison so duplicate sort values still page
        deterministically through the unique ``id`` tie-breaker. Returns a
        fragment of ``None`` when no cursor is supplied (first batch).
        """
        if after_id is None:
            return None, []
        op = '>' if str(direction).casefold().startswith('a') else '<'
        last_id = int(after_id)
        if order_expr and order_expr != 'id':
            fragment = f"({order_expr}, id) {op} (%s, %s)"
            return fragment, [after_sort, last_id]
        return f"id {op} %s", [last_id]

    @staticmethod
    def _summary_order_expression(order_by):
        """Resolve a validated sort column to a SQL expression usable both in
        ORDER BY and in the keyset WHERE clause for the Sales/Imports summary
        query (SELECT aliases are not visible inside WHERE)."""
        if not order_by or str(order_by).casefold() == 'id':
            return None
        column = str(order_by)
        if column not in _ORDER_COLUMNS:
            return None
        summary_columns = {
            'subtotal': 'COALESCE(summary.subtotal, 0)',
            'total': 'COALESCE(summary.subtotal - COALESCE(s.remise, 0.0), 0)',
            'information': "COALESCE(summary.information, '')",
            'total_quantity': 'COALESCE(summary.total_quantity, 0)',
            'total_production': 'COALESCE(summary.total_production, 0)',
        }
        if column in summary_columns:
            return summary_columns[column]
        return Database._order_column_expression(column, prefix='s.')

    def get_items(
        self, section, search_text=None, search_columns=None,
        order_by=None, order_dir='asc', limit=None, offset=None,
        after_id=None, after_sort=None
    ):
        """Get items from section, optionally filtered, sorted, and paginated.

        ``after_id`` / ``after_sort`` implement keyset (seek) pagination: the
        next batch is the first batch of rows after the previous batch's last
        row in the same stable ORDER BY (sort column, id). This avoids the
        deep-OFFSET slowdown and duplicate/skipped rows on large tables.
        """
        if not self.cursor or section not in self.registered_classes:
            return []

        try:
            query = f"SELECT * FROM {section}"
            params = []
            conditions = []

            if search_text and search_columns:
                search_term = f"%{search_text.lower()}%"
                clauses = []
                for col in search_columns:
                    clauses.append(
                        f"LOWER(COALESCE(CAST({col} AS text), '')) LIKE %s"
                    )
                    params.append(search_term)
                if clauses:
                    conditions.append("(" + " OR ".join(clauses) + ")")

            direction = 'DESC' if str(order_dir).lower().startswith('d') else 'ASC'
            order_expr = self._order_column_expression(order_by)
            cursor_value = self._keyset_sort_value(order_by, after_sort)
            keyset_fragment, keyset_params = self._keyset_condition(
                order_expr, direction, after_id, cursor_value
            )
            if keyset_fragment:
                conditions.append(keyset_fragment)
                params.extend(keyset_params)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            if order_expr:
                query += f" ORDER BY {order_expr} {direction}, id {direction}"
            else:
                query += " ORDER BY id"

            if limit is not None:
                query += " LIMIT %s"
                params.append(int(limit))
                if offset is not None:
                    query += " OFFSET %s"
                    params.append(int(offset))

            self.cursor.execute(query, params)
            rows = self.cursor.fetchall()

            # Get column names - Postgres folds unquoted columns to lowercase,
            # so restore the PK's original 'ID' casing that callers throughout
            # the app expect (classes/base_class.py etc. do item.get('ID')).
            columns = [description[0] for description in self.cursor.description]
            if columns and columns[0].lower() == 'id':
                columns[0] = 'ID'

            return [dict(zip(columns, row)) for row in rows]

        except Exception as e:
            self.conn.rollback()
            print(f"Error getting items from {section}: {e}")
            return []

    def get_operation_summary_items(
        self, section, search_text=None, search_columns=None,
        order_by=None, order_dir='asc', limit=None, offset=None,
        after_id=None, after_sort=None,
        user=None,
    ):
        """Get Sales and Imports rows with precomputed totals and summaries.

        Sales are company-wide, not per-creator: this must return the exact
        same rows get_items_for_user('Sales', ...) does (no created_by
        filter) - see get_client_sales()/get_client_account() for the same
        policy and why an inconsistent filter here previously made this
        summary query silently return zero rows for any non-superadmin user
        viewing sales someone else created, forced through the
        get_items(...) fallback in ui/tabs/base_tab.py's fetch().
        """
        if section not in ('Sales', 'Imports'):
            return self.get_items(
                section,
                search_text=search_text,
                search_columns=search_columns,
                order_by=order_by,
                order_dir=order_dir,
                limit=limit,
                offset=offset,
                after_id=after_id,
                after_sort=after_sort,
            )

        base_table = section.lower()
        item_table = 'sales_items' if section == 'Sales' else 'import_items'
        foreign_key = 'sales_id' if section == 'Sales' else 'import_id'

        # Remise only exists on the sales table (discounts); imports have no
        # discount column, so their computed totals reduce to the raw sums.
        remise_expr = 'COALESCE(s.remise, 0.0)' if section == 'Sales' else '0'
        # Authoritative table totals (no VAT):
        #   Total = Subtotal - Remise
        total_expr = f'COALESCE(summary.subtotal - {remise_expr}, 0)'

        if section == 'Sales':
            information_select = (
                "COALESCE(STRING_AGG(COALESCE(si.information, ''), "
                "', ' ORDER BY si.id), '')"
            )
            production_select = "COALESCE(SUM(si.production), 0)"
        else:
            information_select = "''"
            production_select = "0"

        query = (
            f"SELECT s.*, "
            f"COALESCE(summary.subtotal, 0) AS subtotal, "
            f"{total_expr} AS total, "
            f"COALESCE(summary.information, '') AS information, "
            f"COALESCE(summary.total_quantity, 0) AS total_quantity, "
            f"COALESCE(summary.total_production, 0) AS total_production"
        )
        if section == 'Sales':
            # The persisted devis reference wins; legacy rows (or rows saved
            # before the TEXT column backfill) fall back to a computed
            # DE-YEAR-N so the Sales table always shows a stable reference.
            # The later duplicate "devis" key overrides s.* in the row dict.
            query += (
                f", COALESCE(NULLIF(BTRIM(s.devis), ''), "
                f"'DE-' || {_DEVIS_YEAR_EXPR} || '-' || COALESCE(s.devis_number::text, '')) AS devis"
            )
        query += (
            f" FROM {base_table} s "
            f"LEFT JOIN ("
            f"  SELECT si.{foreign_key}, "
            f"         SUM(si.quantity * si.unit_price) AS subtotal, "
            f"         {information_select} AS information, "
            f"         COALESCE(SUM(si.quantity), 0) AS total_quantity, "
            f"         {production_select} AS total_production "
            f"  FROM {item_table} si "
            f"  JOIN {base_table} i ON i.id = si.{foreign_key} "
            f"  GROUP BY si.{foreign_key} "
            f") summary ON summary.{foreign_key} = s.id "
        )
        params = []
        conditions = []

        if search_text and search_columns:
            search_term = f"%{search_text.lower()}%"
            clauses = []
            for col in search_columns:
                if col == 'information':
                    clauses.append("LOWER(COALESCE(summary.information, '')) LIKE %s")
                else:
                    clauses.append(
                        f"LOWER(COALESCE(CAST(s.{col} AS text), '')) LIKE %s"
                    )
                params.append(search_term)
            if clauses:
                conditions.append("(" + " OR ".join(clauses) + ")")

        direction = 'DESC' if str(order_dir).lower().startswith('d') else 'ASC'
        order_expr = self._summary_order_expression(order_by)
        cursor_value = self._keyset_sort_value(order_by, after_sort)
        keyset_fragment, keyset_params = self._keyset_condition(
            order_expr, direction, after_id, cursor_value
        )
        if keyset_fragment:
            conditions.append(keyset_fragment)
            params.extend(keyset_params)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        if order_expr:
            query += f" ORDER BY {order_expr} {direction}, s.id {direction}"
        else:
            query += " ORDER BY s.id"

        if limit is not None:
            query += " LIMIT %s"
            params.append(int(limit))
            if offset is not None:
                query += " OFFSET %s"
                params.append(int(offset))

        mode = 'remote' if user is not None else 'local'
        try:
            self.cursor.execute(query, params)
            rows = self.cursor.fetchall()
            columns = [description[0] for description in self.cursor.description]
            if columns and columns[0].lower() == 'id':
                columns[0] = 'ID'
            result = [dict(zip(columns, row)) for row in rows]
        except Exception:
            self.conn.rollback()
            logger.exception(
                "get_operation_summary_items failed: mode=%s section=%s user_id=%s "
                "sql_params=%s",
                mode, section, user.get('id') if user else None, params,
            )
            return []
        logger.info(
            "get_operation_summary_items: mode=%s section=%s user_id=%s role_id=%s "
            "sql_params=%s row_count=%s",
            mode, section, user.get('id') if user else None,
            user.get('role_id') if user else None, params, len(result),
        )
        return result

    def get_items_for_user(
        self, section, user, owner_id=None, date_from=None, date_to=None,
        report_type=None, search_text=None, search_columns=None,
        order_by=None, order_dir='asc', limit=None, offset=None,
        after_id=None, after_sort=None,
    ):
        """Return ownership-filtered Sales or Reports rows.

        Regular users are always pinned to their authenticated session ID.
        Super admins may request one owner or leave it empty for all rows.
        Legacy rows with no owner remain visible only in the all-user admin view.
        """
        if section == "Sales_Items":
            return self.get_items(
                section,
                search_text=search_text,
                search_columns=search_columns,
                order_by=order_by,
                order_dir=order_dir,
                limit=limit,
                offset=offset,
                after_id=after_id,
                after_sort=after_sort,
            )
        if section == "Sales":
            return self.get_items(
                section,
                search_text=search_text,
                search_columns=search_columns,
                order_by=order_by,
                order_dir=order_dir,
                limit=limit,
                offset=offset,
                after_id=after_id,
                after_sort=after_sort,
            )
        if section not in ("Sales", "Reports"):
            return self.get_items(
                section,
                search_text=search_text,
                search_columns=search_columns,
                order_by=order_by,
                order_dir=order_dir,
                limit=limit,
                offset=offset,
                after_id=after_id,
                after_sort=after_sort,
            )
        user = user or {}
        is_superadmin = bool(user.get("is_superadmin"))
        effective_owner = owner_id if is_superadmin else user.get("id")
        if not is_superadmin and effective_owner is None:
            return []

        query = f"SELECT * FROM {section}"
        params = []
        conditions = []

        if effective_owner not in (None, "", "all"):
            conditions.append("created_by=%s")
            params.append(int(effective_owner))

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
                conditions.append(f"{date_expression} >= %s::date")
                params.append(str(date_from))
            if date_to:
                conditions.append(f"{date_expression} <= %s::date")
                params.append(str(date_to))

        if search_text and search_columns:
            search_term = f"%{search_text.lower()}%"
            clauses = []
            for col in search_columns:
                clauses.append(
                    f"LOWER(COALESCE(CAST({col} AS text), '')) LIKE %s"
                )
                params.append(search_term)
            if clauses:
                conditions.append("(" + " OR ".join(clauses) + ")")

        direction = 'DESC' if str(order_dir).lower().startswith('d') else 'ASC'
        order_expr = self._order_column_expression(order_by)
        cursor_value = self._keyset_sort_value(order_by, after_sort)
        keyset_fragment, keyset_params = self._keyset_condition(
            order_expr, direction, after_id, cursor_value
        )
        if keyset_fragment:
            conditions.append(keyset_fragment)
            params.extend(keyset_params)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        if order_expr:
            query += f" ORDER BY {order_expr} {direction}, id {direction}"
        else:
            query += " ORDER BY id"

        if limit is not None:
            query += " LIMIT %s"
            params.append(int(limit))
            if offset is not None:
                query += " OFFSET %s"
                params.append(int(offset))

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
                SELECT ii.product_id, SUM(ii.quantity) AS quantity
                FROM import_items ii
                JOIN imports i ON i.id = ii.import_id
                WHERE (i.is_historical IS NULL OR NOT i.is_historical)
                GROUP BY ii.product_id
            ) imported ON imported.product_id=p.id
            LEFT JOIN (
                SELECT si.product_id, SUM(si.quantity) AS quantity
                FROM sales_items si
                JOIN sales s ON s.id=si.sales_id
                WHERE (s.state IS NULL OR s.state<>'on_hold')
                  AND (s.is_historical IS NULL OR NOT s.is_historical)
                GROUP BY si.product_id
            ) sold ON sold.product_id=p.id
            """
        )
        return {int(row[0]): row[1] or 0 for row in self.cursor.fetchall()}

    def get_product_stock_levels_for_product_ids(self, product_ids):
        if not product_ids:
            return {}
        self.cursor.execute(
            """
            SELECT p.id,
                   COALESCE(imported.quantity, 0) - COALESCE(sold.quantity, 0)
            FROM products p
            LEFT JOIN (
                SELECT ii.product_id, SUM(ii.quantity) AS quantity
                FROM import_items ii
                JOIN imports i ON i.id = ii.import_id
                WHERE (i.is_historical IS NULL OR NOT i.is_historical)
                GROUP BY ii.product_id
            ) imported ON imported.product_id=p.id
            LEFT JOIN (
                SELECT si.product_id, SUM(si.quantity) AS quantity
                FROM sales_items si
                JOIN sales s ON s.id=si.sales_id
                WHERE (s.state IS NULL OR s.state<>'on_hold')
                  AND (s.is_historical IS NULL OR NOT s.is_historical)
                GROUP BY si.product_id
            ) sold ON sold.product_id=p.id
            WHERE p.id = ANY(%s)
            """,
            (product_ids,)
        )
        return {int(row[0]): row[1] or 0 for row in self.cursor.fetchall()}

    # Canonical stock-affecting Sale predicate. This is the exact condition
    # save_sale_with_items() validates against at write time (and
    # update_product_with_stock() recomputes from): on-hold and historical
    # sales never consume stock. Every stock/history/analytics read path must
    # use this same form so displayed stock always matches validated stock.
    _SALE_STOCK_PREDICATE = (
        "(s.state IS NULL OR s.state<>'on_hold') "
        "AND (s.is_historical IS NULL OR NOT s.is_historical)"
    )
    # Canonical stock-affecting Import predicate: historical imports are
    # books-only records that never add stock.
    _IMPORT_STOCK_PREDICATE = "(i.is_historical IS NULL OR NOT i.is_historical)"

    @staticmethod
    def _clean_decimal_str(value):
        """Render a numeric value as a plain string without trailing zeros
        ('100.000' -> '100', '2.500' -> '2.5'). Never raises."""
        try:
            number = Decimal(str(value if value is not None else 0))
        except Exception:
            return str(value or 0)
        return format(number.normalize(), 'f')

    def get_product_stock_history(
        self, product_id, movement_type='all', date_from=None, date_to=None,
        search=None, limit=500, offset=0,
    ):
        """Return the derived stock-movement ledger for one product.

        Stock in this application is not stored on the product row - it is
        derived from the documents themselves (imports minus sales). This
        method therefore derives the movement history from those same source
        rows with running totals, so it can never disagree with the
        authoritative stock calculation:

        * every non-historical import line is an inbound movement
          ('import', plus 'opening'/'adjustment' for the special
          Opening Stock / Stock Adjustment imports the product dialogs
          create),
        * every line of a non-on_hold, non-historical sale is an outbound
          'sale' movement,
        * services can never appear (only products carry stock).

        Editing a Sale/Import rewrites its lines, so the ledger always shows
        each document's current net effect - the same net-difference rule the
        derived stock itself follows. stock_before/stock_after are computed
        over the FULL unfiltered event stream (window function) before any
        filter is applied, so filtered views stay globally consistent.

        movement_type: 'all' | 'sale' | 'import' | 'adjustment'
        (the adjustment filter includes Opening Stock entries).
        date_from/date_to: inclusive 'YYYY-MM-DD' strings compared against
        each event's effective date.
        search: case-insensitive substring match on reference/note/user.
        """
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            raise ValueError("Product ID must be an integer")
        limit = max(1, min(int(limit), 2000))
        offset = max(0, int(offset))
        movement_type = str(movement_type or 'all').strip().casefold()
        if movement_type not in ('all', 'sale', 'import', 'adjustment'):
            movement_type = 'all'

        type_filter = ""
        if movement_type == 'sale':
            type_filter = "WHERE movement_type = 'sale'"
        elif movement_type == 'import':
            type_filter = "WHERE movement_type IN ('import', 'opening')"
        elif movement_type == 'adjustment':
            type_filter = "WHERE movement_type IN ('adjustment', 'opening')"

        clauses, params = [], []
        if date_from:
            clauses.append("ev_date >= %s")
            params.append(str(date_from))
        if date_to:
            clauses.append("ev_date <= %s")
            params.append(str(date_to))
        if search:
            clauses.append(
                "(reference ILIKE %s OR note ILIKE %s OR username ILIKE %s)"
            )
            like = f"%{search}%"
            params.extend([like, like, like])
        row_filter = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        sql = f"""
            WITH ev AS (
                SELECT ii.id AS event_id,
                       CASE WHEN i.supplier_name = 'Opening Stock'
                            THEN 'opening'
                            WHEN i.supplier_name = 'Stock Adjustment'
                            THEN 'adjustment'
                            ELSE 'import' END AS movement_type,
                       ii.quantity AS delta,
                       COALESCE(NULLIF(BTRIM(i.bl_number), ''),
                                'IMP-' || i.id) AS reference,
                       COALESCE(i.created_by_username, '') AS username,
                       COALESCE(i.notes, '') AS note,
                       COALESCE(NULLIF(BTRIM(i.date), ''),
                                LEFT(COALESCE(i.created_at, ''), 10), '') AS ev_date,
                       COALESCE(i.created_at, '') AS ev_time,
                       0 AS kind_rank
                FROM import_items ii
                JOIN imports i ON i.id = ii.import_id
                WHERE ii.product_id = %s
                  AND {self._IMPORT_STOCK_PREDICATE}
                UNION ALL
                SELECT si.id,
                       'sale',
                       -si.quantity,
                       COALESCE(NULLIF(BTRIM(s.devis), ''),
                                CASE WHEN s.devis_number IS NOT NULL THEN
                                     'DE-' || COALESCE(
                                         NULLIF(SUBSTRING(COALESCE(s.date, '')
                                             FROM '\\d{{4}}'), ''),
                                         NULLIF(SUBSTRING(
                                             COALESCE(s.created_at::text, '')
                                             FROM '\\d{{4}}'), ''),
                                         '0')
                                     || '-' || s.devis_number
                                     ELSE 'V-' || s.id END) AS reference,
                       COALESCE(s.created_by_username, ''),
                       COALESCE(s.notes, ''),
                       COALESCE(NULLIF(BTRIM(s.date), ''),
                                LEFT(COALESCE(s.created_at, ''), 10), ''),
                       COALESCE(s.created_at, ''),
                       1
                FROM sales_items si
                JOIN sales s ON s.id = si.sales_id
                WHERE si.product_id = %s
                  AND {self._SALE_STOCK_PREDICATE}
            ),
            ordered AS (
                SELECT ev.*,
                       SUM(delta) OVER (
                           ORDER BY ev_date, ev_time, kind_rank, event_id
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                       ) AS stock_after
                FROM ev
            ),
            filtered AS (
                SELECT event_id, movement_type, reference, delta,
                       stock_after - delta AS stock_before,
                       stock_after, username, note, ev_date, ev_time,
                       kind_rank
                FROM ordered
                {type_filter}
            )
            SELECT event_id, movement_type, reference, delta,
                   stock_before, stock_after, username, note, ev_date, ev_time,
                   COUNT(*) OVER()
            FROM filtered
            {row_filter}
            ORDER BY ev_date DESC, ev_time DESC, kind_rank DESC, event_id DESC
            LIMIT %s OFFSET %s
        """
        try:
            self.cursor.execute(
                sql, (product_id, product_id, *params, limit, offset)
            )
        except Exception:
            self.conn.rollback()
            raise
        movements = []
        total_count = 0
        for row in self.cursor.fetchall():
            total_count = int(row[10] or 0)
            movements.append({
                "event_id": int(row[0]),
                "movement_type": row[1],
                "reference": row[2] or "",
                "delta": self._clean_decimal_str(row[3]),
                "stock_before": self._clean_decimal_str(row[4]),
                "stock_after": self._clean_decimal_str(row[5]),
                "username": row[6] or "",
                "note": row[7] or "",
                "date": row[8] or "",
                "created_at": row[9] or "",
            })
        levels = self.get_product_stock_levels_for_product_ids([product_id])
        name_row = None
        try:
            self.cursor.execute(
                "SELECT name FROM products WHERE id = %s", (product_id,)
            )
            name_row = self.cursor.fetchone()
        except Exception:
            self.conn.rollback()
        return {
            "product_id": product_id,
            "product_name": (name_row[0] if name_row else "") or "",
            "current_stock": self._clean_decimal_str(levels.get(product_id, 0)),
            "total_count": total_count,
            "movements": movements,
        }

    def get_sale_catalog(self, include_products=True, include_services=True, exclude_sale_id=None,
                          include_clients=False, include_suppliers=False):
        """Return the sale-entry catalog and stock in a small number of queries.

        include_clients/include_suppliers are opt-in and deliberately cheap
        (just username+name, no other columns) - they exist so the New/Edit
        Sale and Import dialogs can prefetch client/supplier existence data
        once, off the GUI thread, instead of firing a live query the moment
        the user clicks Save (see BaseOperationDialog._entity_exists).
        """
        catalog = {"products": [], "services": []}
        if include_products:
            if exclude_sale_id:
                self.cursor.execute(
                    """
                    SELECT p.id, p.name, p.sale_price, p.preview_image,
                           COALESCE(imported.quantity, 0)
                           - COALESCE(sold.quantity, 0) AS stock
                    FROM products p
                    LEFT JOIN (
                        SELECT ii.product_id, SUM(ii.quantity) AS quantity
                        FROM import_items ii
                        JOIN imports i ON i.id = ii.import_id
                        WHERE (i.is_historical IS NULL OR NOT i.is_historical)
                        GROUP BY ii.product_id
                    ) imported ON imported.product_id=p.id
                    LEFT JOIN (
                        SELECT si.product_id, SUM(si.quantity) AS quantity
                        FROM sales_items si
                        JOIN sales s ON s.id=si.sales_id
                        WHERE (s.state IS NULL OR s.state<>'on_hold')
                          AND (s.is_historical IS NULL OR NOT s.is_historical)
                          AND s.id != %s
                        GROUP BY si.product_id
                    ) sold ON sold.product_id=p.id
                    WHERE p.name IS NOT NULL AND p.name<>''
                    ORDER BY LOWER(p.name), p.id
                    """,
                    (exclude_sale_id,)
                )
            else:
                self.cursor.execute(
                    """
                    SELECT p.id, p.name, p.sale_price, p.preview_image,
                           COALESCE(imported.quantity, 0)
                           - COALESCE(sold.quantity, 0) AS stock
                    FROM products p
                    LEFT JOIN (
                        SELECT ii.product_id, SUM(ii.quantity) AS quantity
                        FROM import_items ii
                        JOIN imports i ON i.id = ii.import_id
                        WHERE (i.is_historical IS NULL OR NOT i.is_historical)
                        GROUP BY ii.product_id
                    ) imported ON imported.product_id=p.id
                    LEFT JOIN (
                        SELECT si.product_id, SUM(si.quantity) AS quantity
                        FROM sales_items si
                        JOIN sales s ON s.id=si.sales_id
                        WHERE (s.state IS NULL OR s.state<>'on_hold')
                          AND (s.is_historical IS NULL OR NOT s.is_historical)
                        GROUP BY si.product_id
                    ) sold ON sold.product_id=p.id
                    WHERE p.name IS NOT NULL AND p.name<>''
                    ORDER BY LOWER(p.name), p.id
                    """
                )
            catalog["products"] = [
                {
                    "id": int(row[0]), "name": row[1],
                    "price": str(row[2] or 0), "preview_image": row[3],
                    "stock": str(row[4] or 0),
                }
                for row in self.cursor.fetchall()
            ]
        if include_services:
            self.cursor.execute(
                "SELECT id, name, unit_price, keywords FROM services "
                "WHERE name IS NOT NULL AND name<>'' ORDER BY LOWER(name), id"
            )
            catalog["services"] = [
                {
                    "id": int(row[0]), "name": row[1],
                    "price": str(row[2] or 0), "keywords": row[3] or "",
                }
                for row in self.cursor.fetchall()
            ]
        if include_clients:
            self.cursor.execute(
                "SELECT username, name FROM clients WHERE username IS NOT NULL OR name IS NOT NULL"
            )
            catalog["clients"] = [
                {"username": row[0] or "", "name": row[1] or ""}
                for row in self.cursor.fetchall()
            ]
        if include_suppliers:
            self.cursor.execute(
                "SELECT username, name FROM suppliers WHERE username IS NOT NULL OR name IS NOT NULL"
            )
            catalog["suppliers"] = [
                {"username": row[0] or "", "name": row[1] or ""}
                for row in self.cursor.fetchall()
            ]
        return catalog

    def get_dashboard_snapshot(self):
        """Return dashboard data in three bounded queries for LAN clients."""
        self.cursor.execute(
            """
            SELECT
              (SELECT COALESCE(SUM(si.quantity * si.unit_price), 0)
               FROM sales s JOIN sales_items si ON si.sales_id=s.id
               WHERE (s.state IS NULL OR s.state<>'on_hold')
                 AND LEFT(s.date, 7)=TO_CHAR(CURRENT_DATE, 'YYYY-MM')),
              (SELECT COALESCE(SUM(ii.quantity * ii.unit_price), 0)
               FROM imports i JOIN import_items ii ON ii.import_id=i.id
               WHERE LEFT(i.date, 7)=TO_CHAR(CURRENT_DATE, 'YYYY-MM')),
              (SELECT COUNT(*) FROM products),
              (SELECT COUNT(*) FROM clients),
              (SELECT COUNT(*) FROM suppliers)
            """
        )
        totals = self.cursor.fetchone() or (0, 0, 0, 0, 0)
        self.cursor.execute(
            """
            WITH imported AS (
              SELECT ii.product_id, SUM(ii.quantity) quantity
              FROM import_items ii
              JOIN imports i ON i.id = ii.import_id
              WHERE (i.is_historical IS NULL OR NOT i.is_historical)
              GROUP BY ii.product_id
            ), sold AS (
              SELECT si.product_id, SUM(si.quantity) quantity
              FROM sales_items si JOIN sales s ON s.id=si.sales_id
              WHERE (s.state IS NULL OR s.state<>'on_hold')
                AND (s.is_historical IS NULL OR NOT s.is_historical)
              GROUP BY si.product_id
            ), stock AS (
              SELECT p.name, p.username,
                     COALESCE(imported.quantity,0)-COALESCE(sold.quantity,0) quantity,
                     COALESCE(p.stock_alert,0) alert
              FROM products p
              LEFT JOIN imported ON imported.product_id=p.id
              LEFT JOIN sold ON sold.product_id=p.id
            )
            SELECT name, username, quantity, alert, COUNT(*) OVER()
            FROM stock
            WHERE quantity <= CASE WHEN alert > 0 THEN alert ELSE 5 END
            ORDER BY quantity, name
            LIMIT 50
            """
)
        low_rows = self.cursor.fetchall()
        self.cursor.execute(
            """
            SELECT activity_type, activity_date, amount, description
            FROM (
              SELECT 'Sales' activity_type, s.date activity_date,
                     COALESCE(SUM(si.quantity*si.unit_price),0) amount,
                     'Sale to ' || COALESCE(s.client_username,'') description,
                     s.id
                FROM sales s LEFT JOIN sales_items si ON si.sales_id=s.id
                WHERE s.state IS NULL OR s.state<>'on_hold'
                GROUP BY s.id, s.date, s.client_username
                UNION ALL
                SELECT 'Imports', i.date,
                       COALESCE(SUM(ii.quantity*ii.unit_price),0),
                       'Import from ' || COALESCE(i.supplier_username,''), i.id
                FROM imports i LEFT JOIN import_items ii ON ii.import_id=i.id
                GROUP BY i.id, i.date, i.supplier_username
            ) activity
            ORDER BY activity_date DESC, id DESC
            LIMIT 5
            """
)
        activity_rows = self.cursor.fetchall()
        self.cursor.execute(
            """
            SELECT month_key,
                   COALESCE(SUM(sales_amount),0),
                   COALESCE(SUM(import_amount),0)
            FROM (
              SELECT LEFT(s.date,7) month_key,
                     SUM(si.quantity*si.unit_price) sales_amount,
                     0 import_amount
               FROM sales s JOIN sales_items si ON si.sales_id=s.id
               WHERE (s.state IS NULL OR s.state<>'on_hold')
                 AND LEFT(s.date,7) >= TO_CHAR(CURRENT_DATE-INTERVAL '5 months','YYYY-MM')
               GROUP BY LEFT(s.date,7)
              UNION ALL
              SELECT LEFT(i.date,7), 0,
                     SUM(ii.quantity*ii.unit_price)
               FROM imports i JOIN import_items ii ON ii.import_id=i.id
               WHERE LEFT(i.date,7) >= TO_CHAR(CURRENT_DATE-INTERVAL '5 months','YYYY-MM')
               GROUP BY LEFT(i.date,7)
           ) monthly
           GROUP BY month_key
           ORDER BY month_key
           """
        )
        monthly_rows = self.cursor.fetchall()
        return {
            "sales_total": str(totals[0] or 0),
            "imports_total": str(totals[1] or 0),
            "products_count": int(totals[2] or 0),
            "clients_count": int(totals[3] or 0),
            "suppliers_count": int(totals[4] or 0),
            "low_stock_count": int(low_rows[0][4] if low_rows else 0),
            "low_stock_products": [
                {
                    "name": row[0] or row[1] or "Unknown Product",
                    "username": row[1] or "",
                    "stock": str(row[2] or 0),
                    "alert": str(row[3] or 0),
                }
                for row in low_rows
            ],
            "recent_activities": [
                {
                    "type": row[0], "date": row[1],
                    "amount": str(row[2] or 0), "description": row[3] or "",
                }
                for row in activity_rows
            ],
            "monthly": {
                row[0]: {"sales": str(row[1] or 0), "imports": str(row[2] or 0)}
                for row in monthly_rows
            },
        }

    # ────────────────────────── Profit / Margin engine ──────────────────────
    #
    # Costing method: Weighted Average Cost (WAC) derived from the immutable
    # import_items purchase lines. A product may be purchased at several
    # prices; historical profit must never depend on the product's current
    # editable unit_price. For every sale line, the average cost of all
    # non-historical purchases with an effective date/time at or before that
    # sale line is used:
    #
    #   WAC(t) = SUM(quantity*unit_price of purchases <= t)
    #            / SUM(quantity of purchases <= t)
    #
    # If a sale predates every recorded purchase (legacy data without an
    # opening-stock import), the product's overall average cost is used as a
    # stable fallback; if the product was never purchased at all the COGS
    # contribution is 0 - no value is ever invented.
    #
    # Revenue basis: net HT (excl. VAT). The sale-level remise is allocated
    # proportionally across lines so per-product profit respects discounts.
    # Services contribute revenue but never inventory COGS (services carry no
    # cost field in this application - none is invented).
    #
    # All results are derived from the same immutable document rows the rest
    # of the app uses, so a sale's historical profitability stays stable when
    # product master data changes.

    _ANALYTICS_PURCHASE_EVENTS_SQL = """
        SELECT ii.product_id,
               ii.quantity AS qty,
               ii.quantity * ii.unit_price AS val,
               COALESCE(NULLIF(BTRIM(i.date), ''),
                        LEFT(COALESCE(i.created_at, ''), 10), '') AS ev_date,
               COALESCE(i.created_at, '') AS ev_time,
               ii.id AS event_id
        FROM import_items ii
        JOIN imports i ON i.id = ii.import_id
        WHERE ii.product_id IS NOT NULL
          AND {import_pred}
    """

    _ANALYTICS_SALE_EVENTS_SQL = """
        SELECT si.id AS sale_item_id,
               s.id AS sale_id,
               si.product_id,
               si.service_id,
               si.item_type,
               si.product_name,
               si.quantity AS qty,
               si.quantity * si.unit_price AS gross,
               COALESCE(NULLIF(BTRIM(s.date), ''),
                        LEFT(COALESCE(s.created_at, ''), 10), '') AS ev_date,
               COALESCE(s.created_at, '') AS ev_time,
               si.id AS event_id
        FROM sales_items si
        JOIN sales s ON s.id = si.sales_id
        WHERE (s.state IS NULL OR s.state<>'on_hold')
          AND si.item_type = 'product'
          AND si.product_id IS NOT NULL
    """

    @classmethod
    def _analytics_wac_stream_sql(cls, date_filter_sql=None, sale_id_filter=False):
        """Single-pass weighted-average-cost stream over purchases+sales.

        Purchases sort before sales at identical timestamps (kind_rank), so a
        sale always sees every same-day purchase in its average. Sale rows
        read the running purchase totals BEFORE their own position; they never
        modify them (average-cost method - sales do not layer inventory).

        Every sale row carries its sale-level context (``raw_all`` = gross of
        ALL lines incl. services, ``remise``) so net-of-remise revenue can be
        computed directly from the stream.

        ``date_filter_sql`` optionally scopes sale events to a period using
        two %s placeholders (from/to). ``sale_id_filter=True`` adds one %s
        placeholder restricting the stream to a single sale.
        """
        extra_filters = []
        if date_filter_sql:
            extra_filters.append(f"AND ({date_filter_sql})")
        if sale_id_filter:
            extra_filters.append("AND sal.sale_id = %s")
        filter_sql = " ".join(extra_filters)
        return f"""
            pur AS (
                {cls._ANALYTICS_PURCHASE_EVENTS_SQL.format(
                    import_pred=cls._IMPORT_STOCK_PREDICATE)}
            ),
            sale_agg AS (
                SELECT s.id AS sale_id,
                       COALESCE(SUM(si.quantity * si.unit_price), 0) AS raw_all,
                       COALESCE(MAX(s.remise), 0) AS remise
                FROM sales s JOIN sales_items si ON si.sales_id = s.id
                GROUP BY s.id
            ),
            sal AS (
                {cls._ANALYTICS_SALE_EVENTS_SQL}
            ),
            sal_ctx AS (
                SELECT sal.*, agg.raw_all, agg.remise
                FROM sal JOIN sale_agg agg ON agg.sale_id = sal.sale_id
                WHERE TRUE {filter_sql}
            ),
            events AS (
                SELECT product_id, qty, val,
                       NULL::double precision AS gross,
                       NULL::double precision AS remise,
                       NULL::double precision AS raw_all,
                       NULL::text AS product_name,
                       NULL::bigint AS sale_item_id,
                       NULL::bigint AS sale_id,
                       ev_date, ev_time, 0 AS kind_rank, event_id
                FROM pur
                UNION ALL
                SELECT product_id, qty, NULL::double precision AS val,
                       gross, remise, raw_all, product_name,
                       sale_item_id, sale_id,
                       ev_date, ev_time, 1 AS kind_rank, event_id
                FROM sal_ctx
            ),
            stream AS (
                SELECT events.*,
                    SUM(CASE WHEN kind_rank = 0 THEN qty ELSE 0 END) OVER prev AS p_qty_prev,
                    SUM(CASE WHEN kind_rank = 0 THEN val ELSE 0 END) OVER prev AS p_val_prev
                FROM events
                WINDOW prev AS (
                    PARTITION BY product_id
                    ORDER BY ev_date, ev_time, kind_rank, event_id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                )
            ),
            prod_wac AS (
                SELECT product_id, SUM(qty) AS q, SUM(val) AS v FROM pur GROUP BY product_id
            )
        """

    @staticmethod
    def _user_can(user, section, action='read'):
        return bool((user or {}).get('permissions', {}).get(section, {}).get(action))

    def get_sale_profitability(self, sale_id, user=None):
        """Return internal (never customer-facing) profitability for one Sale.

        Authorization: remote callers need Sales read AND Imports read -
        purchase costs are Imports data and revenue is Sales data. Local host
        calls pass user=None and are fully trusted.
        """
        if user is not None and not user.get('is_superadmin'):
            if not (self._user_can(user, 'Sales') and self._user_can(user, 'Imports')):
                raise PermissionError(
                    "Viewing sale profitability requires Sales and Imports "
                    "read access"
                )
        try:
            sale_id = int(sale_id)
        except (TypeError, ValueError):
            raise ValueError("Sale ID must be an integer")

        self.cursor.execute(
            """
            SELECT id, COALESCE(devis, ''), COALESCE(date, ''),
                   COALESCE(client_name, client_username, ''), COALESCE(remise, 0.0),
                   COALESCE(state, 'pending'),
                   COALESCE(is_historical, FALSE)
            FROM sales WHERE id = %s
            """,
            (sale_id,),
        )
        header_row = self.cursor.fetchone()
        if not header_row:
            raise ValueError(f"Sale {sale_id} does not exist")

        from core.calculations import (
            calculate_operation_totals, to_decimal, round_money,
        )

        sql = f"""
            WITH {self._analytics_wac_stream_sql(sale_id_filter=True)}
            SELECT st.sale_item_id, st.product_name, st.qty, st.gross,
                   CASE WHEN st.raw_all > 0
                        THEN st.gross * (st.raw_all - st.remise) / st.raw_all
                        ELSE st.gross END AS net_revenue,
                   CASE
                     WHEN st.p_qty_prev > 0 THEN st.p_val_prev / st.p_qty_prev
                     WHEN pw.q > 0 THEN pw.v / pw.q
                     ELSE NULL
                   END AS avg_cost
            FROM stream st
            LEFT JOIN prod_wac pw ON pw.product_id = st.product_id
            WHERE st.kind_rank = 1
            ORDER BY st.event_id
        """
        self.cursor.execute(sql, (sale_id,))
        rows = self.cursor.fetchall()

        items = []
        revenue = Decimal("0")
        cogs = Decimal("0")
        service_revenue = Decimal("0")
        for row in rows:
            name = str(row[1] or "")
            qty = to_decimal(row[2])
            gross = to_decimal(row[3])
            net = to_decimal(row[4])
            avg_cost = to_decimal(row[5]) if row[5] is not None else None
            line_cogs = (qty * avg_cost) if avg_cost is not None else Decimal("0")
            items.append({
                "item_type": "product",
                "name": name,
                "quantity": self._clean_decimal_str(qty),
                "unit_price": self._clean_decimal_str(
                    gross / qty if qty else Decimal("0")
                ),
                "gross": str(round_money(gross)),
                "net_revenue": str(round_money(net)),
                "avg_cost": (
                    self._clean_decimal_str(avg_cost)
                    if avg_cost is not None else None
                ),
                "cogs": str(round_money(line_cogs)),
                "profit": str(round_money(net - line_cogs)),
            })
            revenue += net
            cogs += line_cogs

        # Service + manual lines: revenue only, no inventory COGS.
        self.cursor.execute(
            """
            SELECT si.item_type, si.product_name, si.quantity, si.unit_price,
                   si.quantity * si.unit_price,
                   COALESCE(agg.raw_all, 0)
            FROM sales_items si
            JOIN sales s ON s.id = si.sales_id
            LEFT JOIN (
                SELECT s2.id AS sale_id,
                       COALESCE(SUM(si2.quantity * si2.unit_price), 0) AS raw_all
                FROM sales s2 JOIN sales_items si2 ON si2.sales_id = s2.id
                WHERE s2.id = %s GROUP BY s2.id
            ) agg ON agg.sale_id = s.id
            WHERE s.id = %s AND si.item_type <> 'product'
            ORDER BY si.id
            """,
            (sale_id, sale_id),
        )
        for itype, name, qty, unit_price, gross, raw_all in self.cursor.fetchall():
            qty_d = to_decimal(qty)
            gross_d = to_decimal(gross)
            raw_all_d = to_decimal(raw_all)
            remise_d = to_decimal(header_row[4])
            net = (
                gross_d * (raw_all_d - remise_d) / raw_all_d
                if raw_all_d > 0 else gross_d
            )
            items.append({
                "item_type": str(itype or "manual"),
                "name": str(name or ""),
                "quantity": str(qty_d),
                "unit_price": str(to_decimal(unit_price)),
                "gross": str(gross_d),
                "net_revenue": str(net),
                "avg_cost": None,
                "cogs": "0",
                "profit": str(net),
            })
            revenue += net
            service_revenue += net

        gross_profit = revenue - cogs
        margin = (
            str(round_money(gross_profit / revenue * 100))
            if revenue > 0 else None
        )
        totals = calculate_operation_totals(
            sum(to_decimal(i["gross"]) for i in items),
            header_row[4],
        )
        return {
            "sale_id": sale_id,
            "devis": header_row[1],
            "date": header_row[2],
            "client_name": header_row[3],
            "state": header_row[6],
            "is_historical": bool(header_row[7]),
            "total_ttc": str(totals["total_ttc"]),
            "revenue_ht": str(round_money(revenue)),
            "product_revenue_ht": str(round_money(revenue - service_revenue)),
            "service_revenue_ht": str(round_money(service_revenue)),
            "cogs": str(round_money(cogs)),
            "gross_profit": str(round_money(gross_profit)),
            "gross_margin_pct": margin,
            "items": items,
        }

    def get_analytics_snapshot(self, date_from, date_to, user=None):
        """Return the full business-analytics snapshot for an inclusive date
        range in ONE call (a small fixed number of aggregate queries - no
        N+1 patterns).

        ``date_from``/``date_to`` are 'YYYY-MM-DD' strings compared against
        each document's effective date. Receivables/payables/stock metrics are
        current-position values (not period-scoped) and are labelled as such
        by the UI.

        Remote callers receive only the metric groups their role may read
        (mirroring get_dashboard_snapshot's server-side filtering):
        Sales->revenue/profit/top lists, Imports->purchases/COGS,
        Clients->receivables, Suppliers->payables, Products->stock.
        Gross Profit/Margin additionally require BOTH Sales and Imports read.
        """
        date_from = str(date_from or "")
        date_to = str(date_to or "")

        # ---- Period revenue / COGS / profit (single WAC stream pass) -------
        sql = f"""
            WITH {self._analytics_wac_stream_sql(
                date_filter_sql="sal.ev_date >= %s AND sal.ev_date <= %s")}
            SELECT
              COALESCE(SUM(CASE WHEN st.kind_rank = 1 THEN
                  CASE WHEN st.raw_all > 0
                       THEN st.gross * (st.raw_all - st.remise) / st.raw_all
                       ELSE st.gross END END), 0),
              COALESCE(SUM(CASE WHEN st.kind_rank = 1 THEN
                  st.qty * COALESCE(
                      CASE WHEN st.p_qty_prev > 0
                           THEN st.p_val_prev / st.p_qty_prev END,
                      CASE WHEN pw.q > 0 THEN pw.v / pw.q END,
                      0) END), 0)
            FROM stream st
            LEFT JOIN prod_wac pw ON pw.product_id = st.product_id
        """
        self.cursor.execute(sql, (date_from, date_to))
        revenue_raw, cogs_raw = self.cursor.fetchone()

        # Sales count covers every non-on_hold sale in the period (including
        # service-only and manual-line sales, which the product stream skips).
        self.cursor.execute(
            f"""
            SELECT COUNT(*) FROM sales s
            WHERE (s.state IS NULL OR s.state<>'on_hold')
              AND COALESCE(NULLIF(BTRIM(s.date), ''),
                           LEFT(COALESCE(s.created_at, ''), 10), '') >= %s
              AND COALESCE(NULLIF(BTRIM(s.date), ''),
                           LEFT(COALESCE(s.created_at, ''), 10), '') <= %s
            """,
            (date_from, date_to),
        )
        sales_count = self.cursor.fetchone()[0] or 0

        # Service/manual revenue for the period (revenue-only lines).
        self.cursor.execute(
            f"""
            SELECT COALESCE(SUM(
                CASE WHEN agg.raw_all > 0
                     THEN si.quantity * si.unit_price
                          * (agg.raw_all - COALESCE(s.remise, 0.0)) / agg.raw_all
                     ELSE si.quantity * si.unit_price END), 0)
            FROM sales_items si
            JOIN sales s ON s.id = si.sales_id
            JOIN (
                SELECT s2.id AS sale_id,
                       COALESCE(SUM(si2.quantity * si2.unit_price), 0) AS raw_all
                FROM sales s2 JOIN sales_items si2 ON si2.sales_id = s2.id
                WHERE (s2.state IS NULL OR s2.state<>'on_hold')
                GROUP BY s2.id
            ) agg ON agg.sale_id = s.id
            WHERE (s.state IS NULL OR s.state<>'on_hold')
              AND si.item_type <> 'product'
              AND COALESCE(NULLIF(BTRIM(s.date), ''),
                           LEFT(COALESCE(s.created_at, ''), 10), '') >= %s
              AND COALESCE(NULLIF(BTRIM(s.date), ''),
                           LEFT(COALESCE(s.created_at, ''), 10), '') <= %s
            """,
            (date_from, date_to),
        )
        service_revenue_raw = self.cursor.fetchone()[0] or 0

        # ---- Per-period imports total (HT) + count -------------------------
        self.cursor.execute(
            f"""
            SELECT COUNT(DISTINCT i.id),
                   COALESCE(SUM(ii.quantity * ii.unit_price), 0)
            FROM imports i JOIN import_items ii ON ii.import_id = i.id
            WHERE COALESCE(NULLIF(BTRIM(i.date), ''),
                           LEFT(COALESCE(i.created_at, ''), 10), '') >= %s
              AND COALESCE(NULLIF(BTRIM(i.date), ''),
                           LEFT(COALESCE(i.created_at, ''), 10), '') <= %s
            """,
            (date_from, date_to),
        )
        imports_count, purchases_raw = self.cursor.fetchone()

        # ---- Per-period operating charges total (HT) + count ----------------
        self.cursor.execute(
            f"""
            SELECT COUNT(*), COALESCE(SUM(amount), 0)
            FROM charges
            WHERE expense_date >= %s AND expense_date <= %s
            """,
            (date_from, date_to),
        )
        charges_count, charges_total_raw = self.cursor.fetchone()

        # Charges by category for the period
        self.cursor.execute(
            f"""
            SELECT cc.name, COALESCE(SUM(c.amount), 0) as total
            FROM charges c
            JOIN charge_categories cc ON cc.id = c.category_id
            WHERE c.expense_date >= %s AND c.expense_date <= %s
            GROUP BY cc.id, cc.name
            ORDER BY total DESC
            """,
            (date_from, date_to),
        )
        charges_by_category = [
            {"category": r[0] or "", "amount": str(r[1] or 0)}
            for r in self.cursor.fetchall()
        ]

        # ---- Evolution buckets ---------------------------------------------
        span_days = 0
        try:
            from datetime import date as _date
            y0, m0, d0 = (int(x) for x in date_from.split("-"))
            y1, m1, d1 = (int(x) for x in date_to.split("-"))
            span_days = (_date(y1, m1, d1) - _date(y0, m0, d0)).days
        except Exception:
            span_days = 0
        monthly_buckets = span_days > 92
        day_expr = "LEFT(ev_date, 7)" if monthly_buckets else "ev_date"

        evolution_sql = f"""
            WITH {self._analytics_wac_stream_sql(
                date_filter_sql="sal.ev_date >= %s AND sal.ev_date <= %s")},
            profit_lines AS (
                SELECT {day_expr} AS bucket,
                       CASE WHEN st.raw_all > 0
                            THEN st.gross * (st.raw_all - st.remise) / st.raw_all
                            ELSE st.gross END
                       - st.qty * COALESCE(
                             CASE WHEN st.p_qty_prev > 0
                                  THEN st.p_val_prev / st.p_qty_prev END,
                             CASE WHEN pw.q > 0 THEN pw.v / pw.q END,
                             0) AS profit
                FROM stream st
                LEFT JOIN prod_wac pw ON pw.product_id = st.product_id
                WHERE st.kind_rank = 1
            ),
            rev AS (
                SELECT {day_expr} AS bucket, SUM(net) AS revenue FROM (
                    SELECT st.ev_date,
                           CASE WHEN st.raw_all > 0
                                THEN st.gross * (st.raw_all - st.remise) / st.raw_all
                                ELSE st.gross END AS net
                    FROM stream st
                    WHERE st.kind_rank = 1
                ) r GROUP BY 1
            ),
            prof AS (
                SELECT bucket, SUM(profit) AS profit FROM profit_lines GROUP BY 1
            ),
            purch AS (
                SELECT {day_expr.replace('ev_date', 'i_ev')} AS bucket,
                       SUM(val) AS purchases
                FROM (
                    SELECT COALESCE(NULLIF(BTRIM(i.date), ''),
                                    LEFT(COALESCE(i.created_at, ''), 10), '') AS i_ev,
                           ii.quantity * ii.unit_price AS val
                    FROM imports i JOIN import_items ii ON ii.import_id = i.id
                    WHERE COALESCE(NULLIF(BTRIM(i.date), ''),
                                   LEFT(COALESCE(i.created_at, ''), 10), '') >= %s
                      AND COALESCE(NULLIF(BTRIM(i.date), ''),
                                   LEFT(COALESCE(i.created_at, ''), 10), '') <= %s
                ) p GROUP BY 1
            ),
            chrg AS (
                SELECT {day_expr.replace('ev_date', 'c_ev')} AS bucket,
                       SUM(amount) AS charges
                FROM (
                    SELECT COALESCE(NULLIF(BTRIM(expense_date), ''),
                                    LEFT(COALESCE(created_at, ''), 10), '') AS c_ev,
                           amount
                    FROM charges
                    WHERE expense_date >= %s AND expense_date <= %s
                ) c GROUP BY 1
            )
            SELECT COALESCE(rev.bucket, prof.bucket, purch.bucket, chrg.bucket) AS bucket,
                   COALESCE(rev.revenue, 0), COALESCE(prof.profit, 0),
                   COALESCE(purch.purchases, 0), COALESCE(chrg.charges, 0)
            FROM rev
            FULL OUTER JOIN prof ON prof.bucket = rev.bucket
            FULL OUTER JOIN purch ON purch.bucket = COALESCE(rev.bucket, prof.bucket)
            FULL OUTER JOIN chrg ON chrg.bucket = COALESCE(rev.bucket, prof.bucket, purch.bucket)
            ORDER BY 1
        """
        self.cursor.execute(evolution_sql, (date_from, date_to, date_from, date_to, date_from, date_to))
        evolution = [
            {
                "bucket": row[0] or "",
                "revenue": str(row[1] or 0),
                "profit": str(row[2] or 0),
                "purchases": str(row[3] or 0),
                "charges": str(row[4] or 0),
            }
            for row in self.cursor.fetchall()
        ]

        # ---- Top products: selling vs profitable are different rankings ----
        top_sql = f"""
            WITH {self._analytics_wac_stream_sql(
                date_filter_sql="sal.ev_date >= %s AND sal.ev_date <= %s")},
            lines AS (
                SELECT st.product_id,
                       MAX(st.product_name) AS product_name,
                       SUM(st.qty) AS qty,
                       SUM(CASE WHEN st.raw_all > 0
                                THEN st.gross * (st.raw_all - st.remise) / st.raw_all
                                ELSE st.gross END) AS revenue,
                       SUM(st.qty * COALESCE(
                               CASE WHEN st.p_qty_prev > 0
                                    THEN st.p_val_prev / st.p_qty_prev END,
                               CASE WHEN pw.q > 0 THEN pw.v / pw.q END,
                               0)) AS cogs
                FROM stream st
                LEFT JOIN prod_wac pw ON pw.product_id = st.product_id
                WHERE st.kind_rank = 1
                GROUP BY st.product_id
            )
            SELECT product_id, product_name, qty, revenue, cogs
            FROM lines
            ORDER BY {{order}}
            LIMIT 10
        """
        self.cursor.execute(top_sql.format(order="revenue DESC"), (date_from, date_to))
        top_selling = [
            {
                "product_id": int(r[0]), "name": r[1] or "", "qty": str(r[2] or 0),
                "revenue": str(r[3] or 0), "cogs": str(r[4] or 0),
                "profit": str((r[3] or 0) - (r[4] or 0)),
            }
            for r in self.cursor.fetchall()
        ]
        self.cursor.execute(top_sql.format(order="(revenue - cogs) DESC"), (date_from, date_to))
        most_profitable = [
            {
                "product_id": int(r[0]), "name": r[1] or "", "qty": str(r[2] or 0),
                "revenue": str(r[3] or 0), "cogs": str(r[4] or 0),
                "profit": str((r[3] or 0) - (r[4] or 0)),
            }
            for r in self.cursor.fetchall()
        ]

        # ---- Top clients (net HT revenue per client, mirrors account math) --
        self.cursor.execute(
            f"""
            SELECT COALESCE(NULLIF(BTRIM(s.client_name), ''),
                            NULLIF(BTRIM(s.client_username), ''), '') AS cname,
                   COUNT(DISTINCT s.id) AS sales_count,
                   COALESCE(SUM(agg.raw_all - COALESCE(s.remise, 0.0)), 0) AS revenue
            FROM sales s
            JOIN (
                SELECT s2.id AS sale_id,
                       COALESCE(SUM(si2.quantity * si2.unit_price), 0) AS raw_all
                FROM sales s2 JOIN sales_items si2 ON si2.sales_id = s2.id
                WHERE (s2.state IS NULL OR s2.state<>'on_hold')
                GROUP BY s2.id
            ) agg ON agg.sale_id = s.id
            WHERE (s.state IS NULL OR s.state<>'on_hold')
              AND COALESCE(NULLIF(BTRIM(s.date), ''),
                           LEFT(COALESCE(s.created_at, ''), 10), '') >= %s
              AND COALESCE(NULLIF(BTRIM(s.date), ''),
                           LEFT(COALESCE(s.created_at, ''), 10), '') <= %s
            GROUP BY cname
            ORDER BY revenue DESC
            LIMIT 10
            """,
            (date_from, date_to),
        )
        top_clients = [
            {"name": r[0] or "", "sales_count": int(r[1] or 0), "revenue": str(r[2] or 0)}
            for r in self.cursor.fetchall()
        ]

# ---- Client receivables (current position; mirrors
        #      get_client_sale_summaries: Total, paid capped, remaining>=0) ----
        self.cursor.execute(
            """
            WITH sale_raw AS (
                SELECT s.id AS sale_id, s.client_id,
                       COALESCE(NULLIF(BTRIM(s.client_name), ''),
                                NULLIF(BTRIM(s.client_username), ''), '') AS cname,
                       COALESCE(SUM(si.quantity * si.unit_price), 0) AS raw,
                       COALESCE(s.remise, 0.0) AS remise
                FROM sales s LEFT JOIN sales_items si ON si.sales_id = s.id
                GROUP BY s.id, s.client_id,
                         NULLIF(BTRIM(s.client_name), ''),
                         NULLIF(BTRIM(s.client_username), ''),
                         s.remise
            ),
ttc AS (
                SELECT sale_id, client_id, cname,
                       ROUND(ROUND(raw::numeric, 2) - ROUND(remise::numeric, 2), 2) AS total
                FROM sale_raw
            ),
            paid AS (
                SELECT sale_id, SUM(amount)::numeric AS amt
                FROM payments WHERE sale_id IS NOT NULL GROUP BY sale_id
            ),
            remaining AS (
                SELECT t.client_id, t.cname,
                       GREATEST(t.total - LEAST(COALESCE(p.amt, 0), t.total), 0)
                           AS remaining
                FROM ttc t LEFT JOIN paid p ON p.sale_id = t.sale_id
            )
            SELECT COALESCE(SUM(remaining), 0),
                   COUNT(*) FILTER (WHERE remaining > 0),
                   COUNT(*) FILTER (WHERE client_id IS NOT NULL)
           FROM remaining
           """
       )
        receivables_total, receivables_clients, _total_client_rows = \
            self.cursor.fetchone()
        self.cursor.execute(
            """
            WITH sale_raw AS (
                SELECT s.id AS sale_id, s.client_id,
                       COALESCE(NULLIF(BTRIM(s.client_name), ''),
                                NULLIF(BTRIM(s.client_username), ''), '') AS cname,
                       COALESCE(SUM(si.quantity * si.unit_price), 0) AS raw,
                       COALESCE(s.remise, 0.0) AS remise
                FROM sales s LEFT JOIN sales_items si ON si.sales_id = s.id
                GROUP BY s.id, s.client_id,
                         NULLIF(BTRIM(s.client_name), ''),
                         NULLIF(BTRIM(s.client_username), ''),
                         s.remise
            ),
            ttc AS (
                SELECT sale_id, client_id, cname,
                       ROUND(ROUND(raw::numeric, 2) - ROUND(remise::numeric, 2), 2) AS total
                FROM sale_raw
            ),
            paid AS (
                SELECT sale_id, SUM(amount)::numeric AS amt
                FROM payments WHERE sale_id IS NOT NULL GROUP BY sale_id
            )
            SELECT cname, GREATEST(t.total - LEAST(COALESCE(p.amt, 0), t.total), 0)
                   AS remaining
            FROM ttc t LEFT JOIN paid p ON p.sale_id = t.sale_id
            WHERE t.client_id IS NOT NULL
            ORDER BY remaining DESC
            LIMIT 64
            """
        )
        debtor_rows = [
            [r[0] or "", r[1]] for r in self.cursor.fetchall() if (r[1] or 0) > 0
        ]
        # Aggregate the per-sale rows into per-client balances client-side
        # (bounded by LIMIT 64 above to keep the payload small).
        debt_by_client = {}
        for cname, remaining in debtor_rows:
            key = cname or "Unknown"
            debt_by_client[key] = debt_by_client.get(key, 0) + (remaining or 0)
        top_debtors = sorted(
            (
                [{"name": k, "balance": str(v)}
                 for k, v in debt_by_client.items()]
            ),
            key=lambda d: float(d["balance"] or 0), reverse=True,
        )[:10]

        # ---- Supplier payables (current position; mirrors
        #      get_supplier_import_summaries) ---------------------------------
        self.cursor.execute(
            """
            WITH imp_raw AS (
                SELECT i.id AS import_id, i.supplier_id,
                       COALESCE(NULLIF(BTRIM(i.supplier_name), ''),
                                NULLIF(BTRIM(i.supplier_username), ''), '') AS sname,
                       COALESCE(SUM(ii.quantity * ii.unit_price), 0) AS raw
                FROM imports i LEFT JOIN import_items ii ON ii.import_id = i.id
                GROUP BY i.id, i.supplier_id,
                         NULLIF(BTRIM(i.supplier_name), ''),
                         NULLIF(BTRIM(i.supplier_username), '')
            ),
            ttc AS (
                SELECT import_id, supplier_id, sname,
                       ROUND(raw::numeric, 2) AS total
                FROM imp_raw
            ),
            paid AS (
                SELECT import_id, SUM(amount)::numeric AS amt
                FROM payments WHERE import_id IS NOT NULL GROUP BY import_id
            )
            SELECT COALESCE(SUM(GREATEST(
                       t.total - LEAST(COALESCE(p.amt, 0), t.total), 0)), 0),
                   COUNT(*) FILTER (WHERE
                       GREATEST(t.total - LEAST(COALESCE(p.amt, 0), t.total), 0) > 0)
            FROM ttc t LEFT JOIN paid p ON p.import_id = t.import_id
            """
        )
        payables_total, payables_suppliers = self.cursor.fetchone()
        self.cursor.execute(
            """
            WITH imp_raw AS (
                SELECT i.id AS import_id, i.supplier_id,
                       COALESCE(NULLIF(BTRIM(i.supplier_name), ''),
                                NULLIF(BTRIM(i.supplier_username), ''), '') AS sname,
                       COALESCE(SUM(ii.quantity * ii.unit_price), 0) AS raw
                FROM imports i LEFT JOIN import_items ii ON ii.import_id = i.id
                GROUP BY i.id, i.supplier_id,
                         NULLIF(BTRIM(i.supplier_name), ''),
                         NULLIF(BTRIM(i.supplier_username), '')
            ),
            ttc AS (
                SELECT import_id, supplier_id, sname,
                       ROUND(raw::numeric, 2) AS total
                FROM imp_raw
            ),
            paid AS (
                SELECT import_id, SUM(amount)::numeric AS amt
                FROM payments WHERE import_id IS NOT NULL GROUP BY import_id
            )
            SELECT sname, GREATEST(t.total - LEAST(COALESCE(p.amt, 0), t.total), 0)
                   AS remaining
            FROM ttc t LEFT JOIN paid p ON p.import_id = t.import_id
            WHERE t.supplier_id IS NOT NULL
            ORDER BY remaining DESC
            LIMIT 64
            """
        )
        credit_by_supplier = {}
        for sname, remaining in self.cursor.fetchall():
            if (remaining or 0) > 0:
                key = sname or "Unknown"
                credit_by_supplier[key] = credit_by_supplier.get(key, 0) + (remaining or 0)
        top_creditors = sorted(
            ({"name": k, "balance": str(v)} for k, v in credit_by_supplier.items()),
            key=lambda d: float(d["balance"] or 0), reverse=True,
        )[:10]

        # ---- Current stock value + alerts (Products only, never services) ---
        self.cursor.execute(
            f"""
            WITH imported AS (
                SELECT ii.product_id, SUM(ii.quantity) AS quantity
                FROM import_items ii JOIN imports i ON i.id = ii.import_id
                WHERE ii.product_id IS NOT NULL AND {self._IMPORT_STOCK_PREDICATE}
                GROUP BY ii.product_id
            ),
            sold AS (
                SELECT si.product_id, SUM(si.quantity) AS quantity
                FROM sales_items si JOIN sales s ON s.id = si.sales_id
                WHERE si.product_id IS NOT NULL AND {self._SALE_STOCK_PREDICATE}
                GROUP BY si.product_id
            ),
            stock AS (
                SELECT p.id, p.name, p.username, COALESCE(p.stock_alert, 0) AS alert,
                       p.unit_price, p.sale_price,
                       COALESCE(imp.quantity, 0) - COALESCE(sol.quantity, 0) AS qty
                FROM products p
                LEFT JOIN imported imp ON imp.product_id = p.id
                LEFT JOIN sold sol ON sol.product_id = p.id
            ),
            wac AS (
                SELECT ii.product_id,
                       SUM(ii.quantity) AS q,
                       SUM(ii.quantity * ii.unit_price) AS v
                FROM import_items ii JOIN imports i ON i.id = ii.import_id
                WHERE ii.product_id IS NOT NULL AND {self._IMPORT_STOCK_PREDICATE}
                GROUP BY ii.product_id
            )
            SELECT
              COALESCE(SUM(CASE WHEN s.qty > 0
                  THEN s.qty * COALESCE(w.v / NULLIF(w.q, 0), 0) END), 0),
              COALESCE(SUM(CASE WHEN s.qty > 0
                  THEN s.qty * COALESCE(s.sale_price, 0) END), 0),
              COALESCE(SUM(CASE WHEN s.qty > 0
                  THEN s.qty * COALESCE(s.sale_price - s.unit_price, 0) END), 0),
              COUNT(*) FILTER (WHERE s.qty > 0
                  AND s.qty <= CASE WHEN s.alert > 0 THEN s.alert ELSE 5 END),
              COUNT(*) FILTER (WHERE s.qty <= 0)
            FROM stock s LEFT JOIN wac w ON w.product_id = s.id
            """
        )
        stock_value_raw, total_stock_sale_value_raw, potential_stock_profit_raw, low_stock_count, out_of_stock_count = self.cursor.fetchone()
        self.cursor.execute(
            f"""
            WITH imported AS (
                SELECT ii.product_id, SUM(ii.quantity) AS quantity
                FROM import_items ii JOIN imports i ON i.id = ii.import_id
                WHERE ii.product_id IS NOT NULL AND {self._IMPORT_STOCK_PREDICATE}
                GROUP BY ii.product_id
            ),
            sold AS (
                SELECT si.product_id, SUM(si.quantity) AS quantity
                FROM sales_items si JOIN sales s ON s.id = si.sales_id
                WHERE si.product_id IS NOT NULL AND {self._SALE_STOCK_PREDICATE}
                GROUP BY si.product_id
            )
            SELECT p.id, p.name, p.username,
                   COALESCE(imp.quantity, 0) - COALESCE(sol.quantity, 0) AS qty,
                   COALESCE(p.stock_alert, 0) AS alert
            FROM products p
            LEFT JOIN imported imp ON imp.product_id = p.id
            LEFT JOIN sold sol ON sol.product_id = p.id
            WHERE COALESCE(imp.quantity, 0) - COALESCE(sol.quantity, 0)
                  <= CASE WHEN COALESCE(p.stock_alert, 0) > 0
                          THEN p.stock_alert ELSE 5 END
            ORDER BY 4, p.name
            LIMIT 50
            """
        )
        low_stock_products = [
            {
                "product_id": int(r[0]),
                "name": r[1] or r[2] or "Unknown Product",
                "username": r[2] or "",
                "stock": str(r[3] or 0),
                "alert": str(r[4] or 0),
            }
            for r in self.cursor.fetchall()
        ]

        snapshot = {
            "period": {"from": date_from, "to": date_to},
            "sales_count": int(sales_count or 0),
            "imports_count": int(imports_count or 0),
            "revenue_total": str(revenue_raw or 0),
            "product_revenue": str((revenue_raw or 0) - (service_revenue_raw or 0)),
            "service_revenue": str(service_revenue_raw or 0),
            "cogs_total": str(cogs_raw or 0),
            "gross_profit": str((revenue_raw or 0) - (cogs_raw or 0)),
            "gross_margin_pct": (
                str(round(
                    (float(revenue_raw) - float(cogs_raw or 0))
                    / float(revenue_raw) * 100, 2))
                if (revenue_raw or 0) > 0 else None
            ),
            "purchases_total": str(purchases_raw or 0),
            "charges_total": str(charges_total_raw or 0),
            "charges_count": int(charges_count or 0),
            "charges_by_category": charges_by_category,
            "net_profit": str((revenue_raw or 0) - (cogs_raw or 0) - (charges_total_raw or 0)),
            "net_margin_pct": (
                str(round(
                    (float(revenue_raw) - float(cogs_raw or 0) - float(charges_total_raw or 0))
                    / float(revenue_raw) * 100, 2))
                if (revenue_raw or 0) > 0 else None
            ),
            "purchases_total": str(purchases_raw or 0),
            "receivables_total": str(receivables_total or 0),
            "receivables_clients": int(receivables_clients or 0),
            "top_debtors": top_debtors,
            "payables_total": str(payables_total or 0),
            "payables_suppliers": int(payables_suppliers or 0),
            "top_creditors": top_creditors,
            "stock_value": str(stock_value_raw or 0),
            "total_stock_sale_value": str(total_stock_sale_value_raw or 0),
            "potential_stock_profit": str(potential_stock_profit_raw or 0),
            "low_stock_count": int(low_stock_count or 0),
            "out_of_stock_count": int(out_of_stock_count or 0),
            "low_stock_products": low_stock_products,
            "evolution": evolution,
            "top_selling_products": top_selling,
            "most_profitable_products": most_profitable,
            "top_clients": top_clients,
            "charges_by_category": charges_by_category,
            "bucket_mode": "month" if monthly_buckets else "day",
        }

        # Server-side permission filtering (remote callers only): strip every
        # group the caller's role may not read. Unauthorized clients can never
        # pull sensitive financial data through RPC.
        if user is not None and not user.get('is_superadmin'):
            scalar_keys = (
                'sales_count', 'imports_count', 'revenue_total', 'product_revenue',
                'service_revenue', 'cogs_total', 'gross_profit', 'gross_margin_pct',
                'purchases_total', 'charges_total', 'charges_count', 'net_profit',
                'net_margin_pct', 'receivables_total', 'receivables_clients',
                'payables_total', 'payables_suppliers', 'stock_value',
                'total_stock_sale_value', 'potential_stock_profit',
                'low_stock_count', 'out_of_stock_count',
            )
            list_keys = (
                'top_debtors', 'top_creditors', 'low_stock_products',
                'top_selling_products', 'most_profitable_products', 'top_clients',
                'charges_by_category',
            )

            def _strip(keys):
                for key in keys:
                    snapshot[key] = [] if key in list_keys else None

            can_sales = self._user_can(user, 'Sales')
            can_imports = self._user_can(user, 'Imports')
            if not can_sales:
                _strip((
                    'sales_count', 'revenue_total', 'product_revenue',
                    'service_revenue', 'top_selling_products',
                    'most_profitable_products', 'top_clients',
                ))
                snapshot['evolution'] = [
                    {**row, "revenue": None, "profit": None}
                    for row in snapshot['evolution']
                ]
            if not (can_sales and can_imports):
                _strip(('cogs_total', 'gross_profit', 'gross_margin_pct'))
                snapshot['evolution'] = [
                    {**row, "profit": None} for row in snapshot['evolution']
                ]
            if not can_imports:
                _strip(('purchases_total', 'imports_count'))
                snapshot['evolution'] = [
                    {**row, "purchases": None} for row in snapshot['evolution']
                ]
            can_charges = self._user_can(user, 'Charges')
            if not can_charges:
                _strip(('charges_total', 'charges_count', 'charges_by_category'))
                snapshot['evolution'] = [
                    {**row, "charges": None} for row in snapshot['evolution']
                ]
            if not (can_sales and can_imports and can_charges):
                _strip(('net_profit', 'net_margin_pct'))
            if not self._user_can(user, 'Clients'):
                _strip(('receivables_total', 'receivables_clients', 'top_debtors'))
            if not self._user_can(user, 'Suppliers'):
                _strip(('payables_total', 'payables_suppliers', 'top_creditors'))
            if not self._user_can(user, 'Products'):
                _strip((
                    'stock_value', 'total_stock_sale_value', 'potential_stock_profit',
                    'low_stock_count', 'out_of_stock_count',
                    'low_stock_products',
                ))
        return snapshot

    def get_operation_items_for_user(self, operation_id, section, user):
        return self.get_items_by_operation_id(operation_id, section)

    def list_report_users(self):
        self.cursor.execute(
            "SELECT id, username FROM users ORDER BY LOWER(username), id"
        )
        return [{"id": int(row[0]), "username": row[1]} for row in self.cursor.fetchall()]

    def get_reports(
        self, owner_id=None, date_from=None, date_to=None, report_type=None,
        search_text=None, search_columns=None, order_by=None, order_dir='asc',
        limit=None, offset=None, after_id=None, after_sort=None,
    ):
        return self.get_items_for_user(
            "Reports",
            {"is_superadmin": True, "username": "Local Admin"},
            owner_id,
            date_from,
            date_to,
            report_type,
            search_text=search_text,
            search_columns=search_columns,
            order_by=order_by,
            order_dir=order_dir,
            limit=limit,
            offset=offset,
            after_id=after_id,
            after_sort=after_sort,
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
            self.record_change(
                'Reports', int(saved_id), 'upsert',
                self._row_snapshot('Reports', int(saved_id)),
            )
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
        self.record_change('Reports', int(report_id), 'delete', None)
        return True

    def get_items_by_operation_ids(self, operation_ids, section):
        """Get items for multiple operations (Sales_Items or Import_Items) in bulk"""
        if not self.cursor or section not in self.registered_classes or not operation_ids:
            return {}

        try:
            # Determine the foreign key column name based on section
            if section == 'Sales_Items':
                fk_column = 'sales_id'
            elif section == 'Import_Items':
                fk_column = 'import_id'
            else:
                print(f"Unknown item section: {section}")
                return {}

            format_strings = ','.join(['%s'] * len(operation_ids))
            self.cursor.execute(f"SELECT * FROM {section} WHERE {fk_column} IN ({format_strings})", tuple(operation_ids))
            rows = self.cursor.fetchall()

            columns = [description[0] for description in self.cursor.description]
            if columns and columns[0].lower() == 'id':
                columns[0] = 'ID'

            result = {op_id: [] for op_id in operation_ids}
            for row in rows:
                item = dict(zip(columns, row))
                op_id = item.get(fk_column)
                if op_id in result:
                    result[op_id].append(item)
                    
            return result

        except Exception as e:
            print(f"Error getting bulk items from {section}: {e}")
            return {}

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

        Sales are company-wide data, not per-creator data: the main Sales tab
        (get_items_for_user) never filters Sales/Sales_Items by created_by -
        only Reports gets that treatment. This method must return the exact
        same authorized Sales, so it does not filter by created_by either;
        access is controlled solely by the Clients:read permission check the
        LAN server already enforces before calling this method.
        """
        client_id = int(client_id)
        mode = 'remote' if user is not None else 'local'
        user_id = user.get('id') if user else None
        role_id = user.get('role_id') if user else None
        self.cursor.execute("SELECT id, username FROM clients WHERE id = %s", (client_id,))
        client_row = self.cursor.fetchone()
        if not client_row:
            logger.warning(
                "get_client_account: client not found client_id=%s mode=%s user_id=%s",
                client_id, mode, user_id,
            )
            raise ValueError(f"Client {client_id} does not exist")
        norm = self._normalize_exact(client_row[1]) if client_row[1] else None

        # Match by client_id as well as by the client's username against
        # sales.client_username: a sale's client_id can get zeroed out
        # independently of its client_name/client_username snapshot (e.g.
        # when the linked client record was temporarily unresolved) while
        # still belonging to this client. Matching only one of the two hides
        # real sales - see get_client_sales() for the same pattern.
        if norm:
            match_clause = (
                "(s.client_id=%s OR "
                "LOWER(REGEXP_REPLACE(BTRIM(COALESCE(s.client_username, '')), '\\s+', ' ', 'g')) = LOWER(%s))"
            )
            match_params = [client_id, norm]
        else:
            match_clause = "s.client_id=%s"
            match_params = [client_id]

        sql = (
            "SELECT s.id, COALESCE(s.date, ''), COALESCE(s.state, 'pending'), "
            "si.id, COALESCE(si.product_name, ''), COALESCE(si.quantity, 0), "
            "COALESCE(si.unit_price, 0), "
            "COALESCE(s.remise, 0.0), "
            "COALESCE(si.information, ''), COALESCE(si.production, 0), "
            "COALESCE(s.notes, ''), COALESCE(s.is_historical, FALSE), "
            "COALESCE(s.created_by_username, '') "
            "FROM sales s JOIN sales_items si ON si.sales_id = s.id "
            f"WHERE {match_clause} ORDER BY s.id, si.id"
        )
        self.cursor.execute(sql, tuple(match_params))
        purchase_rows = self.cursor.fetchall()
        sale_ids = sorted({row[0] for row in purchase_rows})
        payment_rows = []
        if sale_ids:
            self.cursor.execute(
                """
                SELECT p.id, p.sale_id, p.sales_item_id, p.date, p.amount
                FROM payments p
                WHERE p.sale_id = ANY(%s) OR (p.sale_id IS NULL AND p.import_id IS NULL)
                ORDER BY p.id DESC
                """,
                (sale_ids,),
            )
            payment_rows = self.cursor.fetchall()
        else:
            self.cursor.execute(
                """
                SELECT p.id, p.sale_id, p.sales_item_id, p.date, p.amount
                FROM payments p
                WHERE p.sale_id IS NULL AND p.import_id IS NULL
                ORDER BY p.id DESC
                """,
            )
            payment_rows = self.cursor.fetchall()

        logger.info(
            "get_client_account: mode=%s user_id=%s role_id=%s client_id=%s "
            "sql_params=%s sale_count=%s item_rows=%s payment_count=%s",
            mode, user_id, role_id, client_id, match_params,
            len(sale_ids), len(purchase_rows), len(payment_rows),
        )
        # Canonical named schema - see normalize_client_account() above.
        return normalize_client_account(purchase_rows, payment_rows)

    def get_client_sale_summaries(self, client_id, user=None):
        """Return one row per Sale (never one per item) plus payment history.

        The Sales History table only needs sale-level facts - Sale #, date,
        Devis, status and the financial block - so this method aggregates the
        sale items instead of downloading them. Per-Sale TTC uses the same
        central formulas as the Client Account dialog and ``paid`` is capped at
        the sale total so an overpayment can never push it past Total.

        Devis numbers are assigned and persisted before returning: a sale can
        be created after the last host-startup backfill and must still show a
        stable, sequential, per-year reference across refreshes and printing.
        """
        client_id = int(client_id)
        mode = 'remote' if user is not None else 'local'
        user_id = user.get('id') if user else None
        role_id = user.get('role_id') if user else None
        self.cursor.execute(
            "SELECT id, username FROM clients WHERE id = %s", (client_id,)
        )
        client_row = self.cursor.fetchone()
        if not client_row:
            logger.warning(
                "get_client_sale_summaries: client not found client_id=%s "
                "mode=%s user_id=%s",
                client_id, mode, user_id,
            )
            raise ValueError(f"Client {client_id} does not exist")
        norm = self._normalize_exact(client_row[1]) if client_row[1] else None
        if norm:
            match_clause = (
                "(s.client_id=%s OR "
                "LOWER(REGEXP_REPLACE(BTRIM(COALESCE(s.client_username, '')), '\\s+', ' ', 'g')) = LOWER(%s))"
            )
            match_params = [client_id, norm]
        else:
            match_clause = "s.client_id=%s"
            match_params = [client_id]

        sql = (
            f"SELECT s.id, COALESCE(s.date, ''), COALESCE(s.state, 'pending'), "
            f"COALESCE(s.is_historical, FALSE), "
            f"COALESCE(NULLIF(BTRIM(s.devis), ''), ''), s.devis_number, "
            f"{_DEVIS_YEAR_EXPR} AS devis_year, "
            f"{_DEVIS_YEAR_EXPR} AS year, "
            f"COALESCE(s.remise, 0.0), "
            f"COALESCE(SUM(si.quantity * si.unit_price), 0) "
            f"FROM sales s LEFT JOIN sales_items si ON si.sales_id = s.id "
            f"WHERE {match_clause} "
            f"GROUP BY s.id, s.date, s.state, s.is_historical, s.devis, "
            f"s.devis_number, "
            f"devis_year, year, s.remise, s.created_at "
            f"ORDER BY s.id"
        )
        self.cursor.execute(sql, tuple(match_params))
        rows = self.cursor.fetchall()

        # Persist missing Devis numbers/text (a sale may have been created
        # after the last startup backfill), then re-read so every returned
        # summary has a stable reference.
        missing_num = [row[0] for row in rows if row[5] is None]
        missing_text = [
            row[0] for row in rows
            if not (row[4] or "").strip() and row[5] is not None
        ]
        if missing_num:
            self._ensure_devis_numbers(missing_num)
        if missing_num or missing_text:
            self._ensure_devis_text(missing_num + missing_text)
            self.cursor.execute(sql, tuple(match_params))
            rows = self.cursor.fetchall()

        from core.calculations import calculate_operation_totals, to_decimal
        sale_rows = []
        for row in rows:
            sale_id, date, state, is_hist, devis_text, devis_number, year, devis_year, remise, raw = row
            total = calculate_operation_totals(
                to_decimal(raw), to_decimal(remise)
            )["total"]
            if devis_text:
                devis = devis_text
            elif devis_number is not None:
                devis = f"DE-{year}-{devis_number}"
            else:
                devis = f"DE-{year}-"
            sale_rows.append([
                sale_id, date, state, is_hist, devis, total,
                Decimal("0"), Decimal("0"),
            ])

        payment_rows = []
        if sale_rows:
            self.cursor.execute(
                """
                SELECT p.id, p.sale_id, p.sales_item_id, p.date, p.amount
                FROM payments p
                WHERE p.sale_id = ANY(%s) OR (p.sale_id IS NULL AND p.import_id IS NULL)
                ORDER BY p.id DESC
                """,
                ([sale[0] for sale in sale_rows],),
            )
            payment_rows = self.cursor.fetchall()
        else:
            self.cursor.execute(
                """
                SELECT p.id, p.sale_id, p.sales_item_id, p.date, p.amount
                FROM payments p
                WHERE p.sale_id IS NULL AND p.import_id IS NULL
                ORDER BY p.id DESC
                """,
            )
            payment_rows = self.cursor.fetchall()

        paid_by_sale = {}
        for row in payment_rows:
            paid_by_sale[row[1]] = paid_by_sale.get(row[1], Decimal("0")) + to_decimal(
                row[4]
            )
        for sale in sale_rows:
            total = sale[5]
            paid = min(paid_by_sale.get(sale[0], Decimal("0")), total)
            sale[6] = paid
            sale[7] = max(total - paid, Decimal("0"))

        logger.info(
            "get_client_sale_summaries: mode=%s user_id=%s role_id=%s client_id=%s "
            "sale_count=%s payment_count=%s",
            mode, user_id, role_id, client_id, len(sale_rows), len(payment_rows),
        )
        return normalize_client_sale_summaries(sale_rows, payment_rows)

    def get_client_sale_items(self, sale_id, user=None):
        """Return one Sale's item rows + its payments (for single-sale PDFs).

        The Sales History table never calls this - only the "Print Selected
        Sale" report path needs the item-level detail. Returns the canonical
        purchase rows (same named fields as ``get_client_account``) plus the
        sale's payments and a tiny sale block carrying the Devis reference.
        """
        sale_id = int(sale_id)
        mode = 'remote' if user is not None else 'local'
        user_id = user.get('id') if user else None
        role_id = user.get('role_id') if user else None

        sql = (
            "SELECT s.id, COALESCE(s.date, ''), COALESCE(s.state, 'pending'), "
            "si.id, COALESCE(si.product_name, ''), COALESCE(si.quantity, 0), "
            "COALESCE(si.unit_price, 0), "
            "COALESCE(s.remise, 0.0), "
            "COALESCE(si.information, ''), COALESCE(si.production, 0), "
            "COALESCE(s.notes, ''), COALESCE(s.is_historical, FALSE), "
            "COALESCE(s.created_by_username, '') "
            "FROM sales s JOIN sales_items si ON si.sales_id = s.id "
            "WHERE s.id = %s ORDER BY si.id"
        )
        self.cursor.execute(sql, (sale_id,))
        purchase_rows = self.cursor.fetchall()

        self.cursor.execute(
            """
            SELECT p.id, p.sale_id, p.sales_item_id, p.date, p.amount
            FROM payments p
            WHERE p.sale_id = %s
            ORDER BY p.id DESC
            """,
            (sale_id,),
        )
        payment_rows = self.cursor.fetchall()

        # Sale-level block (Devis reference) used by the print worker.
        self.cursor.execute(
            f"""
            SELECT s.id, COALESCE(s.date, ''), COALESCE(s.state, 'pending'),
                   COALESCE(s.is_historical, FALSE),
                   COALESCE(NULLIF(BTRIM(s.devis), ''), ''), s.devis_number,
                   {_DEVIS_YEAR_EXPR} AS devis_year
            FROM sales s
            WHERE s.id = %s
            """,
            (sale_id,),
        )
        sale_row = self.cursor.fetchone()
        sale_block = []
        if sale_row:
            if sale_row[5] is None or not (sale_row[4] or "").strip():
                self._ensure_devis_numbers([sale_row[0]])
                self._ensure_devis_text([sale_row[0]])
                self.cursor.execute(
                    f"""
                    SELECT s.id, COALESCE(s.date, ''), COALESCE(s.state, 'pending'),
                           COALESCE(s.is_historical, FALSE),
                           COALESCE(NULLIF(BTRIM(s.devis), ''), ''), s.devis_number,
                           {_DEVIS_YEAR_EXPR} AS devis_year
                    FROM sales s
                    WHERE s.id = %s
                    """,
                    (sale_id,),
                )
                sale_row = self.cursor.fetchone()
            if sale_row:
                devis_text, devis_number, year = sale_row[4], sale_row[5], sale_row[6]
                if devis_text:
                    devis = devis_text
                elif devis_number is not None:
                    devis = f"DE-{year}-{devis_number}"
                else:
                    devis = f"DE-{year}-"
                sale_block = [{
                    "sale_id": sale_row[0],
                    "date": sale_row[1],
                    "state": sale_row[2],
                    "is_historical": sale_row[3],
                    "devis": devis,
                }]

        logger.info(
            "get_client_sale_items: mode=%s user_id=%s role_id=%s sale_id=%s "
            "item_rows=%s payment_count=%s",
            mode, user_id, role_id, sale_id, len(purchase_rows), len(payment_rows),
        )
        return {
            "purchases": [
                dict(zip(CLIENT_ACCOUNT_PURCHASE_FIELDS, row)) for row in purchase_rows
            ],
            "payments": [
                dict(zip(CLIENT_ACCOUNT_PAYMENT_FIELDS, row)) for row in payment_rows
            ],
            "sales": sale_block,
        }

    def get_client_sales(self, client_id, user=None):
        """Return aggregate sale rows for a client through an ownership-safe API.

        Matches sales both by client_id and by the client's username against
        sales.client_username, since a sale's client_id can get zeroed out
        independently of its client_name snapshot (e.g. when the linked
        client record is temporarily unresolved) while still belonging to
        this client. Matching only one of the two hides real sales.

        Sales are company-wide data, not per-creator data: the main Sales tab
        (get_items_for_user) never filters Sales/Sales_Items by created_by -
        only Reports gets that treatment. This method must return the exact
        same authorized Sales as that tab, so it does not filter by
        created_by either; access is controlled solely by the Clients:read
        permission check the LAN server already enforces before calling this
        method.
        """
        client_id = int(client_id)
        mode = 'remote' if user is not None else 'local'
        user_id = user.get('id') if user else None
        role_id = user.get('role_id') if user else None

        self.cursor.execute("SELECT username FROM clients WHERE id=%s", (client_id,))
        cres = self.cursor.fetchone()
        username = str(cres[0] or '').strip() if cres else ''
        norm = self._normalize_exact(username) if username else None

        if norm:
            match_clause = (
                "(s.client_id=%s OR "
                "LOWER(REGEXP_REPLACE(BTRIM(COALESCE(s.client_username, '')), '\\s+', ' ', 'g')) = LOWER(%s))"
            )
            params = [client_id, norm]
        else:
            match_clause = "s.client_id=%s"
            params = [client_id]

        sql = (
            "SELECT s.id, COALESCE(s.notes, ''), COALESCE(s.date, ''), "
            "COALESCE(SUM(si.quantity * si.unit_price), 0) AS subtotal "
            "FROM sales s LEFT JOIN sales_items si ON si.sales_id=s.id "
            f"WHERE {match_clause} GROUP BY s.id, s.notes, s.date ORDER BY s.date DESC, s.id DESC"
        )
        try:
            self.cursor.execute(sql, params)
            rows = [list(row) for row in self.cursor.fetchall()]
        except Exception:
            logger.exception(
                "get_client_sales failed: mode=%s user_id=%s role_id=%s client_id=%s sql_params=%s",
                mode, user_id, role_id, client_id, params,
            )
            try:
                self.conn.rollback()
            except Exception:
                logger.exception("get_client_sales: rollback after failed query also failed")
            raise

        logger.info(
            "get_client_sales: mode=%s user_id=%s role_id=%s client_id=%s "
            "sql_params=%s sale_count=%s",
            mode, user_id, role_id, client_id, params, len(rows),
        )
        return rows

    def add_client_payment(
        self, client_id, sale_id, sales_item_id, amount, date, user=None
    ):
        """Record a payment after verifying it belongs to the requested client.

        ``sales_item_id`` may be ``None`` for a sale-level payment: the Sales
        History table is one row per Sale, so payments no longer need to target
        a single item. When an item id is given it must belong to the sale.

        ``sale_id`` may be ``None`` for a general client-level payment that is
        not associated with any specific sale/devis.
        """
        client_id = int(client_id)
        sale_id = int(sale_id) if sale_id is not None else None
        sales_item_id = int(sales_item_id) if sales_item_id else None
        amount = float(amount)
        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero")

        try:
            # Verify the client exists
            self.cursor.execute(
                "SELECT username FROM clients WHERE id=%s", (client_id,)
            )
            cres = self.cursor.fetchone()
            norm = None
            if cres:
                username = str(cres[0] or '').strip()
                norm = self._normalize_exact(username) if username else None

            owner_clause = ""
            owner_params = []
            if user and not user.get("is_superadmin"):
                owner_clause = " AND s.created_by = %s"
                owner_params.append(int(user.get("id") or 0))

            if sale_id is not None:
                if sales_item_id:
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
                else:
                    if norm:
                        match_clause = (
                            "(s.client_id=%s OR "
                            "LOWER(REGEXP_REPLACE(BTRIM(COALESCE(s.client_username, '')), '\\s+', ' ', 'g')) = LOWER(%s))"
                        )
                        match_params = [client_id, norm]
                    else:
                        match_clause = "s.client_id=%s"
                        match_params = [client_id]
                    self.cursor.execute(
                        f"SELECT 1 FROM sales s WHERE s.id = %s AND {match_clause}{owner_clause}",
                        (sale_id, *match_params, *owner_params),
                    )
                    if not self.cursor.fetchone():
                        raise ValueError("The selected sale does not belong to this client")

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

    def update_client_payment(self, payment_id, amount, user=None):
        """Edit ONLY the amount of a single payment.

        No other field and no other row is touched - the sale, its items,
        stock and totals are never modified by this call. This backs the
        Client Account "Edit Payment Amount" feature. The no-overpayment rule
        is enforced by the dialog before this is called.
        """
        payment_id = int(payment_id)
        amount = float(amount)
        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero")
        mode = 'remote' if user is not None else 'local'
        user_id = user.get('id') if user else None
        role_id = user.get('role_id') if user else None
        try:
            self.cursor.execute(
                "UPDATE payments SET amount = %s WHERE id = %s RETURNING id",
                (amount, payment_id),
            )
            row = self.cursor.fetchone()
            if not row:
                raise ValueError(f"Payment {payment_id} does not exist")
            self.conn.commit()
            logger.info(
                "update_client_payment: mode=%s user_id=%s role_id=%s "
                "payment_id=%s amount=%s",
                mode, user_id, role_id, payment_id, amount,
            )
            return int(row[0])
        except Exception:
            self.conn.rollback()
            raise

    def delete_client_payment(self, payment_id, user=None):
        """Delete ONLY a single payment record by its persisted payment ID.

        No other row is touched - the sale, its items, stock, the client and
        the Devis reference are never modified by this call. Backs the Client
        Account "Delete Payment" feature; the user confirms before this is
        called. Raises ValueError if the payment does not exist.
        """
        payment_id = int(payment_id)
        mode = 'remote' if user is not None else 'local'
        user_id = user.get('id') if user else None
        role_id = user.get('role_id') if user else None
        try:
            self.cursor.execute(
                "DELETE FROM payments WHERE id = %s RETURNING id",
                (payment_id,),
            )
            row = self.cursor.fetchone()
            if not row:
                raise ValueError(f"Payment {payment_id} does not exist")
            self.conn.commit()
            logger.info(
                "delete_client_payment: mode=%s user_id=%s role_id=%s "
                "payment_id=%s",
                mode, user_id, role_id, payment_id,
            )
            return int(row[0])
        except Exception:
            self.conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Supplier Account (mirror of the Client Account API above)
    # ------------------------------------------------------------------
    def _supplier_match_clause(self, supplier_row):
        """Build the imports lookup clause for one supplier.

        Matches by supplier_id as well as by the supplier's username against
        imports.supplier_username, exactly like the client account lookup.
        Returns ``(clause, params)`` with ``clause`` carrying ``%s`` holes.
        """
        norm = self._normalize_exact(supplier_row[1]) if supplier_row[1] else None
        if norm:
            clause = (
                "(i.supplier_id=%s OR "
                "LOWER(REGEXP_REPLACE(BTRIM(COALESCE(i.supplier_username, '')), '\\s+', ' ', 'g')) = LOWER(%s))"
            )
            return clause, [int(supplier_row[0]), norm]
        return "i.supplier_id=%s", [int(supplier_row[0])]

    def _supplier_import_sql(self, alias_owner=True):
        """Shared 10-column Import x Import_Items SELECT (named-field order)."""
        return (
            "SELECT i.id, COALESCE(i.date, ''), "
            "ii.id, COALESCE(ii.product_name, ''), COALESCE(ii.quantity, 0), "
            "COALESCE(ii.unit_price, 0), "
            "COALESCE(i.notes, ''), COALESCE(i.is_historical, FALSE), "
            "COALESCE(i.created_by_username, '') "
            "FROM imports i JOIN import_items ii ON ii.import_id = i.id "
        )

    def get_supplier_account(self, supplier_id, user=None):
        """Return supplier account rows through one permission-gated backend API.

        The LAN server exposes this method under Suppliers/read, mirroring
        ``get_client_account`` under Clients/read. Imports are company-wide
        data, not per-creator data: access is controlled solely by the
        Suppliers:read permission check the LAN server already enforces before
        calling this method (no created_by ownership filter is applied).
        """
        supplier_id = int(supplier_id)
        mode = 'remote' if user is not None else 'local'
        user_id = user.get('id') if user else None
        role_id = user.get('role_id') if user else None
        self.cursor.execute(
            "SELECT id, username FROM suppliers WHERE id = %s", (supplier_id,)
        )
        supplier_row = self.cursor.fetchone()
        if not supplier_row:
            logger.warning(
                "get_supplier_account: supplier not found supplier_id=%s "
                "mode=%s user_id=%s",
                supplier_id, mode, user_id,
            )
            raise ValueError(f"Supplier {supplier_id} does not exist")

        match_clause, match_params = self._supplier_match_clause(supplier_row)
        sql = self._supplier_import_sql() + f"WHERE {match_clause} ORDER BY i.id, ii.id"
        self.cursor.execute(sql, tuple(match_params))
        import_rows = self.cursor.fetchall()
        import_ids = sorted({row[0] for row in import_rows})
        payment_rows = []
        if import_ids:
            self.cursor.execute(
                """
                SELECT p.id, p.import_id, p.import_item_id, p.date, p.amount
                FROM payments p
                WHERE p.import_id = ANY(%s)
                ORDER BY p.id DESC
                """,
                (import_ids,),
            )
            payment_rows = self.cursor.fetchall()

        logger.info(
            "get_supplier_account: mode=%s user_id=%s role_id=%s supplier_id=%s "
            "import_count=%s item_rows=%s payment_count=%s",
            mode, user_id, role_id, supplier_id,
            len(import_ids), len(import_rows), len(payment_rows),
        )
        return normalize_supplier_account(import_rows, payment_rows)

    def get_supplier_import_summaries(self, supplier_id, user=None):
        """Return one row per Import (never one per item) plus payment history.

        The Import History table only needs import-level facts - Import #,
        date, BL reference, status and the financial block - so this method
        aggregates the import items instead of downloading them. Per-Import
        TTC uses the same central formula as the account dialog and ``paid``
        is capped at the import total.
        """
        supplier_id = int(supplier_id)
        mode = 'remote' if user is not None else 'local'
        user_id = user.get('id') if user else None
        role_id = user.get('role_id') if user else None
        self.cursor.execute(
            "SELECT id, username FROM suppliers WHERE id = %s", (supplier_id,)
        )
        supplier_row = self.cursor.fetchone()
        if not supplier_row:
            logger.warning(
                "get_supplier_import_summaries: supplier not found "
                "supplier_id=%s mode=%s user_id=%s",
                supplier_id, mode, user_id,
            )
            raise ValueError(f"Supplier {supplier_id} does not exist")

        match_clause, match_params = self._supplier_match_clause(supplier_row)
        sql = (
            "SELECT i.id, COALESCE(i.date, ''), "
            "COALESCE(NULLIF(BTRIM(i.bl_number), ''), ''), "
            "COALESCE(i.is_historical, FALSE), "
            "COALESCE(SUM(ii.quantity * ii.unit_price), 0) "
            "FROM imports i LEFT JOIN import_items ii ON ii.import_id = i.id "
            f"WHERE {match_clause} "
            "GROUP BY i.id, i.date, i.bl_number, i.is_historical, "
            "i.created_at ORDER BY i.id"
        )
        self.cursor.execute(sql, tuple(match_params))
        rows = self.cursor.fetchall()

        from core.calculations import calculate_operation_totals, to_decimal
        import_rows = []
        for row in rows:
            import_id, date, bl_number, is_hist, raw = row
            total = calculate_operation_totals(
                to_decimal(raw), to_decimal(0)
            )["total"]
            import_rows.append([
                import_id, date, bl_number, is_hist, total,
                Decimal("0"), Decimal("0"),
            ])

        payment_rows = []
        if import_rows:
            self.cursor.execute(
                """
                SELECT p.id, p.import_id, p.import_item_id, p.date, p.amount
                FROM payments p
                WHERE p.import_id = ANY(%s)
                ORDER BY p.id DESC
                """,
                ([row[0] for row in import_rows],),
            )
            payment_rows = self.cursor.fetchall()

        paid_by_import = {}
        for row in payment_rows:
            paid_by_import[row[1]] = paid_by_import.get(row[1], Decimal("0")) + to_decimal(
                row[4]
            )
        for imp in import_rows:
            total = imp[4]
            paid = min(paid_by_import.get(imp[0], Decimal("0")), total)
            imp[5] = paid
            imp[6] = max(total - paid, Decimal("0"))

        summaries = [
            dict(zip(SUPPLIER_ACCOUNT_IMPORT_SUMMARY_FIELDS, row))
            for row in import_rows
        ]
        payments = [
            dict(zip(SUPPLIER_ACCOUNT_PAYMENT_FIELDS, row))
            for row in payment_rows
        ]
        logger.info(
            "get_supplier_import_summaries: mode=%s user_id=%s role_id=%s "
            "supplier_id=%s import_count=%s payment_count=%s",
            mode, user_id, role_id, supplier_id, len(import_rows), len(payment_rows),
        )
        return {"imports": summaries, "payments": payments}

    def get_supplier_import_items(self, import_id, user=None):
        """Return one Import's item rows + its payments (for single-import PDFs)."""
        import_id = int(import_id)
        mode = 'remote' if user is not None else 'local'
        user_id = user.get('id') if user else None
        role_id = user.get('role_id') if user else None

        sql = self._supplier_import_sql() + "WHERE i.id = %s ORDER BY ii.id"
        self.cursor.execute(sql, (import_id,))
        import_rows = self.cursor.fetchall()

        self.cursor.execute(
            """
            SELECT p.id, p.import_id, p.import_item_id, p.date, p.amount
            FROM payments p
            WHERE p.import_id = %s
            ORDER BY p.id DESC
            """,
            (import_id,),
        )
        payment_rows = self.cursor.fetchall()

        self.cursor.execute(
            """
            SELECT i.id, COALESCE(i.date, ''),
                   COALESCE(i.notes, ''), COALESCE(i.is_historical, FALSE),
                   COALESCE(NULLIF(BTRIM(i.bl_number), ''), ''),
                   COALESCE(i.supplier_username, ''), COALESCE(i.supplier_name, '')
            FROM imports i WHERE i.id = %s
            """,
            (import_id,),
        )
        block_row = self.cursor.fetchone() or (
            import_id, '', 0, '', False, '', '', ''
        )

        logger.info(
            "get_supplier_import_items: mode=%s user_id=%s role_id=%s "
            "import_id=%s item_rows=%s payment_count=%s",
            mode, user_id, role_id, import_id, len(import_rows), len(payment_rows),
        )
        return {
            "imports": [
                dict(zip(SUPPLIER_ACCOUNT_IMPORT_FIELDS, row))
                for row in import_rows
            ],
            "payments": [
                dict(zip(SUPPLIER_ACCOUNT_PAYMENT_FIELDS, row))
                for row in payment_rows
            ],
            "import": {
                "import_id": int(block_row[0]),
                "date": block_row[1],
                "vat": block_row[2],
                "notes": block_row[3],
                "is_historical": block_row[4],
                "bl_number": block_row[5],
                "supplier_username": block_row[6],
                "supplier_name": block_row[7],
            },
        }

    def add_supplier_payment(
        self, supplier_id, import_id, import_item_id, amount, date, user=None
    ):
        """Record a payment after verifying it belongs to the requested supplier.

        ``import_item_id`` may be ``None`` for an import-level payment: the
        Import History table is one row per Import, so payments no longer need
        to target a single item. When an item id is given it must belong to
        the import.
        """
        supplier_id = int(supplier_id)
        import_id = int(import_id)
        import_item_id = int(import_item_id) if import_item_id else None
        amount = float(amount)
        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero")

        try:
            self.cursor.execute(
                "SELECT username FROM suppliers WHERE id=%s", (supplier_id,)
            )
            sres = self.cursor.fetchone()
            norm = None
            if sres:
                username = str(sres[0] or '').strip()
                norm = self._normalize_exact(username) if username else None

            if import_item_id:
                self.cursor.execute(
                    """
                    SELECT 1
                    FROM imports i
                    JOIN import_items ii ON ii.import_id = i.id
                    WHERE i.id = %s AND ii.id = %s AND i.supplier_id = %s
                    """,
                    (import_id, import_item_id, supplier_id),
                )
                if not self.cursor.fetchone():
                    raise ValueError("The selected import item does not belong to this supplier")
            else:
                if norm:
                    match_clause = (
                        "(i.supplier_id=%s OR "
                        "LOWER(REGEXP_REPLACE(BTRIM(COALESCE(i.supplier_username, '')), '\\s+', ' ', 'g')) = LOWER(%s))"
                    )
                    match_params = [supplier_id, norm]
                else:
                    match_clause = "i.supplier_id=%s"
                    match_params = [supplier_id]
                self.cursor.execute(
                    f"SELECT 1 FROM imports i WHERE i.id = %s AND {match_clause}",
                    (import_id, *match_params),
                )
                if not self.cursor.fetchone():
                    raise ValueError("The selected import does not belong to this supplier")

            self.cursor.execute(
                """
                INSERT INTO payments (import_id, import_item_id, amount, date)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (import_id, import_item_id, amount, str(date)),
            )
            payment_id = self.cursor.fetchone()[0]
            self.conn.commit()
            return int(payment_id)
        except Exception:
            self.conn.rollback()
            raise

    def update_supplier_payment(self, payment_id, amount, user=None):
        """Edit ONLY the amount of a single supplier payment.

        No other field and no other row is touched - the import, its items,
        stock and totals are never modified by this call. The no-overpayment
        rule is enforced by the dialog before this is called.
        """
        payment_id = int(payment_id)
        amount = float(amount)
        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero")
        mode = 'remote' if user is not None else 'local'
        user_id = user.get('id') if user else None
        role_id = user.get('role_id') if user else None
        try:
            self.cursor.execute(
                "UPDATE payments SET amount = %s "
                "WHERE id = %s AND import_id IS NOT NULL RETURNING id",
                (amount, payment_id),
            )
            row = self.cursor.fetchone()
            if not row:
                raise ValueError(f"Payment {payment_id} does not exist")
            self.conn.commit()
            logger.info(
                "update_supplier_payment: mode=%s user_id=%s role_id=%s "
                "payment_id=%s amount=%s",
                mode, user_id, role_id, payment_id, amount,
            )
            return int(row[0])
        except Exception:
            self.conn.rollback()
            raise

    def delete_supplier_payment(self, payment_id, user=None):
        """Delete ONLY a single supplier payment record by its persisted ID.

        No other row is touched - the import, its items, stock, the supplier
        and the BL reference are never modified by this call. Raises
        ValueError if the payment does not exist.
        """
        payment_id = int(payment_id)
        mode = 'remote' if user is not None else 'local'
        user_id = user.get('id') if user else None
        role_id = user.get('role_id') if user else None
        try:
            self.cursor.execute(
                "DELETE FROM payments WHERE id = %s AND import_id IS NOT NULL "
                "RETURNING id",
                (payment_id,),
            )
            row = self.cursor.fetchone()
            if not row:
                raise ValueError(f"Payment {payment_id} does not exist")
            self.conn.commit()
            logger.info(
                "delete_supplier_payment: mode=%s user_id=%s role_id=%s "
                "payment_id=%s",
                mode, user_id, role_id, payment_id,
            )
            return int(row[0])
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
            deleted = self.cursor.rowcount > 0
            if deleted:
                self.record_change(section, int(item_id), 'delete', None)
            return deleted
        except Exception as e:
            self.conn.rollback()
            print(f"Error deleting item from {section}: {e}")
            return False

    # Attachment operations transfer bytes as base64 over LAN RPC. The host's
    # data directory is never returned to a workstation.
    # ────────────────────────── Charges / Operating Expenses ──────────────────
    #
    # Charges are business operating expenses (rent, salaries, electricity...).
    # They are distinct from product imports (COGS) and stock adjustments.
    # A charge may be linked to a recurring template for idempotent due-date
    # confirmation. All operations are transactional.

    def get_charge_categories(self, user=None):
        """Return all charge categories with their active status."""
        try:
            self.cursor.execute(
                """SELECT cc.id, cc.name, cc.active,
                          COUNT(DISTINCT ch.id), COUNT(DISTINCT rt.id)
                   FROM charge_categories cc
                   LEFT JOIN charges ch ON ch.category_id = cc.id
                   LEFT JOIN charge_recurring_templates rt ON rt.category_id = cc.id
                   GROUP BY cc.id, cc.name, cc.active
                   ORDER BY cc.name"""
            )
            rows = self.cursor.fetchall()
            return [
                {
                    "id": r[0], "name": r[1], "active": bool(r[2]),
                    "charges_count": int(r[3] or 0),
                    "templates_count": int(r[4] or 0),
                }
                for r in rows
            ]
        except Exception:
            self.conn.rollback()
            raise

    def add_charge_category(self, name, user=None):
        """Create a new charge category."""
        if not name or not name.strip():
            raise ValueError("Category name cannot be empty")
        try:
            self.cursor.execute(
                "INSERT INTO charge_categories (name) VALUES (%s) RETURNING id",
                (name.strip(),),
            )
            row = self.cursor.fetchone()
            self.conn.commit()
            return int(row[0])
        except Exception:
            self.conn.rollback()
            raise

    def update_charge_category(self, category_id, name=None, active=None, user=None):
        """Update an existing charge category."""
        if name is not None and not name.strip():
            raise ValueError("Category name cannot be empty")
        updates = []
        params = []
        if name is not None:
            updates.append("name = %s")
            params.append(name.strip())
        if active is not None:
            updates.append("active = %s")
            params.append(bool(active))
        if not updates:
            return True
        params.append(category_id)
        try:
            self.cursor.execute(
                f"UPDATE charge_categories SET {', '.join(updates)} WHERE id = %s",
                params,
            )
            if self.cursor.rowcount == 0:
                raise ValueError(f"Category {category_id} does not exist")
            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            raise

    def delete_charge_category(self, category_id, user=None):
        """Delete a charge category if not referenced by any charge."""
        try:
            self.cursor.execute(
                "SELECT 1 FROM charges WHERE category_id = %s LIMIT 1",
                (category_id,),
            )
            if self.cursor.fetchone():
                raise ValueError("Cannot delete category: it is referenced by charges")
            self.cursor.execute(
                "SELECT 1 FROM charge_recurring_templates WHERE category_id = %s LIMIT 1",
                (category_id,),
            )
            if self.cursor.fetchone():
                raise ValueError(
                    "Cannot delete category: it is used by recurring templates"
                )
            self.cursor.execute(
                "DELETE FROM charge_categories WHERE id = %s", (category_id,)
            )
            if self.cursor.rowcount == 0:
                raise ValueError(f"Category {category_id} does not exist")
            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            raise

    def get_charges(self, date_from, date_to, category_id=None, search=None,
                    limit=100, offset=0, order_by=None, order_dir='desc',
                    user=None):
        """List charges in a date range with optional filters."""
        try:
            from decimal import Decimal
            clauses = ["expense_date >= %s", "expense_date <= %s"]
            params = [date_from, date_to]
            if category_id:
                clauses.append("category_id = %s")
                params.append(category_id)
            if search:
                clauses.append(
                    "(ch.description ILIKE %s OR ch.reference ILIKE %s OR ch.notes ILIKE %s)"
                )
                like = f"%{search}%"
                params.extend([like, like, like])
            where_sql = " AND ".join(clauses)
            qualified_where = where_sql.replace("expense_date", "ch.expense_date")
            qualified_where = qualified_where.replace("category_id", "ch.category_id")
            allowed_order = {
                'expense_date': 'ch.expense_date',
                'date': 'ch.expense_date',
                'category_id': 'cc.name',
                'amount': 'ch.amount',
                'description': 'ch.description',
            }
            order_column = allowed_order.get(order_by, 'ch.expense_date')
            direction = 'ASC' if str(order_dir).lower() == 'asc' else 'DESC'

            # Total count
            self.cursor.execute(
                f"SELECT COUNT(*) FROM charges ch WHERE {qualified_where}",
                params,
            )
            total = self.cursor.fetchone()[0] or 0

            # Period total amount
            self.cursor.execute(
                f"SELECT COALESCE(SUM(ch.amount), 0) FROM charges ch WHERE {qualified_where}",
                params,
            )
            period_total = self.cursor.fetchone()[0] or 0

            # Paginated list
            self.cursor.execute(
                f"""SELECT ch.id, ch.expense_date, ch.category_id, ch.description,
                           ch.amount, ch.payment_method, ch.reference, ch.notes,
                           ch.recurring_template_id, ch.created_by,
                           ch.created_by_username, ch.created_at, ch.updated_by,
                           ch.updated_by_username, ch.updated_at,
                           cc.name, rt.name
                    FROM charges ch
                    JOIN charge_categories cc ON cc.id = ch.category_id
                    LEFT JOIN charge_recurring_templates rt
                           ON rt.id = ch.recurring_template_id
                    WHERE {qualified_where}
                    ORDER BY {order_column} {direction}, ch.id {direction}
                    LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            rows = self.cursor.fetchall()
            charges = []
            for r in rows:
                charges.append({
                    "id": r[0],
                    "expense_date": r[1],
                    "category_id": r[2],
                    "description": r[3] or "",
                    "amount": str(r[4] or 0),
                    "payment_method": r[5] or "Cash",
                    "reference": r[6] or "",
                    "notes": r[7] or "",
                    "recurring_template_id": r[8],
                    "created_by": r[9],
                    "created_by_username": r[10] or "",
                    "created_at": r[11] or "",
                    "updated_by": r[12],
                    "updated_by_username": r[13] or "",
                    "updated_at": r[14] or "",
                    "category_name": r[15] or "",
                    "recurring_template_name": r[16] or "No recurring template",
                })
            return {
                "charges": charges,
                "total_count": total,
                "period_total": str(period_total or 0),
            }
        except Exception:
            self.conn.rollback()
            raise

    def get_charge(self, charge_id, user=None):
        """Get a single charge by ID."""
        try:
            self.cursor.execute(
                """SELECT ch.id, ch.expense_date, ch.category_id, ch.description,
                          ch.amount, ch.payment_method, ch.reference, ch.notes,
                          ch.recurring_template_id, ch.created_by,
                          ch.created_by_username, ch.created_at, ch.updated_by,
                          ch.updated_by_username, ch.updated_at, cc.name, rt.name
                   FROM charges ch
                   JOIN charge_categories cc ON cc.id = ch.category_id
                   LEFT JOIN charge_recurring_templates rt
                          ON rt.id = ch.recurring_template_id
                   WHERE ch.id = %s""",
                (charge_id,),
            )
            r = self.cursor.fetchone()
            if not r:
                return None
            return {
                "id": r[0], "expense_date": r[1], "category_id": r[2],
                "description": r[3] or "", "amount": str(r[4] or 0),
                "payment_method": r[5] or "Cash", "reference": r[6] or "",
                "notes": r[7] or "", "recurring_template_id": r[8],
                "created_by": r[9], "created_by_username": r[10] or "",
                "created_at": r[11] or "", "updated_by": r[12],
                "updated_by_username": r[13] or "", "updated_at": r[14] or "",
                "category_name": r[15] or "",
                "recurring_template_name": r[16] or "No recurring template",
            }
        except Exception:
            self.conn.rollback()
            raise

    def save_charge(self, charge_data, charge_id=None, user=None):
        """Create or update a charge."""
        try:
            from decimal import Decimal
            actor = self._actor_fields(user)
            amount = Decimal(str(charge_data.get("amount") or 0))
            if amount <= 0:
                raise ValueError("Charge amount must be greater than zero")

            category_id = charge_data.get("category_id")
            if not category_id:
                raise ValueError("Category is required")

            expense_date = charge_data.get("expense_date")
            if not expense_date:
                raise ValueError("Expense date is required")
            from datetime import datetime
            try:
                datetime.strptime(str(expense_date), "%Y-%m-%d")
            except ValueError as error:
                raise ValueError("Expense date must use YYYY-MM-DD") from error
            payment_method = charge_data.get("payment_method") or "Cash"
            if payment_method not in ("Cash", "Bank", "Check", "Card", "Other"):
                raise ValueError("Invalid payment method")
            self.cursor.execute(
                "SELECT active FROM charge_categories WHERE id = %s", (category_id,)
            )
            category_row = self.cursor.fetchone()
            if not category_row:
                raise ValueError("Selected category does not exist")
            if not charge_id and not category_row[0]:
                raise ValueError("Selected category is inactive")
            recurring_template_id = charge_data.get("recurring_template_id") or None
            if recurring_template_id:
                self.cursor.execute(
                    "SELECT 1 FROM charge_recurring_templates WHERE id = %s",
                    (recurring_template_id,),
                )
                if not self.cursor.fetchone():
                    raise ValueError("Selected recurring template does not exist")

            if charge_id:
                # Update
                self.cursor.execute(
                    """UPDATE charges SET expense_date=%s, category_id=%s,
                          description=%s, amount=%s, payment_method=%s,
                           reference=%s, notes=%s, recurring_template_id=%s,
                           updated_by=%s,
                          updated_by_username=%s, updated_at=%s
                    WHERE id=%s RETURNING id""",
                    (charge_data.get("expense_date"), charge_data.get("category_id"),
                     charge_data.get("description", ""), amount,
                      payment_method,
                      charge_data.get("reference", ""), charge_data.get("notes", ""),
                      recurring_template_id,
                      actor["created_by"], actor["created_by_username"],
                     actor["created_at"], charge_id),
                )
                row = self.cursor.fetchone()
                if not row:
                    raise ValueError(f"Charge {charge_id} not found")
                self.conn.commit()
                return {"id": row[0], "transaction": "committed"}
            else:
                # Create new
                self.cursor.execute(
                    """INSERT INTO charges
                         (expense_date, category_id, description, amount,
                          payment_method, reference, notes, recurring_template_id,
                          created_by, created_by_username, created_at)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                     RETURNING id""",
                    (charge_data.get("expense_date"), charge_data.get("category_id"),
                     charge_data.get("description", ""), amount,
                      payment_method,
                     charge_data.get("reference", ""), charge_data.get("notes", ""),
                      recurring_template_id,
                     actor["created_by"], actor["created_by_username"],
                     actor["created_at"]),
                )
                row = self.cursor.fetchone()
                self.conn.commit()
                return {"id": row[0], "transaction": "committed"}
        except Exception:
            self.conn.rollback()
            raise

    def delete_charge(self, charge_id, user=None):
        """Delete a charge by ID."""
        try:
            from core.attachments import AttachmentService
            AttachmentService(self).delete_owner("charge", int(charge_id))
            self.cursor.execute(
                "DELETE FROM charges WHERE id = %s RETURNING id",
                (charge_id,),
            )
            row = self.cursor.fetchone()
            if not row:
                raise ValueError(f"Charge {charge_id} does not exist")
            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            raise

    # ────────────────────────── Recurring Charges ──────────────────────────────
    
    def get_recurring_templates(self, user=None):
        """List all recurring charge templates."""
        try:
            self.cursor.execute(
                """SELECT rt.id, rt.name, rt.category_id, rt.default_amount, rt.frequency,
                          next_due_date, payment_method, reference_template,
                          notes, enabled, created_by, created_by_username, created_at,
                          cc.name
                   FROM charge_recurring_templates rt
                   JOIN charge_categories cc ON cc.id = rt.category_id
                   ORDER BY rt.name"""
            )
            return [
                {
                    "id": r[0], "name": r[1], "category_id": r[2],
                    "default_amount": str(r[3] or 0), "frequency": r[4],
                    "next_due_date": r[5], "payment_method": r[6] or "Cash",
                    "reference_template": r[7] or "", "notes": r[8] or "",
                    "enabled": bool(r[9]),
                    "created_by": r[10], "created_by_username": r[11] or "",
                    "created_at": r[12] or "",
                    "category_name": r[13] or "",
                }
                for r in self.cursor.fetchall()
            ]
        except Exception:
            self.conn.rollback()
            raise

    def get_due_recurring_charges(self, date_str, user=None):
        """Return recurring templates that are due on or before the given date."""
        try:
            self.cursor.execute(
                """SELECT rt.id, rt.name, rt.category_id, rt.default_amount, rt.frequency,
                          next_due_date, payment_method, reference_template, notes
                          , cc.name
                   FROM charge_recurring_templates rt
                   JOIN charge_categories cc ON cc.id = rt.category_id
                   WHERE rt.enabled AND rt.next_due_date <= %s
                   ORDER BY rt.next_due_date""",
                (date_str,),
            )
            return [
                {
                    "id": r[0], "name": r[1], "category_id": r[2],
                    "default_amount": str(r[3] or 0), "frequency": r[4],
                    "next_due_date": r[5], "payment_method": r[6] or "Cash",
                    "reference_template": r[7] or "", "notes": r[8] or "",
                    "category_name": r[9] or "",
                }
                for r in self.cursor.fetchall()
            ]
        except Exception:
            self.conn.rollback()
            raise

    def confirm_recurring_charge(self, template_id, expense_date=None,
                                  amount=None, user=None):
        """Confirm one occurrence of a recurring charge.
        
        Creates the actual charge record, advances the template's next_due_date
        by its frequency, and returns the created charge ID.
        The unique index on (recurring_template_id, expense_date) prevents
        duplicate confirmations.
        """
        try:
            import calendar
            from datetime import date, datetime, timedelta
            from decimal import Decimal

            self.cursor.execute(
                """SELECT id, name, category_id, default_amount, frequency,
                          next_due_date, payment_method, reference_template, notes
                   FROM charge_recurring_templates WHERE id = %s""",
                (template_id,),
            )
            tpl = self.cursor.fetchone()
            if not tpl:
                raise ValueError(f"Recurring template {template_id} not found")

            name, category_id, default_amount, frequency, next_due, payment_method, ref_template, notes = tpl[1:]
            if not amount:
                amount = Decimal(str(default_amount or 0))
            if not expense_date:
                expense_date = next_due

            # Create the charge
            self.cursor.execute(
                """INSERT INTO charges
                     (expense_date, category_id, description, amount,
                      payment_method, reference, notes, recurring_template_id)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                 RETURNING id""",
                (expense_date, category_id, name, amount,
                 payment_method or "Cash", ref_template, notes or "", template_id),
            )
            charge_row = self.cursor.fetchone()
            charge_id = int(charge_row[0])

            # Advance next_due_date
            if isinstance(next_due, datetime):
                next_due = next_due.date()
            elif not isinstance(next_due, date):
                next_due = datetime.strptime(str(next_due), "%Y-%m-%d").date()
            if frequency == "monthly":
                month = 1 if next_due.month == 12 else next_due.month + 1
                year = next_due.year + 1 if next_due.month == 12 else next_due.year
                next_due = next_due.replace(
                    year=year, month=month,
                    day=min(next_due.day, calendar.monthrange(year, month)[1]),
                )
            elif frequency == "weekly":
                next_due = next_due + timedelta(days=7)
            elif frequency == "yearly":
                next_due = next_due.replace(year=next_due.year + 1)
            next_due_str = next_due.isoformat()

            self.cursor.execute(
                "UPDATE charge_recurring_templates SET next_due_date = %s WHERE id = %s",
                (next_due_str, template_id),
            )
            self.conn.commit()
            return {"charge_id": charge_id, "next_due_date": next_due_str}
        except Exception:
            self.conn.rollback()
            raise

    def save_recurring_template(self, data, template_id=None, user=None):
        """Create or update a recurring charge template."""
        try:
            actor = self._actor_fields(user)
            freq = data.get("frequency", "monthly")
            if freq not in ("monthly", "weekly", "yearly"):
                freq = "monthly"

            if template_id:
                # Update
                self.cursor.execute(
                    """UPDATE charge_recurring_templates SET
                         name=%s, category_id=%s, default_amount=%s,
                         frequency=%s, next_due_date=%s, payment_method=%s,
                         reference_template=%s, notes=%s, enabled=%s
                     WHERE id=%s RETURNING id""",
                     (data.get("name"), data.get("category_id"),
                      data.get("default_amount", 0), freq,
                      data.get("next_due_date"), data.get("payment_method", "Cash"),
                      data.get("reference_template", ""), data.get("notes", ""),
                      bool(data.get("enabled")), template_id),
                )
                if self.cursor.rowcount == 0:
                    raise ValueError(f"Template {template_id} not found")
            else:
                self.cursor.execute(
                    """INSERT INTO charge_recurring_templates
                         (name, category_id, default_amount, frequency,
                          next_due_date, payment_method, reference_template,
                          notes, enabled, created_by, created_by_username, created_at)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                     RETURNING id""",
                    (data.get("name"), data.get("category_id"),
                     data.get("default_amount", 0), freq,
                     data.get("next_due_date"), data.get("payment_method", "Cash"),
                     data.get("reference_template", ""), data.get("notes", ""),
                     bool(data.get("enabled")),
                     actor["created_by"], actor["created_by_username"],
                     actor["created_at"]),
                )
            row = self.cursor.fetchone()
            self.conn.commit()
            return {"id": row[0], "transaction": "committed"}
        except Exception:
            self.conn.rollback()
            raise

    def delete_recurring_template(self, template_id, user=None):
        """Delete a recurring template (cascades NULL on charges)."""
        try:
            self.cursor.execute(
                "DELETE FROM charge_recurring_templates WHERE id = %s RETURNING id",
                (template_id,),
            )
            if self.cursor.rowcount == 0:
                raise ValueError(f"Template {template_id} not found")
            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            raise

    def get_charge_summary(self, date_from, date_to, category_id=None, user=None):
        """Get charge summary for a date range."""
        try:
            from decimal import Decimal
            clauses = ["expense_date >= %s", "expense_date <= %s"]
            params = [date_from, date_to]
            if category_id:
                clauses.append("category_id = %s")
                params.append(category_id)
            where_sql = " AND ".join(clauses)

            # Total count
            self.cursor.execute(
                f"SELECT COUNT(*) FROM charges WHERE {where_sql}",
                params,
            )
            total_count = self.cursor.fetchone()[0] or 0

            # Total amount
            self.cursor.execute(
                f"SELECT COALESCE(SUM(amount), 0) FROM charges WHERE {where_sql}",
                params,
            )
            total_amount = self.cursor.fetchone()[0] or 0

            # By category
            self.cursor.execute(
                f"""SELECT c.name, COUNT(ch.id), COALESCE(SUM(ch.amount), 0)
                   FROM charges ch
                   JOIN charge_categories c ON c.id = ch.category_id
                   WHERE {where_sql}
                   GROUP BY c.id, c.name
                   ORDER BY c.name""",
                params,
            )
            by_category = []
            for row in self.cursor.fetchall():
                by_category.append({
                    "category": row[0],
                    "count": row[1],
                    "total": str(row[2] or 0)
                })

            return {
                "date_from": date_from,
                "date_to": date_to,
                "total_count": total_count,
                "total_amount": str(total_amount),
                "by_category": by_category,
            }
        except Exception:
            self.conn.rollback()
            raise

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

    def get_attachment_thumbnails_bulk(self, attachment_ids):
        from core.attachments import AttachmentService
        return AttachmentService(self).thumbnails([int(aid) for aid in attachment_ids])

    def update_attachment(self, attachment_id, display_name=None, description=None, category=None):
        from core.attachments import AttachmentService
        return AttachmentService(self).update(int(attachment_id), display_name, description, category)

    def delete_attachment(self, attachment_id):
        from core.attachments import AttachmentService
        return AttachmentService(self).delete(int(attachment_id))

    def close(self):
        """Close database connection"""
        if self.conn:
            diagnostics.db_connection_closed(kind="local")
            self.conn.close()
            self.conn = None
            self.cursor = None
