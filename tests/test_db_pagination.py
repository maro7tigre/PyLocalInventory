"""Keyset pagination tests for the Database query layer.

These verify the infinite-scroll SQL fragments (composite row comparison on
(sort_expr, id)), the date normalization of the cursor value, and the summary
path used by the Sales/Imports tabs - all against a fake cursor, no live DB.
"""

import unittest
from decimal import Decimal

from classes.sales_class import SalesClass
from core.database import Database
from tests.test_network_sale_saving import _Connection, _Cursor


class _PageCursor(_Cursor):
    """Like _Cursor but keeps description/fetchall_value intact after execute,
    so the pagination SELECT queries can build column names from them."""

    def execute(self, sql, params=()):
        normalized = ' '.join(sql.lower().split())
        self.statements.append((normalized, params))


def _database(section='Products', existing=()):
    database = Database.__new__(Database)
    database.conn = _Connection()
    database.cursor = _PageCursor(existing)
    database.registered_classes = {section: SalesClass}
    return database


def _simulate_rows(cursor, columns, rows):
    cursor.description = [(name,) for name in columns]
    cursor.fetchall_value = list(rows)


class KeysetPaginationTests(unittest.TestCase):
    def test_first_batch_has_no_keyset_condition(self):
        database = _database()
        _simulate_rows(database.cursor, ['id', 'name'], [(1, 'A'), (2, 'B')])
        result = database.get_items('Products', limit=10)
        self.assertEqual(len(result), 2)
        normalized = database.cursor.statements[0][0]
        self.assertIn('select * from products', normalized)
        self.assertIn('order by id', normalized)
        self.assertNotIn('(%s, %s)', normalized)

    def test_after_cursor_builds_composite_keyset_condition(self):
        database = _database()
        _simulate_rows(database.cursor, ['id', 'name'], [(6, 'Zed')])
        result = database.get_items(
            'Products', order_by='name', order_dir='asc', limit=10,
            after_id=5, after_sort='Acme',
        )
        self.assertEqual(len(result), 1)
        sql, params = database.cursor.statements[0]
        self.assertIn("(coalesce(name, ''), id) > (%s, %s)", sql)
        self.assertEqual(params[:2], ['Acme', 5])
        self.assertIn('order by coalesce(name, \'\') asc, id asc', sql)
        self.assertIn('limit %s', sql)

    def test_desc_keyset_uses_less_than(self):
        database = _database()
        _simulate_rows(database.cursor, ['id', 'name'], [])
        database.get_items(
            'Products', order_by='name', order_dir='desc', limit=10,
            after_id=5, after_sort='Zed',
        )
        sql, params = database.cursor.statements[0]
        self.assertIn("(coalesce(name, ''), id) < (%s, %s)", sql)
        self.assertEqual(params[:2], ['Zed', 5])

    def test_date_cursor_value_normalized(self):
        database = _database('Sales')
        _simulate_rows(database.cursor, ['id', 'date'], [])
        database.get_items(
            'Sales', order_by='date', order_dir='desc', limit=10,
            after_id=3, after_sort='31-12-2024',
        )
        sql, params = database.cursor.statements[0]
        self.assertIn('to_date(date', sql)
        self.assertEqual(params[:2], ['2024-12-31', 3])

    def test_unparseable_date_cursor_falls_back_to_coalesce_default(self):
        self.assertEqual(
            Database._keyset_sort_value('date', 'December 2024'),
            '1900-01-01',
        )

    def test_summary_query_supports_keyset_on_total_price(self):
        database = _database('Sales')
        _simulate_rows(database.cursor, ['id', 'total_price'], [(1, Decimal('50'))])
        result = database.get_operation_summary_items(
            'Sales', order_by='total_price', order_dir='asc', limit=10,
            after_id=5, after_sort=Decimal('100'),
        )
        self.assertEqual(len(result), 1)
        sql, params = database.cursor.statements[0]
        self.assertIn('(coalesce(summary.total_price, 0), id) > (%s, %s)', sql)
        self.assertEqual(params[:2], [Decimal('100'), 5])
        self.assertIn('order by coalesce(summary.total_price, 0) asc, s.id asc', sql)
        self.assertIn('left join', sql)

    def test_sales_summary_returns_discounted_totals(self):
        """Sales summary query must compute Total HT/TTC with remise (no VAT)."""
        database = _database('Sales')
        _simulate_rows(database.cursor, ['id', 'total_ht', 'total_ttc', 'vat_amount'], [])
        database.get_operation_summary_items('Sales', limit=10)
        sql, _params = database.cursor.statements[0]
        self.assertIn('coalesce(s.remise, 0)', sql)
        self.assertIn('as total_ht', sql)
        self.assertIn('as total_ttc', sql)
        self.assertIn('as vat_amount', sql)

    def test_imports_summary_has_no_remise_reference(self):
        """Imports have no remise column; the shared query must not reference it."""
        database = _database('Imports')
        _simulate_rows(database.cursor, ['id', 'total_ht'], [])
        database.get_operation_summary_items('Imports', limit=10)
        sql, _params = database.cursor.statements[0]
        self.assertNotIn('remise', sql)
        self.assertIn('as total_ht', sql)

    def test_summary_query_supports_keyset_on_total_ttc(self):
        """Sorting the Sales table by Total uses the final Total TTC expression.

        LAMIBOIS applies no VAT: Total TTC is Subtotal - Remise (same as
        Total HT), with no VAT multiplier.
        """
        database = _database('Sales')
        _simulate_rows(database.cursor, ['id', 'total_ttc'], [(1, Decimal('98400'))])
        result = database.get_operation_summary_items(
            'Sales', order_by='total_ttc', order_dir='asc', limit=10,
            after_id=5, after_sort=Decimal('90000'),
        )
        self.assertEqual(len(result), 1)
        sql, params = database.cursor.statements[0]
        self.assertIn(
            '(coalesce(summary.subtotal - coalesce(s.remise, 0), 0), id) > (%s, %s)',
            sql,
        )
        self.assertEqual(params[:2], [Decimal('90000'), 5])

    def test_summary_query_without_summarize_delegates_to_get_items(self):
        database = _database('Clients')
        _simulate_rows(database.cursor, ['id', 'name'], [(1, 'A')])
        result = database.get_operation_summary_items('Clients', limit=10)
        self.assertEqual(len(result), 1)
        sql, _params = database.cursor.statements[0]
        self.assertIn('select * from clients', sql)

    def test_get_items_for_user_passes_keyset_through(self):
        database = _database('Reports')
        _simulate_rows(database.cursor, ['id', 'department'], [(7, 'Sales')])
        database.get_items_for_user(
            'Reports', {'is_superadmin': True, 'username': 'admin'},
            order_by='department', order_dir='asc', limit=10,
            after_id=6, after_sort='Support',
        )
        sql, params = database.cursor.statements[0]
        self.assertIn("(coalesce(department, ''), id) > (%s, %s)", sql)
        self.assertEqual(params[:2], ['Support', 6])

    def test_order_column_expression_is_null_safe(self):
        self.assertEqual(
            Database._order_column_expression('name'),
            "COALESCE(name, '')",
        )
        self.assertEqual(
            Database._order_column_expression('quantity'),
            'COALESCE(quantity, 0)',
        )
        self.assertEqual(Database._order_column_expression('id'), None)

    def test_summary_order_expression_handles_aliases(self):
        self.assertEqual(
            Database._summary_order_expression('total_price'),
            'COALESCE(summary.total_price, 0)',
        )
        self.assertEqual(
            Database._summary_order_expression('name'),
            "COALESCE(s.name, '')",
        )
        self.assertEqual(Database._summary_order_expression('id'), None)


if __name__ == '__main__':
    unittest.main()
