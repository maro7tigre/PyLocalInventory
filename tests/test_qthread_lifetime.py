import os
import threading
import time
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

class TestReportsDialogQThreadLifetime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from ui.dialogs.reports_dialog import ReportsDialog
        
        class MinimalReportsDialog(ReportsDialog):
            def __init__(self):
                # We skip real UI init to avoid dependencies
                super(ReportsDialog, self).__init__()
                self._report_thread = None
                self._report_worker = None
                self.finished_called = False
                self.failed_called = False
                # Mock UI elements needed for generate_report
                self.devis_btn = type("btn", (), {"setEnabled": lambda s, x: None})()
                self.bdl_btn = type("btn", (), {"setEnabled": lambda s, x: None})()
                self.cancel_btn = type("btn", (), {"setEnabled": lambda s, x: None})()
                self.status_label = type("lbl", (), {"setText": lambda s, x: None})()

            def _prepare_report(self, report_type):
                return "<html></html>", "test.pdf"

            def _html_to_pdf(self, html_content, output_path):
                # The mocked render method
                return self.blocking_render()

            def _report_rendered_on_ui(self, pdf_path):
                self.finished_called = True

            def _report_failed_on_ui(self, error):
                self.failed_called = True
                
        self.dialog = MinimalReportsDialog()
        self.release_worker = threading.Event()
        self.worker_started = threading.Event()
        
        def blocking_render():
            self.worker_started.set()
            self.release_worker.wait()
            return "test.pdf"
            
        self.dialog.blocking_render = blocking_render
        
    def tearDown(self):
        self.release_worker.set()
        self.dialog._wait_for_report_thread(2000)
        thread = getattr(self.dialog, "_report_thread", None)
        if thread:
            thread.wait(2000)
            self.assertFalse(thread.isRunning(), "Test leaked running QThread")

    def test_reports_dialog_wait_success(self):
        self.dialog.generate_report("devis")
        
        self.assertTrue(self.worker_started.wait(2.0))
        self.assertIsNotNone(self.dialog._report_thread)
        self.assertTrue(self.dialog._report_thread.isRunning())
        
        self.release_worker.set()
        result = self.dialog._wait_for_report_thread(2000)
        
        self.assertTrue(result)
        QApplication.processEvents()
        
        self.assertIsNone(self.dialog._report_thread)
        self.assertIsNone(self.dialog._report_worker)

    def test_reports_dialog_wait_timeout(self):
        self.dialog.generate_report("devis")
        
        self.assertTrue(self.worker_started.wait(2.0))
        
        result = self.dialog._wait_for_report_thread(100)
        
        self.assertFalse(result)
        self.assertIsNotNone(self.dialog._report_thread)
        self.assertTrue(self.dialog._report_thread.isRunning())

    def test_interruption_prevents_stale_data(self):
        self.dialog.generate_report("devis")
        self.assertTrue(self.worker_started.wait(2.0))
        
        thread = self.dialog._report_thread
        thread.requestInterruption()
        self.release_worker.set()
        
        self.dialog._wait_for_report_thread(2000)
        QApplication.processEvents()
        
        self.assertFalse(self.dialog.finished_called)
        self.assertFalse(self.dialog.failed_called)


class TestOperationDialogLoadThreadLifetime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_close_waits_for_initial_load_thread(self):
        from ui.dialogs.edit_dialogs import base_operation_dialog as dialog_module

        class MinimalOperationDialog(dialog_module.BaseOperationDialog):
            def __init__(self):
                super(dialog_module.BaseOperationDialog, self).__init__()
                self.load_thread = QThread()
                self.load_worker = object()
                dialog_module._active_background_threads.add(self.load_thread)
                self.load_thread.finished.connect(self.load_thread.deleteLater)
                self.load_thread.finished.connect(self._on_load_thread_finished)

        dialog = MinimalOperationDialog()
        dialog.show()
        dialog.load_thread.start()
        self.assertTrue(dialog.load_thread.isRunning())

        self.assertFalse(dialog.close())
        self.assertTrue(dialog.isVisible())
        self.assertTrue(dialog._close_after_load)

        thread = dialog.load_thread
        thread.quit()
        deadline = time.time() + 2.0
        while dialog.load_thread is not None and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        for _ in range(3):
            self.app.processEvents()

        self.assertIsNone(dialog.load_thread)
        self.assertFalse(dialog.isVisible())
        self.assertNotIn(thread, dialog_module._active_background_threads)

class TestBackupsDialogQThreadLifetime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from ui.dialogs.backups_dialog import BackupsDialog
        
        class MinimalBackupsDialog(BackupsDialog):
            def __init__(self):
                super(BackupsDialog, self).__init__()
                self._backup_thread = None
                self._backup_worker = None
                self._backup_running = False
                self.finished_called = False
                self.failed_called = False
                self.restore_btn = type("btn", (), {"setEnabled": lambda s, x: None})()
                self.close_btn = type("btn", (), {"setEnabled": lambda s, x: None})()
                self.status_label = type("lbl", (), {"setText": lambda s, x: None})()

            def _restore_completed(self, success):
                self.finished_called = True

            def _restore_failed(self, error):
                self.failed_called = True
                
        self.dialog = MinimalBackupsDialog()
        self.release_worker = threading.Event()
        self.worker_started = threading.Event()
        
        def blocking_restore():
            self.worker_started.set()
            self.release_worker.wait()
            return True
            
        self.dialog.blocking_restore = blocking_restore
        
    def tearDown(self):
        self.release_worker.set()
        self.dialog._wait_for_backup_thread(2000)
        thread = getattr(self.dialog, "_backup_thread", None)
        if thread:
            thread.wait(2000)
            self.assertFalse(thread.isRunning(), "Test leaked running QThread")

    def _start_mock_backup(self):
        from ui.dialogs.backups_dialog import _BackupCreateWorker
        self.dialog._backup_running = True
        thread = QThread()
        worker = _BackupCreateWorker(
            self.dialog.blocking_restore,
            "restore_backup",
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        
        worker.finished.connect(self.dialog._restore_completed)
        worker.failed.connect(self.dialog._restore_failed)
        
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.cancelled.connect(worker.deleteLater)
        
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self.dialog._on_backup_thread_finished)
        
        self.dialog._backup_thread = thread
        self.dialog._backup_worker = worker
        thread.start()

    def test_backups_dialog_wait_success(self):
        self._start_mock_backup()
        
        self.assertTrue(self.worker_started.wait(2.0))
        self.assertIsNotNone(self.dialog._backup_thread)
        self.assertTrue(self.dialog._backup_thread.isRunning())
        
        self.release_worker.set()
        result = self.dialog._wait_for_backup_thread(2000)
        
        self.assertTrue(result)
        QApplication.processEvents()
        
        self.assertIsNone(self.dialog._backup_thread)
        self.assertIsNone(self.dialog._backup_worker)

    def test_backups_dialog_wait_timeout(self):
        self._start_mock_backup()
        
        self.assertTrue(self.worker_started.wait(2.0))
        
        result = self.dialog._wait_for_backup_thread(100)
        
        self.assertFalse(result)
        self.assertIsNotNone(self.dialog._backup_thread)
        self.assertTrue(self.dialog._backup_thread.isRunning())

    def test_interruption_prevents_stale_data(self):
        self._start_mock_backup()
        self.assertTrue(self.worker_started.wait(2.0))
        
        thread = self.dialog._backup_thread
        thread.requestInterruption()
        self.release_worker.set()
        
        self.dialog._wait_for_backup_thread(2000)
        QApplication.processEvents()
        
        self.assertFalse(self.dialog.finished_called)
        self.assertFalse(self.dialog.failed_called)

if __name__ == "__main__":
    unittest.main()
