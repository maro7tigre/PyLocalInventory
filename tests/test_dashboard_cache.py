"""Phase 13 tests: Home dashboard snapshot caching for LAN clients.

The dashboard is a derived aggregation computed by the host. A network client
persists each successful snapshot to its SQLite cache so the Home tab can
render instantly without a round-trip, and keep rendering offline from the
last-known snapshot instead of hanging on the host.
"""

import os
import tempfile
import time
import unittest
from unittest import mock

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QLabel

from core.cache_manager import CacheManager
from ui.tabs.home_tab import HomeTab

_SNAPSHOT = {
    "sales_total": "1200.5",
    "imports_total": "300",
    "products_count": 42,
    "clients_count": 9,
    "suppliers_count": 3,
    "low_stock_count": 2,
    "low_stock_products": [
        {"name": "Porte", "username": "", "stock": "1", "alert": "5"},
    ],
    "recent_activities": [
        {"type": "Sales", "date": "2026-08-05", "amount": "1200.5",
         "description": "Sale to Alice"},
    ],
    "monthly": {
        "2026-08": {"sales": "1200.5", "imports": "300"},
    },
}


class RemoteDatabase:
    """Fake database whose class name matches the network client."""

    def __init__(self, cache=None, offline=False):
        self.cache = cache
        self.offline = offline
        self.conn = object()


class DashboardCacheStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache = CacheManager(
            host='192.168.1.10', port='8765', username='alice',
            db_path=os.path.join(self.temp_dir.name, 'cache.db'),
        )
        self.addCleanup(self.cache.close)

    def test_roundtrip_persists_snapshot(self):
        self.assertTrue(self.cache.store_dashboard(_SNAPSHOT))
        snapshot, stored_at = self.cache.get_dashboard()
        self.assertEqual(snapshot['products_count'], 42)
        self.assertEqual(snapshot['monthly']['2026-08']['sales'], '1200.5')
        self.assertGreater(stored_at, 0)

    def test_store_overwrites_latest_snapshot(self):
        self.cache.store_dashboard(_SNAPSHOT)
        self.cache.store_dashboard({**_SNAPSHOT, "products_count": 99})
        snapshot, _ = self.cache.get_dashboard()
        self.assertEqual(snapshot['products_count'], 99)

    def test_identity_isolation(self):
        other = CacheManager(
            host='192.168.1.10', port='8765', username='bob',
            db_path=os.path.join(self.temp_dir.name, 'cache.db'),
        )
        self.addCleanup(other.close)
        self.cache.store_dashboard(_SNAPSHOT)
        snapshot, _ = other.get_dashboard()
        self.assertIsNone(snapshot)

    def test_clear_identity_removes_dashboard(self):
        self.cache.store_dashboard(_SNAPSHOT)
        self.cache.clear_identity()
        snapshot, _ = self.cache.get_dashboard()
        self.assertIsNone(snapshot)


class HomeTabDashboardCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # These tests exercise the experimental on-disk cache, which is off by
        # default - enable it just for this module.
        self._cache_flag = mock.patch('ui.tabs.home_tab.ENABLE_SQLITE_CACHE', True)
        self._cache_flag.start()
        self.addCleanup(self._cache_flag.stop)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache = CacheManager(
            host='192.168.1.10', port='8765', username='alice',
            db_path=os.path.join(self.temp_dir.name, 'cache.db'),
        )
        self.addCleanup(self.cache.close)

    def tearDown(self):
        app = QApplication.instance()
        # Deliver queued worker signals (finished -> thread.quit/deleteLater)
        # so no QThread is left running or pending deletion for later modules.
        for child in getattr(self, '_tabs', []):
            child.refresh_timer.stop()
            child._wait_for_dashboard_thread()
            child.deleteLater()
        if app is not None:
            app.processEvents()
            app.processEvents()

    def make_home(self, offline=False, seeded=True):
        if seeded:
            self.cache.store_dashboard(_SNAPSHOT)
        database = RemoteDatabase(cache=self.cache, offline=offline)
        tab = HomeTab(database=database, language='en')
        self._tabs = getattr(self, '_tabs', []) + [tab]
        return tab

    @staticmethod
    def _find_text(widget, text):
        if widget is None:
            return False
        if isinstance(widget, QLabel) and widget.text() == text:
            return True
        layout = getattr(widget, 'layout', lambda: None)()
        if layout is not None:
            for i in range(layout.count()):
                if HomeTabDashboardCacheTests._find_text(
                    layout.itemAt(i).widget(), text
                ):
                    return True
        return False

    def _has_label(self, tab, text):
        layout = tab.low_stock_products_layout
        return any(
            self._find_text(layout.itemAt(i).widget(), text)
            for i in range(layout.count())
        )

    def test_offline_renders_cached_snapshot_without_thread(self):
        tab = self.make_home(offline=True)
        self.assertIsNone(tab._dashboard_thread)
        self.assertEqual(tab._dashboard_snapshot['products_count'], 42)
        self.assertTrue(self._has_label(tab, 'Porte'))
        self.assertEqual(tab._monthly_sales_set.at(5), 1200.5)

    def test_offline_without_cache_stays_idle(self):
        tab = self.make_home(offline=True, seeded=False)
        self.assertIsNone(tab._dashboard_thread)
        self.assertIsNone(tab._dashboard_snapshot)

    def test_success_persists_snapshot_to_cache(self):
        tab = self.make_home(offline=True, seeded=False)
        tab._dashboard_snapshot = None
        tab._remote_dashboard_finished(dict(_SNAPSHOT), time.perf_counter())
        snapshot, _ = self.cache.get_dashboard()
        self.assertEqual(snapshot['products_count'], 42)
        self.assertEqual(tab._monthly_sales_set.at(5), 1200.5)
        self.assertTrue(self._has_label(tab, 'Porte'))

    def test_failure_falls_back_to_cached_snapshot(self):
        tab = self.make_home(offline=True)
        tab._dashboard_snapshot = None
        tab._remote_dashboard_failed('host unreachable', time.perf_counter())
        self.assertEqual(tab._dashboard_snapshot['products_count'], 42)
        self.assertEqual(tab._monthly_sales_set.at(5), 1200.5)

    def test_refresh_statistics_online_starts_thread(self):
        tab = self.make_home(offline=False)
        database = tab.database
        database.get_dashboard_snapshot = lambda: dict(_SNAPSHOT)
        tab.refresh_statistics(force=True)
        thread = tab._dashboard_thread
        self.assertIsNotNone(thread)
        if thread is not None:
            loop = QEventLoop()
            thread.finished.connect(loop.quit)
            timed_out = []
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: timed_out.append(True))
            timer.timeout.connect(loop.quit)
            timer.start(5000)
            loop.exec()
            timer.stop()
            self.assertFalse(timed_out, "Dashboard worker did not finish in time")
        # The successful worker persisted the snapshot to the cache.
        snapshot, _ = self.cache.get_dashboard()
        self.assertEqual(snapshot['products_count'], 42)


if __name__ == '__main__':
    unittest.main()
