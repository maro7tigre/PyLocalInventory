"""
Door Type Management Dialog
"""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QHBoxLayout
from ui.widgets.table_widgets import ParameterTableWidget
from ui.widgets.themed_widgets import RedButton
from classes.door_type_class import DoorTypeClass
from ui.dialogs.edit_dialogs.door_type_dialog import DoorTypeEditDialog


class DoorTypeManagementDialog(QDialog):
    def __init__(self, database, parent=None):
        super().__init__(parent)
        self.database = database
        self.setWindowTitle("Manage Door Types")
        self.setMinimumSize(760, 520)

        layout = QVBoxLayout(self)
        title = QLabel("Door Type Management")
        title.setStyleSheet("font-size: 22px; font-weight: bold; margin-bottom: 12px;")
        layout.addWidget(title)

        self.table_widget = ParameterTableWidget(DoorTypeClass, database, DoorTypeEditDialog, parent=self)
        layout.addWidget(self.table_widget)

        footer = QHBoxLayout()
        footer.addStretch()
        self.close_btn = RedButton("Close")
        self.close_btn.clicked.connect(self.reject)
        footer.addWidget(self.close_btn)
        layout.addLayout(footer)
