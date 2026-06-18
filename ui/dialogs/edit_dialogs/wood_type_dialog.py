"""
Wood Type Edit Dialog
"""
from ui.dialogs.edit_dialogs.base_dialog import BaseEditDialog
from classes.wood_type_class import WoodTypeClass
from ui.widgets.themed_widgets import GreenButton, RedButton
from PySide6.QtWidgets import QLineEdit, QFormLayout, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QMessageBox


class WoodTypeEditDialog(BaseEditDialog):
    def __init__(self, wood_type_id=None, database=None, parent=None):
        self.wood_type_id = wood_type_id
        self.database = database

        if wood_type_id:
            self.wood_type = WoodTypeClass(wood_type_id, database)
            self.wood_type.load_database_data()
            title = f"Edit Wood Type - {self.wood_type.get_value('name') or wood_type_id}"
        else:
            self.wood_type = WoodTypeClass(0, database)
            title = "New Wood Type"

        super().__init__(self.wood_type, None, parent)
        self.setWindowTitle(title)

    def setup_ui(self):
        self.setMinimumSize(520, 220)
        layout = QVBoxLayout(self)

        form_layout = QFormLayout()
        self.name_edit = QLineEdit(self.wood_type.get_value('name') or '')
        form_layout.addRow(QLabel("Wood Type Name:"), self.name_edit)

        layout.addLayout(form_layout)

        buttons = QHBoxLayout()
        buttons.addStretch()
        save_btn = GreenButton("Save")
        save_btn.clicked.connect(self.save_changes)
        cancel_btn = RedButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)

        layout.addLayout(buttons)

    def validate_data(self):
        errors = []
        name = self.name_edit.text().strip().upper()

        if not name:
            errors.append("Wood type name is required")
        if not self.wood_type.validate_name_uniqueness(name):
            errors.append("Wood type name must be unique")

        return errors

    def save_changes(self):
        errors = self.validate_data()
        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return

        self.wood_type.set_value('name', self.name_edit.text().strip().upper())

        if not self.wood_type.save_to_database():
            QMessageBox.critical(self, "Error", "Failed to save wood type")
            return

        self.accept()
