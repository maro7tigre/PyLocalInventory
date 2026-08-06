import os
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThread

from ui.tabs.base_tab import BaseTab

class TestQThreadLifetime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # A minimal tab inheriting from BaseTab to avoid heavy UI layout code
        class MinimalBaseTab(BaseTab):
            def __init__(self):
                super(BaseTab, self).__init__()
                self.section = "Test"
                self._cache = {}
                self.finished_called = False
                self.failed_called = False
            def _remote_refresh_finished(self, *args):
                self.finished_called = True
            def _remote_refresh_failed(self, *args):
                self.failed_called = True
                
        self.tab = MinimalBaseTab()
        self.release_worker = threading.Event()
        self.worker_started = threading.Event()
        
    def tearDown(self):
        # Guaranteed cleanup regardless of test assertions
        self.release_worker.set()
        self.tab._wait_for_refresh_thread(2000)
        thread = getattr(self.tab, "_refresh_thread", None)
        if thread:
            thread.wait(2000)
            self.assertFalse(thread.isRunning(), "Test leaked running QThread")

    def blocking_fetch(self):
        self.worker_started.set()
        self.release_worker.wait()
        return []

    def test_base_tab_wait_for_refresh_thread_success(self):
        self.tab._start_refresh(self.blocking_fetch, refresh_id="123")
        
        # Ensure worker is inside fetch
        self.assertTrue(self.worker_started.wait(2.0))
        
        self.assertIsNotNone(self.tab._refresh_thread)
        self.assertTrue(self.tab._refresh_thread.isRunning())
        
        # Test waiting successfully
        self.release_worker.set()
        result = self.tab._wait_for_refresh_thread(2000)
        
        self.assertTrue(result)
        # Process queued signals
        QApplication.processEvents()
        
        # Verify deterministic completion removes references
        self.assertIsNone(self.tab._refresh_thread)
        self.assertIsNone(self.tab._refresh_worker)

    def test_base_tab_wait_for_refresh_thread_timeout(self):
        self.tab._start_refresh(self.blocking_fetch, refresh_id="123")
        
        # Wait until we are definitely blocked in fetch
        self.assertTrue(self.worker_started.wait(2.0))
        
        # Wait while blocked
        result = self.tab._wait_for_refresh_thread(100)
        
        self.assertFalse(result)
        # References must survive timeout to prevent teardown crashes
        self.assertIsNotNone(self.tab._refresh_thread)
        self.assertTrue(self.tab._refresh_thread.isRunning())

    def test_duplicate_refresh_ignored(self):
        self.tab._start_refresh(self.blocking_fetch, refresh_id="123")
        self.assertTrue(self.worker_started.wait(2.0))
        
        first_thread = self.tab._refresh_thread
        
        # Try to start another refresh while running
        self.tab._start_refresh(self.blocking_fetch, refresh_id="456")
        
        self.assertIs(self.tab._refresh_thread, first_thread)

    def test_interruption_prevents_stale_data(self):
        self.tab._start_refresh(self.blocking_fetch, refresh_id="123")
        self.assertTrue(self.worker_started.wait(2.0))
        
        # Cancel before fetch returns
        thread = self.tab._refresh_thread
        thread.requestInterruption()
        self.release_worker.set()
        
        self.tab._wait_for_refresh_thread(2000)
        QApplication.processEvents()
        
        self.assertFalse(self.tab.finished_called)
        self.assertTrue(self.tab.failed_called)

class TestHomeTabQThreadLifetime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from ui.tabs.home_tab import HomeTab
        
        class MinimalHomeTab(HomeTab):
            def __init__(self):
                # Init QWidget
                super(HomeTab, self).__init__()
                self._dashboard_thread = None
                self._dashboard_worker = None
                self.database = type("DB", (), {})()
                self.finished_called = False
                self.failed_called = False
            def _remote_dashboard_finished(self, *args):
                self.finished_called = True
            def _remote_dashboard_failed(self, *args):
                self.failed_called = True
                
        self.tab = MinimalHomeTab()
        self.release_worker = threading.Event()
        self.worker_started = threading.Event()
        
        def blocking_fetch():
            self.worker_started.set()
            self.release_worker.wait()
            return {"total_sales": 100}
            
        self.tab.database.get_dashboard_snapshot = blocking_fetch
        
    def tearDown(self):
        self.release_worker.set()
        self.tab._wait_for_dashboard_thread(2000)
        thread = getattr(self.tab, "_dashboard_thread", None)
        if thread:
            thread.wait(2000)
            self.assertFalse(thread.isRunning(), "Test leaked running QThread")

    def test_home_tab_wait_for_dashboard_thread_success(self):
        self.tab._start_remote_dashboard_refresh()
        
        self.assertTrue(self.worker_started.wait(2.0))
        self.assertIsNotNone(self.tab._dashboard_thread)
        self.assertTrue(self.tab._dashboard_thread.isRunning())
        
        self.release_worker.set()
        result = self.tab._wait_for_dashboard_thread(2000)
        
        self.assertTrue(result)
        QApplication.processEvents()
        
        self.assertIsNone(self.tab._dashboard_thread)
        self.assertIsNone(self.tab._dashboard_worker)

    def test_home_tab_wait_for_dashboard_thread_timeout(self):
        self.tab._start_remote_dashboard_refresh()
        
        self.assertTrue(self.worker_started.wait(2.0))
        
        result = self.tab._wait_for_dashboard_thread(100)
        
        self.assertFalse(result)
        self.assertIsNotNone(self.tab._dashboard_thread)
        self.assertTrue(self.tab._dashboard_thread.isRunning())

    def test_interruption_prevents_stale_data(self):
        self.tab._start_remote_dashboard_refresh()
        self.assertTrue(self.worker_started.wait(2.0))
        
        thread = self.tab._dashboard_thread
        thread.requestInterruption()
        self.release_worker.set()
        
        self.tab._wait_for_dashboard_thread(2000)
        QApplication.processEvents()
        
        self.assertFalse(self.tab.finished_called)
        self.assertFalse(self.tab.failed_called)

if __name__ == "__main__":
    unittest.main()
