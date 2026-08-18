"""Tests for the centralized Remise / discount calculation logic (LAMIBOIS
branch: no VAT anywhere).

Covers:
  Test 1: Basic discount calculation (1 000 - 100 remise)
  Test 2: Real-world confirmed values (70 679 - 5 654.32 remise)
  Test 3: Round-trip: save then reopen retains correct values
  Test 4: Restart simulation: recalculate from raw data after object reload
  Test 5: Sales without Remise still calculate correctly
  Test 6: Remise validation blocks negative / excess values
  Test 7: Sales table columns show only Total TTC (no Total HT)
  Test 8: Report/PDF data extraction uses discounted Net à payer
  Test 9: A legacy/stale 'tva' value on the object never affects a total
"""
import os
import unittest
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from classes.sales_class import SalesClass, calculate_sale_totals
from classes.sales_item_class import SalesItemClass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, rows=None):
        self._rows = rows or []
    def execute(self, *_a, **_kw):
        pass
    def fetchone(self):
        return self._rows.pop(0) if self._rows else None
    def fetchall(self):
        r, self._rows = self._rows, []
        return r


class _FakeDB:
    def __init__(self, cursor=None):
        self.cursor = cursor or _FakeCursor()
        self.conn = type("C", (), {"commit": lambda s: None})()
    def has_permission(self, *_a, **_kw):
        return True
    def get_items_by_operation_id(self, *_a, **_kw):
        return []


def _make_sale_obj(raw_items, remise=0, tva_rate=None):
    """Build a SalesClass instance with fake items and a given remise.

    ``tva_rate``, when given, is stored on the object to prove it has no
    effect on any LAMIBOIS total (see Test 9) - it is never read by the
    calculation methods.
    """
    sale = SalesClass(0, None)
    sale.set_value("remise", remise)
    if tva_rate is not None:
        sale.set_value("tva", tva_rate)

    items = []
    for idx, (qty, price) in enumerate(raw_items, start=1):
        item = SalesItemClass(0, None)
        item.set_value("quantity", Decimal(str(qty)))
        item.set_value("unit_price", Decimal(str(price)))
        # subtotal is calculated (qty * unit_price), no need to set
        items.append(item)
    sale.items = items
    return sale


# ---------------------------------------------------------------------------
# Test 1: Basic discount - 1 000 subtotal, 100 remise
# ---------------------------------------------------------------------------

class TestRemiseBasic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_basic_discount(self):
        """Subtotal 1 000, Remise 100, no VAT."""
        totals = calculate_sale_totals(raw_subtotal=1000, remise=100, tva_rate=0)
        self.assertEqual(totals["original_subtotal"], Decimal("1000.00"))
        self.assertEqual(totals["remise"], Decimal("100.00"))
        self.assertEqual(totals["total_ht"], Decimal("900.00"))
        self.assertEqual(totals["vat_amount"], Decimal("0.00"))
        self.assertEqual(totals["total_ttc"], Decimal("900.00"))


# ---------------------------------------------------------------------------
# Test 2: Real-world confirmed values (Sale ID 18)
# ---------------------------------------------------------------------------

class TestRemiseRealWorld(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_sale_id_18_values(self):
        """Subtotal 70 679, Remise 5 654.32, no VAT -> Net à payer 65 024.68."""
        totals = calculate_sale_totals(raw_subtotal=70679.00, remise=5654.32, tva_rate=0)
        self.assertEqual(totals["total_ht"], Decimal("65024.68"))
        self.assertEqual(totals["vat_amount"], Decimal("0.00"))
        self.assertEqual(totals["total_ttc"], Decimal("65024.68"))

    def test_sale_object_calculate_total_price(self):
        """SalesClass.calculate_total_price() returns discounted Net à payer."""
        sale = _make_sale_obj([(10, 7067.90)], remise=5654.32)
        self.assertAlmostEqual(sale.calculate_total_price(), 65024.68, places=2)

    def test_sale_object_calculate_subtotal_returns_discounted(self):
        """SalesClass.calculate_subtotal() returns Net à payer (discounted)."""
        sale = _make_sale_obj([(10, 7067.90)], remise=5654.32)
        self.assertAlmostEqual(sale.calculate_subtotal(), 65024.68, places=2)

    def test_sale_object_calculate_total_tva_is_always_zero(self):
        """SalesClass.calculate_total_tva() is always 0 - LAMIBOIS has no VAT."""
        sale = _make_sale_obj([(10, 7067.90)], remise=5654.32)
        self.assertAlmostEqual(sale.calculate_total_tva(), 0.0, places=2)


# ---------------------------------------------------------------------------
# Test 3: Round-trip - values survive set -> get cycle
# ---------------------------------------------------------------------------

class TestRemiseRoundTrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_remise_persists_through_set_get(self):
        """After set_value('remise', ...), all derived values are correct."""
        sale = _make_sale_obj([(5, 200)], remise=150)
        self.assertAlmostEqual(sale.calculate_subtotal(), 850.00, places=2)
        self.assertAlmostEqual(sale.calculate_total_tva(), 0.0, places=2)
        self.assertAlmostEqual(sale.calculate_total_price(), 850.00, places=2)

    def test_change_remise_updates_totals(self):
        """Changing remise on an existing sale recalculates correctly."""
        sale = _make_sale_obj([(5, 200)], remise=100)
        self.assertAlmostEqual(sale.calculate_total_price(), 900.00, places=2)
        sale.set_value("remise", 200)
        self.assertAlmostEqual(sale.calculate_total_price(), 800.00, places=2)


# ---------------------------------------------------------------------------
# Test 4: Restart simulation - recalculate from raw data
# ---------------------------------------------------------------------------

class TestRemiseAfterReload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_recalculate_from_scratch(self):
        """Simulate reload: create a new SalesClass with same stored values."""
        # First object
        sale1 = _make_sale_obj([(3, 1000), (2, 500)], remise=200)
        expected_total = sale1.calculate_total_price()

        # Second object (simulates restart / reload from DB)
        sale2 = _make_sale_obj([(3, 1000), (2, 500)], remise=200)
        self.assertAlmostEqual(sale2.calculate_total_price(), expected_total, places=2)
        # Raw subtotal = 3*1000 + 2*500 = 4000, discounted = 4000-200 = 3800
        self.assertAlmostEqual(sale2.calculate_subtotal(), 3800.00, places=2)
        self.assertAlmostEqual(sale2.calculate_total_tva(), 0.0, places=2)


# ---------------------------------------------------------------------------
# Test 5: Sales without Remise
# ---------------------------------------------------------------------------

class TestRemiseZero(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_zero_remise(self):
        """Remise 0: Net à payer equals original subtotal."""
        totals = calculate_sale_totals(1000, remise=0, tva_rate=0)
        self.assertEqual(totals["total_ht"], Decimal("1000.00"))
        self.assertEqual(totals["vat_amount"], Decimal("0.00"))
        self.assertEqual(totals["total_ttc"], Decimal("1000.00"))

    def test_zero_remise_object(self):
        """SalesClass with zero remise: totals equal the raw items total."""
        sale = _make_sale_obj([(4, 250)], remise=0)
        self.assertAlmostEqual(sale.calculate_subtotal(), 1000.00, places=2)
        self.assertAlmostEqual(sale.calculate_total_tva(), 0.0, places=2)
        self.assertAlmostEqual(sale.calculate_total_price(), 1000.00, places=2)


# ---------------------------------------------------------------------------
# Test 6: Remise validation
# ---------------------------------------------------------------------------

class TestRemiseValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_negative_remise_blocked(self):
        """Remise < 0 results in a Net à payer above subtotal - UI validation blocks this."""
        totals = calculate_sale_totals(1000, remise=-50, tva_rate=0)
        self.assertEqual(totals["total_ht"], Decimal("1050.00"))

    def test_remise_exceeds_subtotal(self):
        """Remise > subtotal results in a negative Net à payer (caller must validate)."""
        totals = calculate_sale_totals(100, remise=200, tva_rate=0)
        self.assertEqual(totals["total_ht"], Decimal("-100.00"))


# ---------------------------------------------------------------------------
# Test 7: Sales table columns - LAMIBOIS shows only Total TTC (no Total HT,
# no VAT/TVA anywhere in the visible column set).
# ---------------------------------------------------------------------------

class TestRemiseNotInTableColumns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_remise_not_in_table_visible_params(self):
        """SalesClass 'table' visible parameters must NOT contain 'remise'."""
        sale = SalesClass(0, None)
        table_params = sale.get_visible_parameters("table")
        self.assertNotIn("remise", table_params)

    def test_remise_still_in_database_params(self):
        """SalesClass 'database' visible parameters must contain 'remise'."""
        sale = SalesClass(0, None)
        db_params = sale.get_visible_parameters("database")
        self.assertIn("remise", db_params)

    def test_table_columns_for_sales(self):
        """Verify expected visible columns for the Sales table.

        LAMIBOIS removes "Total HT" entirely; only "Total TTC" remains as
        the single final (no-VAT) total column, and the canonical Devis
        reference is the second column.
        """
        sale = SalesClass(0, None)
        table_cols = sale.get_visible_parameters("table")
        expected = ["id", "devis", "state", "client_name", "notes", "date", "total_ttc"]
        self.assertEqual(table_cols, expected)

    def test_total_ht_not_a_visible_table_column(self):
        """'total_ht' must not be a visible Sales table column anymore."""
        sale = SalesClass(0, None)
        table_cols = sale.get_visible_parameters("table")
        self.assertNotIn("total_ht", table_cols)

    def test_old_financial_headers_removed_from_table(self):
        """'subtotal' and 'total_price' must not be visible Sales table columns."""
        sale = SalesClass(0, None)
        table_cols = sale.get_visible_parameters("table")
        self.assertNotIn("subtotal", table_cols)
        self.assertNotIn("total_price", table_cols)

    def test_no_vat_checkbox_in_dialog(self):
        """'tva' must not be a visible/editable Sale dialog parameter."""
        sale = SalesClass(0, None)
        dialog_params = sale.get_visible_parameters("dialog")
        self.assertNotIn("tva", dialog_params)


# ---------------------------------------------------------------------------
# Test 7b: Sales table values - Total TTC as injected by the summary query
# (authoritative saved values from the Host). LAMIBOIS: no VAT, so Total TTC
# is simply Subtotal - Remise.
# ---------------------------------------------------------------------------

class TestSalesTableFinancialValues(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _inject(self, raw_subtotal, remise):
        """Simulate BaseTab._objects_from_records injecting a summary row."""
        sale = SalesClass(0, None)
        sale.set_value('remise', remise)
        injected = {
            'subtotal': float(raw_subtotal),
            'total_ttc': float(raw_subtotal - remise),
        }
        for key, value in injected.items():
            sale.set_raw_value(key, value)
        return sale

    def test_scenario_one(self):
        """1 000 - 100 remise => Total TTC 900.00."""
        sale = self._inject(1000.00, 100.00)
        self.assertAlmostEqual(sale.get_value('total_ttc'), 900.00, places=2)

    def test_scenario_two(self):
        """132 000 - 50 000 remise => Total TTC 82 000."""
        sale = self._inject(132000.00, 50000.00)
        self.assertAlmostEqual(sale.get_value('total_ttc'), 82000.00, places=2)

    def test_scenario_three(self):
        """70 679 - 5 654.32 remise => Total TTC 65 024.68."""
        sale = self._inject(70679.00, 5654.32)
        self.assertAlmostEqual(sale.get_value('total_ttc'), 65024.68, places=2)

    def test_calculate_methods_match_injected_values(self):
        """Direct calculation methods agree with the injected authoritative values."""
        totals = calculate_sale_totals(132000.00, 50000.00, 0)
        self.assertEqual(totals["total_ht"], Decimal("82000.00"))
        self.assertEqual(totals["total_ttc"], Decimal("82000.00"))
        self.assertEqual(totals["vat_amount"], Decimal("0.00"))

    def test_sales_without_remise_table_values(self):
        """No remise: Total TTC = subtotal."""
        sale = self._inject(1000.00, 0.00)
        self.assertAlmostEqual(sale.get_value('total_ttc'), 1000.00, places=2)


# ---------------------------------------------------------------------------
# Test 8: Report/PDF data extraction uses discounted Net à payer, no VAT
# ---------------------------------------------------------------------------

class _Values:
    def __init__(self, values):
        self.values = values
        self.config_path = os.path.join(os.path.dirname(__file__), "config.json")
    def get_value(self, key):
        return self.values.get(key)


class TestRemiseReportExtraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_report_net_a_payer_is_discounted(self):
        """Report extraction must return a discounted Net à payer, not raw subtotal."""
        from ui.dialogs.reports_dialog import ReportsDialog
        item = SalesItemClass(0, None)
        item.set_value("product_name", "Product A")
        item.set_value("quantity", 10)
        item.set_value("unit_price", 7067.90)

        sale = _Values({
            "id": 18, "client_name": "Test Client", "client_username": "test",
            "date": "2026-08-04", "remise": 5654.32,
            "notes": "", "client_id": 1,
        })
        sale.items = [item]
        sale.database = None

        profile = _Values({"company name": "Test Co"})
        manager = type("M", (), {"selected_profile": profile})()
        dialog = ReportsDialog(sale, manager)
        data = dialog._extract_sales_data("devis")

        self.assertEqual(data["total_remise"], "5 654,32")
        self.assertEqual(data["net_a_payer"], "65 024,68")

    def test_report_ignores_a_stale_vat_flag_on_the_sale(self):
        """A legacy Sale with a nonzero 'tva' flag must still report no VAT."""
        from ui.dialogs.reports_dialog import ReportsDialog
        item = SalesItemClass(0, None)
        item.set_value("product_name", "Product A")
        item.set_value("quantity", 10)
        item.set_value("unit_price", 7067.90)

        sale = _Values({
            "id": 19, "client_name": "Test Client", "client_username": "test",
            "date": "2026-08-04", "tva": 20.0, "remise": 5654.32,
            "notes": "", "client_id": 1,
        })
        sale.items = [item]
        sale.database = None

        profile = _Values({"company name": "Test Co"})
        manager = type("M", (), {"selected_profile": profile})()
        dialog = ReportsDialog(sale, manager)
        data = dialog._extract_sales_data("devis")

        self.assertEqual(data["net_a_payer"], "65 024,68")

    def test_report_zero_remise(self):
        """Report with zero remise: Net à payer = raw subtotal."""
        from ui.dialogs.reports_dialog import ReportsDialog
        item = SalesItemClass(0, None)
        item.set_value("product_name", "Service X")
        item.set_value("quantity", 2)
        item.set_value("unit_price", 500)

        sale = _Values({
            "id": 99, "client_name": "Client", "client_username": "c",
            "date": "2026-08-04", "remise": 0,
            "notes": "", "client_id": 1,
        })
        sale.items = [item]
        sale.database = None

        profile = _Values({"company name": "Test Co"})
        manager = type("M", (), {"selected_profile": profile})()
        dialog = ReportsDialog(sale, manager)
        data = dialog._extract_sales_data("devis")

        self.assertEqual(data["total_remise"], "0,00")
        self.assertEqual(data["net_a_payer"], "1 000,00")


# ---------------------------------------------------------------------------
# Test 9: A stale/legacy 'tva' value never leaks into any total
# ---------------------------------------------------------------------------

class TestLegacyVatFlagIgnored(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_nonzero_tva_flag_has_no_effect_on_sale_totals(self):
        """Setting tva=20 on the object must not change any computed total."""
        with_vat_flag = _make_sale_obj([(10, 100)], remise=0, tva_rate=20.0)
        without_vat_flag = _make_sale_obj([(10, 100)], remise=0)
        self.assertEqual(
            with_vat_flag.calculate_total_price(),
            without_vat_flag.calculate_total_price(),
        )
        self.assertEqual(with_vat_flag.calculate_total_price(), 1000.00)
        self.assertEqual(with_vat_flag.calculate_total_tva(), 0.0)


if __name__ == "__main__":
    unittest.main()
