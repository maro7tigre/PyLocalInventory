"""Session-cache integration tests for BaseTab.

Verifies that a completed batch is stored in the session cache, that a fresh
refresh serves from the cache without any database/network request, that
force=True bypasses the cache, and that mutations invalidate it.
"""

import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from ui.tabs.base_tab import BaseTab


class _FakeEntity:
    section = 'Widgets'

    def __init__(self, oid, database):
        self.id = oid
        self.parameters = {}

    def get_visible_parameters(self, kind):
        return []

    @property
    def available_parameters(self):
        return {'table': {}}


class _FakeDatabase:
    _product_stock_levels = {}

    def __init__(self):
        self.profile_manager = None
        self.conn = None
        self.language = 'en'

    def has_permission(self, section, action='read'):
        return True


def _row(row_id, name):
    return {'ID': row_id, 'name': name}


class BaseTabCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tab = BaseTab(_FakeEntity, None, _FakeDatabase())
        self.tab.page_size = 2
        self.tab._refresh_id = 1

    def _seed(self):
        self.tab._apply_refresh_results(
            [_row(1, 'A'), _row(2, 'B'), _row(3, 'C')],
            levels=None,
            metrics={'after_id': 2, 'after_sort': 'B'},
            started=0.0,
            refresh_id=1,
        )

    def test_cache_hit_renders_without_network(self):
        self._seed()
        with patch.object(self.tab, '_start_local_refresh') as start:
            self.tab.refresh_table()
        self.assertEqual(len(self.tab.all_items), 2)
        self.assertTrue(self.tab._has_more_rows)
        self.assertEqual(self.tab._after_id, 2)
        self.assertEqual(self.tab._after_sort, 'B')
        self.assertIsNone(self.tab._refresh_thread)
        start.assert_not_called()

    def test_force_bypasses_cache(self):
        self._seed()
        with patch.object(self.tab, '_start_local_refresh') as start:
            self.tab.refresh_table(force=True)
        start.assert_called_once()

    def test_different_search_misses_cache(self):
        self._seed()
        self.tab.search_bar.setText('B')
        with patch.object(self.tab, '_start_local_refresh') as start:
            self.tab.refresh_table()
        start.assert_called_once()

    def test_mark_dirty_clears_cache(self):
        self._seed()
        self.assertEqual(len(self.tab._cache), 1)
        self.tab.mark_dirty()
        self.assertEqual(len(self.tab._cache), 0)
        with patch.object(self.tab, '_start_local_refresh') as start:
            self.tab.refresh_table()
        start.assert_called_once()

    def test_append_batch_extends_cache_entry(self):
        self._seed()
        entry = self.tab._cache.get(('', 'Default'))
        self.assertIsNotNone(entry)
        self.assertEqual(len(entry.records), 2)
        self.assertTrue(entry.has_more)
        self.assertEqual(entry.after_id, 2)

        self.tab._appending = True
        self.tab._refresh_id = 2
        self.tab._apply_refresh_results(
            [_row(3, 'C')],
            levels=None,
            metrics={'after_id': 3, 'after_sort': 'C'},
            started=0.0,
            refresh_id=2,
        )
        entry = self.tab._cache.get(('', 'Default'))
        self.assertEqual(len(entry.records), 3)
        self.assertFalse(entry.has_more)
        self.assertEqual(entry.after_id, 3)

    def test_cache_restores_stock_levels(self):
        self.tab._apply_refresh_results(
            [_row(1, 'A')],
            levels={1: 5},
            metrics={'after_id': 1, 'after_sort': 'A'},
            started=0.0,
            refresh_id=1,
        )
        self.tab.database._product_stock_levels = {}
        with patch.object(self.tab, '_start_local_refresh') as start:
            self.tab.refresh_table()
        start.assert_not_called()
        self.assertEqual(self.tab.database._product_stock_levels, {1: 5})

    def test_stale_batch_does_not_clobber_cache(self):
        self._seed()
        self.tab._refresh_id = 5
        self.tab._apply_refresh_results(
            [_row(9, 'Stale')],
            levels=None,
            metrics={'after_id': 9, 'after_sort': 'Stale'},
            started=0.0,
            refresh_id=4,
        )
        entry = self.tab._cache.get(('', 'Default'))
        self.assertEqual(len(entry.records), 2)
        self.assertEqual(entry.after_id, 2)


if __name__ == '__main__':
    unittest.main()
