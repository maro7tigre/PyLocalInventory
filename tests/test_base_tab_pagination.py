"""Infinite-scroll behaviour tests for BaseTab.

Constructs a real BaseTab against a lightweight fake database/entity so the
incremental-append contract (_apply_refresh_results replacing vs extending rows,
advancing the keyset cursor, tracking _has_more_rows) is verified without a
live database connection.
"""

import unittest

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


class BaseTabPaginationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tab = BaseTab(_FakeEntity, None, _FakeDatabase())
        self.tab.page_size = 2
        self.tab._refresh_id = 1

    def test_first_batch_replaces_and_sets_cursor(self):
        self.tab._apply_refresh_results(
            [_row(1, 'A'), _row(2, 'B'), _row(3, 'C')],
            levels=None,
            metrics={'after_id': 2, 'after_sort': 'B'},
            started=0.0,
            refresh_id=1,
        )
        self.assertEqual(len(self.tab.all_items), 2)
        self.assertEqual(self.tab.current_page, 0)
        self.assertTrue(self.tab._has_more_rows)
        self.assertEqual(self.tab._after_id, 2)
        self.assertEqual(self.tab._after_sort, 'B')
        self.assertEqual(self.tab.table.rowCount(), 2)

    def test_append_extends_rows_and_advances_cursor(self):
        self.tab._apply_refresh_results(
            [_row(1, 'A'), _row(2, 'B')],
            levels=None,
            metrics={'after_id': 2, 'after_sort': 'B'},
            started=0.0,
            refresh_id=1,
        )
        self.tab._appending = True
        self.tab._refresh_id = 2
        self.tab._apply_refresh_results(
            [_row(3, 'C')],
            levels=None,
            metrics={'after_id': 3, 'after_sort': 'C'},
            started=0.0,
            refresh_id=2,
        )
        self.assertEqual(len(self.tab.all_items), 3)
        self.assertEqual(self.tab.current_page, 1)
        self.assertFalse(self.tab._has_more_rows)
        self.assertEqual(self.tab._after_id, 3)
        self.assertEqual(self.tab.table.rowCount(), 3)

    def test_stale_result_is_discarded(self):
        self.tab._refresh_id = 5
        self.tab._apply_refresh_results(
            [_row(1, 'A')],
            levels=None,
            metrics={'after_id': 1, 'after_sort': 'A'},
            started=0.0,
            refresh_id=5,
        )
        # A newer refresh has started, so this older batch must not apply.
        self.tab._refresh_id = 7
        self.tab._appending = True
        self.tab._apply_refresh_results(
            [_row(2, 'B')],
            levels=None,
            metrics={'after_id': 2, 'after_sort': 'B'},
            started=0.0,
            refresh_id=6,
        )
        self.assertEqual(len(self.tab.all_items), 1)
        self.assertEqual(self.tab._after_id, 1)
        self.assertEqual(self.tab.table.rowCount(), 1)

    def test_load_more_requires_cursor_and_room(self):
        self.assertFalse(self.tab.load_more_rows())  # no cursor yet
        self.tab._after_id = 2
        self.tab._after_sort = 'B'
        self.tab._has_more_rows = False
        self.assertFalse(self.tab.load_more_rows())  # nothing more to load
        self.tab._has_more_rows = True
        self.tab._refreshing = True
        self.assertFalse(self.tab.load_more_rows())  # a fetch is already running


if __name__ == '__main__':
    unittest.main()
