"""Consistent first-open behaviour for large modal workspaces."""

from PySide6.QtCore import Qt, QTimer


def maximize_workspace_dialog(dialog):
    """Open in the available work area without allowing taskbar overlap."""
    def maximize():
        dialog.showMaximized()

        # Some Windows configurations report a maximized QDialog extending
        # below the taskbar. Keep the normal maximize path, then constrain only
        # that bad geometry to Qt's available work area.
        QTimer.singleShot(0, fit_available_work_area)

    def fit_available_work_area():
        screen = dialog.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = dialog.frameGeometry()
        if frame.bottom() <= available.bottom() and frame.right() <= available.right():
            return
        dialog.setWindowState(dialog.windowState() & ~Qt.WindowMaximized)
        dialog.setGeometry(available)

    QTimer.singleShot(0, maximize)
