"""Phase 6 tests: incremental sync endpoint permission gating and client-side
application of changes into the on-disk SQLite cache."""

import os
import tempfile
import unittest

from classes.sales_class import SalesClass
from core.cache_manager import CacheManager
from core.database import Database
from core.network.client import RemoteDatabase
from core.network.server import _check_permission


def _user(products_read=False):
    return {
        "is_superadmin": False,
        "permissions": {
            "Products": {
                "read": products_read,
                "write": False,
                "delete": False,
            },
        },
    }


class _FakeClient(RemoteDatabase):
    """RemoteDatabase-shaped client whose get_changes returns canned payloads
    and records the (section, since_seq, limit) calls it received."""

    def __init__(self, cache, responses):
        self.cache = cache
        self._responses = list(responses)
        self.calls = []

    def get_changes(self, section, since_seq=0, limit=500, timeout=4):
        self.calls.append((section, since_seq, limit))
        if not self._responses:
            return {'changes': [], 'last_seq': since_seq}
        return self._responses.pop(0)


class _ChangeLogCursor:
    """Fake cursor that executes the real change_log SQL against an in-memory
    store plus the add/update/delete/snapshot SQL used by the write paths."""

    def __init__(self):
        self.rows = []
        self.next_seq = 1
        self.next_row_id = 500
        self.fetchone_value = None
        self.fetchall_value = []
        self.description = None
        self.rowcount = 1

    def execute(self, sql, params=()):
        normalized = ' '.join(sql.lower().split())
        self.fetchone_value = None
        self.fetchall_value = []
        self.description = None
        self.rowcount = 1
        if normalized.startswith('insert into change_log'):
            section, row_id, operation, payload = params
            seq = self.next_seq
            self.next_seq += 1
            self.rows.append([seq, section, row_id, operation, payload])
            self.fetchone_value = (seq,)
        elif normalized.startswith('select seq, row_id, operation, payload from change_log'):
            section, since_seq, limit = params
            matching = [r for r in self.rows if r[1] == section and r[0] > since_seq][:limit]
            self.fetchall_value = [(r[0], r[2], r[3], r[4]) for r in matching]
            self.description = [('seq',), ('row_id',), ('operation',), ('payload',)]
        elif normalized.startswith('insert into '):
            self.fetchone_value = (self.next_row_id,)
            self.next_row_id += 1
        elif normalized.startswith('select * from '):
            self.description = [('id',), ('name',)]
            self.fetchone_value = (int(params[0]) if params else 0, 'Snap')

    def fetchone(self):
        return self.fetchone_value

    def fetchall(self):
        return self.fetchall_value


class _Conn:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _database():
    database = Database.__new__(Database)
    database.conn = _Conn()
    database.cursor = _ChangeLogCursor()
    database.registered_classes = {'Sales': SalesClass, 'Products': SalesClass}
    return database


class IncrementalSyncPermissionTests(unittest.TestCase):
    def test_get_changes_requires_section_read(self):
        allowed, _ = _check_permission(
            _user(products_read=True), 'get_changes', ['Products'], {'since_seq': 0}
        )
        self.assertTrue(allowed)
        denied, _ = _check_permission(
            _user(), 'get_changes', ['Products'], {'since_seq': 0}
        )
        self.assertFalse(denied)

    def test_superadmin_can_sync_any_section(self):
        allowed, _ = _check_permission(
            {"is_superadmin": True, "permissions": {}}, 'get_changes', ['Products'], {}
        )
        self.assertTrue(allowed)


class IncrementalSyncApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache = CacheManager(
            host='192.168.1.10', port='8765', username='alice',
            db_path=os.path.join(self.temp_dir.name, 'cache.db'),
        )
        self.addCleanup(self.cache.close)

    def _rec(self, i, name):
        return {'ID': i, 'name': name}

    def test_first_sync_applies_upserts_and_deletes(self):
        client = _FakeClient(self.cache, [
            {
                'changes': [
                    {'seq': 1, 'row_id': 1, 'operation': 'upsert', 'payload': self._rec(1, 'A')},
                    {'seq': 2, 'row_id': 2, 'operation': 'upsert', 'payload': self._rec(2, 'B')},
                    {'seq': 3, 'row_id': 3, 'operation': 'delete', 'payload': None},
                ],
                'last_seq': 3,
            },
        ])
        result = client.sync_section('Products')
        self.assertEqual(result['applied'], 3)
        self.assertEqual(result['last_seq'], 3)
        self.assertEqual(sorted(self.cache.get_records('Products').keys()), [1, 2])
        self.assertEqual(self.cache.get_sync_state('Products'), 3)
        self.assertEqual(client.calls, [('Products', 0, 500)])

    def test_second_sync_starts_from_stored_seq(self):
        client = _FakeClient(self.cache, [
            {'changes': [
                {'seq': 5, 'row_id': 2, 'operation': 'upsert', 'payload': self._rec(2, 'B2')},
            ], 'last_seq': 5},
        ])
        self.cache.set_sync_state('Products', 4)
        client.sync_section('Products')
        self.assertEqual(client.calls, [('Products', 4, 500)])
        self.assertEqual(self.cache.get_records('Products', [2])[2]['name'], 'B2')
        self.assertEqual(self.cache.get_sync_state('Products'), 5)

    def test_delete_removes_cached_row(self):
        self.cache.store_records('Products', [self._rec(7, 'X'), self._rec(8, 'Y')])
        client = _FakeClient(self.cache, [
            {'changes': [
                {'seq': 10, 'row_id': 7, 'operation': 'delete', 'payload': None},
            ], 'last_seq': 10},
        ])
        client.sync_section('Products')
        self.assertFalse(self.cache.has_record('Products', 7))
        self.assertTrue(self.cache.has_record('Products', 8))
        self.assertEqual(self.cache.get_sync_state('Products'), 10)

    def test_has_more_when_batch_full(self):
        changes = [
            {'seq': i, 'row_id': i, 'operation': 'upsert', 'payload': self._rec(i, f'R{i}')}
            for i in range(1, 3)
        ]
        client = _FakeClient(self.cache, [
            {'changes': changes, 'last_seq': 2},
        ])
        result = client.sync_section('Products', limit=2)
        self.assertTrue(result['has_more'])

    def test_no_cache_returns_none(self):
        client = _FakeClient(None, [])
        self.assertIsNone(client.sync_section('Products'))

    def test_no_changes_keeps_state(self):
        client = _FakeClient(self.cache, [
            {'changes': [], 'last_seq': 0},
        ])
        result = client.sync_section('Products')
        self.assertEqual(result['applied'], 0)
        self.assertIsNone(self.cache.get_sync_state('Products') or None)

    def test_applied_changes_invalidate_section_views(self):
        self.cache.store_view('Products', 'key1', '', [1, 2], True)
        self.cache.store_view('Clients', 'key2', '', [3], True)
        client = _FakeClient(self.cache, [
            {'changes': [
                {'seq': 1, 'row_id': 1, 'operation': 'upsert', 'payload': self._rec(1, 'A')},
            ], 'last_seq': 1},
        ])
        client.sync_section('Products')
        self.assertIsNone(self.cache.get_view('Products', 'key1', ''))
        self.assertIsNotNone(self.cache.get_view('Clients', 'key2', ''))

    def test_no_changes_keeps_views(self):
        self.cache.store_view('Products', 'key1', '', [1], True)
        client = _FakeClient(self.cache, [
            {'changes': [], 'last_seq': 0},
        ])
        client.sync_section('Products')
        self.assertIsNotNone(self.cache.get_view('Products', 'key1', ''))


class ChangeLogContractTests(unittest.TestCase):
    def setUp(self):
        self.db = _database()

    def test_record_change_appends_and_returns_seq(self):
        seq = self.db.record_change('Products', 10, 'upsert', {'ID': 10, 'name': 'A'})
        self.assertEqual(seq, 1)
        seq2 = self.db.record_change('Products', 11, 'upsert', {'ID': 11, 'name': 'B'})
        self.assertEqual(seq2, 2)

    def test_get_changes_returns_only_newer_than_since_seq(self):
        self.db.record_change('Products', 1, 'upsert', {'ID': 1})
        self.db.record_change('Products', 2, 'delete', None)
        self.db.record_change('Clients', 3, 'upsert', {'ID': 3})
        result = self.db.get_changes('Products', since_seq=0)
        self.assertEqual(result['last_seq'], 2)
        self.assertEqual([c['seq'] for c in result['changes']], [1, 2])
        self.assertEqual(result['changes'][0]['payload'], {'ID': 1})
        self.assertIsNone(result['changes'][1]['payload'])

    def test_get_changes_respects_limit_and_since(self):
        for i in range(1, 6):
            self.db.record_change('Products', i, 'upsert', {'ID': i})
        result = self.db.get_changes('Products', since_seq=2, limit=2)
        self.assertEqual([c['seq'] for c in result['changes']], [3, 4])
        self.assertEqual(result['last_seq'], 4)

    def test_get_changes_empty_section(self):
        result = self.db.get_changes('Suppliers', since_seq=7)
        self.assertEqual(result['changes'], [])
        self.assertEqual(result['last_seq'], 7)


class WritePathChangeLogTests(unittest.TestCase):
    def setUp(self):
        self.db = _database()

    def test_add_item_records_upsert_change(self):
        new_id = self.db.add_item({'client_username': 'Client', 'tva': 20}, 'Sales')
        self.assertIsNotNone(new_id)
        result = self.db.get_changes('Sales')
        self.assertEqual(result['last_seq'], 1)
        self.assertEqual(result['changes'][0]['operation'], 'upsert')
        self.assertEqual(result['changes'][0]['row_id'], new_id)
        self.assertEqual(result['changes'][0]['payload']['id'], new_id)

    def test_update_item_records_upsert_change(self):
        self.assertTrue(self.db.update_item(10, {'tva': 5}, 'Sales'))
        result = self.db.get_changes('Sales')
        self.assertEqual(result['changes'][0]['row_id'], 10)
        self.assertEqual(result['changes'][0]['operation'], 'upsert')

    def test_delete_item_records_delete_change(self):
        self.assertTrue(self.db.delete_item(7, 'Products'))
        result = self.db.get_changes('Products')
        self.assertEqual(result['changes'][0]['operation'], 'delete')
        self.assertIsNone(result['changes'][0]['payload'])


if __name__ == '__main__':
    unittest.main()
