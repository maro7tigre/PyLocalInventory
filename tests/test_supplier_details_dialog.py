"""Dialog-level tests for the View Supplier account feature.

Mirrors the client-side dialog tests in test_client_account.py: the
SupplierDetailsDialog is driven with a scripted in-memory database stub and
per-Import summary fixtures, and the report worker is exercised against the
real supplier statement template.
"""

import json
import os
import tempfile
import time
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QDialog

import ui.dialogs.supplier_details_dialog as sdd_module
from ui.dialogs.supplier_details_dialog import (
    _EditPaymentDialog,
    _PaymentDeleteWorker,
    _PaymentUpdateWorker,
    _SupplierAccountWorker,
    _SupplierReportWorker,
    SupplierDetailsDialog,
)


def _canonical_import(import_id, **overrides):
    row = {
        "import_id": import_id,
        "date": "01-08-2026",
        "bl_number": f"BL-2026-{import_id}",
        "is_historical": False,
        "total": Decimal("0"),
        "paid": Decimal("0"),
        "remaining": Decimal("0"),
    }
    row.update(overrides)
    return row


def _canonical_payment(payment_id, import_id, amount, item_id=None, date="01-08-2026"):
    return {
        "payment_id": payment_id,
        "import_id": import_id,
        "item_id": item_id,
        "date": date,
        "amount": amount,
    }


def _canonical_item(import_id, item_id, **overrides):
    row = {
        "import_id": import_id,
        "date": "01-08-2026",
        "item_id": item_id,
        "product": f"item-{item_id}",
        "quantity": Decimal("1"),
        "unit_price": Decimal("0"),
        "vat": Decimal("20"),
        "notes": "",
        "is_historical": False,
        "created_by_username": "host",
    }
    row.update(overrides)
    return row


def _supplier_obj():
    supplier = MagicMock()
    supplier.id = 1

    def get_value(key):
        values = {
            "id": 1,
            "name": "Fournisseur Alpha",
            "username": "fournisseur-alpha",
            "preview_image": None,
            "phone": "0612345678",
            "email": None,
            "address": "Asilah",
            "notes": None,
        }
        return values.get(key)

    supplier.get_value.side_effect = get_value
    return supplier


class _StubDatabase:
    """Host-style database: per-Import summaries, write permission, no network."""

    def __init__(self, account):
        self.account = account

    def has_permission(self, section, action="read"):
        return True

    def get_supplier_import_summaries(self, supplier_id):
        return self.account

    def add_supplier_payment(self, supplier_id, import_id, import_item_id, amount, date):
        return None

    def update_supplier_payment(self, payment_id, amount):
        return None

    def delete_supplier_payment(self, payment_id):
        return None


class _ReadOnlyDatabase(_StubDatabase):
    def has_permission(self, section, action="read"):
        return action == "read"


class _FailingDatabase(_StubDatabase):
    def get_supplier_import_summaries(self, supplier_id):
        raise RuntimeError("host is down")


class SupplierDetailsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _build_dialog(self, account, database_cls=_StubDatabase):
        database = database_cls(account)
        with patch.object(SupplierDetailsDialog, "refresh_data", lambda self: None):
            dialog = SupplierDetailsDialog(_supplier_obj(), database)
        self.addCleanup(dialog.close)
        dialog._apply_account_data(account)
        return dialog

    def test_single_import_shows_total_and_remaining(self):
        account = {
            "imports": [
                _canonical_import(1, total=Decimal("120.00"), paid=Decimal("0"),
                                  remaining=Decimal("120.00")),
            ],
            "payments": [],
        }
        dialog = self._build_dialog(account)
        self.assertEqual(len(dialog.imports), 1)
        self.assertEqual(dialog.imports[0]["total"], Decimal("120.00"))
        self.assertEqual(dialog.imports[0]["remaining"], Decimal("120.00"))
        self.assertEqual(dialog.purchases_table.rowCount(), 1)
        self.assertEqual(dialog.total_bought_label.text(), "120.00 MAD")

    def test_multiple_imports_with_payments_and_remaining(self):
        account = {
            "imports": [
                _canonical_import(1, total=Decimal("200.00"), paid=Decimal("50.00"),
                                  remaining=Decimal("150.00")),
                _canonical_import(2, total=Decimal("1000.00"), paid=Decimal("1000.00"),
                                  remaining=Decimal("0.00")),
            ],
            "payments": [
                _canonical_payment(1, 1, amount=50),
                _canonical_payment(2, 2, amount=2000),  # overpayment capped at total
            ],
        }
        dialog = self._build_dialog(account)
        self.assertEqual(dialog.imports[0]["remaining"], Decimal("150.00"))
        self.assertEqual(dialog.imports[1]["paid"], Decimal("1000.00"))
        self.assertEqual(dialog.imports[1]["remaining"], Decimal("0.00"))
        self.assertEqual(dialog.total_bought_label.text(), "1 200.00 MAD")
        self.assertEqual(dialog.total_paid_label.text(), "1 050.00 MAD")
        self.assertEqual(dialog.remaining_label.text(), "150.00 MAD")
        self.assertEqual(dialog.payments_table.rowCount(), 2)

    def test_import_rows_show_bl_and_historical_status(self):
        account = {
            "imports": [
                _canonical_import(1, bl_number="BL-2026-1"),
                _canonical_import(2, bl_number="BL-2026-2", is_historical=True),
            ],
            "payments": [],
        }
        dialog = self._build_dialog(account)
        self.assertEqual(dialog.purchases_table.rowCount(), 2)
        self.assertEqual(dialog.purchases_table.item(0, 2).text(), "BL N° BL-2026-1")
        self.assertEqual(dialog.purchases_table.item(1, 2).text(), "BL N° BL-2026-2")
        self.assertEqual(dialog.purchases_table.item(0, 3).text(), "-")
        self.assertEqual(dialog.purchases_table.item(1, 3).text(), "Historique")
        # Row maps to the Import ID (hidden item-level data is fetched on demand).
        self.assertEqual(int(dialog.purchases_table.item(0, 0).data(Qt.UserRole)), 1)
        self.assertEqual(int(dialog.purchases_table.item(1, 0).data(Qt.UserRole)), 2)

    def test_import_history_has_exactly_four_columns(self):
        account = {
            "imports": [
                _canonical_import(1, date="31-07-2026"),
                _canonical_import(2, date="31-07-2026"),
                _canonical_import(3, date="03-08-2026"),
            ],
            "payments": [],
        }
        dialog = self._build_dialog(account)
        headers = [
            dialog.purchases_table.horizontalHeaderItem(c).text()
            for c in range(dialog.purchases_table.columnCount())
        ]
        self.assertEqual(headers, ["Import #", "Date", "BL N°", "Status"])
        self.assertEqual(dialog.purchases_table.columnCount(), 4)
        self.assertEqual(dialog.purchases_table.rowCount(), 3)
        for r, (import_id, date, bl) in enumerate(
            [("#1", "31/07/2026", "BL N° BL-2026-1"),
             ("#2", "31/07/2026", "BL N° BL-2026-2"),
             ("#3", "03/08/2026", "BL N° BL-2026-3")]
        ):
            self.assertEqual(dialog.purchases_table.item(r, 0).text(), import_id)
            self.assertEqual(dialog.purchases_table.item(r, 1).text(), date)
            self.assertEqual(dialog.purchases_table.item(r, 2).text(), bl)
            self.assertEqual(
                int(dialog.purchases_table.item(r, 0).data(Qt.UserRole)), r + 1
            )

    def test_import_with_many_items_still_one_row(self):
        account = {
            "imports": [
                _canonical_import(1, bl_number="BL-2026-1", total=Decimal("500.00"),
                                  paid=Decimal("0"), remaining=Decimal("500.00")),
            ],
            "payments": [],
        }
        dialog = self._build_dialog(account)
        self.assertEqual(dialog.purchases_table.rowCount(), 1)
        self.assertEqual(dialog.purchases_table.item(0, 2).text(), "BL N° BL-2026-1")

    def test_payment_history_has_exactly_five_columns(self):
        account = {
            "imports": [_canonical_import(2, bl_number="BL-2026-2")],
            "payments": [_canonical_payment(1, 2, amount=10000, item_id=None)],
        }
        dialog = self._build_dialog(account)
        headers = [
            dialog.payments_table.horizontalHeaderItem(c).text()
            for c in range(dialog.payments_table.columnCount())
        ]
        self.assertEqual(headers, ["Payment #", "Import #", "Date", "Amount", "BL N°"])
        # Payment -> Import -> BL reference (payment itself carries no BL).
        self.assertEqual(dialog.payments_table.item(0, 0).text(), "#1")
        self.assertEqual(dialog.payments_table.item(0, 1).text(), "#2")
        self.assertEqual(dialog.payments_table.item(0, 3).text(), "10 000.00")
        self.assertEqual(dialog.payments_table.item(0, 4).text(), "BL N° BL-2026-2")
        self.assertEqual(dialog.bl_by_import[2], "BL-2026-2")

    def test_print_buttons_start_disabled_then_statement_enabled_after_load(self):
        account = {
            "imports": [_canonical_import(1, total=Decimal("10.00"),
                                          paid=Decimal("0"), remaining=Decimal("10.00"))],
            "payments": [],
        }
        database = _StubDatabase(account)
        with patch.object(SupplierDetailsDialog, "refresh_data", lambda self: None):
            dialog = SupplierDetailsDialog(_supplier_obj(), database)
        self.addCleanup(dialog.close)
        self.assertFalse(dialog.print_selected_btn.isEnabled())
        self.assertFalse(dialog.print_statement_btn.isEnabled())
        dialog._apply_account_data(account)
        self.assertTrue(dialog.print_statement_btn.isEnabled())

    def test_selecting_import_row_enables_selected_import_print(self):
        account = {
            "imports": [
                _canonical_import(1, total=Decimal("10.00")),
                _canonical_import(2, total=Decimal("20.00")),
            ],
            "payments": [],
        }
        dialog = self._build_dialog(account)
        self.assertFalse(dialog.print_selected_btn.isEnabled())
        dialog.purchases_table.setCurrentCell(1, 0)
        self.assertTrue(dialog.print_selected_btn.isEnabled())

    def test_print_selected_import_uses_selected_import_id(self):
        account = {
            "imports": [
                _canonical_import(1, total=Decimal("10.00")),
                _canonical_import(7, total=Decimal("20.00")),
            ],
            "payments": [],
        }
        dialog = self._build_dialog(account)
        dialog.purchases_table.setCurrentCell(1, 0)
        with patch.object(dialog, "_start_report_worker") as start:
            dialog._print_selected_import()
        start.assert_called_once_with("selected_import", 7)

    def test_selected_bar_shows_import_bl_and_remaining(self):
        account = {
            "imports": [_canonical_import(3, total=Decimal("200.00"),
                                          paid=Decimal("50.00"), remaining=Decimal("150.00"))],
            "payments": [],
        }
        dialog = self._build_dialog(account)
        dialog.purchases_table.setCurrentCell(0, 0)
        self.assertEqual(dialog.selected_import_label.text(), "Selected Import #3")
        self.assertEqual(dialog.selected_bl_label.text(), "BL: BL N° BL-2026-3")
        self.assertEqual(dialog.selected_remaining_label.text(), "Remaining: 150.00 MAD")
        self.assertTrue(dialog.amount_input.isEnabled())
        self.assertTrue(dialog.add_payment_button.isEnabled())

    def test_first_load_error_keeps_empty_tables_and_marks_loaded_once(self):
        database = _StubDatabase({"imports": [], "payments": []})
        with patch.object(SupplierDetailsDialog, "refresh_data", lambda self: None):
            dialog = SupplierDetailsDialog(_supplier_obj(), database)
        self.addCleanup(dialog.close)
        with patch("ui.dialogs.supplier_details_dialog.QMessageBox.critical") as critical:
            dialog._on_account_load_error("boom")
        critical.assert_called_once()
        # A failed first load never pretends an empty account is the truth.
        self.assertFalse(dialog._account_loaded_once)
        self.assertEqual(dialog.purchases_table.rowCount(), 0)

    def test_failed_refresh_keeps_previously_loaded_data(self):
        account = {
            "imports": [_canonical_import(1, total=Decimal("12.00"),
                                          paid=Decimal("0"), remaining=Decimal("12.00"))],
            "payments": [],
        }
        database = _StubDatabase(account)
        with patch.object(SupplierDetailsDialog, "refresh_data", lambda self: None):
            dialog = SupplierDetailsDialog(_supplier_obj(), database)
        self.addCleanup(dialog.close)
        dialog._apply_account_data(account)
        with patch("ui.dialogs.supplier_details_dialog.QMessageBox.warning") as warning:
            dialog._on_account_load_error("network down")
        warning.assert_called_once()
        self.assertEqual(dialog.purchases_table.rowCount(), 1)
        self.assertEqual(dialog.total_bought_label.text(), "12.00 MAD")

    def test_lan_round_trip_stringified_numbers_still_total(self):
        # The LAN server serializes results with json.dumps(default=str), so a
        # RemoteDatabase receives numeric strings instead of Decimals. The
        # dialog must total them exactly like the host-side Decimal path.
        account = {
            "imports": [
                _canonical_import(1, total=Decimal("200.00"), paid=Decimal("50.00"),
                                  remaining=Decimal("150.00")),
                _canonical_import(2, total=Decimal("1000.00"), paid=Decimal("1000.00"),
                                  remaining=Decimal("0.00")),
            ],
            "payments": [
                _canonical_payment(1, 1, amount=50),
                _canonical_payment(2, 2, amount=2000),
            ],
        }
        over_wire = json.loads(json.dumps(account, default=str))
        dialog = self._build_dialog(over_wire)
        self.assertEqual(dialog.total_bought_label.text(), "1 200.00 MAD")
        self.assertEqual(dialog.total_paid_label.text(), "1 050.00 MAD")
        self.assertEqual(dialog.remaining_label.text(), "150.00 MAD")
        self.assertEqual(dialog.imports[0]["remaining"], Decimal("150.00"))

    def test_read_only_mode_when_imports_write_denied(self):
        account = {
            "imports": [_canonical_import(1, total=Decimal("100.00"),
                                          paid=Decimal("0"), remaining=Decimal("100.00"))],
            "payments": [],
        }
        dialog = self._build_dialog(account, database_cls=_ReadOnlyDatabase)
        self.assertFalse(dialog.can_record_payment)
        self.assertIn("Read-only view", dialog.imports_hint_label.text())

    def test_add_payment_records_import_level_payment(self):
        account = {
            "imports": [_canonical_import(1, total=Decimal("100.00"),
                                          paid=Decimal("0"), remaining=Decimal("100.00"))],
            "payments": [],
        }
        database = _StubDatabase(account)
        with patch.object(SupplierDetailsDialog, "refresh_data", lambda self: None):
            dialog = SupplierDetailsDialog(_supplier_obj(), database)
        self.addCleanup(dialog.close)
        dialog._apply_account_data(account)
        dialog.date_input.setDate(QDate(2026, 8, 1))
        with patch.object(database, "add_supplier_payment") as add:
            add.side_effect = lambda *_args: None
            dialog.purchases_table.setCurrentCell(0, 0)
            dialog.amount_input.setText("50")
            with patch("ui.dialogs.supplier_details_dialog.QMessageBox.information"):
                dialog.add_payment()
        # Import-level payment: item_id is None.
        add.assert_called_once_with(1, 1, None, 50.0, "01-08-2026")
        # add_payment() called the REAL refresh_data() here (the construction
        # patch scope already ended), which kicks off a genuine async
        # account-fetch QThread. Pump the event loop until it finishes so the
        # queued QThread.finished cleanup (_on_account_thread_finished) runs
        # before the test exits - otherwise a dangling thread wrapper on the
        # closed dialog triggers a PySide6 native fail-fast at shutdown.
        thread = getattr(dialog, "_account_thread", None)
        deadline = time.time() + 3.0
        while thread and thread.isRunning() and time.time() < deadline:
            QApplication.processEvents()
            time.sleep(0.005)
        for _ in range(10):
            QApplication.processEvents()

    def test_add_payment_blocks_overpayment(self):
        account = {
            "imports": [_canonical_import(1, total=Decimal("100.00"),
                                          paid=Decimal("0"), remaining=Decimal("100.00"))],
            "payments": [],
        }
        database = _StubDatabase(account)
        with patch.object(SupplierDetailsDialog, "refresh_data", lambda self: None):
            dialog = SupplierDetailsDialog(_supplier_obj(), database)
        self.addCleanup(dialog.close)
        dialog._apply_account_data(account)
        dialog.purchases_table.setCurrentCell(0, 0)
        dialog.amount_input.setText("200")
        with patch.object(database, "add_supplier_payment") as add, patch(
            "ui.dialogs.supplier_details_dialog.QMessageBox.warning"
        ) as warning:
            dialog.add_payment()
        add.assert_not_called()
        warning.assert_called_once()

    def test_add_payment_without_selection_is_a_noop(self):
        account = {
            "imports": [_canonical_import(1, total=Decimal("100.00"))],
            "payments": [],
        }
        database = _StubDatabase(account)
        with patch.object(SupplierDetailsDialog, "refresh_data", lambda self: None):
            dialog = SupplierDetailsDialog(_supplier_obj(), database)
        self.addCleanup(dialog.close)
        dialog._apply_account_data(account)
        with patch.object(database, "add_supplier_payment") as add, patch(
            "ui.dialogs.supplier_details_dialog.QMessageBox.information"
        ) as info:
            dialog.add_payment()
        add.assert_not_called()
        info.assert_called_once()

    def test_edit_payment_dialog_validates_amount_range(self):
        dialog = _EditPaymentDialog(None, payment_id=3, import_id=1, bl="BL-2026-1",
                                    current=Decimal("40.00"), max_allowed=Decimal("160.00"))
        dialog.amount_edit.setText("200")
        with patch("ui.dialogs.supplier_details_dialog.QMessageBox.warning") as warning:
            dialog._validate_and_accept()
        warning.assert_called_once()
        self.assertEqual(dialog.result(), 0)
        dialog.amount_edit.setText("60")
        dialog._validate_and_accept()
        self.assertEqual(dialog.amount_decimal(), Decimal("60.00"))

    def test_edit_selected_payment_calls_update_supplier_payment(self):
        account = {
            "imports": [_canonical_import(1, total=Decimal("200.00"),
                                          paid=Decimal("40.00"), remaining=Decimal("160.00"))],
            "payments": [_canonical_payment(3, 1, amount=40, item_id=None)],
        }
        database = _StubDatabase(account)
        with patch.object(SupplierDetailsDialog, "refresh_data", lambda self: None):
            dialog = SupplierDetailsDialog(_supplier_obj(), database)
        self.addCleanup(dialog.close)
        dialog._apply_account_data(account)
        with patch("ui.dialogs.supplier_details_dialog._EditPaymentDialog") as edit_cls, patch.object(
            dialog, "_start_payment_edit"
        ) as start:
            edit_cls.return_value.exec.return_value = QDialog.Accepted
            edit_cls.return_value.amount_decimal.return_value = Decimal("60.00")
            dialog.payments_table.setCurrentCell(0, 0)
            dialog._edit_selected_payment()
        start.assert_called_once()
        args, _kwargs = start.call_args
        self.assertEqual(args[0], 3)
        self.assertIsInstance(args[1], Decimal)

    def test_delete_payment_button_sits_next_to_edit_button(self):
        account = {
            "imports": [_canonical_import(1)],
            "payments": [_canonical_payment(12, 1, amount=40, item_id=None)],
        }
        dialog = self._build_dialog(account)
        header = dialog.delete_payment_btn.parentWidget()
        layout = header.layout()
        edit_index = delete_index = -1
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if widget is dialog.edit_payment_btn:
                edit_index = i
            elif widget is dialog.delete_payment_btn:
                delete_index = i
        self.assertTrue(edit_index >= 0)
        self.assertEqual(delete_index, edit_index + 1)

    def test_delete_payment_with_no_selection_deletes_nothing(self):
        account = {
            "imports": [_canonical_import(1, total=Decimal("200.00"),
                                          paid=Decimal("40.00"), remaining=Decimal("160.00"))],
            "payments": [_canonical_payment(12, 1, amount=40, item_id=None)],
        }
        database = _StubDatabase(account)
        with patch.object(SupplierDetailsDialog, "refresh_data", lambda self: None):
            dialog = SupplierDetailsDialog(_supplier_obj(), database)
        self.addCleanup(dialog.close)
        dialog._apply_account_data(account)
        with patch.object(database, "delete_supplier_payment") as delete, patch(
            "ui.dialogs.supplier_details_dialog.QMessageBox.information"
        ) as info:
            dialog._delete_selected_payment()
        delete.assert_not_called()
        info.assert_called_once()
        self.assertEqual(dialog.payments_table.rowCount(), 1)

    def test_delete_payment_cancel_confirmation_deletes_nothing(self):
        account = {
            "imports": [_canonical_import(1, total=Decimal("200.00"),
                                          paid=Decimal("40.00"), remaining=Decimal("160.00"))],
            "payments": [_canonical_payment(12, 1, amount=40, item_id=None)],
        }
        database = _StubDatabase(account)
        with patch.object(SupplierDetailsDialog, "refresh_data", lambda self: None):
            dialog = SupplierDetailsDialog(_supplier_obj(), database)
        self.addCleanup(dialog.close)
        dialog._apply_account_data(account)
        with patch.object(dialog, "_confirm_payment_delete", return_value=False) as confirm, patch.object(
            database, "delete_supplier_payment"
        ) as delete, patch.object(dialog, "_start_payment_delete") as start:
            dialog.payments_table.setCurrentCell(0, 0)
            dialog._delete_selected_payment()
        confirm.assert_called_once()
        delete.assert_not_called()
        start.assert_not_called()

    def test_delete_selected_payment_asks_confirmation_and_calls_delete(self):
        account = {
            "imports": [_canonical_import(1, total=Decimal("200.00"),
                                          paid=Decimal("40.00"), remaining=Decimal("160.00"))],
            "payments": [_canonical_payment(12, 1, amount=40, item_id=None)],
        }
        database = _StubDatabase(account)
        with patch.object(SupplierDetailsDialog, "refresh_data", lambda self: None):
            dialog = SupplierDetailsDialog(_supplier_obj(), database)
        self.addCleanup(dialog.close)
        dialog._apply_account_data(account)
        with patch.object(dialog, "_confirm_payment_delete", return_value=True) as confirm, patch.object(
            dialog, "_start_payment_delete"
        ) as start:
            dialog.payments_table.setCurrentCell(0, 0)
            dialog._delete_selected_payment()
        confirm.assert_called_once()
        args, _kwargs = confirm.call_args
        self.assertEqual(args[0]["payment_id"], 12)
        self.assertEqual(args[1], "BL-2026-1")
        start.assert_called_once_with(12)

    def test_confirm_delete_builds_message_with_delete_and_cancel_buttons(self):
        account = {
            "imports": [_canonical_import(1)],
            "payments": [_canonical_payment(12, 1, amount=40, item_id=None)],
        }
        dialog = self._build_dialog(account)
        with patch("ui.dialogs.supplier_details_dialog.QMessageBox") as box_cls:
            box = box_cls.return_value
            box.addButton.return_value = "delete-btn"
            box.clickedButton.return_value = "delete-btn"
            result = dialog._confirm_payment_delete(
                dialog.payments[0], "BL-2026-1"
            )
            button_texts = [call.args[0] for call in box.addButton.call_args_list]
            self.assertIn("Delete", button_texts)
            self.assertIn("Cancel", button_texts)
            self.assertTrue(result)

    def test_delete_payment_worker_refreshes_after_delete(self):
        account = {
            "imports": [_canonical_import(1, total=Decimal("200.00"),
                                          paid=Decimal("40.00"), remaining=Decimal("160.00"))],
            "payments": [_canonical_payment(12, 1, amount=40, item_id=None)],
        }
        database = _StubDatabase(account)
        with patch.object(SupplierDetailsDialog, "refresh_data", lambda self: None):
            dialog = SupplierDetailsDialog(_supplier_obj(), database)
        self.addCleanup(dialog.close)
        dialog._apply_account_data(account)
        # The worker's finished handler calls self.refresh_data() and shows a
        # modal QMessageBox; keep both patched while we pump the event loop.
        with patch.object(dialog, "refresh_data") as refresh, patch(
            "ui.dialogs.supplier_details_dialog.QMessageBox.information"
        ):
            dialog._start_payment_delete(12)
            deadline = time.time() + 3.0
            while getattr(dialog, "_payment_delete_thread", None) is not None and time.time() < deadline:
                QApplication.processEvents()
                time.sleep(0.005)
        self.assertFalse(dialog._payment_delete_inflight)
        self.assertEqual(dialog.delete_payment_btn.text(), "Delete Payment")
        refresh.assert_called_once()


class SupplierWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _report_worker(self, report_type="full_statement", supplier_data=None):
        database = _StubDatabase({"imports": [], "payments": []})
        data = supplier_data or {
            "id": 1,
            "name": "Fournisseur Alpha",
            "username": "fournisseur-alpha",
            "phone": None,
            "email": None,
            "address": None,
        }
        return _SupplierReportWorker(
            report_type, data, {"currency": "MAD", "report_footer": ""},
            database, 1, None,
        )

    def test_account_worker_emits_finished_with_summaries(self):
        account = {"imports": [_canonical_import(1)], "payments": []}
        database = _StubDatabase(account)
        worker = _SupplierAccountWorker(database, 1)
        received = []
        worker.finished.connect(received.append)
        worker.run()
        self.assertEqual(len(received), 1)
        self.assertIs(received[0], account)

    def test_account_worker_emits_error_on_failure(self):
        worker = _SupplierAccountWorker(_FailingDatabase({}), 1)
        errors = []
        worker.error.connect(errors.append)
        worker.run()
        self.assertEqual(len(errors), 1)
        self.assertIn("host is down", errors[0])

    def test_payment_update_worker_emits_payload(self):
        database = _StubDatabase({"imports": [], "payments": []})
        worker = _PaymentUpdateWorker(database, 77, Decimal("60.00"))
        payloads = []
        errors = []
        worker.finished.connect(payloads.append)
        worker.error.connect(errors.append)
        worker.run()
        self.assertEqual(payloads, [{"payment_id": 77, "amount": Decimal("60.00")}])
        self.assertEqual(errors, [])

    def test_payment_update_worker_emits_error_on_failure(self):
        class _UpdateFailure(_StubDatabase):
            def update_supplier_payment(self, payment_id, amount):
                raise ValueError("no such payment")

        worker = _PaymentUpdateWorker(_UpdateFailure({}), 77, Decimal("60.00"))
        errors = []
        worker.error.connect(errors.append)
        worker.run()
        self.assertEqual(len(errors), 1)
        self.assertIn("no such payment", errors[0])

    def test_payment_delete_worker_emits_payload(self):
        database = _StubDatabase({"imports": [], "payments": []})
        worker = _PaymentDeleteWorker(database, 12)
        payloads = []
        worker.finished.connect(payloads.append)
        worker.run()
        self.assertEqual(payloads, [{"payment_id": 12}])

    def test_format_french_date_normalizes_variants(self):
        self.assertEqual(_SupplierReportWorker._format_french_date("2026-08-01"), "01/08/2026")
        self.assertEqual(_SupplierReportWorker._format_french_date("01-08-2026"), "01/08/2026")
        self.assertEqual(_SupplierReportWorker._format_french_date("01/08/2026"), "01/08/2026")
        self.assertEqual(_SupplierReportWorker._format_french_date(""), "")
        self.assertEqual(_SupplierReportWorker._format_french_date("garbage"), "garbage")

    def _full_statement_worker(self):
        worker = self._report_worker("full_statement")
        worker.imports = [
            _canonical_item(1, 10, product="Porte", quantity=Decimal("2"),
                            unit_price=Decimal("100")),
        ]
        worker.payments = [
            _canonical_payment(7, 1, amount=Decimal("60.00"), date="02-08-2026"),
        ]
        worker.bl_by_import = {1: "BL-2026-1"}
        worker.historical_by_import = {1: False}
        return worker

    def test_report_worker_full_statement_generates_complete_html(self):
        worker = self._full_statement_worker()
        with patch.object(_SupplierReportWorker, "_get_lamidap_logo_block", return_value="LOGO"):
            html = worker._generate_html()
        self.assertNotIn("{{", html)
        self.assertIn("Relevé de Compte Fournisseur", html)
        self.assertIn("Fournisseur Alpha", html)
        self.assertIn("BL N° BL-2026-1", html)
        self.assertIn("IMPORTATION N°1", html)
        self.assertIn("Porte", html)
        # raw 200.00 at 20% VAT => 240.00 TTC, 60.00 paid => 180.00 due.
        self.assertIn("240,00", html)
        self.assertIn("180,00", html)
        self.assertIn("Total des achats", html)
        self.assertIn("Solde restant", html)

    def test_report_worker_selected_import_uses_detail_title(self):
        worker = self._full_statement_worker()
        worker.report_type = "selected_import"
        with patch.object(_SupplierReportWorker, "_get_lamidap_logo_block", return_value="LOGO"):
            html = worker._generate_html()
        self.assertIn("Détail d'Importation", html)
        # The global/final account summary blocks are full-statement only.
        self.assertNotIn("Total des achats", html)

    def test_report_worker_renders_historical_badge(self):
        worker = self._report_worker("full_statement")
        worker.imports = [
            _canonical_item(1, 10, product="Porte", quantity=Decimal("1"),
                            unit_price=Decimal("100"), is_historical=True),
        ]
        worker.payments = []
        worker.bl_by_import = {1: ""}
        worker.historical_by_import = {1: True}
        with patch.object(_SupplierReportWorker, "_get_lamidap_logo_block", return_value="LOGO"):
            html = worker._generate_html()
        self.assertIn("HISTORIQUE", html)

    def test_report_worker_raises_on_leftover_placeholder(self):
        fd, path = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        self.addCleanup(os.unlink, path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "<html>{{ logo_block }}{{ document_title }}{{ document_date }}"
                "{{ supplier_block }}{{ global_summary }}{{ import_content }}"
                "{{ final_summary }}{{ report_footer }}{{ unknown_tag }}</html>"
            )
        real_resource_path = sdd_module.resource_path

        def fake_resource_path(*parts):
            if "supplier_statement_templet.html" in parts:
                return path
            return real_resource_path(*parts)

        worker = self._report_worker("full_statement")
        worker.imports = []
        worker.payments = []
        with patch.object(sdd_module, "resource_path", side_effect=fake_resource_path), \
                patch.object(_SupplierReportWorker, "_get_lamidap_logo_block", return_value="LOGO"):
            with self.assertRaises(RuntimeError):
                worker._generate_html()


if __name__ == "__main__":
    unittest.main()
