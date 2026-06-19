"""
Door Type Edit Dialog
"""
from ui.dialogs.edit_dialogs.base_dialog import BaseEditDialog
from classes.door_type_class import DoorTypeClass
from ui.widgets.themed_widgets import GreenButton, RedButton
from PySide6.QtWidgets import QLineEdit, QFormLayout, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget
from PySide6.QtCore import Qt


class DoorTypeEditDialog(BaseEditDialog):
    def __init__(self, door_type_id=None, database=None, parent=None):
        self.door_type_id = door_type_id
        self.database = database

        if door_type_id:
            self.door_type = DoorTypeClass(door_type_id, database)
            self.door_type.load_database_data()
            title = f"Edit Door Type - {self.door_type.get_value('name') or door_type_id}"
        else:
            self.door_type = DoorTypeClass(0, database)
            title = "New Door Type"

        super().__init__(self.door_type, None, parent)
        self.setWindowTitle(title)

    def setup_ui(self):
        self.setMinimumSize(520, 280)
        layout = QVBoxLayout(self)

        form_layout = QFormLayout()
        self.name_edit = QLineEdit(self.door_type.get_value('name') or '')
        self.serial_edit = QLineEdit(str(self.door_type.get_value('serial') or ''))
        self.image_edit = QLineEdit(self.door_type.get_value('image_path') or '')
        self.image_edit.setReadOnly(True)

        browse_btn = QPushButton("Browse")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self.browse_image)
        image_row = QWidget()
        image_layout = QHBoxLayout(image_row)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.addWidget(self.image_edit)
        image_layout.addWidget(browse_btn)

        form_layout.addRow(QLabel("Door Name:"), self.name_edit)
        form_layout.addRow(QLabel("Serial Number:"), self.serial_edit)
        form_layout.addRow(QLabel("Image Path:"), image_row)

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

    def browse_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Door Image", "", "Image Files (*.png *.jpg *.jpeg *.bmp *.gif)")
        if path:
            self.image_edit.setText(path)

    def validate_data(self):
        errors = []
        name = self.name_edit.text().strip()
        serial = self.serial_edit.text().strip()

        if not name:
            errors.append("Door name is required")
        if not serial:
            errors.append("Serial number is required")
        else:
            try:
                serial_num = int(serial)
                if serial_num < 1:
                    errors.append("Serial number must be at least 1")
            except ValueError:
                errors.append("Serial number must be an integer")

        if not self.door_type.validate_name_uniqueness(name):
            errors.append("Door type name must be unique")
        if serial and not self.door_type.validate_serial_uniqueness(int(serial)):
            errors.append("Door type serial must be unique")

        return errors

    def save_changes(self):
        errors = self.validate_data()
        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return

        self.door_type.set_value('name', self.name_edit.text().strip())
        self.door_type.set_value('serial', int(self.serial_edit.text().strip()))
        self.door_type.set_value('image_path', self.image_edit.text().strip() or None)

        if not self.door_type.save_to_database():
            QMessageBox.critical(self, "Error", "Failed to save door type")
            return

        self.accept()
