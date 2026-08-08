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


if __name__ == "__main__":
    unittest.main()
