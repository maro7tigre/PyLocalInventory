"""Window sizing regressions: normal startup and resizable workspaces."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow

from ui.main_window import MainWindow
from ui.widgets.workspace_dialog import maximize_workspace_dialog


class _FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value


class WindowStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _bare_window(self):
        with patch.object(
            MainWindow, "__init__", lambda self: super(MainWindow, self).__init__()
        ):
            window = MainWindow()
        window.setMinimumSize(1000, 700)
        self.addCleanup(window.close)
        return window

    def test_saved_maximized_state_is_restored_as_a_normal_window(self):
        source = QMainWindow()
        source.setMinimumSize(1000, 700)
        source.resize(1200, 800)
        source.show()
        self.app.processEvents()
        source.showMaximized()
        self.app.processEvents()
        saved_geometry = source.saveGeometry()
        source.close()

        window = self._bare_window()
        window.settings = _FakeSettings({"geometry": saved_geometry})
        window.load_app_config()
        window.show()
        self.app.processEvents()

        self.assertFalse(window.isMaximized())
        self.assertFalse(window.isFullScreen())
        self.assertFalse(
            window.windowState() & (Qt.WindowMaximized | Qt.WindowFullScreen)
        )
        self.assertTrue(window.windowFlags() & Qt.WindowMaximizeButtonHint)
        self.assertTrue(window.windowFlags() & Qt.WindowMinimizeButtonHint)

    def test_default_geometry_is_sensible_and_centered(self):
        window = self._bare_window()
        with patch.object(
            MainWindow, "_available_screen_geometry", return_value=QRect(0, 0, 1920, 1080)
        ):
            window._set_default_window_geometry()

        self.assertEqual((window.width(), window.height()), (1280, 820))
        self.assertLessEqual(window.frameGeometry().right(), 1920)
        self.assertLessEqual(window.frameGeometry().bottom(), 1080)

    def test_corrupt_saved_geometry_falls_back_to_default_size(self):
        window = self._bare_window()
        window.settings = _FakeSettings({"geometry": b"not-a-qt-geometry"})
        with patch.object(
            MainWindow, "_available_screen_geometry", return_value=QRect(0, 0, 1920, 1080)
        ):
            window.load_app_config()

        self.assertEqual((window.width(), window.height()), (1280, 820))

    def test_offscreen_saved_geometry_is_brought_back_on_screen(self):
        window = self._bare_window()
        window.setGeometry(5000, 5000, 1200, 800)
        with patch.object(
            MainWindow, "_available_screen_geometry", return_value=QRect(0, 0, 1920, 1080)
        ):
            window._fit_window_to_available_screen()

        self.assertGreaterEqual(window.x(), 0)
        self.assertGreaterEqual(window.y(), 0)
        self.assertLessEqual(window.frameGeometry().right(), 1920)
        self.assertLessEqual(window.frameGeometry().bottom(), 1080)

    def test_workspace_helper_never_maximizes(self):
        dialog = QDialog()
        dialog.resize(900, 600)
        dialog.show()
        self.app.processEvents()
        maximize_workspace_dialog(dialog)
        self.app.processEvents()
        self.assertFalse(dialog.isMaximized())
        self.assertFalse(dialog.isFullScreen())
        dialog.close()


if __name__ == "__main__":
    unittest.main()
