"""Tests for the shared monetary calculation helpers (core.calculations).

Regression coverage for the crash:

    Error calculating subtotal: unsupported operand type(s) for *:
    'decimal.Decimal' and 'float'

which happened whenever an Import line's Decimal quantity (decimal parameter
type) was multiplied by its float unit price. All quantity/price math must
now go through the shared helpers, which normalize every input through
``Decimal(str(value or 0))`` so a raw float is never combined with a Decimal.
"""

import os
import unittest
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.calculations import (
    calculate_line_subtotal,
    calculate_operation_totals,
    to_decimal,
)
from classes.import_class import ImportClass
from classes.import_item_class import ImportItemClass
from classes.sales_item_class import SalesItemClass
from classes.sales_class import calculate_sale_totals


class ToDecimalTests(unittest.TestCase):
    """to_decimal() normalizes every supported input type."""

    def test_decimal(self):
        self.assertEqual(to_decimal(Decimal("12.34")), Decimal("12.34"))

    def test_int(self):
        self.assertEqual(to_decimal(42), Decimal("42"))

    def test_float(self):
        self.assertEqual(to_decimal(12.5), Decimal("12.5"))

    def test_float_never_via_decimal_constructor(self):
        # Decimal(str(0.1)) == Decimal("0.1"); Decimal(0.1) would be the full
        # binary approximation. This is the heart of the regression fix.
        self.assertEqual(to_decimal(0.1), Decimal("0.1"))

    def test_float_binary_exactness(self):
        # 19.99 cannot be represented exactly in binary; the str() round-trip
        # keeps the decimal representation the user actually saw.
        self.assertEqual(to_decimal(19.99), Decimal("19.99"))

    def test_string(self):
        self.assertEqual(to_decimal("12.34"), Decimal("12.34"))

    def test_string_comma_decimal_separator(self):
        self.assertEqual(to_decimal("12,34"), Decimal("12.34"))

    def test_string_with_spaces_and_commas(self):
        self.assertEqual(to_decimal("70 679,00"), Decimal("70679.00"))

    def test_empty_string(self):
        self.assertEqual(to_decimal(""), Decimal("0"))

    def test_whitespace_string(self):
        self.assertEqual(to_decimal("   "), Decimal("0"))

    def test_none(self):
        self.assertEqual(to_decimal(None), Decimal("0"))


class LineSubtotalTests(unittest.TestCase):
    """calculate_line_subtotal(qty, unit_price) == qty * unit_price."""

    def test_decimal_times_decimal(self):
        self.assertEqual(
            calculate_line_subtotal(Decimal("5"), Decimal("19.99")),
            Decimal("99.95"),
        )

    def test_float_origin_price(self):
        # Decimal quantity * float unit price - the original TypeError.
        self.assertEqual(calculate_line_subtotal(Decimal("5"), 19.99), Decimal("99.95"))

    def test_float_origin_quantity(self):
        self.assertEqual(calculate_line_subtotal(3.5, Decimal("10.00")), Decimal("35.00"))

    def test_string_inputs(self):
        self.assertEqual(calculate_line_subtotal("5", "19.99"), Decimal("99.95"))

    def test_comma_string_inputs(self):
        self.assertEqual(calculate_line_subtotal("5", "19,99"), Decimal("99.95"))

    def test_empty_and_none(self):
        self.assertEqual(calculate_line_subtotal(None, None), Decimal("0"))
        self.assertEqual(calculate_line_subtotal("", "2"), Decimal("0"))


class OperationTotalsTests(unittest.TestCase):
    """calculate_operation_totals formulas and 2-dp ROUND_HALF_UP policy."""

    def test_full_chain(self):
        totals = calculate_operation_totals(1000, 100, 20)
        self.assertEqual(totals["original_subtotal"], Decimal("1000.00"))
        self.assertEqual(totals["remise"], Decimal("100.00"))
        self.assertEqual(totals["total_ht"], Decimal("900.00"))
        self.assertEqual(totals["vat_amount"], Decimal("180.00"))
        self.assertEqual(totals["total_ttc"], Decimal("1080.00"))

    def test_mixed_input_types(self):
        totals = calculate_operation_totals("1000,00", 100.0, Decimal("20"))
        self.assertEqual(totals["total_ht"], Decimal("900.00"))
        self.assertEqual(totals["vat_amount"], Decimal("180.00"))
        self.assertEqual(totals["total_ttc"], Decimal("1080.00"))

    def test_negative_remise(self):
        totals = calculate_operation_totals(1000, -50, 20)
        self.assertEqual(totals["total_ht"], Decimal("1050.00"))

    def test_negative_subtotal(self):
        totals = calculate_operation_totals(-100, 0, 20)
        self.assertEqual(totals["total_ht"], Decimal("-100.00"))
        self.assertEqual(totals["vat_amount"], Decimal("-20.00"))
        self.assertEqual(totals["total_ttc"], Decimal("-120.00"))

    def test_half_up_rounding(self):
        # 1.005 must round to 1.01 (ROUND_HALF_UP), never 1.00 (banker's).
        totals = calculate_operation_totals("1.005", 0, 0)
        self.assertEqual(totals["total_ttc"], Decimal("1.01"))

    def test_zero_vat_rate(self):
        totals = calculate_operation_totals(5000, 500, 0)
        self.assertEqual(totals["total_ht"], Decimal("4500.00"))
        self.assertEqual(totals["vat_amount"], Decimal("0.00"))
        self.assertEqual(totals["total_ttc"], Decimal("4500.00"))

    def test_delegation_from_sales_module(self):
        # calculate_sale_totals keeps its public contract and returns Decimals.
        totals = calculate_sale_totals(raw_subtotal=70679.00, remise=5654.32, tva_rate=20)
        self.assertEqual(totals["total_ht"], Decimal("65024.68"))
        self.assertEqual(totals["vat_amount"], Decimal("13004.94"))
        self.assertEqual(totals["total_ttc"], Decimal("78029.62"))


class ImportItemSubtotalRegressionTests(unittest.TestCase):
    """The exact crash scenarios: Decimal quantity * float unit price."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_import_item_quantity_decimal_price_float(self):
        item = ImportItemClass(0, None)
        item.set_value("quantity", Decimal("5"))
        item.set_value("unit_price", 19.99)
        self.assertEqual(item.get_value("subtotal"), Decimal("99.95"))

    def test_import_item_integer_quantity_price_float(self):
        item = ImportItemClass(0, None)
        item.set_value("quantity", 3)
        item.set_value("unit_price", 250.0)
        self.assertEqual(item.get_value("subtotal"), Decimal("750.00"))

    def test_sales_item_quantity_decimal_price_float(self):
        item = SalesItemClass(0, None)
        item.set_value("quantity", Decimal("2"))
        item.set_value("unit_price", 250.0)
        self.assertEqual(item.get_value("subtotal"), Decimal("500.00"))

    def test_import_operation_total_matches_formula(self):
        """Import totals reuse the shared Decimal math end to end.

        LAMIBOIS applies no VAT: setting 'tva' (a legacy/schema-only column)
        must have zero effect on the computed total.
        """
        item_a = ImportItemClass(0, None)
        item_a.set_value("quantity", Decimal("10"))
        item_a.set_value("unit_price", 7067.90)

        item_b = ImportItemClass(0, None)
        item_b.set_value("quantity", 2)
        item_b.set_value("unit_price", 999.99)

        imp = ImportClass(0, None)
        imp.database = type("D", (), {"cursor": object()})()
        imp.set_value("tva", 20)
        imp.items = [item_a, item_b]

        self.assertEqual(imp.calculate_subtotal(), Decimal("72678.98"))
        # No VAT: total_price = 10*7067.90 + 2*999.99, unaffected by 'tva'.
        self.assertAlmostEqual(imp.calculate_total_price(), 72678.98, places=2)



class TestDecimalParsing(unittest.TestCase):
    def test_parse_decimal_input(self):
        from core.calculations import parse_decimal_input, InputState
        from decimal import Decimal

        # Valid cases
        self.assertEqual(parse_decimal_input('12'), (InputState.VALID, Decimal('12')))
        self.assertEqual(parse_decimal_input('12.50'), (InputState.VALID, Decimal('12.50')))
        self.assertEqual(parse_decimal_input('12,50'), (InputState.VALID, Decimal('12.50')))
        self.assertEqual(parse_decimal_input('1 234,50'), (InputState.VALID, Decimal('1234.50')))
        self.assertEqual(parse_decimal_input(12), (InputState.VALID, Decimal('12')))
        self.assertEqual(parse_decimal_input(12.50), (InputState.VALID, Decimal('12.5')))
        self.assertEqual(parse_decimal_input(Decimal('12.50')), (InputState.VALID, Decimal('12.50')))

        # Empty cases
        self.assertEqual(parse_decimal_input(''), (InputState.EMPTY, Decimal('0')))
        self.assertEqual(parse_decimal_input('   '), (InputState.EMPTY, Decimal('0')))
        self.assertEqual(parse_decimal_input(None), (InputState.EMPTY, Decimal('0')))

        # Intermediate cases (should not crash)
        self.assertEqual(parse_decimal_input('-'), (InputState.INTERMEDIATE, Decimal('0')))
        self.assertEqual(parse_decimal_input('+'), (InputState.INTERMEDIATE, Decimal('0')))
        self.assertEqual(parse_decimal_input('.'), (InputState.INTERMEDIATE, Decimal('0')))
        self.assertEqual(parse_decimal_input(','), (InputState.INTERMEDIATE, Decimal('0')))
        self.assertEqual(parse_decimal_input('1.'), (InputState.INTERMEDIATE, Decimal('0')))
        self.assertEqual(parse_decimal_input('1,'), (InputState.INTERMEDIATE, Decimal('0')))
        self.assertEqual(parse_decimal_input('-.'), (InputState.INTERMEDIATE, Decimal('0')))

        # Malformed/Invalid cases
        self.assertEqual(parse_decimal_input('abc'), (InputState.INVALID, Decimal('0')))
        self.assertEqual(parse_decimal_input('12..5'), (InputState.INVALID, Decimal('0')))

if __name__ == "__main__":
    unittest.main()


