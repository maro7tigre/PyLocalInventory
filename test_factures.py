"""Focused no-database regression tests for the Factures presentation contract."""

import os
import unittest
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.moroccan_dirham_words import amount_to_words
from core.database import Database
from core.network.client import RemoteDatabase
from core.network.server import _check_permission
from ui.tabs.factures_tab import FactureEditor, FacturesTab


class _FactureDatabase:
    def __init__(self):
        self.saved = None

    def get_sale_catalog(self, *_args, **_kwargs):
        return {"clients": [{"id": 7, "name": "Client Test", "username": "client.test"}]}

    def save_facture_with_items(self, header, items, facture_id=None):
        self.saved = (header, items, facture_id)
        return {"facture_id": 11, "facture_number": "FA001/2026"}

    def has_permission(self, _section, _action):
        return True

    def list_factures(self):
        return []


class _Cursor:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))


class _Connection:
    def __init__(self):
        self.committed = False
        self.rollback_count = 0

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rollback_count += 1


class _CopyCursor:
    def __init__(self):
        self._fetchone_rows = [(18, 7, "client.test", "Client Test", "2026-09-23", Decimal("20"), "Note", "DE-2026-18")]
        self._fetchall_rows = [[
            (41, "product", "Produit", "Info", Decimal("2"), Decimal("500"), Decimal("0"), 1),
            (42, "section", "Pose", "", None, None, None, 2),
            (43, "service", "Installation", "", Decimal("1"), Decimal("100"), Decimal("10"), 3),
        ]]

    def execute(self, _sql, _params=None):
        pass

    def fetchone(self):
        return self._fetchone_rows.pop(0)

    def fetchall(self):
        return self._fetchall_rows.pop(0)


class _CopyDatabase(Database):
    def __init__(self):
        super().__init__()
        self.cursor = _CopyCursor()
        self.saved = None

    def save_facture_with_items(self, header, items, facture_id=None, user=None):
        self.saved = (header, items, facture_id, user)
        return {"facture_id": 31, "facture_number": "FA001/2026"}


class _PaymentCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return (9,)


class _PaymentDatabase(Database):
    def __init__(self):
        super().__init__()
        self.cursor = _PaymentCursor()
        self.conn = _Connection()

    def get_facture(self, _facture_id, user=None):
        return {"client_id": 7, "remaining": Decimal("100000.00")}


class FactureEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_manual_facture_keeps_decimal_line_data_and_live_totals(self):
        database = _FactureDatabase()
        dialog = FactureEditor(database)
        try:
            dialog.items.item(0, 0).setText("service")
            dialog.items.item(0, 1).setText("Pose")
            dialog.items.item(0, 4).setText("12")
            dialog.items.item(0, 5).setText("15")
            dialog.items.item(0, 6).setText("5")
            dialog.update_totals()
            self.assertEqual(dialog.total_ttc.text(), "Total TTC: 205.20 MAD")
            dialog.save()
            header, items, facture_id = database.saved
            self.assertEqual(header["client_id"], 7)
            self.assertEqual(facture_id, None)
            self.assertEqual(items[0]["item_type"], "service")
            self.assertEqual(items[0]["discount_percentage"], "5")
        finally:
            dialog.reject()

    def test_amount_in_words_for_invoice_totals(self):
        self.assertEqual(amount_to_words(Decimal("200000")), "DEUX CENT MILLE DIRHAMS")
        self.assertEqual(amount_to_words(Decimal("700000")), "SEPT CENT MILLE DIRHAMS")
        self.assertEqual(
            amount_to_words(Decimal("1250.50")),
            "MILLE DEUX CENT CINQUANTE DIRHAMS ET CINQUANTE CENTIMES",
        )

    def test_facture_rpc_permissions_are_explicit(self):
        user = {"is_superadmin": False, "permissions": {
            "Factures": {"read": True, "write": True, "delete": False},
            "Sales": {"read": True, "write": False, "delete": False},
        }}
        self.assertTrue(_check_permission(user, "list_factures", [], {})[0])
        self.assertTrue(_check_permission(user, "create_facture_from_sale", [], {})[0])
        self.assertFalse(_check_permission(user, "delete_facture", [], {})[0])

    def test_additive_migration_creates_only_invoice_objects(self):
        database = Database()
        database.cursor = _Cursor()
        database.conn = _Connection()
        database._ensure_facture_tables()
        statements = "\n".join(sql for sql, _params in database.cursor.statements).upper()
        self.assertIn("CREATE TABLE IF NOT EXISTS FACTURES", statements)
        self.assertIn("CREATE TABLE IF NOT EXISTS FACTURE_ITEMS", statements)
        self.assertIn("ALTER TABLE PAYMENTS ADD COLUMN IF NOT EXISTS FACTURE_ID", statements)
        self.assertIn("FACTURES_NUMBER_UIDX", statements)
        self.assertNotIn("DROP TABLE", statements)
        self.assertTrue(database.conn.committed)
        self.assertEqual(database.conn.rollback_count, 0)

    def test_tab_participates_in_main_window_refresh_lifecycle(self):
        tab = FacturesTab(_FactureDatabase())
        tab.refresh_table(force=True)
        tab.refresh_on_tab_switch()
        self.assertEqual(tab.table.rowCount(), 0)

    def test_invoice_rpc_payloads_are_json_safe(self):
        payload = RemoteDatabase._json_safe({"total": Decimal("1200.00"), "none": None})
        self.assertEqual(payload, {"total": "1200.00", "none": None})

    def test_create_from_devis_copies_an_independent_snapshot_payload(self):
        database = _CopyDatabase()
        result = database.create_facture_from_sale(18, "advance", user={"id": 3})
        header, items, facture_id, user = database.saved
        self.assertEqual(result["facture_id"], 31)
        self.assertIsNone(facture_id)
        self.assertEqual(user, {"id": 3})
        self.assertEqual(header["client_id"], 7)
        self.assertEqual(header["source_sale_id"], 18)
        self.assertEqual(header["source_devis"], "DE-2026-18")
        self.assertEqual(header["facture_type"], "advance")
        self.assertEqual(items[0]["source_sale_item_id"], 41)
        self.assertEqual(items[1]["item_type"], "section")
        self.assertEqual(items[2]["discount_percentage"], Decimal("10"))

    def test_facture_payment_cannot_overallocate_the_shared_ledger(self):
        database = _PaymentDatabase()
        with self.assertRaisesRegex(ValueError, "remaining invoice balance"):
            database.add_facture_payment(5, "100000.01", "2026-09-23")
        payment_id = database.add_facture_payment(5, "100000.00", "2026-09-23", "Virement")
        self.assertEqual(payment_id, 9)
        self.assertTrue(database.conn.committed)
        self.assertIn("INSERT INTO payments", database.cursor.calls[-1][0])


if __name__ == "__main__":
    unittest.main()
