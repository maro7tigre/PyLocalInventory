"""Phase 5 tests: BaseTab disk-first render and record-ID reconciliation.

Verifies that a network client tab renders from the on-disk SQLite cache when
the in-memory session cache misses, rehydrates the RAM layer, mirrors fetched
batches back to disk, and reconciles refresh results by record ID (in-place
patch vs full re-render) while keeping the table on screen.
"""

import os
import tempfile
import time
import unittest

from PySide6.QtWidgets import QApplication

from core.cache_manager import CacheManager
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


class _ProductEntity(_Entity):
    section = 'Products'


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


class BaseTabDiskCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = os.path.join(self.temp_dir.name, 'cache.db')
        self.cache = CacheManager(
            host='192.168.1.10', port='8765', username='alice',
            db_path=self.db_path,
        )
        self.addCleanup(self.cache.close)

    def make_tab(self, entity_class=_Entity, cache=None):
        database = RemoteDatabase(cache=cache if cache is not None else self.cache)
        tab = BaseTab(entity_class, None, database)
        tab.page_size = 2
        tab._refresh_id = 1
        tab._needs_refresh = False
        return tab

    def seed_disk(self, records, section='Widgets', view_key=None,
                  has_more=False, after_id=None, after_sort=None):
        if view_key is None:
            view_key = repr(('', 'Default'))
        self.cache.store_records(section, records)
        self.cache.store_view(
            section, view_key, '',
            [int(r['ID']) for r in records],
            has_more=has_more, after_id=after_id, after_sort=after_sort,
        )

    def test_refresh_table_renders_from_disk_on_ram_miss(self):
        self.seed_disk([_row(1, 'A'), _row(2, 'B')])
        tab = self.make_tab()
        tab.refresh_table()
        self.assertEqual(len(tab.all_items), 2)
        self.assertEqual(tab.table.rowCount(), 2)
        self.assertEqual([o.id for o in tab.all_items], [1, 2])

    def test_disk_render_rehydrates_ram_cache(self):
        self.seed_disk([_row(1, 'A'), _row(2, 'B')])
        tab = self.make_tab()
        tab.refresh_table()
        entry = tab._cache.get(('', 'Default'))
        self.assertIsNotNone(entry)
        self.assertEqual([r['ID'] for r in entry.records], [1, 2])

    def test_apply_refresh_results_persists_to_disk(self):
        tab = self.make_tab()
        tab._apply_refresh_results(
            [_row(1, 'A'), _row(2, 'B'), _row(3, 'C')],
            levels=None,
            metrics={'after_id': 2, 'after_sort': 'B'},
            started=0.0,
            refresh_id=1,
        )
        self.assertEqual(self.cache.count_records('Widgets'), 2)
        view = self.cache.get_view('Widgets', repr(('', 'Default')), '')
        self.assertIsNotNone(view)
        self.assertEqual(view[0], [1, 2])
        self.assertTrue(view[1])

    def test_second_launch_renders_from_persisted_disk(self):
        tab = self.make_tab()
        tab._apply_refresh_results(
            [_row(1, 'A'), _row(2, 'B')],
            levels=None,
            metrics={'after_id': 2, 'after_sort': 'B'},
            started=0.0,
            refresh_id=1,
        )
        # A fresh tab (new RAM session) over the same persisted disk cache must
        # render without any network/database call.
        tab2 = self.make_tab()
        tab2.refresh_table()
        self.assertEqual([o.id for o in tab2.all_items], [1, 2])

    def test_reconcile_patches_in_place_when_set_unchanged(self):
        tab = self.make_tab()
        tab._apply_refresh_results(
            [_row(1, 'A'), _row(2, 'B')],
            levels=None, metrics={'after_id': 2, 'after_sort': 'B'},
            started=0.0, refresh_id=1,
        )
        renders = []
        original = tab.populate_table_with_items
        tab.populate_table_with_items = lambda *a, **k: (renders.append(1), original(*a, **k))
        tab.table.setCurrentCell(0, 0)
        tab._refresh_id = 2
        tab._apply_refresh_results(
            [_row(1, 'A-updated'), _row(2, 'B')],
            levels=None, metrics={'after_id': 2, 'after_sort': 'B'},
            started=0.0, refresh_id=2,
        )
        self.assertEqual(renders, [])  # no full re-render: patched in place
        self.assertEqual(tab.table.rowCount(), 2)
        self.assertEqual(tab.table.currentRow(), 0)  # selection survived
        self.assertEqual(tab.all_items[0].name, 'A-updated')  # cells updated

    def test_reconcile_full_rerender_when_record_deleted(self):
        tab = self.make_tab()
        tab._apply_refresh_results(
            [_row(1, 'A'), _row(2, 'B')],
            levels=None, metrics={'after_id': 2, 'after_sort': 'B'},
            started=0.0, refresh_id=1,
        )
        tab._refresh_id = 2
        tab._apply_refresh_results(
            [_row(2, 'B'), _row(3, 'C')],
            levels=None, metrics={'after_id': 3, 'after_sort': 'C'},
            started=0.0, refresh_id=2,
        )
        self.assertEqual([o.id for o in tab.all_items], [2, 3])
        self.assertEqual(tab.table.rowCount(), 2)

    def test_product_stock_roundtrips_through_disk(self):
        tab = self.make_tab(entity_class=_ProductEntity)
        tab._apply_refresh_results(
            [_row(1, 'A')],
            levels={1: 12, 2: 0.5},
            metrics={'after_id': 1, 'after_sort': 'A'},
            started=0.0,
            refresh_id=1,
        )
        self.assertEqual(self.cache.get_stock(), {1: 12.0, 2: 0.5})
        tab2 = self.make_tab(entity_class=_ProductEntity)
        tab2.refresh_table()
        self.assertEqual(tab2.database._product_stock_levels, {1: 12.0, 2: 0.5})

    def test_offline_banner_shown_on_failure_hidden_on_success(self):
        tab = self.make_tab()
        self.assertTrue(tab._offline_banner.isHidden())
        tab._remote_refresh_failed('host unreachable', 0.0)
        self.assertFalse(tab._offline_banner.isHidden())
        tab._refresh_id = 2
        tab._apply_refresh_results(
            [_row(1, 'A')],
            levels=None, metrics={}, started=0.0, refresh_id=2,
        )
        self.assertTrue(tab._offline_banner.isHidden())

    def test_offline_renders_from_disk_without_network(self):
        self.seed_disk([_row(1, 'A'), _row(2, 'B')])
        tab = self.make_tab()
        tab.database.offline = True
        refreshes = []
        tab._start_full_refresh = lambda preserve_table=False: refreshes.append(1)
        tab.refresh_table()
        self.assertEqual([o.id for o in tab.all_items], [1, 2])
        self.assertEqual(refreshes, [])
        self.assertFalse(tab._offline_banner.isHidden())
        self.assertFalse(tab._refreshing)

    def test_offline_stale_disk_does_not_trigger_network(self):
        self.seed_disk([_row(1, 'A')])
        with self.cache._lock:
            self.cache._conn.execute(
                "UPDATE views SET stored_at=? WHERE identity=?",
                (time.time() - 3600, self.cache.identity),
            )
            self.cache._conn.commit()
        tab = self.make_tab()
        tab.database.offline = True
        refreshes = []
        tab._start_full_refresh = lambda preserve_table=False: refreshes.append(1)
        tab.refresh_table()
        self.assertEqual([o.id for o in tab.all_items], [1])
        self.assertEqual(refreshes, [])
        self.assertFalse(tab._offline_banner.isHidden())
        self.assertFalse(tab._refreshing)

    def test_offline_empty_cache_shows_banner_only(self):
        tab = self.make_tab()
        tab.database.offline = True
        refreshes = []
        tab._start_full_refresh = lambda preserve_table=False: refreshes.append(1)
        tab.refresh_table()
        self.assertEqual(tab.all_items, [])
        self.assertEqual(refreshes, [])
        self.assertFalse(tab._offline_banner.isHidden())
        self.assertFalse(tab._refreshing)

    def test_online_stale_disk_still_refreshes(self):
        self.seed_disk([_row(1, 'A')])
        with self.cache._lock:
            self.cache._conn.execute(
                "UPDATE views SET stored_at=? WHERE identity=?",
                (time.time() - 3600, self.cache.identity),
            )
            self.cache._conn.commit()
        tab = self.make_tab()
        tab.database.offline = False
        refreshes = []
        tab._start_full_refresh = lambda preserve_table=False: refreshes.append(1)
        tab.refresh_table()
        self.assertEqual([o.id for o in tab.all_items], [1])
        self.assertEqual(refreshes, [1])
        self.assertTrue(tab._offline_banner.isHidden())


if __name__ == '__main__':
    unittest.main()
