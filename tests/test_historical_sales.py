import json
import unittest
from unittest.mock import patch

from classes.sales_class import SalesClass
from core.database import Database
from core.network.client import RemoteDatabase
from tests.test_network_sale_saving import _Connection, _Cursor


def _database(existing=()):
    database = Database.__new__(Database)
    database.conn = _Connection()
    database.cursor = _Cursor(existing)
    database.registered_classes = {'Sales': SalesClass}
    return database


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({'result': {'transaction': 'committed', 'saved': 1}}).encode()


class HistoricalSaleSavingTests(unittest.TestCase):
    def _stock_sql(self, database):
        return [sql for sql, _params in database.cursor.statements if 'sales_items' in sql]

    def test_historical_sale_skips_stock_gate_entirely(self):
        database = _database()
        result = database.save_sale_with_items(
            {
                'client_username': 'client', 'date': '2026-07-20',
                'tva': 0, 'state': 'pending', 'is_historical': True,
            },
            [
                {
                    'item_type': 'product', 'product_name': 'Known Product',
                    'quantity': 99999, 'unit_price': 10,
                },
            ],
            visible_row_count=1,
        )
        self.assertEqual(result['saved'], 1)
        self.assertEqual(database.conn.commits, 1)
        self.assertEqual(database.conn.rollbacks, 0)
        # The FOR UPDATE lock used by the normal stock gate must not run.
        self.assertFalse(any(
            sql.startswith('select id from products') and sql.endswith('for update')
            for sql, _params in database.cursor.statements
        ))

    def test_historical_flag_persisted_in_insert_header(self):
        database = _database()
        database.save_sale_with_items(
            {
                'client_username': 'client', 'date': '2026-07-20',
                'tva': 0, 'state': 'pending', 'is_historical': True,
            },
            [
                {
                    'item_type': 'product', 'product_name': 'Known Product',
                    'quantity': 1, 'unit_price': 10,
                },
            ],
            visible_row_count=1,
        )
        inserts = [
            (sql, params) for sql, params in database.cursor.statements
            if sql.startswith('insert into sales ')
        ]
        self.assertEqual(len(inserts), 1)
        _sql, params = inserts[0]
        self.assertIn('is_historical', _sql)
        self.assertIn(True, params)

    def test_normal_sale_within_stock_commits_once(self):
        database = _database()
        result = database.save_sale_with_items(
            {
                'client_username': 'client', 'date': '2026-07-20',
                'tva': 0, 'state': 'pending', 'is_historical': False,
            },
            [
                {
                    'item_type': 'product', 'product_name': 'Known Product',
                    'quantity': 50, 'unit_price': 10,
                },
            ],
            visible_row_count=1,
        )
        self.assertEqual(result['saved'], 1)
        self.assertEqual(database.conn.commits, 1)
        self.assertEqual(database.conn.rollbacks, 0)

    def test_switching_existing_sale_to_historical_skips_gate(self):
        database = _database(existing=(101,))
        result = database.save_sale_with_items(
            {
                'client_username': 'client', 'date': '2026-07-20',
                'tva': 0, 'state': 'pending', 'is_historical': True,
            },
            [
                {
                    'id': 101, 'item_type': 'product', 'product_name': 'Known Product',
                    'quantity': 99999, 'unit_price': 10,
                },
            ],
            sale_id=7,
            visible_row_count=1,
        )
        self.assertEqual(result['saved'], 1)
        self.assertEqual(database.conn.commits, 1)
        self.assertTrue(any(
            sql.startswith('update sales ') for sql, _ in database.cursor.statements
        ))

    def test_manual_keep_only_line_saves_without_catalog_link(self):
        database = _database()
        result = database.save_sale_with_items(
            {
                'client_username': 'client', 'date': '2026-07-20',
                'tva': 0, 'state': 'pending', 'is_historical': True,
            },
            [
                {
                    'item_type': 'manual', 'product_name': 'Handmade Item',
                    'quantity': 2, 'unit_price': 5,
                },
            ],
            visible_row_count=1,
        )
        self.assertEqual(result['saved'], 1)
        self.assertEqual(result['items'][0]['item_type'], 'manual')
        self.assertIsNone(result['items'][0]['product_id'])
        self.assertIsNone(result['items'][0]['service_id'])
        item_inserts = [
            sql for sql, _ in database.cursor.statements
            if sql.startswith('insert into sales_items ')
        ]
        self.assertEqual(len(item_inserts), 1)

    def test_historical_unknown_product_created_with_zero_starting_stock(self):
        database = _database()
        database.cursor.next_product_id = 200
        original_execute = database.cursor.execute

        def execute(sql, params=()):
            normalized = ' '.join(sql.lower().split())
            if normalized.startswith('insert into products '):
                database.cursor.fetchone_value = (200,)
                database.cursor.fetchall_value = []
                database.cursor.rowcount = 1
                database.cursor.description = None
                database.cursor.statements.append((normalized, params))
                return
            original_execute(sql, params)

        database.cursor.execute = execute
        result = database.save_sale_with_items(
            {
                'client_username': 'client', 'date': '2026-07-20',
                'tva': 0, 'state': 'pending', 'is_historical': True,
            },
            [
                {
                    'item_type': 'product', 'product_name': 'Brand New Widget',
                    'quantity': 5, 'unit_price': 20,
                },
            ],
            visible_row_count=1,
            pending_entities=[
                {
                    'type': 'product', 'name': 'Brand New Widget',
                    'unit_price': '20', 'sale_price': '20',
                    'initial_quantity': '0', 'purchase_price': '0',
                },
            ],
        )
        self.assertEqual(result['saved'], 1)
        self.assertEqual(result['items'][0]['product_id'], 200)
        # Zero starting stock -> no opening import rows must be written.
        self.assertFalse(any(
            sql.startswith('insert into imports ')
            for sql, _ in database.cursor.statements
        ))

    def test_pending_duplicate_names_created_only_once_case_insensitive(self):
        database = _database()
        database.cursor.next_product_id = 200
        database.cursor.next_service_id = 300
        original_execute = database.cursor.execute

        def execute(sql, params=()):
            normalized = ' '.join(sql.lower().split())
            if normalized.startswith('insert into products '):
                database.cursor.fetchone_value = (200,)
            elif normalized.startswith('insert into services '):
                database.cursor.fetchone_value = (300,)
            else:
                original_execute(sql, params)
                return
            database.cursor.fetchall_value = []
            database.cursor.rowcount = 1
            database.cursor.description = None
            database.cursor.statements.append((normalized, params))

        database.cursor.execute = execute
        result = database.save_sale_with_items(
            {
                'client_username': 'client', 'date': '2026-07-20',
                'tva': 0, 'state': 'pending', 'is_historical': True,
            },
            [
                {
                    'item_type': 'product', 'product_name': 'Widget Case',
                    'quantity': 1, 'unit_price': 10,
                },
            ],
            visible_row_count=1,
            pending_entities=[
                {
                    'type': 'product', 'name': 'Widget Case',
                    'unit_price': '10', 'sale_price': '10',
                    'initial_quantity': '0', 'purchase_price': '0',
                },
                {
                    'type': 'product', 'name': 'WIDGET CASE',
                    'unit_price': '10', 'sale_price': '10',
                    'initial_quantity': '0', 'purchase_price': '0',
                },
            ],
        )
        self.assertEqual(result['items'][0]['product_id'], 200)
        product_inserts = [
            sql for sql, _ in database.cursor.statements
            if sql.startswith('insert into products ')
        ]
        self.assertEqual(len(product_inserts), 1)

    def test_stock_level_queries_exclude_historical_sales(self):
        database = _database()
        database.get_product_stock_levels()
        statements = [sql for sql, _params in database.cursor.statements]
        self.assertTrue(statements)
        self.assertIn('(s.is_historical is null or not s.is_historical)', statements[-1])

    def test_sale_catalog_excludes_historical_sales(self):
        database = _database()
        database.cursor.fetchall_value = []
        database.get_sale_catalog()
        statements = [sql for sql, _params in database.cursor.statements]
        sold_sql = [s for s in statements if 'sales_items' in s and 'sold' in s]
        self.assertTrue(any(
            '(s.is_historical is null or not s.is_historical)' in s
            for s in statements
        ))

    def test_remote_serializes_historical_flag_in_header(self):
        remote = RemoteDatabase(None, 'host-pc', 8765, 'user', 'password')
        remote._token = 'test-token'
        captured = {}

        def open_request(request, timeout):
            captured.update(json.loads(request.data.decode()))
            return _Response()

        with patch('urllib.request.urlopen', side_effect=open_request):
            remote._call(
                'save_sale_with_items',
                [
                    {
                        'client_username': 'client', 'date': '2026-07-20',
                        'tva': 0, 'state': 'pending', 'is_historical': True,
                    },
                    [{
                        'item_type': 'product', 'product_name': 'Known Product',
                        'quantity': 1, 'unit_price': 10,
                    }],
                    None, 1, [],
                ],
            )
        self.assertIs(captured['args'][0]['is_historical'], True)


if __name__ == '__main__':
    unittest.main()
