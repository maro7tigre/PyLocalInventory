"""Phase 14 tests: filter-aware Reports caching.

Verifies that report views are cached per filter combination (owner/date-range/
type), that the cached views stay owner-safe, that local report mutations
invalidate the on-disk views so a stale snapshot is never served, and that the
reports write path records incremental change-log entries.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication

from core.cache_manager import CacheManager
from core.database import Database
from ui.tabs.base_tab import BaseTab


class _Entity:
    section = 'Widgets'

    def __init__(self, oid, database):
        self.id = oid
        self.name = ''
        self.parameters = {'name': {'type': 'string'}}

    def get_visible_parameters(self, kind):
        return ['name'] if kind == 'table' else []

    @property
    def available_parameters(self):
        return {'table': {'name': 'rw'}}

    def get_display_name(self, key):
        return key

    def get_value(self, key):
        return self.name if key == 'name' else None

    def set_raw_value(self, key, value):
        if key == 'name':
            self.name = value


class _ReportEntity(_Entity):
    section = 'Reports'


class _ReportsTab(BaseTab):
    """BaseTab whose cache key mimics ReportsTab's filter-aware key tuple."""

    def __init__(self, database, owner_id=None, report_type=None,
                 date_from=None, date_to=None):
        self._owner_id = owner_id
        self._report_type = report_type
        self._date_from = date_from
        self._date_to = date_to
        super().__init__(_ReportEntity, None, database)

    def _cache_key(self):
        return (
            '', 'Default', self._owner_id,
            self._date_from, self._date_to, self._report_type,
        )


class RemoteDatabase:
    """Fake database whose class name matches the network client so
    BaseTab._disk_cache() treats it as a remote client."""

    def __init__(self, cache=None):
        self.cache = cache
        self.conn = object()
        self._product_stock_levels = {}

    def has_permission(self, section, action='read'):
        return True


def _row(row_id, name):
    return {'ID': row_id, 'name': name}


class _ChangeLogCursor:
    """Fake cursor executing the real change_log and reports SQL against an
    in-memory store."""

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


class ReportsCacheViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # These tests exercise the experimental on-disk cache, which is off by
        # default - enable it just for this module.
        self._cache_flag = mock.patch('ui.tabs.base_tab.ENABLE_SQLITE_CACHE', True)
        self._cache_flag.start()
        self.addCleanup(self._cache_flag.stop)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = os.path.join(self.temp_dir.name, 'cache.db')
        self.cache = CacheManager(
            host='192.168.1.10', port='8765', username='alice',
            db_path=self.db_path,
        )
        self.addCleanup(self.cache.close)

    def make_tab(self, cache=None, owner_id=None, report_type=None):
        database = RemoteDatabase(cache=cache if cache is not None else self.cache)
        tab = _ReportsTab(database, owner_id=owner_id, report_type=report_type)
        tab.page_size = 2
        tab._refresh_id = 1
        tab._needs_refresh = False
        return tab

    def seed_disk(self, records, view_key, has_more=False,
                  after_id=None, after_sort=None):
        self.cache.store_records('Reports', records)
        self.cache.store_view(
            'Reports', view_key, '',
            [int(r['ID']) for r in records],
            has_more=has_more, after_id=after_id, after_sort=after_sort,
        )

    def test_filter_aware_views_serve_distinct_rows(self):
        key_a = repr(('', 'Default', 1, None, None, 'Sales'))
        key_b = repr(('', 'Default', 2, None, None, 'General'))
        self.seed_disk([_row(1, 'Sales report')], view_key=key_a)
        self.seed_disk([_row(2, 'General report')], view_key=key_b)

        tab_a = self.make_tab(owner_id=1, report_type='Sales')
        tab_a.refresh_table()
        self.assertEqual([o.id for o in tab_a.all_items], [1])

        tab_b = self.make_tab(owner_id=2, report_type='General')
        tab_b.refresh_table()
        self.assertEqual([o.id for o in tab_b.all_items], [2])

    def test_filter_view_not_served_across_filter_change(self):
        self.seed_disk([_row(1, 'Sales report')], view_key=repr(('', 'Default', 1, None, None, 'Sales')))
        tab = self.make_tab(owner_id=1, report_type='Sales')
        tab.refresh_table()
        self.assertEqual([o.id for o in tab.all_items], [1])
        # A different filter combination must not reuse that owner's view.
        tab_other = self.make_tab(owner_id=2, report_type='Sales')
        refreshes = []
        tab_other._start_full_refresh = lambda preserve_table=False: refreshes.append(1)
        tab_other.refresh_table()
        self.assertEqual(refreshes, [1])
        self.assertEqual(tab_other.all_items, [])

    def test_fetched_batch_persists_reports_view_to_disk(self):
        tab = self.make_tab(owner_id=1, report_type='Sales')
        tab._apply_refresh_results(
            [_row(1, 'A'), _row(2, 'B')],
            levels=None,
            metrics={'after_id': 2, 'after_sort': 'B'},
            started=0.0,
            refresh_id=1,
        )
        view = self.cache.get_view('Reports', repr(tab._cache_key()), '')
        self.assertIsNotNone(view)
        self.assertEqual(view[0], [1, 2])
        self.assertEqual(self.cache.count_records('Reports'), 2)

    def test_mutation_invalidates_disk_view(self):
        tab = self.make_tab(owner_id=1, report_type='Sales')
        tab._apply_refresh_results(
            [_row(1, 'A'), _row(2, 'B')],
            levels=None, metrics={}, started=0.0, refresh_id=1,
        )
        self.assertIsNotNone(self.cache.get_view('Reports', repr(tab._cache_key()), ''))

        refreshes = []
        tab._start_full_refresh = lambda preserve_table=False: refreshes.append(1)
        tab._cache.clear()
        tab._invalidate_disk_views()
        tab.refresh_table()

        self.assertIsNone(self.cache.get_view('Reports', repr(tab._cache_key()), ''))
        self.assertEqual(refreshes, [1])
        # No stale snapshot was rehydrated into the RAM session cache.
        self.assertIsNone(tab._cache.get(tab._cache_key()))

    def test_control_stale_disk_served_without_invalidation(self):
        self.seed_disk([_row(1, 'A'), _row(2, 'B')], view_key=repr(('', 'Default', 1, None, None, 'Sales')))
        tab = self.make_tab(owner_id=1, report_type='Sales')
        refreshes = []
        tab._start_full_refresh = lambda preserve_table=False: refreshes.append(1)
        tab.refresh_table()
        self.assertEqual([o.id for o in tab.all_items], [1, 2])
        self.assertEqual(refreshes, [])

    def test_offline_serves_filter_aware_reports_view(self):
        key = repr(('', 'Default', 1, None, None, 'Sales'))
        self.seed_disk([_row(1, 'A')], view_key=key)
        tab = self.make_tab(owner_id=1, report_type='Sales')
        tab.database.offline = True
        refreshes = []
        tab._start_full_refresh = lambda preserve_table=False: refreshes.append(1)
        tab.refresh_table()
        self.assertEqual([o.id for o in tab.all_items], [1])
        self.assertEqual(refreshes, [])
        self.assertFalse(tab._offline_banner.isHidden())


class ReportsChangeLogTests(unittest.TestCase):
    def _database(self):
        database = Database.__new__(Database)
        database.conn = _Conn()
        database.cursor = _ChangeLogCursor()
        database.registered_classes = {}
        return database

    def test_save_new_report_records_upsert_change(self):
        database = self._database()
        saved_id = database.save_report_for_user(
            None,
            {'date': '05-08-2026', 'report_type': 'Sales', 'report': 'Strong month'},
            {"is_superadmin": True, "id": 7, "username": "alice"},
        )
        self.assertTrue(saved_id > 0)
        seq, section, row_id, operation, payload = database.cursor.rows[-1]
        self.assertEqual(section, 'Reports')
        self.assertEqual(row_id, saved_id)
        self.assertEqual(operation, 'upsert')
        snapshot = json.loads(payload)
        self.assertEqual(snapshot['id'], saved_id)

    def test_update_report_records_upsert_change(self):
        database = self._database()
        database.save_report_for_user(
            10,
            {'date': '05-08-2026', 'report_type': 'General', 'report': 'Updated'},
            {"is_superadmin": True, "id": 7, "username": "alice"},
        )
        seq, section, row_id, operation, payload = database.cursor.rows[-1]
        self.assertEqual((section, row_id, operation), ('Reports', 10, 'upsert'))
        self.assertIsNotNone(payload)

    def test_delete_report_records_delete_change(self):
        database = self._database()
        database.delete_report_for_user(10, {"is_superadmin": True, "id": 7})
        seq, section, row_id, operation, payload = database.cursor.rows[-1]
        self.assertEqual((section, row_id, operation, payload), ('Reports', 10, 'delete', None))

    def test_get_changes_round_trips_report_upsert(self):
        database = self._database()
        saved_id = database.save_report_for_user(
            None,
            {'date': '05-08-2026', 'report_type': 'Sales', 'report': 'Strong month'},
            {"is_superadmin": True, "id": 7, "username": "alice"},
        )
        result = database.get_changes('Reports', since_seq=0, limit=50)
        self.assertEqual(len(result['changes']), 1)
        change = result['changes'][0]
        self.assertEqual(change['row_id'], saved_id)
        self.assertEqual(change['operation'], 'upsert')
        self.assertEqual(change['payload']['id'], saved_id)


if __name__ == '__main__':
    unittest.main()
