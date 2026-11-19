import sys
sys.path.insert(0, '.')
import time
import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThread, QObject, Signal, Slot
import shiboken6

# Ensure QApplication exists
if not QApplication.instance():
    _app = QApplication([])

# We will mock the base_tab behavior
from ui.tabs.base_tab import BaseTab
from unittest.mock import MagicMock

class TestQThreadRegression(unittest.TestCase):
    def test_deleted_qthread_wrapper_crash(self):
        """Test that _wait_for_refresh_thread safely handles a deleted QThread."""
        
        # 1. Create a dummy worker and thread
        class DummyWorker(QObject):
            finished = Signal()
            failed = Signal(str)
            @Slot()
            def run(self):
                self.finished.emit()
                
        thread = QThread()
        worker = DummyWorker()
        worker.moveToThread(thread)
        
        # 2. Attach lifecycle exactly as BaseTab does
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        
        # Assign to mock tab
        tab = MagicMock(spec=BaseTab)
        tab._refresh_thread = thread
        tab._refresh_worker = worker
        tab._cache = {}
        tab.section = "Test"
        
        # Use the actual wait method
        tab._wait_for_refresh_thread = BaseTab._wait_for_refresh_thread.__get__(tab, BaseTab)
        
        # 3. Start and allow it to finish
        thread.start()
        
        # 4. Wait for OS thread to finish
        while thread.isRunning():
            QApplication.processEvents()
            time.sleep(0.01)
            
        # 5. Process Qt events so deleteLater() executes and destroys the C++ object
        QApplication.processEvents()
        QApplication.processEvents()
        
        # Now the C++ object is deleted.
        self.assertFalse(shiboken6.isValid(tab._refresh_thread))
        
        # 6. Trigger the cleanup path
        # If this crashes, the test suite will instantly die with RuntimeError or exit code 1
        result = tab._wait_for_refresh_thread()
        
        # 7. Confirm references become None and no crash occurred
        self.assertTrue(result)
        self.assertIsNone(tab._refresh_thread)
        self.assertIsNone(tab._refresh_worker)
        print("Regression test passed! No crash on deleted QThread.")

if __name__ == '__main__':
    unittest.main()
