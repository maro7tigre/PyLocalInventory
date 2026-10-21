"""Compatibility helper for large workspaces.

Large dialogs now open as normal resizable windows. This helper remains for
older call sites: it only keeps the dialog inside the available work area and
never maximizes or enters full-screen mode.
"""

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication


def maximize_workspace_dialog(dialog):
    """Fit a workspace dialog to the screen without taking over the desktop."""
    def fit_available_work_area():
        screen = dialog.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        geometry = dialog.geometry()
        width = max(dialog.minimumWidth(), min(geometry.width(), available.width()))
        height = max(dialog.minimumHeight(), min(geometry.height(), available.height()))
        x, y = geometry.x(), geometry.y()
        if x < available.left() or x + width > available.right() + 1:
            x = available.left() + max(0, (available.width() - width) // 2)
        if y < available.top() or y + height > available.bottom() + 1:
            y = available.top() + max(0, (available.height() - height) // 2)
        dialog.setGeometry(x, y, width, height)

    QTimer.singleShot(0, fit_available_work_area)
