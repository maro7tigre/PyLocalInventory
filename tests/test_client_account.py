import unittest
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QDate, Qt

from core.calculations import calculate_operation_totals
from core.database import (
    CLIENT_ACCOUNT_PAYMENT_FIELDS,
    CLIENT_ACCOUNT_PURCHASE_FIELDS,
    CLIENT_ACCOUNT_SALE_FIELDS,
    normalize_client_account,
    normalize_client_sale_summaries,
)
from ui.dialogs.client_details_dialog import ClientDetailsDialog, _EditPaymentDialog


def _canonical_purchase(sale_id, item_id, **overrides):
    row = {
        "sale_id": sale_id,
        "date": "01-08-2026",
        "state": "pending",
        "item_id": item_id,
        "product": f"item-{item_id}",
        "quantity": Decimal("1"),
        "unit_price": Decimal("0"),
        "vat": Decimal("20"),
        "remise": Decimal("0"),
        "information": "",
        "production": 0,
        "notes": "",
        "is_historical": False,
        "created_by_username": "host",
    }
    row.update(overrides)
    return row


def _canonical_payment(payment_id, sale_id, amount, item_id=None, date="01-08-2026"):
    return {
        "payment_id": payment_id,
        "sale_id": sale_id,
        "item_id": item_id,
        "date": date,
        "amount": amount,
    }


def _canonical_sale(sale_id, **overrides):
    row = {
        "sale_id": sale_id,
        "date": "01-08-2026",
        "state": "pending",
        "is_historical": False,
        "devis": None,
        "total": Decimal("0"),
        "paid": Decimal("0"),
        "remaining": Decimal("0"),
    }
    row.update(overrides)
    return row


def _client_obj():
    client = MagicMock()
    client.id = 1

    def get_value(key):
        values = {
            "id": 1,
            "name": "majid asilah",
            "username": "majid asilah",
            "preview_image": None,
            "client_type": "individual",
            "ice": None,
            "phone": None,
            "email": None,
            "address": None,
            "notes": None,
        }
        return values.get(key)

    client.get_value.side_effect = get_value
    return client


class _StubDatabase:
    """Host-style database: own schema, Sales write permission, no network."""

    def __init__(self, account):
        self.account = account
        self.cursor = MagicMock()
        self.conn = MagicMock()

    def has_permission(self, section, action="read"):
        return True

    def get_client_sale_summaries(self, client_id):
        return self.account

    def add_client_payment(self, client_id, sale_id, sales_item_id, amount, date):
        return None

    def update_client_payment(self, payment_id, amount):
        return None


class ClientAccountSchemaTests(unittest.TestCase):
    def test_purchase_fields_are_exactly_the_14_column_join(self):
        self.assertEqual(
            CLIENT_ACCOUNT_PURCHASE_FIELDS,
            (
                "sale_id", "date", "state", "item_id", "product", "quantity",
                "unit_price", "vat", "remise", "information", "production",
                "notes", "is_historical", "created_by_username",
            ),
        )
        self.assertEqual(len(CLIENT_ACCOUNT_PURCHASE_FIELDS), 14)

    def test_payment_fields_are_the_5_column_payments_select(self):
        self.assertEqual(
            CLIENT_ACCOUNT_PAYMENT_FIELDS,
            ("payment_id", "sale_id", "item_id", "date", "amount"),
        )

    def test_sale_summary_fields_are_the_8_column_per_sale_contract(self):
        self.assertEqual(
            CLIENT_ACCOUNT_SALE_FIELDS,
            (
                "sale_id", "date", "state", "is_historical", "devis", "total",
                "paid", "remaining",
            ),
        )
        # Devis is a display string (DE-YEAR-N), never part of the 14-column
        # item-level purchase contract.
        self.assertNotIn("devis", CLIENT_ACCOUNT_PURCHASE_FIELDS)

    def test_normalize_client_account_builds_named_dicts(self):
        purchase_rows = [
            (1, "01-08-2026", "pending", 10, "hammer", Decimal("2"), Decimal("50"),
             Decimal("20"), Decimal("0"), "", 0, "", False, "host"),
            (2, "02-08-2026", "paid", 11, "nails", Decimal("1"), Decimal("30"),
             Decimal("20"), Decimal("5"), "", 0, "", False, "host"),
        ]
        payment_rows = [
            (7, 2, 11, "02-08-2026", Decimal("30")),
        ]
        account = normalize_client_account(purchase_rows, payment_rows)
        self.assertEqual(len(account["purchases"]), 2)
        self.assertEqual(len(account["payments"]), 1)
        purchase = account["purchases"][0]
        self.assertEqual(purchase["sale_id"], 1)
        self.assertEqual(purchase["product"], "hammer")
        self.assertIn("created_by_username", purchase)
        self.assertEqual(account["payments"][0]["payment_id"], 7)
        self.assertEqual(account["payments"][0]["amount"], Decimal("30"))

    def test_normalize_client_sale_summaries_builds_named_dicts(self):
        sale_rows = [
            (1, "01-08-2026", "pending", False, "DE-2026-1",
             Decimal("120.00"), Decimal("50.00"), Decimal("70.00")),
            (2, "02-08-2026", "paid", False, "DE-2026-2",
             Decimal("30.00"), Decimal("30.00"), Decimal("0.00")),
        ]
        payment_rows = [
            (7, 2, None, "02-08-2026", Decimal("30")),
        ]
        account = normalize_client_sale_summaries(sale_rows, payment_rows)
        self.assertEqual(len(account["sales"]), 2)
        self.assertEqual(len(account["payments"]), 1)
        sale = account["sales"][0]
        self.assertEqual(sale["sale_id"], 1)
        self.assertEqual(sale["devis"], "DE-2026-1")
        self.assertEqual(sale["total"], Decimal("120.00"))
        self.assertEqual(sale["remaining"], Decimal("70.00"))


class _FakeCursor:
    """Scripted cursor for the REAL core.database.Database queries.

    Returns the db_haitam 'majid asilah' shapes so the sale-summaries code path
    (which previously raised ``NameError: name 'Decimal' is not defined``) runs
    for real.
    """

    def __init__(self):
        self.queries = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        self._sql = sql

    def fetchone(self):
        if "FROM clients" in self._sql:
            return (1, "majid asilah")
        return None

    def fetchall(self):
        if "FROM sales" in self._sql:
            return [
                # (sale_id, date, state, is_historical, devis_text,
                #  devis_number, year, tva, remise, raw_total)
                (1, "2026-07-01", "sold", False, "", 1, "2026", 20, 0, 0),
                (2, "2026-07-05", "pending", False, "", 2, "2026", 20, 100033, 132000),
            ]
        if "FROM payments" in self._sql:
            return [(1, 2, None, "2026-07-06", Decimal("10000.00"))]
        return []


class _FakeConn:
    def commit(self):
        pass

    def rollback(self):
        pass


class ClientAccountBackendTests(unittest.TestCase):
    """Exercise the real Database.get_client_sale_summaries() code path."""

    def test_get_client_sale_summaries_runs_without_name_error(self):
        from core.database import Database

        db = Database.__new__(Database)
        db.cursor = _FakeCursor()
        db.conn = _FakeConn()
        result = db.get_client_sale_summaries(1)
        self.assertEqual(len(result["sales"]), 2)
        self.assertEqual(len(result["payments"]), 1)
        sale2 = result["sales"][1]
        self.assertEqual(sale2["devis"], "DE-2026-2")
        self.assertEqual(sale2["total"], Decimal("38360.40"))
        self.assertEqual(sale2["paid"], Decimal("10000.00"))
        self.assertEqual(sale2["remaining"], Decimal("28360.40"))
        self.assertEqual(result["payments"][0]["amount"], Decimal("10000.00"))


class ClientAccountDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _build_dialog(self, account):
        database = _StubDatabase(account)
        with patch.object(ClientDetailsDialog, "refresh_data", lambda self: None):
            dialog = ClientDetailsDialog(_client_obj(), database)
        self.addCleanup(dialog.close)
        dialog._apply_account_data(account)
        return dialog

    def test_single_sale_shows_total_and_remaining(self):
        expected = calculate_operation_totals(100, 0, 20)["total_ttc"]
        account = {
            "sales": [
                _canonical_sale(1, total=expected, paid=Decimal("0"),
                                remaining=expected, state="pending"),
            ],
            "payments": [],
        }
        dialog = self._build_dialog(account)
        self.assertEqual(len(dialog.sales), 1)
        self.assertEqual(dialog.sales[0]["total"], expected)
        self.assertEqual(dialog.sales[0]["paid"], Decimal("0"))
        self.assertEqual(dialog.sales[0]["remaining"], expected)
        self.assertEqual(dialog.purchases_table.rowCount(), 1)
        self.assertEqual(
            dialog.total_bought_label.text(), f"{float(expected):,.2f} MAD".replace(",", " ")
        )

    def test_multiple_sales_with_payments_and_remaining(self):
        account = {
            "sales": [
                _canonical_sale(1, total=Decimal("200.00"), paid=Decimal("50.00"),
                                remaining=Decimal("150.00"), state="pending"),
                _canonical_sale(2, total=Decimal("1000.00"), paid=Decimal("1000.00"),
                                remaining=Decimal("0.00"), state="paid"),
            ],
            "payments": [
                _canonical_payment(1, 1, amount=50),
                _canonical_payment(2, 2, amount=2000),  # overpayment capped at total
            ],
        }
        dialog = self._build_dialog(account)
        self.assertEqual(dialog.sales[0]["remaining"], Decimal("150.00"))
        self.assertEqual(dialog.sales[1]["paid"], Decimal("1000.00"))
        self.assertEqual(dialog.sales[1]["remaining"], Decimal("0.00"))
        self.assertEqual(dialog.total_bought_label.text(), "1 200.00 MAD")
        self.assertEqual(dialog.total_paid_label.text(), "1 050.00 MAD")
        self.assertEqual(dialog.remaining_label.text(), "150.00 MAD")
        self.assertEqual(dialog.payments_table.rowCount(), 2)

    def test_payment_rows_show_sale_and_devis_reference(self):
        account = {
            "sales": [
                _canonical_sale(1, devis="DE-2026-1"),
                _canonical_sale(2, devis="DE-2026-2"),
            ],
            "payments": [
                _canonical_payment(1, 1, amount=10, item_id=None),
                _canonical_payment(2, 2, amount=20, item_id=None),
            ],
        }
        dialog = self._build_dialog(account)
        self.assertEqual(dialog.payments_table.rowCount(), 2)
        # Column order: Payment # | Sale # | Date | Amount | Devis
        self.assertEqual(dialog.payments_table.item(0, 1).text(), "#1")
        self.assertEqual(dialog.payments_table.item(0, 4).text(), "Devis N° DE-2026-1")
        self.assertEqual(dialog.payments_table.item(1, 4).text(), "Devis N° DE-2026-2")
        self.assertEqual(dialog.devis_by_sale[2], "DE-2026-2")

    def test_sales_history_has_exactly_three_columns(self):
        account = {
            "sales": [
                _canonical_sale(1, devis="DE-2026-1", date="31-07-2026"),
                _canonical_sale(2, devis="DE-2026-2", date="31-07-2026"),
                _canonical_sale(3, devis="DE-2026-3", date="03-08-2026"),
            ],
            "payments": [],
        }
        dialog = self._build_dialog(account)
        headers = [
            dialog.purchases_table.horizontalHeaderItem(c).text()
            for c in range(dialog.purchases_table.columnCount())
        ]
        self.assertEqual(headers, ["Sale #", "Date", "Devis"])
        self.assertEqual(dialog.purchases_table.columnCount(), 3)
        # One Sale = one row, one row per Sale.
        self.assertEqual(dialog.purchases_table.rowCount(), 3)
        for r, (sale_id, date, devis) in enumerate(
            [("#1", "31/07/2026", "Devis N° DE-2026-1"),
             ("#2", "31/07/2026", "Devis N° DE-2026-2"),
             ("#3", "03/08/2026", "Devis N° DE-2026-3")]
        ):
            self.assertEqual(dialog.purchases_table.item(r, 0).text(), sale_id)
            self.assertEqual(dialog.purchases_table.item(r, 1).text(), date)
            self.assertEqual(dialog.purchases_table.item(r, 2).text(), devis)
            # Row maps to the Sale ID (hidden item-level data is fetched on demand).
            self.assertEqual(
                int(dialog.purchases_table.item(r, 0).data(Qt.UserRole)), r + 1
            )

    def test_sale_with_many_items_still_one_row(self):
        # A Sale with 10 items must appear exactly once in Sales History.
        account = {
            "sales": [
                _canonical_sale(1, devis="DE-2026-1", total=Decimal("500.00"),
                                paid=Decimal("0"), remaining=Decimal("500.00")),
            ],
            "payments": [],
        }
        dialog = self._build_dialog(account)
        self.assertEqual(dialog.purchases_table.rowCount(), 1)
        self.assertEqual(dialog.purchases_table.item(0, 2).text(), "Devis N° DE-2026-1")

    def test_payment_history_has_exactly_five_columns(self):
        account = {
            "sales": [_canonical_sale(2, devis="DE-2026-2")],
            "payments": [_canonical_payment(1, 2, amount=10000, item_id=None)],
        }
        dialog = self._build_dialog(account)
        headers = [
            dialog.payments_table.horizontalHeaderItem(c).text()
            for c in range(dialog.payments_table.columnCount())
        ]
        self.assertEqual(headers, ["Payment #", "Sale #", "Date", "Amount", "Devis"])
        # Payment -> Sale -> Devis (payment itself carries no Devis).
        self.assertEqual(dialog.payments_table.item(0, 0).text(), "#1")
        self.assertEqual(dialog.payments_table.item(0, 1).text(), "#2")
        self.assertEqual(dialog.payments_table.item(0, 3).text(), "10 000.00")
        self.assertEqual(dialog.payments_table.item(0, 4).text(), "Devis N° DE-2026-2")

    def test_print_buttons_start_disabled_then_statement_enabled_after_load(self):
        account = {
            "sales": [_canonical_sale(1, total=Decimal("10.00"),
                                      paid=Decimal("0"), remaining=Decimal("10.00"))],
            "payments": [],
        }
        database = _StubDatabase(account)
        with patch.object(ClientDetailsDialog, "refresh_data", lambda self: None):
            dialog = ClientDetailsDialog(_client_obj(), database)
        self.addCleanup(dialog.close)
        self.assertFalse(dialog.print_selected_btn.isEnabled())
        self.assertFalse(dialog.print_statement_btn.isEnabled())
        dialog._apply_account_data(account)
        self.assertTrue(dialog.print_statement_btn.isEnabled())

    def test_selecting_sale_row_enables_selected_sale_print(self):
        account = {
            "sales": [
                _canonical_sale(1, total=Decimal("10.00")),
                _canonical_sale(2, total=Decimal("20.00")),
            ],
            "payments": [],
        }
        dialog = self._build_dialog(account)
        self.assertFalse(dialog.print_selected_btn.isEnabled())
        dialog.purchases_table.setCurrentCell(1, 0)
        self.assertTrue(dialog.print_selected_btn.isEnabled())

    def test_print_selected_sale_uses_selected_sale_id(self):
        account = {
            "sales": [
                _canonical_sale(1, total=Decimal("10.00")),
                _canonical_sale(7, total=Decimal("20.00")),
            ],
            "payments": [],
        }
        dialog = self._build_dialog(account)
        dialog.purchases_table.setCurrentCell(1, 0)
        with patch.object(dialog, "_start_report_worker") as start:
            dialog._print_selected_sale()
        start.assert_called_once_with("selected_sale", 7)

    def test_first_load_error_keeps_empty_tables_and_marks_loaded_once(self):
        database = _StubDatabase({"sales": [], "payments": []})
        with patch.object(ClientDetailsDialog, "refresh_data", lambda self: None):
            dialog = ClientDetailsDialog(_client_obj(), database)
        self.addCleanup(dialog.close)
        with patch("ui.dialogs.client_details_dialog.QMessageBox.critical") as critical:
            dialog._on_account_load_error("boom")
        critical.assert_called_once()
        # A failed first load never pretends an empty account is the truth.
        self.assertFalse(dialog._account_loaded_once)
        self.assertEqual(dialog.purchases_table.rowCount(), 0)

    def test_failed_refresh_keeps_previously_loaded_data(self):
        account = {
            "sales": [_canonical_sale(1, total=Decimal("12.00"),
                                      paid=Decimal("0"), remaining=Decimal("12.00"))],
            "payments": [],
        }
        database = _StubDatabase(account)
        with patch.object(ClientDetailsDialog, "refresh_data", lambda self: None):
            dialog = ClientDetailsDialog(_client_obj(), database)
        self.addCleanup(dialog.close)
        dialog._apply_account_data(account)
        with patch("ui.dialogs.client_details_dialog.QMessageBox.warning") as warning:
            dialog._on_account_load_error("network down")
        warning.assert_called_once()
        self.assertEqual(dialog.purchases_table.rowCount(), 1)
        self.assertEqual(dialog.total_bought_label.text(), "12.00 MAD")

    def test_global_totals_match_real_database_shapes(self):
        # Mirrors the sale-level shapes seen on the real db_haitam "majid asilah"
        # account: zero-TTC sales, a remised sale with a partial payment, and
        # extra single-sale rows.
        account = {
            "sales": [
                _canonical_sale(1, total=Decimal("0.00"), paid=Decimal("0.00"),
                                remaining=Decimal("0.00")),
                _canonical_sale(2, total=Decimal("180.00"), paid=Decimal("40.00"),
                                remaining=Decimal("140.00")),
                _canonical_sale(3, total=Decimal("1000.00"), paid=Decimal("0.00"),
                                remaining=Decimal("1000.00")),
            ],
            "payments": [_canonical_payment(1, 2, amount=40, item_id=None)],
        }
        dialog = self._build_dialog(account)
        self.assertEqual(dialog.total_bought_label.text(), "1 180.00 MAD")
        self.assertEqual(dialog.total_paid_label.text(), "40.00 MAD")
        self.assertEqual(dialog.remaining_label.text(), "1 140.00 MAD")
        self.assertEqual(dialog.purchases_table.rowCount(), 3)
        self.assertEqual(dialog.payments_table.rowCount(), 1)

    def test_lan_round_trip_stringified_numbers_still_total(self):
        # The LAN server serializes results with json.dumps(default=str), so a
        # RemoteDatabase receives numeric strings instead of Decimals. The
        # dialog must total them exactly like the host-side Decimal path.
        account = {
            "sales": [
                _canonical_sale(1, total=Decimal("200.00"), paid=Decimal("50.00"),
                                remaining=Decimal("150.00")),
                _canonical_sale(2, total=Decimal("1000.00"), paid=Decimal("1000.00"),
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
        self.assertEqual(dialog.sales[0]["remaining"], Decimal("150.00"))

    def test_add_payment_records_sale_level_payment(self):
        account = {
            "sales": [_canonical_sale(1, devis="DE-2026-1",
                                      total=Decimal("100.00"), paid=Decimal("0.00"),
                                      remaining=Decimal("100.00"))],
            "payments": [],
        }
        database = _StubDatabase(account)
        with patch.object(ClientDetailsDialog, "refresh_data", lambda self: None):
            dialog = ClientDetailsDialog(_client_obj(), database)
        self.addCleanup(dialog.close)
        dialog._apply_account_data(account)
        dialog.date_input.setDate(QDate(2026, 8, 1))
        with patch.object(database, "add_client_payment") as add:
            add.side_effect = lambda *_args: None
            dialog.purchases_table.setCurrentCell(0, 0)
            dialog.amount_input.setText("50")
            with patch("ui.dialogs.client_details_dialog.QMessageBox.information"):
                dialog.add_payment()
        # Sale-level payment: item_id is None.
        add.assert_called_once_with(1, 1, None, 50.0, "01-08-2026")

    def test_add_payment_blocks_overpayment(self):
        account = {
            "sales": [_canonical_sale(1, total=Decimal("100.00"), paid=Decimal("0.00"),
                                      remaining=Decimal("100.00"))],
            "payments": [],
        }
        database = _StubDatabase(account)
        with patch.object(ClientDetailsDialog, "refresh_data", lambda self: None):
            dialog = ClientDetailsDialog(_client_obj(), database)
        self.addCleanup(dialog.close)
        dialog._apply_account_data(account)
        dialog.purchases_table.setCurrentCell(0, 0)
        dialog.amount_input.setText("200")
        with patch.object(database, "add_client_payment") as add, patch(
            "ui.dialogs.client_details_dialog.QMessageBox.warning"
        ) as warning:
            dialog.add_payment()
        add.assert_not_called()
        warning.assert_called_once()

    def test_edit_payment_dialog_validates_amount_range(self):
        dialog = _EditPaymentDialog(None, payment_id=3, sale_id=1, devis="DE-2026-1",
                                    current=Decimal("40.00"), max_allowed=Decimal("160.00"))
        dialog.amount_edit.setText("200")
        with patch("ui.dialogs.client_details_dialog.QMessageBox.warning") as warning:
            dialog._validate_and_accept()
        warning.assert_called_once()
        self.assertEqual(dialog.result(), 0)
        dialog.amount_edit.setText("60")
        dialog._validate_and_accept()
        self.assertEqual(dialog.amount_decimal(), Decimal("60.00"))

    def test_edit_selected_payment_calls_update_client_payment(self):
        account = {
            "sales": [_canonical_sale(1, devis="DE-2026-1",
                                      total=Decimal("200.00"), paid=Decimal("40.00"),
                                      remaining=Decimal("160.00"))],
            "payments": [_canonical_payment(3, 1, amount=40, item_id=None)],
        }
        database = _StubDatabase(account)
        with patch.object(ClientDetailsDialog, "refresh_data", lambda self: None):
            dialog = ClientDetailsDialog(_client_obj(), database)
        self.addCleanup(dialog.close)
        dialog._apply_account_data(account)
        with patch("ui.dialogs.client_details_dialog._EditPaymentDialog") as edit_cls, patch.object(
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


if __name__ == "__main__":
    unittest.main()
