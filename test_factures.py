"""Focused no-database regression tests for the Factures presentation contract."""

import os
import unittest
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.moroccan_dirham_words import amount_to_words
from core.network.server import _check_permission
from ui.tabs.factures_tab import FactureEditor


class _FactureDatabase:
    def __init__(self):
        self.saved = None

    def get_sale_catalog(self, *_args, **_kwargs):
        return {"clients": [{"id": 7, "name": "Client Test", "username": "client.test"}]}

    def save_facture_with_items(self, header, items, facture_id=None):
        self.saved = (header, items, facture_id)
        return {"facture_id": 11, "facture_number": "FA001/2026"}


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


if __name__ == "__main__":
    unittest.main()
