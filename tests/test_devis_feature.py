"""Tests for the canonical, year-scoped Sale Devis reference (DE-YEAR-N).

Covers the host-side resolver/allocator, the read-only preview, the legacy
text backfill, the table/summary integration, and the GUI-side wiring
(SalesClass parameter, StringWidget max length, server permission gate).
Real PostgreSQL is not required - queries are exercised against a scripted
cursor and pure-logic helpers.
"""

import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from classes.sales_class import SalesClass
from core.database import DEVIS_MAX_LENGTH, Database
from core.network.server import _check_permission


class _FakeConn:
    def commit(self):
        pass

    def rollback(self):
        pass


class _DevisFakeCursor:
    """Scripted cursor for the real Database._resolve_sale_devis() and
    get_next_devis_preview()/_ensure_devis_text() code paths."""

    def __init__(self):
        self.queries = []
        self._sql = None
        self.rowcount = 0
        self.max_number = 0
        self.stored_devis = None
        self.duplicate_id = None

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        self._sql = sql

    def fetchone(self):
        if "MAX(devis_number)" in self._sql:
            # The SQL computes COALESCE(MAX(devis_number), 0) + 1 itself.
            return (self.max_number + 1,)
        if "LOWER(BTRIM(devis))" in self._sql:
            if self.duplicate_id is not None:
                return (self.duplicate_id,)
            return None
        if self._sql.strip().startswith("SELECT devis FROM sales"):
            return (self.stored_devis,)
        return None

    def fetchall(self):
        return []


class _SummaryFakeCursor:
    """Scripted cursor for get_operation_summary_items() query capture."""

    def __init__(self):
        self.queries = []
        self.description = []

    def execute(self, sql, params=None):
        self.queries.append(sql)

    def fetchall(self):
        return []


class DevisResolverTests(unittest.TestCase):
    def setUp(self):
        self.cursor = _DevisFakeCursor()
        self.db = Database.__new__(Database)
        self.db.cursor = self.cursor
        self.db.conn = _FakeConn()

    def test_create_allocates_next_per_year_number(self):
        self.cursor.max_number = 524
        header = {"date": "2026-07-01", "devis": "", "devis_number": None}
        self.db._resolve_sale_devis(None, header)
        self.assertEqual(header["devis"], "DE-2026-525")
        self.assertEqual(header["devis_number"], 525)

    def test_create_stores_provided_value_verbatim(self):
        header = {"date": "2026-07-01", "devis": "  DE-2026-525-A  "}
        self.db._resolve_sale_devis(None, header)
        self.assertEqual(header["devis"], "DE-2026-525-A")
        self.assertNotIn("devis_number", header)

    def test_provided_value_is_normalized_case_insensitively_for_dup_check(self):
        header = {"date": "2026-07-01", "devis": "de-2026-525"}
        self.db._resolve_sale_devis(None, header)
        dup_sql, dup_params = self.cursor.queries[-1]
        self.assertIn("LOWER(BTRIM(devis))", dup_sql)
        self.assertEqual(dup_params, ["de-2026-525"])

    def test_duplicate_value_raises(self):
        self.cursor.duplicate_id = 7
        header = {"date": "2026-07-01", "devis": "DE-2026-525"}
        with self.assertRaises(ValueError):
            self.db._resolve_sale_devis(3, header)

    def test_over_length_value_raises_before_any_query(self):
        header = {"date": "2026-07-01", "devis": "X" * (DEVIS_MAX_LENGTH + 1)}
        with self.assertRaises(ValueError):
            self.db._resolve_sale_devis(None, header)
        self.assertEqual(self.cursor.queries, [])

    def test_edit_preserves_stored_reference_when_field_empty(self):
        self.cursor.stored_devis = "DE-2026-525"
        header = {"date": "2026-07-01", "devis": "   "}
        self.db._resolve_sale_devis(9, header)
        self.assertEqual(header["devis"], "DE-2026-525")
        self.assertNotIn("devis_number", header)

    def test_edit_allocates_for_legacy_row_with_no_reference(self):
        self.cursor.stored_devis = None
        self.cursor.max_number = 3
        header = {"date": "2026-01-15", "devis": ""}
        self.db._resolve_sale_devis(9, header)
        self.assertEqual(header["devis"], "DE-2026-4")
        self.assertEqual(header["devis_number"], 4)

    def test_create_with_unmodified_preview_text_recovers_devis_number(self):
        # New Sale pre-fills the Devis field with get_next_devis_preview()'s
        # advisory value; if the user leaves it untouched, it is submitted
        # here exactly like a manually-typed reference. Recovering
        # devis_number from it (since it is still in the exact "DE-YEAR-N"
        # generator format) is the fix for the generator getting stuck: without
        # it, devis_number stays NULL forever and MAX(devis_number) - what
        # _allocate_devis_number() reads - never advances.
        header = {"date": "2026-07-01", "devis": "DE-2026-32"}
        self.db._resolve_sale_devis(None, header)
        self.assertEqual(header["devis"], "DE-2026-32")
        self.assertEqual(header["devis_number"], 32)

    def test_edit_with_unmodified_canonical_text_recovers_devis_number(self):
        # Same recovery on edit - self-heals a previously-affected row the
        # next time it is opened and saved, without changing its devis text.
        header = {"date": "2026-07-01", "devis": "DE-2026-15"}
        self.db._resolve_sale_devis(9, header)
        self.assertEqual(header["devis"], "DE-2026-15")
        self.assertEqual(header["devis_number"], 15)

    def test_customized_reference_with_suffix_does_not_set_devis_number(self):
        # A genuinely hand-edited reference (not the untouched generator
        # format) must not be misread as a sequence number.
        header = {"date": "2026-07-01", "devis": "DE-2026-525-A"}
        self.db._resolve_sale_devis(None, header)
        self.assertNotIn("devis_number", header)

    def test_regression_generator_no_longer_stuck_after_verbatim_save(self):
        """End-to-end reproduction of the reported bug: DE-2026-31 kept being
        proposed to every new Sale because devis_number was never persisted
        for sales saved with the dialog's unmodified preview text.
        """
        # Sale #31 gets saved with its pre-filled preview "DE-2026-31" left
        # untouched (sale_id=None: this is the create path).
        header = {"date": "2026-07-01", "devis": "DE-2026-31"}
        self.db._resolve_sale_devis(None, header)
        self.assertEqual(header["devis_number"], 31)

        # The Postgres MAX(devis_number) the next preview reads now reflects
        # that sale (in the old broken code this stayed at whatever it was
        # before sale #31, so the same "DE-2026-31" kept getting proposed).
        self.cursor.max_number = 31
        self.assertEqual(self.db.get_next_devis_preview("2026-07-02"), "DE-2026-32")


class DevisPreviewTests(unittest.TestCase):
    def setUp(self):
        self.cursor = _DevisFakeCursor()
        self.db = Database.__new__(Database)
        self.db.cursor = self.cursor
        self.db.conn = _FakeConn()

    def test_preview_uses_sale_year_and_next_number(self):
        self.cursor.max_number = 524
        self.assertEqual(self.db.get_next_devis_preview("2026-09-01"), "DE-2026-525")

    def test_preview_defaults_year_to_today(self):
        self.cursor.max_number = 0
        self.assertEqual(
            self.db.get_next_devis_preview(),
            f"DE-{datetime.now().year}-1",
        )

    def test_year_extraction_first_4_digit_group(self):
        self.assertEqual(Database._devis_year_from_date("2026-07-01"), "2026")
        self.assertEqual(Database._devis_year_from_date("bon de livraison 2025"), "2025")
        self.assertEqual(
            Database._devis_year_from_date(None), str(datetime.now().year)
        )

    def test_normalize_exact_collapses_and_casefolds(self):
        self.assertEqual(Database._normalize_exact("  DE  2026-1 "), "de 2026-1")


class DevisBackfillTests(unittest.TestCase):
    def setUp(self):
        self.cursor = _DevisFakeCursor()
        self.db = Database.__new__(Database)
        self.db.cursor = self.cursor
        self.db.conn = _FakeConn()

    def test_backfill_only_touches_empty_text_rows(self):
        self.db._ensure_devis_text()
        sql, params = self.cursor.queries[-1]
        self.assertIn("UPDATE sales", sql)
        self.assertIn("BTRIM(s.devis)", sql)
        self.assertIn("s.devis_number IS NOT NULL", sql)
        self.assertEqual(params, ())

    def test_backfill_restricts_to_requested_sale_ids(self):
        self.db._ensure_devis_text([1, 5])
        sql, params = self.cursor.queries[-1]
        self.assertIn("s.id = ANY(%s)", sql)
        self.assertEqual(params, ([1, 5],))

    def test_summary_query_includes_computed_devis_fallback(self):
        db = Database.__new__(Database)
        cursor = _SummaryFakeCursor()
        db.cursor = cursor
        db.conn = _FakeConn()
        db.get_operation_summary_items("Sales")
        sql = cursor.queries[-1]
        self.assertIn("BTRIM(s.devis)", sql)
        self.assertIn("AS devis", sql)

    def test_imports_summary_has_no_devis_fallback(self):
        db = Database.__new__(Database)
        cursor = _SummaryFakeCursor()
        db.cursor = cursor
        db.conn = _FakeConn()
        db.get_operation_summary_items("Imports")
        sql = cursor.queries[-1]
        self.assertNotIn("BTRIM(s.devis)", sql)
        self.assertNotIn("AS devis", sql)


class SalesClassDevisParameterTests(unittest.TestCase):
    def test_devis_parameter_exists_with_maxlength(self):
        obj = SalesClass(0, None)
        self.assertIn("devis", obj.parameters)
        self.assertEqual(obj.parameters["devis"]["type"], "string")
        self.assertEqual(obj.parameters["devis"].get("maxlength"), DEVIS_MAX_LENGTH)
        self.assertIn(
            "Devis N°", obj.parameters["devis"]["display_name"].values()
        )

    def test_devis_wired_into_all_destinations(self):
        obj = SalesClass(0, None)
        self.assertIn("devis", obj.available_parameters["table"])
        self.assertIn("devis", obj.available_parameters["dialog"])
        self.assertIn("devis", obj.available_parameters["database"])

    def test_table_columns_exact_order(self):
        obj = SalesClass(0, None)
        self.assertEqual(
            list(obj.available_parameters["table"].keys()),
            ["id", "devis", "state", "client_name", "notes", "date",
             "total_ht", "total_ttc"],
        )

    def test_devis_is_not_calculated(self):
        obj = SalesClass(0, None)
        self.assertFalse(obj.is_parameter_calculated("devis"))


class DevisServerPermissionTests(unittest.TestCase):
    def _user(self, sales_read=False, sales_write=False):
        return {
            "is_superadmin": False,
            "permissions": {
                "Sales": {"read": sales_read, "write": sales_write, "delete": False},
                "Clients": {"read": False, "write": False, "delete": False},
            },
        }

    def test_preview_denied_without_sales_access(self):
        allowed, _ = _check_permission(self._user(), "get_next_devis_preview", [], {})
        self.assertFalse(allowed)

    def test_preview_allowed_with_sales_read(self):
        allowed, _ = _check_permission(
            self._user(sales_read=True), "get_next_devis_preview", [], {}
        )
        self.assertTrue(allowed)

    def test_preview_allowed_with_sales_write(self):
        allowed, _ = _check_permission(
            self._user(sales_write=True), "get_next_devis_preview", [], {}
        )
        self.assertTrue(allowed)

    def test_preview_allowed_for_superadmin(self):
        allowed, _ = _check_permission(
            {"is_superadmin": True, "permissions": {}},
            "get_next_devis_preview", [], {},
        )
        self.assertTrue(allowed)


class DevisGuiWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_string_widget_enforces_maxlength(self):
        from ui.widgets.parameters_widgets import StringWidget
        widget = StringWidget({"type": "string", "maxlength": DEVIS_MAX_LENGTH})
        widget.setText("X" * 100)
        self.assertEqual(len(widget.text()), DEVIS_MAX_LENGTH)

    def test_load_worker_captures_preview_off_thread(self):
        from ui.dialogs.edit_dialogs.base_operation_dialog import LoadWorker

        class RemoteDatabase:
            def __init__(self):
                self.preview_calls = []
                self.sale_catalog = None

            def get_next_devis_preview(self, date=None):
                self.preview_calls.append(date)
                return "DE-2026-525"

            def has_permission(self, section, action="read"):
                return True

        db = RemoteDatabase()
        worker = LoadWorker(None, db, fetch_catalog=False, fetch_devis_preview=True)
        worker.process()
        self.assertEqual(worker.devis_preview, "DE-2026-525")
        self.assertEqual(db.preview_calls, [None])

    def test_load_worker_skips_preview_when_disabled(self):
        from ui.dialogs.edit_dialogs.base_operation_dialog import LoadWorker

        class RemoteDatabase:
            def __init__(self):
                self.preview_calls = []

            def get_next_devis_preview(self, date=None):
                self.preview_calls.append(date)
                return "DE-2026-525"

            def has_permission(self, section, action="read"):
                return True

        db = RemoteDatabase()
        worker = LoadWorker(None, db, fetch_catalog=False, fetch_devis_preview=False)
        worker.process()
        self.assertIsNone(worker.devis_preview)
        self.assertEqual(db.preview_calls, [])


if __name__ == "__main__":
    unittest.main()
