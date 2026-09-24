"""Focused no-database regression tests for the Factures presentation contract."""

import os
import unittest
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from core.moroccan_dirham_words import amount_to_words
from core.database import Database
from core.network.client import RemoteDatabase
from core.network.server import _check_permission
from ui.facture_document import render_facture_preview_pages
from ui.tabs.factures_tab import DevisSelectorDialog, FactureEditor, FacturePreviewDialog, FacturesTab


class _FactureDatabase:
    def __init__(self, clients=None):
        self.saved = None
        self.clients = clients if clients is not None else [
            {"id": 7, "name": "Client Test", "username": "client.test"}
        ]

    def get_sale_catalog(self, *_args, **_kwargs):
        return {"clients": self.clients}

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

    def fetchall(self):
        return []


class _CatalogCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""

    def execute(self, sql, _params=None):
        self.sql = sql

    def fetchall(self):
        return self.rows


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
            (41, "product", "Produit", "Info", "U", Decimal("2"), Decimal("500"), Decimal("0"), 1),
            (42, "section", "Pose", "", "", None, None, None, 2),
            (43, "service", "Installation", "", "ENS", Decimal("1"), Decimal("100"), Decimal("10"), 3),
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


class _MultiDraftDatabase(Database):
    def __init__(self, client_ids):
        super().__init__(); self.client_ids = client_ids

    def get_facture_draft_from_sale(self, sale_id, facture_type="normal", date=None, user=None):
        return {
            "client_id": self.client_ids[sale_id], "source_sale_id": sale_id, "date": "2026-09-23",
            "tva_rate": Decimal("20"), "notes": "", "source_devis": f"DE-{sale_id}",
            "facture_type": facture_type,
            "items": [{"item_type": "manual", "designation": f"Ligne {sale_id}", "quantity": 1,
                       "unit_price": Decimal("100"), "discount_percentage": 0}],
        }


class FactureEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_manual_facture_keeps_decimal_line_data_and_live_totals(self):
        database = _FactureDatabase()
        dialog = FactureEditor(database)
        try:
            dialog.items.cellWidget(0, 0).setCurrentIndex(dialog.items.cellWidget(0, 0).findData("service"))
            dialog.items.cellWidget(0, 1).setCurrentText("Pose")
            dialog._set_client(7)
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
        self.assertIn("CREATE TABLE IF NOT EXISTS FACTURE_SOURCES", statements)
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

    def test_client_catalog_normalizes_the_canonical_primary_key(self):
        database = Database()
        cursor = _CatalogCursor([(7, "client.test", "Client Test", "Rue Test", "ICE7")])
        database.cursor = cursor
        catalog = database.get_sale_catalog(False, False, include_clients=True)
        self.assertEqual(catalog["clients"], [
            {"id": 7, "username": "client.test", "name": "Client Test", "address": "Rue Test", "ice": "ICE7"}
        ])
        self.assertIn("SELECT id, username, name, address, ice FROM clients", cursor.sql)

    def test_client_picker_keeps_the_catalog_outside_the_editor(self):
        empty = FactureEditor(_FactureDatabase([]))
        self.assertTrue(empty.client.isReadOnly())
        self.assertEqual(empty.client.text(), "")
        empty.reject()
        dialog = FactureEditor(_FactureDatabase([
            {"id": 1, "name": None, "username": "alpha"},
            {"id": 2, "name": "Beta SARL", "username": None},
            {"id": 3, "name": None, "username": None},
        ]))
        try:
            self.assertEqual(set(dialog.client_records), {1, 2, 3})
            dialog._set_client(2)
            self.assertEqual(dialog.client.text(), "Beta SARL")
        finally:
            dialog.reject()

    def test_existing_invoice_keeps_a_missing_client_snapshot_identity(self):
        database = _FactureDatabase([])
        facture = {"id": 8, "facture_number": "FA001/2026", "date": "2026-09-23", "facture_type": "normal",
                   "tva_rate": "20", "client_id": 91, "client_name": "Aptiv", "client_address": "Zone industrielle",
                   "client_city": "Tanger", "client_ice": "001", "notes": "", "items": []}
        dialog = FactureEditor(database, facture)
        try:
            self.assertEqual(dialog.client_id, 91)
            self.assertIn("historique", dialog.client.text())
        finally:
            dialog.reject()

    def test_devis_selector_uses_visible_rows_not_an_id_prompt(self):
        database = _FactureDatabase()
        database.get_operation_summary_items = lambda *_args, **_kwargs: [{
            "ID": 18, "devis": "DE-2026-18", "client_name": "Aptiv", "date": "2026-09-23",
            "total_ht": Decimal("22725"), "total_ttc": Decimal("27270"), "state": "confirmed",
        }]
        dialog = DevisSelectorDialog(database)
        try:
            self.assertEqual(dialog.table.item(0, 1).text(), "DE-2026-18")
            dialog.table.item(0, 0).setCheckState(Qt.Checked); dialog.select()
            self.assertEqual(dialog.sale_ids, [18])
        finally:
            dialog.reject()

    def test_advance_and_balance_editors_generate_distinct_financial_lines(self):
        draft = {
            "client_id": 7, "date": "2026-09-23", "tva_rate": Decimal("20"),
            "source_sale_ids": [18, 19], "source_devis": "DE-2026-18 / DE-2026-19",
            "selected_total_ttc": Decimal("500000"), "previous_advance_ttc": Decimal("600000"),
            "remaining_ttc": Decimal("100000"), "items": [],
        }
        advance_db = _FactureDatabase(); advance = FactureEditor(advance_db)
        try:
            draft["facture_type"] = "advance"; advance.load_draft(draft); advance.advance_amount.setValue(200000); advance.save()
            header, lines, _facture_id = advance_db.saved
            self.assertEqual(header["source_sale_ids"], [18, 19])
            self.assertEqual(lines[0]["unit_price"], "166666.67")
            self.assertIn("SUIVANT DEVIS N° DE-2026-18 / DE-2026-19", lines[0]["designation"])
        finally:
            advance.reject()
        balance_db = _FactureDatabase(); balance = FactureEditor(balance_db)
        try:
            draft["facture_type"] = "balance"; balance.load_draft(draft); balance.save()
            _header, lines, _facture_id = balance_db.saved
            self.assertEqual(lines[0]["unit_price"], "83333.33")
            self.assertIn("SOLDE", lines[0]["designation"])
        finally:
            balance.reject()

    def test_multi_devis_rejects_different_clients_before_invoice_creation(self):
        database = _MultiDraftDatabase({18: 7, 19: 8})
        with self.assertRaisesRegex(ValueError, "même client"):
            database.get_facture_draft_from_sales([18, 19])

    def test_main_list_keeps_payment_amounts_in_the_payment_screen(self):
        tab = FacturesTab(_FactureDatabase())
        self.assertEqual([tab.table.horizontalHeaderItem(i).text() for i in range(tab.table.columnCount())], [
            "ID", "Facture N°", "Type", "Client", "Date", "Devis source", "Total TTC", "Statut",
        ])

    def test_preview_defaults_to_fit_page_without_a_scroll_area(self):
        facture = {"facture_number": "FA001/2026", "date": "2026-09-23", "client_name": "Aptiv",
                   "client_address": "Adresse", "client_city": "Tanger", "client_ice": "ICE", "items": [],
                   "total_ht": Decimal("0"), "vat_amount": Decimal("0"), "total_ttc": Decimal("0"),
                   "paid": Decimal("0"), "remaining": Decimal("0"), "amount_in_words": "ZÉRO DIRHAM"}
        pages, _geometry = render_facture_preview_pages(facture, [])
        dialog = FacturePreviewDialog(pages)
        try:
            dialog.show(); self.app.processEvents()
            self.assertEqual(dialog.zoom, 0)
            self.assertLessEqual(dialog.page.pixmap().height(), dialog.page.height())
            self.assertLessEqual(dialog.page.pixmap().width(), dialog.page.width())
        finally:
            dialog.close()

    def test_printable_document_uses_a4_width_and_contains_payment_reference(self):
        facture = {"facture_number": "FA001/2026", "date": "2026-09-23", "client_name": "Aptiv",
                   "client_address": "Adresse", "client_city": "Tanger", "client_ice": "ICE", "source_devis": "DE-1",
                   "items": [{"item_type": "manual", "designation": "Avance", "unit": "ENS", "quantity": 1,
                              "unit_price": Decimal("166666.67"), "discount_percentage": 0}],
                   "total_ht": Decimal("166666.67"), "vat_amount": Decimal("33333.33"), "total_ttc": Decimal("200000"),
                   "paid": Decimal("100000"), "remaining": Decimal("100000"), "amount_in_words": "DEUX CENT MILLE DIRHAMS"}
        pages, geometry = render_facture_preview_pages(
            facture, [{"method": "Chèque", "amount": Decimal("100000"), "reference": "1300019"}]
        )
        self.assertEqual(len(pages), 1)
        self.assertAlmostEqual(geometry["printable_mm"].width(), 182, places=1)
        self.assertAlmostEqual(geometry["printable_px"].width() / geometry["page_px"].width(), 182 / 210, places=2)

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
        self.assertEqual(items[0]["unit"], "U")
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
