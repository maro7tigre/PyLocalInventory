"""Consistent first-open behaviour for large modal workspaces."""

from PySide6.QtCore import QTimer


def maximize_workspace_dialog(dialog):
    """Maximize after the modal event loop starts, on the dialog's current screen."""
    QTimer.singleShot(0, dialog.showMaximized)
