"""Regression tests: Sales state widget survives refresh + client debt rules."""

import os
import unittest
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QPushButton

from core.sales_states import is_financially_active, sale_state_label
from ui.dialogs.client_details_dialog import ClientDetailsDialog, _ClientReportWorker
from ui.tabs.sales_tab import SalesTab


class _ReadOnlyDatabase:
    """Minimal host-like stand-in; named RemoteDatabase to skip local DDL."""

    offline = False
    remote_profile = None

    def has_permission(self, *_args):
        return True

    def get_client_sale_summaries(self, _client_id):
        return ACCOUNT


class _Sale:
    def __init__(self, sale_id, state):
        self.id = sale_id
        self._state = state

    def get_value(self, key):
        return {"state": self._state, "is_historical": False}.get(key, "")


def _state_button(widget):
    if widget is None:
        return None
    return next(iter(widget.findChildren(QPushButton)), None)


ACCOUNT = {
    "sales": [
        {"sale_id": 6, "date": "2026-08-03", "state": "pending", "is_historical": False,
         "devis": "DE-2026-6", "total": "10000.00", "paid": "0", "remaining": "10000.00"},
        {"sale_id": 7, "date": "2026-08-03", "state": "on_hold", "is_historical": False,
         "devis": "DE-2026-7", "total": "5000.00", "paid": "0", "remaining": "5000.00"},
        {"sale_id": 8, "date": "2026-08-03", "state": "confirmed", "is_historical": False,
         "devis": "DE-2026-8", "total": "20000.00", "paid": "5000.00", "remaining": "15000.00"},
        {"sale_id": 9, "date": "2026-08-06", "state": "finished", "is_historical": False,
         "devis": "DE-2026-9", "total": "30000.00", "paid": "30000.00", "remaining": "0"},
        # Legacy inconsistency: a payment exists against a still-pending Devis.
        {"sale_id": 10, "date": "2026-08-07", "state": "pending", "is_historical": False,
         "devis": "DE-2026-10", "total": "14400.00", "paid": "100.00", "remaining": "14300.00"},
    ],
    "payments": [
        {"payment_id": 1, "sale_id": 8, "item_id": None, "date": "2026-08-04", "amount": "5000.00"},
        {"payment_id": 2, "sale_id": 10, "item_id": None, "date": "2026-08-08", "amount": "100.00"},
        {"payment_id": 3, "sale_id": None, "item_id": None, "date": "2026-08-09", "amount": "1000.00"},
    ],
}


class SalesStateRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        database = type("DB", (), {"has_permission": lambda self, *a: True})()
        self.tab = SalesTab(database)
        self.tab.table_columns = ["id", "state", "is_historical"]
        self.tab.table.setColumnCount(3)

    def tearDown(self):
        self.tab.deleteLater()

    def test_pending_state_button_survives_in_place_refresh(self):
        pending = _Sale(1, "pending")
        self.tab.populate_table_with_items([pending])
        self.tab.all_items = [pending]
        self.assertTrue(self.tab._reconcile_in_place([pending], [pending]))
        button = _state_button(self.tab.table.cellWidget(0, 1))
        self.assertIsNotNone(button, "state widget was replaced by plain text")
        self.assertEqual(button.text(), "Pending")
        self.assertIn("#FF9800", button.styleSheet())

    def test_confirmed_state_button_stays_green_and_clickable(self):
        pending, confirmed = _Sale(1, "pending"), _Sale(2, "confirmed")
        self.tab.populate_table_with_items([pending, confirmed])
        self.tab.all_items = [pending, confirmed]
        self.tab._reconcile_in_place([pending, confirmed], [pending, confirmed])
        button = _state_button(self.tab.table.cellWidget(1, 1))
        self.assertIsNotNone(button)
        self.assertEqual(button.text(), "Confirmed")
        self.assertIn("#4CAF50", button.styleSheet())
        self.tab._state_popup = None
        button.click()
        self.app.processEvents()
        self.assertIsNotNone(getattr(self.tab, "_state_popup", None))
        self.tab._state_popup.close()


class StatePopupPlacementTests(unittest.TestCase):
    """The State popup must stay inside the screen working area (taskbar-free)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.screen = QGuiApplication.primaryScreen()
        cls.available = cls.screen.availableGeometry()

    def setUp(self):
        self.tab = SalesTab(type("DB", (), {"has_permission": lambda self, *a: True})())

    def tearDown(self):
        popup = getattr(self.tab, "_state_popup", None)
        if popup is not None:
            popup.close()
        self.tab.deleteLater()

    def _anchor_at(self, y):
        """A real top-level button placed at an exact global y position."""
        button = QPushButton("State")
        button.resize(90, 24)
        button.move(self.available.left() + 40, y)
        button.show()
        self.app.processEvents()
        return button

    def _open_popup_for(self, anchor):
        self.tab._open_state_popup(_Sale(1, "pending"), anchor)
        self.app.processEvents()
        return self.tab._state_popup

    def test_popup_opens_below_for_a_row_near_the_top(self):
        popup = self._open_popup_for(self._anchor_at(self.available.top() + 20))
        anchor_bottom = self.available.top() + 20 + 24
        self.assertGreaterEqual(popup.y(), anchor_bottom)
        self.assertTrue(self.available.contains(popup.geometry()))

    def test_popup_opens_below_for_a_row_in_the_middle(self):
        middle = self.available.center().y()
        popup = self._open_popup_for(self._anchor_at(middle - 12))
        self.assertGreaterEqual(popup.y(), middle + 12)
        self.assertTrue(self.available.contains(popup.geometry()))

    def test_popup_flips_above_for_the_last_row_near_the_taskbar(self):
        # Anchor hugging the bottom of the working area: no room below.
        anchor = self._anchor_at(self.available.bottom() - 24)
        popup = self._open_popup_for(anchor)
        self.assertLessEqual(popup.geometry().bottom(), anchor.mapToGlobal(QPoint(0, 0)).y())
        self.assertTrue(self.available.contains(popup.geometry()))
        # Every option must still be reachable, not clipped.
        self.assertLessEqual(popup.height(), self.available.height())

    def test_popup_never_crosses_either_screen_edge(self):
        for x in (self.available.left() - 30, self.available.right() - 20):
            anchor = self._anchor_at(self.available.center().y() - 12)
            anchor.move(x, anchor.y())
            self.app.processEvents()
            popup = self._open_popup_for(anchor)
            self.assertGreaterEqual(popup.x(), self.available.left())
            self.assertLessEqual(popup.geometry().right(), self.available.right())
            popup.close()

    def test_popup_fits_after_resizing_to_a_small_window(self):
        for width, height in ((420, 320), (900, 600), (1600, 1000)):
            self.tab.resize(width, height)
            self.app.processEvents()
            anchor = self._anchor_at(self.available.bottom() - 24)
            popup = self._open_popup_for(anchor)
            self.assertTrue(
                self.available.contains(popup.geometry()),
                f"popup escaped the working area at {width}x{height}",
            )
            popup.close()

    def test_all_state_options_and_cancel_remain_present_and_clickable(self):
        popup = self._open_popup_for(self._anchor_at(self.available.top() + 20))
        labels = [button.text() for button in popup.findChildren(QPushButton)]
        self.assertEqual(
            labels, ["On Hold", "Pending", "Confirmed", "Finished", "Cancel"]
        )
        for button in popup.findChildren(QPushButton):
            self.assertTrue(button.isVisible())
            self.assertTrue(button.isEnabled())
        # Cancel must still be wired to the cancel handler. The real handler
        # shows a blocking confirmation, so it is replaced here.
        calls = []
        self.tab._cancel_sale_from_popup = lambda pop, _obj: (calls.append(pop), pop.close())
        popup.findChildren(QPushButton)[-1].click()
        self.app.processEvents()
        self.assertEqual(len(calls), 1, "Cancel is not wired to the cancel handler")
        self.assertFalse(popup.isVisible())


class ClientActiveDebtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        database = type("RemoteDatabase", (_ReadOnlyDatabase,), {})()
        client = type("C", (), {
            "id": 1,
            "get_value": lambda self, key: {"name": "Aptiv", "username": "aptiv"}.get(key),
        })()
        self.dialog = ClientDetailsDialog(client, database)
        # The dialog loads asynchronously; drive the deterministic path.
        self.dialog._apply_account_data(ACCOUNT)

    def tearDown(self):
        self.dialog.deleteLater()

    def test_only_confirmed_and_finished_states_are_active(self):
        self.assertFalse(is_financially_active("on_hold"))
        self.assertFalse(is_financially_active("pending"))
        self.assertTrue(is_financially_active("confirmed"))
        self.assertTrue(is_financially_active("finished"))
        self.assertEqual(sale_state_label("on_hold"), "On Hold")

    def test_every_devis_stays_visible_with_state_and_amount(self):
        table = self.dialog.purchases_table
        self.assertEqual(
            [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())],
            ["Sale #", "Date", "Devis", "State", "Amount"],
        )
        self.assertEqual(table.rowCount(), 5)
        self.assertEqual(table.item(0, 3).text(), "Pending")
        self.assertEqual(table.item(1, 3).text(), "On Hold")
        self.assertEqual(table.item(3, 3).text(), "Finished")
        self.assertEqual(table.item(0, 4).text(), "—")
        self.assertEqual(table.item(1, 4).text(), "—")
        self.assertIn("20 000.00", table.item(2, 4).text())
        self.assertIn("30 000.00", table.item(3, 4).text())

    def test_totals_only_count_active_sales_and_active_payments(self):
        self.assertTrue(self.dialog.total_bought_label.text().startswith("50 000.00"))
        # 5 000 (confirmed) + 30 000 (finished) + 1 000 general; the legacy
        # 100 paid against the pending Devis is history, not active credit.
        self.assertTrue(self.dialog.total_paid_label.text().startswith("36 000.00"))
        self.assertTrue(self.dialog.remaining_label.text().startswith("14 000.00"))

    def test_payment_history_keeps_every_record(self):
        self.assertEqual(self.dialog.payments_table.rowCount(), 3)

    def test_pending_selection_blocks_sale_payment_but_allows_printing(self):
        self.dialog.purchases_table.setCurrentCell(0, 0)
        self.dialog._purchase_selected(0, 0, -1, -1)
        self.assertFalse(self.dialog.amount_input.isEnabled())
        self.assertFalse(self.dialog.add_payment_button.isEnabled())
        self.assertTrue(self.dialog.print_selected_btn.isEnabled())
        self.assertIn("confirm", self.dialog.selected_remaining_label.text())

    def test_confirmed_selection_allows_payment_and_shows_remaining(self):
        self.dialog.purchases_table.setCurrentCell(2, 0)
        self.dialog._purchase_selected(2, 0, 0, 0)
        self.assertTrue(self.dialog.amount_input.isEnabled())
        self.assertIn("15 000.00", self.dialog.selected_remaining_label.text())

    def test_general_payment_mode_still_available(self):
        self.dialog._purchase_selected(-1, -1, -1, -1)
        self.assertTrue(self.dialog.amount_input.isEnabled())
        self.assertIn("General Payment", self.dialog.selected_sale_label.text())


def _statement_worker(report_type, selected_sale_id=None):
    worker = _ClientReportWorker(
        report_type, {"name": "Aptiv"}, {"currency": "MAD"},
        _ReadOnlyDatabase(), 1, selected_sale_id,
    )
    worker.purchases = [
        {"sale_id": 6, "date": "2026-08-03", "state": "pending", "quantity": 1, "unit_price": 10000,
         "remise": 0, "vat": 0, "product": "P", "information": ""},
        {"sale_id": 8, "date": "2026-08-03", "state": "confirmed", "quantity": 1, "unit_price": 20000,
         "remise": 0, "vat": 0, "product": "P", "information": ""},
        {"sale_id": 9, "date": "2026-08-06", "state": "finished", "quantity": 1, "unit_price": 30000,
         "remise": 0, "vat": 0, "product": "P", "information": ""},
    ]
    worker.payments = [
        {"payment_id": 1, "sale_id": 8, "item_id": None, "date": "2026-08-04", "amount": "5000.00"},
        {"payment_id": 2, "sale_id": 10, "item_id": None, "date": "2026-08-08", "amount": "100.00"},
        {"payment_id": 3, "sale_id": None, "item_id": None, "date": "2026-08-09", "amount": "1000.00"},
    ]
    worker.sale_state_by_id = {6: "pending", 8: "confirmed", 9: "finished"}
    return worker


class ClientStatementRuleTests(unittest.TestCase):
    def test_statement_totals_match_the_view_client_rule(self):
        worker = _statement_worker("full_statement")
        sections = {
            purchase["sale_id"]: worker._render_sale_section(purchase["sale_id"], [purchase], "MAD")
            for purchase in worker.purchases
        }
        total_sales = sum(worker.sale_ttc_by_id.values(), Decimal("0"))
        total_paid = sum(worker.sale_paid_by_id.values(), Decimal("0")) + Decimal("1000.00")
        self.assertEqual(total_sales, Decimal("50000.00"))
        self.assertEqual(total_paid, Decimal("6000.00"))
        self.assertEqual(max(total_sales - total_paid, Decimal("0")), Decimal("44000.00"))
        self.assertEqual(worker.sale_ttc_by_id[6], Decimal("0"))
        self.assertIn("DEVIS NON CONFIRM", sections[6])
        self.assertNotIn("Total TTC", sections[6])
        self.assertIn("Reste à payer : <strong>— (devis non confirmé)", sections[6])

    def test_pending_sale_document_is_still_printable_in_full(self):
        worker = _statement_worker("selected_sale", 6)
        document = worker._render_sale_section(6, worker.purchases[:1], "MAD")
        self.assertIn("Total TTC", document)
        self.assertIn("Reste à payer", document)
        self.assertNotIn("DEVIS NON CONFIRM", document)


if __name__ == "__main__":
    unittest.main()
