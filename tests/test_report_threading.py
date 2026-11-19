import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication

from ui.dialogs.reports_dialog import ReportsDialog


class _Values:
    def __init__(self, values):
        self.values = values

    def get_value(self, key):
        return self.values.get(key)


class ReportThreadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_report_completion_dialog_runs_on_gui_thread(self):
        sale = _Values({"client_name": "Client", "date": "2026-07-27"})
        sale.database = None
        profile = _Values({"company name": "Test"})
        manager = type("Manager", (), {"selected_profile": profile})()
        dialog = ReportsDialog(sale, manager)
        dialog._prepare_report = lambda _kind: ("<html></html>", "report.pdf")
        dialog._html_to_pdf = lambda _html, output: output
        callback_threads = []

        def information(*_args, **_kwargs):
            callback_threads.append(QThread.currentThread())
            return 0

        loop = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timed_out = []
        timeout.timeout.connect(lambda: timed_out.append(True))
        timeout.timeout.connect(loop.quit)
        with patch(
            "ui.dialogs.reports_dialog.QMessageBox.information",
            side_effect=information,
        ), patch.object(dialog, "open_pdf"):
            dialog.generate_report("devis")
            dialog._report_thread.finished.connect(loop.quit)
            timeout.start(5000)
            loop.exec()

        timeout.stop()
        self.assertFalse(timed_out, "Report worker did not finish in time")
        self.assertEqual(callback_threads, [self.app.thread()])
        dialog.close()


if __name__ == "__main__":
    unittest.main()
