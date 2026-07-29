import threading
import unittest

from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication

from ui.tabs.base_tab import _RemoteTableFetchWorker
from ui.tabs.home_tab import HomeTab


class RemoteTableWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_remote_fetch_does_not_block_gui_event_loop(self):
        gui_timer_ran = []
        release_worker = threading.Event()

        def fetch():
            release_worker.wait(1)
            return [{"ID": 1}]

        thread = QThread()
        worker = _RemoteTableFetchWorker(fetch)
        worker.moveToThread(thread)
        loop = QEventLoop()
        results = []
        worker.finished.connect(lambda items, _levels, _started: results.extend(items))
        worker.finished.connect(thread.quit)
        worker.finished.connect(loop.quit)
        thread.started.connect(worker.run)

        def gui_callback():
            gui_timer_ran.append(True)
            release_worker.set()

        QTimer.singleShot(0, gui_callback)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        timeout.start(2000)
        thread.start()
        loop.exec()
        thread.wait(2000)

        self.assertTrue(gui_timer_ran)
        self.assertEqual(results, [{"ID": 1}])
        self.assertFalse(thread.isRunning())

    def test_remote_dashboard_uses_one_background_snapshot(self):
        RemoteDatabase = type("RemoteDatabase", (), {})
        database = RemoteDatabase()
        database.conn = True
        database.calls = 0

        def snapshot():
            database.calls += 1
            return {
                "sales_total": "10", "imports_total": "4",
                "products_count": 2, "clients_count": 3,
                "suppliers_count": 1, "low_stock_count": 0,
                "low_stock_products": [], "recent_activities": [],
                "monthly": {},
            }

        database.get_dashboard_snapshot = snapshot
        tab = HomeTab(database)
        loop = QEventLoop()
        timeout = QTimer()
        timeout.setInterval(10)
        timeout.timeout.connect(
            lambda: loop.quit() if (
                tab._dashboard_snapshot is not None
                and tab._dashboard_thread is None
            ) else None
        )
        timeout.start()
        QTimer.singleShot(2000, loop.quit)
        loop.exec()

        self.assertEqual(database.calls, 1)
        self.assertEqual(tab._dashboard_snapshot["products_count"], 2)
        tab.refresh_timer.stop()
        tab.close()


if __name__ == "__main__":
    unittest.main()
