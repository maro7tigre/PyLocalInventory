import json
import unittest
from decimal import Decimal
from unittest.mock import patch

from classes.sales_class import SalesClass
from core.database import Database
from core.network.client import RemoteDatabase
from core.network.server import DatabaseServer


class _Connection:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _Cursor:
    def __init__(self, existing=()):
        self.existing = list(existing)
        self.fetchone_value = None
        self.fetchall_value = []
        self.rowcount = 1
        self.next_sale_id = 42
        self.next_item_id = 1000
        self.statements = []
        self.description = None

    def execute(self, sql, params=()):
        normalized = ' '.join(sql.lower().split())
        self.statements.append((normalized, params))
        self.fetchone_value = None
        self.fetchall_value = []
        self.rowcount = 1
        self.description = None
        if normalized.startswith('select id, name from products'):
            self.fetchone_value = (11, 'Known Product') if str(params[0]).lower() == 'known product' else None
        elif normalized.startswith('select id from products where id=') and normalized.endswith('for update'):
            self.fetchone_value = (int(params[0]),)
        elif normalized.startswith('select id, name from services'):
            self.fetchone_value = (22, 'Known Service') if str(params[0]).lower() == 'known service' else None
        elif normalized.startswith('select id, name, username from clients'):
            self.fetchone_value = (33, 'Client', 'client')
        elif normalized.startswith('select coalesce(sum(ii.quantity), 0) from import_items'):
            self.fetchone_value = (100,)
        elif normalized.startswith('select coalesce(sum(si.quantity), 0)'):
            self.fetchone_value = (0,)
        elif normalized.startswith('insert into sales '):
            self.fetchone_value = (self.next_sale_id,)
        elif normalized.startswith('select id from sales_items'):
            self.fetchall_value = [(item_id,) for item_id in self.existing]
        elif normalized.startswith('select * from sales'):
            self.description = [
                ('id',), ('state',), ('client_id',), ('client_username',), ('date',),
                ('tva',), ('notes',), ('created_by',), ('created_by_username',),
                ('created_at',), ('operation_token',),
            ]
            self.fetchall_value = [
                (1, 'pending', 33, 'client', '2026-07-24', 20.0, '', 1, 'user1', '2026-07-24', ''),
                (2, 'pending', 34, 'client2', '2026-07-25', 0.0, '', 2, 'user2', '2026-07-25', ''),
            ]
        elif normalized.startswith('insert into sales_items'):
            self.next_item_id += 1
            self.fetchone_value = (self.next_item_id,)

    def fetchone(self):
        return self.fetchone_value

    def fetchall(self):
        return self.fetchall_value


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


class _SchemaCursor:
    description = None
    rowcount = -1

    def execute(self, sql, params=()):
        self.sql = sql

    def close(self):
        pass


class _SchemaConnection:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.cursor_instance = _SchemaCursor()

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    def getconn(self):
        return self.connection

    def putconn(self, connection):
        self.returned = connection


class NetworkSaleSavingTests(unittest.TestCase):
    def test_schema_rpc_commits_on_the_connection_that_executes_it(self):
        connection = _SchemaConnection()
        server = DatabaseServer.__new__(DatabaseServer)
        server.database = type('HostDatabase', (), {'registered_classes': {}})()
        server.database_name = 'test'
        server.schema_name = 'test'
        server._pool = _Pool(connection)
        server._dispatch('cursor.execute', ['CREATE TABLE IF NOT EXISTS Payments (id INTEGER)', []], {})
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 1)
        self.assertIs(server._pool.returned, connection)

    def test_remote_request_serializes_decimal_lines(self):
        remote = RemoteDatabase(None, 'host-pc', 8765, 'user', 'password')
        remote._token = 'test-token'
        captured = {}

        def open_request(request, timeout):
            captured.update(json.loads(request.data.decode()))
            return _Response()

        with patch('urllib.request.urlopen', side_effect=open_request):
            result = remote._call(
                'save_sale_with_items',
                [{'client_username': 'client'}, [{'product_name': 'Manual', 'quantity': Decimal('2.50'), 'unit_price': Decimal('0')}]],
            )
        self.assertEqual(captured['args'][1][0]['quantity'], '2.50')
        self.assertEqual(captured['args'][1][0]['unit_price'], '0')
        self.assertEqual(result['saved'], 1)

    def test_create_saves_product_and_service_lines_atomically(self):
        database = _database()
        result = database.save_sale_with_items(
            {'client_username': 'client', 'date': '2026-07-20', 'tva': 20, 'state': 'pending'},
            [
                {'item_type': 'product', 'product_name': 'Known Product', 'quantity': '1,5', 'unit_price': '10'},
                {'item_type': 'service', 'product_name': 'Known Service', 'quantity': 2, 'unit_price': 15},
            ],
            visible_row_count=2,
        )
        self.assertEqual(result['saved'], 2)
        self.assertEqual(result['inserted'], 2)
        self.assertEqual([item['item_type'] for item in result['items']], ['product', 'service'])
        self.assertEqual(database.conn.commits, 1)
        self.assertEqual(database.conn.rollbacks, 0)

    def test_edit_updates_inserts_and_deletes_without_delete_first(self):
        database = _database(existing=(101, 102))
        result = database.save_sale_with_items(
            {'client_username': 'client', 'date': '2026-07-20', 'tva': 0, 'state': 'pending'},
            [
                {'id': 101, 'item_type': 'product', 'product_name': 'Known Product', 'quantity': 3, 'unit_price': 9},
                {'item_type': 'service', 'product_name': 'Known Service', 'quantity': 1, 'unit_price': 4},
            ],
            sale_id=7,
            visible_row_count=2,
        )
        self.assertEqual((result['updated'], result['inserted'], result['deleted']), (1, 1, 1))
        line_sql = [sql for sql, _ in database.cursor.statements if 'sales_items' in sql]
        self.assertTrue(any(sql.startswith('update sales_items') for sql in line_sql))
        self.assertTrue(any(sql.startswith('delete from sales_items') for sql in line_sql))
        self.assertFalse(line_sql[0].startswith('delete'))
        self.assertEqual(database.conn.commits, 1)

    def test_invalid_existing_line_rolls_back_header_and_lines(self):
        database = _database(existing=(101,))
        with self.assertRaisesRegex(ValueError, 'does not belong'):
            database.save_sale_with_items(
                {'client_username': 'client', 'date': '2026-07-20', 'tva': 20, 'state': 'pending'},
                [{'id': 999, 'item_type': 'manual', 'product_name': 'Manual', 'quantity': 1, 'unit_price': 1}],
                sale_id=7,
                visible_row_count=1,
            )
        self.assertEqual(database.conn.commits, 0)
        self.assertEqual(database.conn.rollbacks, 1)

    def test_nonempty_visible_rows_cannot_be_sent_as_empty_array(self):
        database = _database()
        with self.assertRaisesRegex(ValueError, 'received 0 valid items'):
            database.save_sale_with_items({}, [], visible_row_count=2)

    def test_insufficient_stock_rolls_back_sale_and_lines(self):
        database = _database()
        with self.assertRaisesRegex(ValueError, "Insufficient stock"):
            database.save_sale_with_items(
                {
                    "client_username": "client", "date": "2026-07-20",
                    "tva": 0, "state": "pending",
                },
                [{
                    "item_type": "product", "product_name": "Known Product",
                    "quantity": 101, "unit_price": 10,
                }],
                visible_row_count=1,
            )
        self.assertEqual(database.conn.commits, 0)
        self.assertEqual(database.conn.rollbacks, 1)
        self.assertTrue(any(
            sql.startswith("select id from products") and sql.endswith("for update")
            for sql, _params in database.cursor.statements
        ))

    def test_get_items_for_user_returns_all_sales(self):
        database = _database()
        database.cursor.fetchall_value = [
            (1, 'pending', 33, 'client', '2026-07-24', 20.0, '', 1, 'user1', '2026-07-24', ''),
            (2, 'pending', 34, 'client2', '2026-07-25', 0.0, '', 1, 'user2', '2026-07-25', ''),
        ]
        database.cursor.description = [
            ('id',), ('state',), ('client_id',), ('client_username',), ('date',),
            ('tva',), ('notes',), ('created_by',), ('created_by_username',),
            ('created_at',), ('operation_token',),
        ]
        user = {'is_superadmin': False, 'id': 7}
        result = database.get_items_for_user('Sales', user)
        self.assertEqual(len(result), 2)


if __name__ == '__main__':
    unittest.main()
