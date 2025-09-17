"""
Base dialog class for section item editing
"""
from PySide6.QtWidgets import QDialog

class BaseEditDialog(QDialog):
    def __init__(self, item_data, section_name="Item", parent=None):
        super().__init__(parent)
        pass