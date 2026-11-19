"""Regression tests for the Clients tab refresh / duplicate-request fixes.

Covers the two reported bugs:

1. On a remote Client PC the Clients tab arrived empty because
   ``ClientsTab.refresh_on_tab_switch`` was gated on
   ``hasattr(self.database, 'conn')``, which is only true on the host's local
   Database. Tests assert the remote scenario now refreshes automatically.

2. Startup preload plus every tab switch forced a second network request
   (duplicate ``load_clients batch=1 completed``). Tests assert one request
   per activation, a single in-flight request at a time, generation-id
   invalidation of superseded fetches, and a pending re-issue after the
   in-flight request unwinds.
"""

import os
import unittest
from time import monotonic
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from ui.tabs.base_tab import BaseTab
from ui.tabs.clients_tab import ClientsTab


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
    """Local-like fake. Notably: has NO ``conn`` attribute, mirroring the
    RemoteDatabase network client (the original gate blocked it)."""
    _product_stock_levels = {}

    def __init__(self):
        self.profile_manager = None
        self.language = 'en'

    def has_permission(self, section, action='read'):
        return True


class BaseTabRequestCoalescingTests(unittest.TestCase):
    """In-flight deduplication, generation ids and pending re-issue."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tab = BaseTab(_FakeEntity, None, _FakeDatabase())
        self.tab._refreshing = True
        self.tab._refresh_pending = False
        self.tab._in_flight_key = ('', 'Default')
        self.tab._refresh_id = 5

    def test_identical_in_flight_request_is_dropped(self):
        """Same (non-forced) view while in flight: no new request, no pending."""
        with patch.object(self.tab, '_start_full_refresh') as start:
            self.tab.refresh_table()
        start.assert_not_called()
        self.assertFalse(self.tab._refresh_pending)
        self.assertEqual(self.tab._refresh_id, 5)

    def test_force_during_in_flight_supersedes_and_queues(self):
        """A forced refresh while a fetch is running bumps the generation id,
        invalidates the in-flight result, and queues a re-issue."""
        with patch.object(self.tab, '_start_full_refresh') as start:
            self.tab.refresh_table(force=True)
        start.assert_not_called()
        self.assertTrue(self.tab._refresh_pending)
        self.assertEqual(self.tab._refresh_id, 6)

    def test_different_search_during_in_flight_supersedes(self):
        """A different search key while in flight also supersedes the request."""
        self.tab.search_bar.setText('other')
        with patch.object(self.tab, '_start_full_refresh') as start:
            self.tab.refresh_table()
        start.assert_not_called()
        self.assertTrue(self.tab._refresh_pending)
        self.assertEqual(self.tab._refresh_id, 6)

    def test_stale_result_is_rejected(self):
        """A result whose generation id is no longer current never renders."""
        self.tab._refresh_id = 6
        self.tab._apply_refresh_results(
            [{'ID': 9, 'name': 'Stale'}],
            levels=None,
            metrics={},
            started=0.0,
            refresh_id=5,
        )
        self.assertEqual(self.tab.all_items, [])

    def test_fresh_result_is_accepted(self):
        """A result matching the current generation id renders."""
        self.tab._refreshing = False
        self.tab._apply_refresh_results(
            [{'ID': 1, 'name': 'A'}],
            levels=None,
            metrics={},
            started=0.0,
            refresh_id=5,
        )
        self.assertEqual(len(self.tab.all_items), 1)

    def test_pending_request_reissues_after_finish(self):
        """After the in-flight fetch unwinds, the queued newer request runs."""
        self.tab._refresh_pending = True
        self.tab._refreshing = True
        with patch.object(self.tab, 'refresh_table') as refresh:
            self.tab._finish_refresh(0.0, mode='client')
            QTest.qWait(30)
        self.assertFalse(self.tab._refresh_pending)
        self.assertFalse(self.tab._refreshing)
        self.assertEqual(refresh.call_count, 1)
        self.assertEqual(refresh.call_args.kwargs.get('force'), True)

    def test_failure_resets_in_flight_state(self):
        """A failed fetch clears the in-flight state and the pending flag."""
        self.tab._refresh_pending = True
        self.tab._refreshing = True
        with patch.object(self.tab, 'refresh_table') as refresh:
            self.tab._remote_refresh_failed('boom', 0.0)
            QTest.qWait(30)
        self.assertFalse(self.tab._refreshing)
        self.assertEqual(refresh.call_count, 1)
        self.assertEqual(refresh.call_args.kwargs.get('force'), True)


class ForceRefreshPreservationTests(unittest.TestCase):
    """A refresh must never blank the table before the fresh rows arrive."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tab = BaseTab(_FakeEntity, None, _FakeDatabase())
        self.tab._refreshing = False
        self.tab._refresh_id = 1
        self.tab._apply_refresh_results(
            [{'ID': 1, 'name': 'A'}, {'ID': 2, 'name': 'B'}],
            levels=None,
            metrics={},
            started=0.0,
            refresh_id=1,
        )
        self.assertEqual(self.tab.table.rowCount(), 2)

    def test_start_full_refresh_does_not_clear_table(self):
        """Starting a background refresh keeps the current rows on screen."""
        with patch.object(self.tab, '_start_local_refresh') as start:
            self.tab._start_full_refresh()
        start.assert_called_once()
        self.assertEqual(self.tab.table.rowCount(), 2)
        self.tab._refreshing = False

    def test_force_refresh_keeps_rows_until_replacement(self):
        """A manual force refresh re-renders the same rows, never blanks them."""
        with patch.object(self.tab, '_start_local_refresh') as start:
            self.tab.refresh_table(force=True)
        start.assert_called_once()
        self.assertEqual(self.tab.table.rowCount(), 2)
        self.tab._refreshing = False

    def test_reconcile_falls_back_when_table_has_no_rows(self):
        """If the table was cleared, rows are fully re-rendered, not patched."""
        obj = self.tab.all_items[0]
        self.tab.table.setRowCount(0)
        self.assertFalse(self.tab._reconcile_in_place(self.tab.all_items, [obj]))

    def test_failed_fetch_keeps_displayed_rows(self):
        """A failed fetch keeps the current records visible."""
        self.tab._refreshing = True
        with patch.object(self.tab, 'refresh_table'):
            self.tab._remote_refresh_failed('host unreachable', 0.0)
        self.assertFalse(self.tab._refreshing)
        self.assertEqual(self.tab.table.rowCount(), 2)


class RefreshButtonTests(unittest.TestCase):
    """The manual Refresh button always forces and is connected exactly once."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tab = BaseTab(_FakeEntity, None, _FakeDatabase())

    def test_refresh_button_forces(self):
        with patch.object(self.tab, 'refresh_table') as refresh:
            self.tab.refresh_btn.clicked.emit()
        refresh.assert_called_once_with(force=True)

    def test_no_duplicate_signal_connections(self):
        """One click produces exactly one refresh call."""
        with patch.object(self.tab, 'refresh_table') as refresh:
            self.tab.refresh_btn.clicked.emit()
        refresh.assert_called_once_with(force=True)


class ClientsTabRefreshTests(unittest.TestCase):
    """The remote-Client empty-tab bug and preload/switch deduplication."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tab = ClientsTab(database=_FakeDatabase())
        self.tab._refreshing = False
        self.tab._last_refresh_at = 0.0

    def test_remote_client_without_conn_still_refreshes(self):
        """A database with no ``conn`` attribute (network client) is no longer
        skipped - the empty-tab root cause."""
        with patch.object(self.tab, 'refresh_table') as refresh:
            self.tab.refresh_on_tab_switch()
        refresh.assert_called_once_with(force=True)

    def test_switch_while_preload_in_flight_does_not_duplicate(self):
        """While a fetch (e.g. startup preload) is running, the switch does not
        fire a second request."""
        self.tab._refreshing = True
        with patch.object(self.tab, 'refresh_table') as refresh:
            self.tab.refresh_on_tab_switch()
        refresh.assert_not_called()

    def test_switch_right_after_preload_does_not_duplicate(self):
        """A switch landing within 2s of a completed fetch skips the duplicate."""
        self.tab._last_refresh_at = monotonic()
        with patch.object(self.tab, 'refresh_table') as refresh:
            self.tab.refresh_on_tab_switch()
        refresh.assert_not_called()

    def test_switch_after_grace_period_refreshes(self):
        """A switch more than 2s after the last fetch forces a fresh load."""
        self.tab._last_refresh_at = monotonic() - 5.0
        with patch.object(self.tab, 'refresh_table') as refresh:
            self.tab.refresh_on_tab_switch()
        refresh.assert_called_once_with(force=True)

    def test_manual_refresh_button_still_forces(self):
        """The user's manual Refresh always reaches the source."""
        with patch.object(self.tab, 'refresh_table') as refresh:
            self.tab.refresh_btn.clicked.emit()
        refresh.assert_called_once_with(force=True)


if __name__ == '__main__':
    unittest.main()
