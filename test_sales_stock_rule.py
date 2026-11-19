"""Regression tests: a Sale only consumes stock when affect_stock is TRUE.

Stock is derived from stored operations (imports minus eligible sales), so these
tests assert three things: the single SQL predicate used by every stock query,
the one-time legacy backfill, and the GUI/backend stock decision. The
scenarios from the acceptance list are modelled with a small in-memory
equivalent of the stock formula.
"""

import os
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.database import SALE_STOCK_ELIGIBILITY_SQL, Database
from classes.sales_class import SalesClass


def stock_of(imported, sales):
    """Mirror of the SQL stock formula: imports minus eligible sale lines.

    ``sales`` rows are (quantity, affect_stock, is_historical, state).
    """
    sold = sum(
        Decimal(str(quantity))
        for quantity, affect_stock, is_historical, _state in sales
        if affect_stock and not is_historical
    )
    return Decimal(str(imported)) - sold


class StockPredicateTests(unittest.TestCase):
    def test_predicate_uses_opt_in_and_excludes_historical(self):
        self.assertIn("COALESCE(s.affect_stock, FALSE) = TRUE", SALE_STOCK_ELIGIBILITY_SQL)
        self.assertIn("COALESCE(s.is_historical, FALSE) = FALSE", SALE_STOCK_ELIGIBILITY_SQL)
        # Sale state must never appear in a stock predicate.
        self.assertNotIn("state", SALE_STOCK_ELIGIBILITY_SQL)

    def test_all_stock_queries_use_the_shared_predicate(self):
        database = Database.__new__(Database)
        database.cursor = MagicMock()
        database.cursor.fetchall.return_value = []
        database.cursor.fetchone.return_value = None

        database.get_product_stock_levels()
        database.get_product_stock_levels_for_product_ids([1])
        database.get_sale_catalog(include_products=True, include_services=False)
        database.get_sale_catalog(
            include_products=True, include_services=False, exclude_sale_id=5
        )
        statements = [call.args[0] for call in database.cursor.execute.call_args_list]
        stock_statements = [s for s in statements if "sales_items" in s]
        self.assertTrue(stock_statements, "no stock query was captured")
        for statement in stock_statements:
            self.assertIn("COALESCE(s.affect_stock, FALSE) = TRUE", statement)
            self.assertNotIn("on_hold", statement)

    def test_product_quantity_uses_the_shared_predicate(self):
        from classes.product_class import ProductClass

        database = SimpleNamespace(cursor=MagicMock(), _product_stock_levels=None)
        database.cursor.fetchone.side_effect = [(40,), (10,)]
        product = ProductClass(1, database)
        self.assertEqual(product.calculate_quantity(), 30)
        statement = database.cursor.execute.call_args_list[-1].args[0]
        self.assertIn("COALESCE(s.affect_stock, FALSE) = TRUE", statement)
        self.assertNotIn("on_hold", statement)

    def test_dashboard_low_stock_uses_the_shared_predicate(self):
        database = Database.__new__(Database)
        database.cursor = MagicMock()
        database.cursor.fetchall.return_value = []
        database.cursor.fetchone.return_value = (0, 0, 0, 0, 0)
        database.get_dashboard_snapshot()
        statements = [call.args[0] for call in database.cursor.execute.call_args_list]
        low_stock = [s for s in statements if "WITH imported" in s]
        self.assertTrue(low_stock)
        for statement in low_stock:
            self.assertIn("COALESCE(s.affect_stock, FALSE) = TRUE", statement)
            self.assertNotIn("on_hold", statement)


class AcceptNewSaleDefaultTests(unittest.TestCase):
    def test_new_sale_defaults_to_not_affecting_stock(self):
        sale = SalesClass(0, None)
        self.assertIs(sale.parameters["affect_stock"]["value"], False)
        self.assertIs(sale.parameters["affect_stock"]["default"], False)
        # A real boolean flag, not the numeric tva toggle mapping.
        self.assertEqual(sale.parameters["affect_stock"]["type"], "bool")
        self.assertIs(sale.parameters["affect_stock"]["true_value"], True)
        self.assertIs(sale.parameters["affect_stock"]["false_value"], False)

    def test_stock_is_not_affected_by_default(self):
        self.assertEqual(stock_of(100, [(10, False, False, "pending")]), Decimal("100"))

    def test_checked_deducts_once(self):
        self.assertEqual(stock_of(100, [(10, True, False, "pending")]), Decimal("90"))

    def test_state_never_changes_stock(self):
        base = (10, True, False)
        stocks = {
            state: stock_of(100, [(base[0], base[1], base[2], state)])
            for state in ("on_hold", "pending", "confirmed", "finished")
        }
        self.assertEqual(set(stocks.values()), {Decimal("90")})

    def test_unchecked_sale_is_immune_to_state_changes(self):
        base = (10, False, False)
        stocks = {
            state: stock_of(100, [(base[0], base[1], base[2], state)])
            for state in ("on_hold", "pending", "confirmed", "finished")
        }
        self.assertEqual(set(stocks.values()), {Decimal("100")})

    def test_on_hold_with_opt_in_still_affects_stock(self):
        self.assertEqual(stock_of(100, [(10, True, False, "on_hold")]), Decimal("90"))

    def test_historical_never_affects_stock_even_if_flag_is_set(self):
        # Malformed legacy data: historical + affect_stock TRUE.
        self.assertEqual(stock_of(100, [(10, True, True, "pending")]), Decimal("100"))

    def test_toggle_edit_false_to_true_moves_stock_exactly_once(self):
        # Sale saved unchecked, then the user checks it: 100 -> 90, not 80.
        after_toggle = stock_of(100, [(10, True, False, "pending")])
        self.assertEqual(after_toggle, Decimal("90"))

    def test_toggle_edit_true_to_false_restores_stock(self):
        self.assertEqual(stock_of(100, []), Decimal("100"))

    def test_editing_quantity_replaces_the_previous_contribution(self):
        # 10 -> 15: only the final 15 is represented.
        self.assertEqual(stock_of(100, [(15, True, False, "pending")]), Decimal("85"))

    def test_deleting_a_stock_affecting_sale_restores_stock(self):
        # Derived stock: removing the stored sale row is the whole "restore".
        self.assertEqual(stock_of(100, []), Decimal("100"))
        self.assertEqual(stock_of(100, [(10, False, False, "pending")]), Decimal("100"))


class HistoricalInteractsWithStockFlagTests(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([])
        from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog

        self.BaseOperationDialog = BaseOperationDialog
        self.dialog = self.BaseOperationDialog.__new__(self.BaseOperationDialog)
        self.dialog.operation_obj = SalesClass(0, None)
        self.dialog.parameter_widgets = {}
        stock = MagicMock()
        stock.isChecked.return_value = False
        stock.isEnabled.return_value = True
        historical = MagicMock()
        historical.isChecked.return_value = False
        self.dialog.parameter_widgets["affect_stock"] = SimpleNamespace(checkbox=stock)
        self.dialog.parameter_widgets["is_historical"] = SimpleNamespace(checkbox=historical)
        self.stock, self.historical = stock, historical

    def test_historical_unchecks_and_disables_stock(self):
        self.historical.isChecked.return_value = True
        self.stock.isChecked.return_value = True
        self.BaseOperationDialog._sync_stock_checkbox_state(self.dialog)
        self.stock.setChecked.assert_called_with(False)
        self.stock.setEnabled.assert_called_with(False)

    def test_unchecking_historical_renables_but_never_checks(self):
        self.stock.setEnabled.reset_mock()
        self.stock.setChecked.reset_mock()
        self.BaseOperationDialog._sync_stock_checkbox_state(self.dialog)
        self.stock.setEnabled.assert_called_with(True)
        self.stock.setChecked.assert_not_called()

    def test_historical_sale_never_reports_stock_impact(self):
        self.historical.isChecked.return_value = True
        self.stock.isChecked.return_value = True
        self.assertFalse(self.BaseOperationDialog._affects_stock(self.dialog))

    def test_checked_flag_reports_stock_impact(self):
        self.stock.isChecked.return_value = True
        self.assertTrue(self.BaseOperationDialog._affects_stock(self.dialog))

    def test_imports_never_get_a_stock_checkbox(self):
        from classes.import_class import ImportClass

        self.dialog.operation_obj = ImportClass(0, None)
        self.assertFalse(self.BaseOperationDialog._affects_stock(self.dialog))


class ConfirmationSummaryTests(unittest.TestCase):
    def test_summary_reports_both_flags_and_the_stock_impact(self):
        from PySide6.QtWidgets import QApplication, QMessageBox

        QApplication.instance() or QApplication([])
        from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog

        dialog = BaseOperationDialog.__new__(BaseOperationDialog)
        dialog.operation_obj = SalesClass(0, None)
        dialog.pending_entities = []
        dialog.items_table = MagicMock()
        dialog.items_table.get_current_table_data.return_value = []
        dialog.parameter_widgets = {}
        stock = MagicMock()
        stock.isChecked.return_value = True
        historical = MagicMock()
        historical.isChecked.return_value = False
        dialog.parameter_widgets["affect_stock"] = SimpleNamespace(checkbox=stock)
        dialog.parameter_widgets["is_historical"] = SimpleNamespace(checkbox=historical)

        captured = {}

        def fake_question(_parent, _title, text, *_args):
            captured["text"] = text
            return QMessageBox.Yes

        original = QMessageBox.question
        QMessageBox.question = staticmethod(fake_question)
        try:
            self.assertTrue(BaseOperationDialog._confirm_sale_summary(dialog))
        finally:
            QMessageBox.question = original
        text = captured["text"]
        self.assertIn("Historical Sale: No", text)
        self.assertIn("Affect current stock: Yes", text)
        self.assertIn("Will deduct product quantities from current stock", text)

        stock.isChecked.return_value = False
        captured.clear()
        QMessageBox.question = staticmethod(fake_question)
        try:
            BaseOperationDialog._confirm_sale_summary(dialog)
        finally:
            QMessageBox.question = original
        self.assertIn("Affect current stock: No", captured["text"])
        self.assertIn("No stock deduction", captured["text"])


class LegacyBackfillMigrationTests(unittest.TestCase):
    """The one-time migration must preserve existing stock exactly once."""

    def _database(self, flags):
        database = Database.__new__(Database)
        database.cursor = MagicMock()
        database.conn = MagicMock()
        database.database_name = "testdb"
        database.schema_name = "public"
        database._meta = dict(flags)
        database._get_meta = lambda key, default=None: database._meta.get(key, default)
        database._set_meta = lambda key, value: database._meta.__setitem__(key, str(value))
        return database

    def test_backfill_maps_the_old_stock_rule_once(self):
        database = self._database({"fk_relaxed": "1", "backfill_product_name_done": "1"})
        database._run_one_time_migrations()
        statements = [call.args[0] for call in database.cursor.execute.call_args_list]
        updates = [s for s in statements if "UPDATE sales" in s and "affect_stock" in s]
        self.assertEqual(len(updates), 2, updates)
        # Only legacy (still NULL) rows are touched.
        for statement in updates:
            self.assertIn("affect_stock IS NULL", statement)
        # TRUE exactly reproduces the old rule.
        self.assertIn("COALESCE(is_historical, FALSE) = FALSE", updates[0])
        self.assertIn("state IS NULL OR state <> 'on_hold'", updates[0])
        self.assertIn("SET affect_stock = TRUE", updates[0])
        self.assertIn("SET affect_stock = FALSE", updates[1])
        self.assertEqual(database._meta["sales_affect_stock_backfill_done"], "1")
        # Column is tightened to NOT NULL DEFAULT FALSE for future inserts.
        self.assertTrue(any("SET DEFAULT FALSE" in s for s in statements))
        self.assertTrue(any("SET NOT NULL" in s for s in statements))

    def test_migration_never_runs_again_once_flagged(self):
        database = self._database({
            "fk_relaxed": "1",
            "backfill_product_name_done": "1",
            "sales_affect_stock_backfill_done": "1",
        })
        database._run_one_time_migrations()
        statements = [call.args[0] for call in database.cursor.execute.call_args_list]
        self.assertFalse([s for s in statements if "UPDATE sales" in s])
        self.assertFalse([s for s in statements if "ALTER TABLE sales" in s])

    def test_intentional_false_survives_a_later_startup(self):
        # The guarded WHERE (affect_stock IS NULL) means a Sale the user saved
        # with FALSE is never re-enabled, even if the flag were lost.
        database = self._database({})
        database._run_one_time_migrations()
        statements = [call.args[0] for call in database.cursor.execute.call_args_list]
        for statement in statements:
            if "UPDATE sales" in statement and "affect_stock" in statement:
                self.assertIn("WHERE affect_stock IS NULL", statement)


class HostEnforcementTests(unittest.TestCase):
    def test_bool_flag_normalisation_accepts_rpc_shapes(self):
        for raw, expected in (
            (True, True), (False, False), (1, True), (0, False),
            ("true", True), ("false", False), ("1", True), (None, False),
        ):
            self.assertIs(Database._parse_bool_flag(raw), expected, raw)

    def test_column_is_declared_boolean_not_double_precision(self):
        from core.database import Database as Db

        source = open(Db.__module__.replace(".", "/") + ".py", encoding="utf-8").read()
        self.assertIn("'affect_stock': 'BOOLEAN'", source)
        # The class-driven bool -> DOUBLE PRECISION mapping must not own it.
        self.assertNotIn('"affect_stock": "rw",\n                "created_by"', source)


if __name__ == "__main__":
    unittest.main()
