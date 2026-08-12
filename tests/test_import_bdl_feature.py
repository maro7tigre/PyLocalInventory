"""Tests for the persistent, year-scoped Import Bon de Livraison reference.

Covers the host-side resolver/allocator (BL-YEAR-N), the legacy backfill,
the read-or-allocate public method used by the report dialog, the server
permission gate, and the import BDL HTML generation. Real PostgreSQL is not
required - queries are exercised against a scripted cursor.
"""

import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.database import BL_MAX_LENGTH, Database
from core.network.server import _check_permission
from classes.import_class import ImportClass


class _FakeConn:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


class _BlFakeCursor:
    """Scripted cursor for the real Database BL resolver/allocator paths."""

    def __init__(self):
        self.queries = []
        self._sql = None
        self.rowcount = 0
        self.max_number = 0
        self.stored_bl = None
        self.duplicate_id = None
        self.missing_import = False
        self.import_date = "2026-07-01"

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        self._sql = sql

    def fetchone(self):
        if "MAX(CAST(SUBSTRING(s.bl_number" in self._sql:
            # The SQL computes COALESCE(MAX(...), 0) + 1 itself.
            return (self.max_number + 1,)
        if "LOWER(BTRIM(bl_number))" in self._sql:
            if self.duplicate_id is not None:
                return (self.duplicate_id,)
            return None
        if self._sql.strip().startswith("SELECT bl_number FROM imports"):
            if self.missing_import:
                return None
            return (self.stored_bl,)
        if self._sql.strip().startswith("SELECT date FROM imports"):
            return (self.import_date,)
        if "SELECT id, name FROM products" in self._sql:
            return (1, "Bois de chêne")
        if "FROM suppliers" in self._sql:
            return (7, "Bois Plus SARL", "boisplus")
        if "RETURNING id" in self._sql:
            return (100,)
        return None

    def fetchall(self):
        return []


class BlResolverTests(unittest.TestCase):
    def setUp(self):
        self.cursor = _BlFakeCursor()
        self.db = Database.__new__(Database)
        self.db.cursor = self.cursor
        self.db.conn = _FakeConn()

    def test_create_allocates_next_per_year_number(self):
        self.cursor.max_number = 4
        header = {"date": "2026-07-01"}
        self.db._resolve_import_bl(None, header)
        self.assertEqual(header["bl_number"], "BL-2026-5")

    def test_create_stores_provided_value_verbatim(self):
        header = {"date": "2026-07-01", "bl_number": "  BL-2026-7  "}
        self.db._resolve_import_bl(None, header)
        self.assertEqual(header["bl_number"], "BL-2026-7")

    def test_provided_value_is_normalized_case_insensitively_for_dup_check(self):
        header = {"date": "2026-07-01", "bl_number": "bl-2026-7"}
        self.db._resolve_import_bl(None, header)
        dup_sql, dup_params = self.cursor.queries[-1]
        self.assertIn("LOWER(BTRIM(bl_number))", dup_sql)
        self.assertEqual(dup_params, ["bl-2026-7"])

    def test_duplicate_value_raises(self):
        self.cursor.duplicate_id = 7
        header = {"date": "2026-07-01", "bl_number": "BL-2026-7"}
        with self.assertRaises(ValueError):
            self.db._resolve_import_bl(3, header)

    def test_over_length_value_raises_before_any_query(self):
        header = {"date": "2026-07-01", "bl_number": "X" * (BL_MAX_LENGTH + 1)}
        with self.assertRaises(ValueError):
            self.db._resolve_import_bl(None, header)
        self.assertEqual(self.cursor.queries, [])

    def test_edit_preserves_stored_reference_when_field_empty(self):
        self.cursor.stored_bl = "BL-2026-3"
        header = {"date": "2026-07-01"}
        self.db._resolve_import_bl(9, header)
        self.assertEqual(header["bl_number"], "BL-2026-3")

    def test_edit_allocates_for_legacy_row_with_no_reference(self):
        self.cursor.stored_bl = None
        self.cursor.max_number = 2
        header = {"date": "2026-01-15"}
        self.db._resolve_import_bl(9, header)
        self.assertEqual(header["bl_number"], "BL-2026-3")

    def test_allocator_sql_extracts_numeric_part_of_stored_reference(self):
        self.cursor.max_number = 11
        header = {"date": "2026-07-01"}
        self.db._allocate_bl_number(1, header)
        sql, params = self.cursor.queries[-1]
        self.assertIn("SUBSTRING(s.bl_number FROM 'BL-\\d{4}-(\\d+)')", sql)
        self.assertIn("bl_year = %s", sql)
        self.assertEqual(params, ("2026",))
        self.assertEqual(header["bl_number"], "BL-2026-12")

    def test_preview_proposes_next_number_for_year(self):
        self.cursor.max_number = 27
        self.assertEqual(self.db.get_next_bl_preview("2026-07-01"), "BL-2026-28")

    def test_preview_is_advisory_only_no_write(self):
        self.cursor.max_number = 27
        before = len(self.cursor.queries)
        self.db.get_next_bl_preview("2026-07-01")
        sql, _ = self.cursor.queries[-1]
        self.assertNotIn("UPDATE", sql)
        self.assertNotIn("INSERT", sql)
        self.assertEqual(self.db.conn.commits, 0)


class BlHistoricalFlagTests(unittest.TestCase):
    def setUp(self):
        self.cursor = _BlFakeCursor()
        self.db = Database.__new__(Database)
        self.db.cursor = self.cursor
        self.db.conn = _FakeConn()
        self.db.registered_classes = {"Imports": ImportClass}

    def test_bool_flag_parser_maps_int_and_bool_to_python_bool(self):
        self.assertIs(self.db._parse_bool_flag(True), True)
        self.assertIs(self.db._parse_bool_flag(False), False)
        self.assertIs(self.db._parse_bool_flag(1), True)
        self.assertIs(self.db._parse_bool_flag(0), False)
        self.assertIs(self.db._parse_bool_flag("1"), True)
        self.assertIs(self.db._parse_bool_flag("false"), False)
        self.assertIs(self.db._parse_bool_flag(None), False)

    def test_import_class_keeps_is_historical_as_python_bool(self):
        from classes.import_class import ImportClass as ImportCls
        obj = ImportCls(0, None)
        for source, expected in [(True, True), (False, False), (1, True), (0, False),
                                 ("true", True), ("", False)]:
            obj.set_value('is_historical', source)
            value = obj.get_value('is_historical')
            self.assertIs(value, expected, f"source={source!r} -> {value!r}")

    def test_save_import_normalizes_integer_is_historical_to_bool(self):
        self.cursor.max_number = 27
        payload = {
            "supplier_username": "boisplus", "supplier_name": "boisplus",
            "date": "2026-07-01", "bl_number": "", "tva": 20.0,
            "is_historical": 1, "operation_token": "tok-hist-1",
        }
        item = [{"product_name": "Bois de chêne", "quantity": "5", "unit_price": "10"}]
        self.db.save_import_with_items(payload, item, import_id=None,
                                       visible_row_count=1)
        insert_sql = insert_params = None
        for sql, params in self.cursor.queries:
            s = str(sql)
            if s.startswith("INSERT INTO imports") and "is_historical" in s:
                insert_sql, insert_params = s, params
                break
        self.assertIsNotNone(insert_params)
        columns = insert_sql.split("(", 1)[1].split(")", 1)[0].split(",")
        idx = [c.strip().strip('"') for c in columns].index("is_historical")
        self.assertIs(type(insert_params[idx]), bool)
        self.assertIs(insert_params[idx], True)


class BlBackfillTests(unittest.TestCase):
    def setUp(self):
        self.cursor = _BlFakeCursor()
        self.db = Database.__new__(Database)
        self.db.cursor = self.cursor
        self.db.conn = _FakeConn()

    def test_backfill_only_touches_empty_rows(self):
        self.db._ensure_bl_numbers()
        sql, params = self.cursor.queries[-1]
        self.assertIn("UPDATE imports", sql)
        self.assertIn("BTRIM(s.bl_number) = ''", sql)
        self.assertIn("BL-", sql)
        self.assertEqual(params, ())

    def test_backfill_restricts_to_requested_import_ids(self):
        self.db._ensure_bl_numbers([2, 9])
        sql, params = self.cursor.queries[-1]
        self.assertIn("s.id = ANY(%s)", sql)
        self.assertEqual(params, ([2, 9],))


class GetImportBlNumberTests(unittest.TestCase):
    def setUp(self):
        self.cursor = _BlFakeCursor()
        self.db = Database.__new__(Database)
        self.db.cursor = self.cursor
        self.db.conn = _FakeConn()

    def test_returns_existing_reference(self):
        self.cursor.stored_bl = "BL-2026-3"
        result = self.db.get_import_bl_number(12)
        self.assertEqual(result, "BL-2026-3")
        self.assertEqual(self.db.conn.commits, 0)

    def test_allocates_and_persists_for_legacy_import(self):
        self.cursor.stored_bl = None
        self.cursor.max_number = 6
        result = self.db.get_import_bl_number(12)
        self.assertEqual(result, "BL-2026-7")
        update_sql, update_params = self.cursor.queries[-1]
        self.assertIn("UPDATE imports SET bl_number", update_sql)
        self.assertEqual(update_params, ("BL-2026-7", 12))
        self.assertEqual(self.db.conn.commits, 1)

    def test_raises_for_missing_import(self):
        self.cursor.missing_import = True
        with self.assertRaises(ValueError):
            self.db.get_import_bl_number(999)


class ImportBlServerPermissionTests(unittest.TestCase):
    def _user(self, imports_read=False, imports_write=False):
        return {
            "is_superadmin": False,
            "permissions": {
                "Imports": {
                    "read": imports_read, "write": imports_write, "delete": False,
                },
                "Products": {"read": True, "write": False, "delete": False},
            },
        }

    def test_denied_without_imports_access(self):
        allowed, _ = _check_permission(
            self._user(), "get_import_bl_number", [12], {}
        )
        self.assertFalse(allowed)

    def test_allowed_with_imports_read(self):
        allowed, _ = _check_permission(
            self._user(imports_read=True), "get_import_bl_number", [12], {}
        )
        self.assertTrue(allowed)

    def test_allowed_with_imports_write(self):
        allowed, _ = _check_permission(
            self._user(imports_write=True), "get_import_bl_number", [12], {}
        )
        self.assertTrue(allowed)

    def test_allowed_for_superadmin(self):
        allowed, _ = _check_permission(
            {"is_superadmin": True, "permissions": {}},
            "get_import_bl_number", [12], {},
        )
        self.assertTrue(allowed)

    def test_bl_preview_denied_without_imports_access(self):
        allowed, _ = _check_permission(
            self._user(), "get_next_bl_preview", [], {}
        )
        self.assertFalse(allowed)

    def test_bl_preview_allowed_with_imports_read(self):
        allowed, _ = _check_permission(
            self._user(imports_read=True), "get_next_bl_preview", [], {}
        )
        self.assertTrue(allowed)

    def test_bl_preview_allowed_with_imports_write(self):
        allowed, _ = _check_permission(
            self._user(imports_write=True), "get_next_bl_preview", [], {}
        )
        self.assertTrue(allowed)

    def test_bl_preview_allowed_for_superadmin(self):
        allowed, _ = _check_permission(
            {"is_superadmin": True, "permissions": {}},
            "get_next_bl_preview", [], {},
        )
        self.assertTrue(allowed)


class _FakeImportObj:
    def __init__(self, database=None, **values):
        self.database = database
        self.values = values

    def get_value(self, key):
        return self.values.get(key, "")


class _FakeBdlDatabase:
    """Network-style fake: no cursor, RPC-like item and BL lookups."""

    def __init__(self):
        self.bl_calls = []
        self.username = "TestUser"

    def get_items_by_operation_id(self, operation_id, section):
        return [
            {"product_id": 5, "product_name": "Bois de chêne", "quantity": "12.5"},
            {"product_id": 0, "product_name": "Colle", "quantity": 2},
        ]

    def get_import_bl_number(self, import_id):
        self.bl_calls.append(import_id)
        return "BL-2026-1"


class ImportBdlHtmlTests(unittest.TestCase):
    def setUp(self):
        self.db = _FakeBdlDatabase()
        self.import_obj = _FakeImportObj(
            database=self.db,
            id=12,
            date="2026-07-01",
            supplier_name="Bois Plus SARL",
            supplier_username="boisplus",
            supplier_id=7,
            notes="Livraison complète\nMerci",
        )
        from ui.dialogs.import_bdl_dialog import _ImportBdlWorker
        self.worker = _ImportBdlWorker(self.import_obj, None)

    def test_html_contains_reference_supplier_items_and_quantities(self):
        html = self.worker._generate_html(12, "BL-2026-1")
        self.assertIn("BON DE LIVRAISON", html)
        self.assertIn("BL-2026-1", html)
        self.assertIn("Bois Plus SARL", html)
        self.assertIn("Bois de chêne", html)
        self.assertIn("12.5", html)
        self.assertIn("Colle", html)
        self.assertIn("Fournisseur", html)
        self.assertIn("2026-07-01", html)

    def test_prepare_allocates_bl_and_targets_reports_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "ui.dialogs.import_bdl_dialog.local_reports_dir", return_value=tmp
            ):
                html, output_path = self.worker._prepare()
        self.assertEqual(self.db.bl_calls, [12])
        self.assertIn("BL-2026-1", html)
        self.assertTrue(output_path.startswith(tmp))
        self.assertIn("DELIVERY_NOTE_12_", os.path.basename(output_path))

    def test_prepare_uses_existing_bl_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "ui.dialogs.import_bdl_dialog.local_reports_dir", return_value=tmp
            ):
                _, output_path = self.worker._prepare()
        self.assertEqual(self.db.bl_calls, [12])


class _ImportEditCursor:
    """Minimal scripted cursor driving save_import_with_items' edit path,
    to prove editing an import created by a different user is no longer
    blocked by ownership alone (see ImportCrossUserEditTests below)."""

    def __init__(self):
        self.statements = []
        self.rowcount = 1
        self._normalized = ""

    def execute(self, sql, params=()):
        self._normalized = " ".join(sql.lower().split())
        self.statements.append((self._normalized, params))

    def fetchone(self):
        sql = self._normalized
        if sql.startswith("select id, name, username from suppliers"):
            return (7, "Bois Plus SARL", "boisplus")
        if sql.startswith("select bl_number from imports"):
            return ("BL-2026-9",)
        if sql.startswith("select id, name from products"):
            return (1, "Bois de chêne")
        if "returning id" in sql:
            return (777,)
        return None

    def fetchall(self):
        if self._normalized.startswith("select id from import_items"):
            return []
        return []


class ImportCrossUserEditTests(unittest.TestCase):
    def test_edit_by_different_user_with_imports_write_succeeds(self):
        cursor = _ImportEditCursor()
        db = Database.__new__(Database)
        db.cursor = cursor
        db.conn = _FakeConn()
        db.registered_classes = {"Imports": ImportClass}

        result = db.save_import_with_items(
            {
                "supplier_username": "boisplus", "date": "2026-07-01",
                "tva": 20.0, "is_historical": False,
            },
            [{"product_name": "Bois de chêne", "quantity": "5", "unit_price": "10"}],
            import_id=55,
            visible_row_count=1,
            # Import was created by user 1; user 999 (not a superadmin) is
            # editing it here. Imports:write permission (checked by the RPC
            # layer before this method is ever reached) is the only gate -
            # ownership alone must not block the edit.
            user={"id": 999, "is_superadmin": False},
        )
        self.assertEqual(result["transaction"], "committed")
        self.assertEqual(result["import_id"], 55)
        self.assertEqual(db.conn.commits, 1)
        self.assertFalse(any(
            "created_by" in sql and sql.startswith("select 1 from imports")
            for sql, _ in cursor.statements
        ))


if __name__ == "__main__":
    unittest.main()
