"""
Service Dialog - Edit dialog for services
"""
from ui.dialogs.edit_dialogs.base_dialog import BaseEditDialog
from classes.service_class import ServiceClass
from classes.door_type_class import DoorTypeClass
from classes.wood_type_class import WoodTypeClass
from ui.dialogs.door_type_management_dialog import DoorTypeManagementDialog
from ui.dialogs.wood_type_management_dialog import WoodTypeManagementDialog
from ui.widgets.themed_widgets import GreenButton, RedButton
from ui.widgets.preview_widget import PreviewWidget
from PySide6.QtWidgets import (
    QMessageBox, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QRadioButton, QPushButton,
    QDoubleSpinBox, QTextEdit, QFileDialog, QWidget, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QIcon


class ServiceEditDialog(BaseEditDialog):
    """Dialog for creating or editing services."""

    def __init__(self, service_id=None, database=None, parent=None):
        self.service_id = service_id
        self.database = database

        if service_id:
            self.service = ServiceClass(service_id, database)
            self.service.load_database_data()
            window_title = f"Edit Service - {self.service.get_value('name') or service_id}"
        else:
            self.service = ServiceClass(0, database)
            window_title = "New Service"

        super().__init__(self.service, None, parent)
        self.setWindowTitle(window_title)

    def setup_ui(self):
        self.setWindowTitle(self.windowTitle())
        self.setMinimumSize(520, 620)

        layout = QVBoxLayout(self)

        # Service type selection
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Service Type:"))
        self.door_radio = QRadioButton("Door Service")
        self.custom_radio = QRadioButton("Custom Service")
        self.door_radio.toggled.connect(self.on_service_type_changed)
        type_layout.addWidget(self.door_radio)
        type_layout.addWidget(self.custom_radio)
        type_layout.addStretch()
        layout.addLayout(type_layout)

        # Main form
        self.form_layout = QFormLayout()

        self.code_edit = QLineEdit()
        self.code_edit.setReadOnly(True)
        self.form_layout.addRow(QLabel("Code:"), self.code_edit)

        self.name_edit = QLineEdit()
        self.form_layout.addRow(QLabel("Service Name:"), self.name_edit)

        # Door service fields
        self.door_service_widget = QWidget()
        door_layout = QVBoxLayout(self.door_service_widget)
        door_layout.setContentsMargins(0, 0, 0, 0)

        # Door type row
        door_type_row = QWidget()
        door_type_layout = QHBoxLayout(door_type_row)
        door_type_layout.setContentsMargins(0, 0, 0, 0)

        self.door_type_combo = QComboBox()
        self.door_type_combo.currentIndexChanged.connect(self.on_door_type_changed)
        door_type_layout.addWidget(self.door_type_combo)

        self.add_door_type_btn = QPushButton("Manage Door Types")
        self.add_door_type_btn.setFixedWidth(120)
        self.add_door_type_btn.clicked.connect(self.manage_door_types)
        door_type_layout.addWidget(self.add_door_type_btn)

        self.door_type_preview = PreviewWidget(size=64, category="product")
        door_type_layout.addWidget(self.door_type_preview)
        door_layout.addLayout(door_type_layout)

        self.wood_type_row = QWidget()
        wood_layout = QHBoxLayout(self.wood_type_row)
        wood_layout.setContentsMargins(0, 0, 0, 0)

        self.wood_type_combo = QComboBox()
        self.wood_type_combo.currentIndexChanged.connect(self.on_wood_type_changed)
        wood_layout.addWidget(self.wood_type_combo)

        self.add_wood_type_btn = QPushButton("Manage Wood Types")
        self.add_wood_type_btn.setFixedWidth(120)
        self.add_wood_type_btn.clicked.connect(self.manage_wood_types)
        wood_layout.addWidget(self.add_wood_type_btn)
        door_layout.addLayout(wood_layout)

        self.length_spin = QDoubleSpinBox()
        self.length_spin.setRange(0.0, 9999.0)
        self.length_spin.setDecimals(2)
        self.length_spin.setSingleStep(0.5)
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.0, 9999.0)
        self.width_spin.setDecimals(2)
        self.width_spin.setSingleStep(0.5)
        self.thickness_spin = QDoubleSpinBox()
        self.thickness_spin.setRange(0.0, 9999.0)
        self.thickness_spin.setDecimals(2)
        self.thickness_spin.setSingleStep(0.1)

        dimensions_widget = QWidget()
        dimensions_layout = QHBoxLayout(dimensions_widget)
        dimensions_layout.setContentsMargins(0, 0, 0, 0)
        dimensions_layout.addWidget(QLabel("Length:"))
        dimensions_layout.addWidget(self.length_spin)
        dimensions_layout.addWidget(QLabel("Width:"))
        dimensions_layout.addWidget(self.width_spin)
        dimensions_layout.addWidget(QLabel("Thickness:"))
        dimensions_layout.addWidget(self.thickness_spin)
        door_layout.addWidget(dimensions_widget)

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["cm", "m"])
        door_layout.addWidget(QWidget())
        door_layout.addWidget(QLabel("Unit:"))
        door_layout.addWidget(self.unit_combo)

        self.color_edit = QLineEdit()
        door_layout.addWidget(QLabel("Color:"))
        door_layout.addWidget(self.color_edit)

        door_layout.addStretch()

        # Add fields to main form for door service
        self.form_layout.addRow(QLabel("Door Type:"), door_type_row)
        self.form_layout.addRow(QLabel("Door Preview:"), self.door_type_preview)
        self.form_layout.addRow(QLabel("Wood Type:"), self.wood_type_row)
        self.form_layout.addRow(QLabel("Dimensions:"), dimensions_widget)
        self.form_layout.addRow(QLabel("Unit:"), self.unit_combo)
        self.form_layout.addRow(QLabel("Color:"), self.color_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setFixedHeight(110)
        self.form_layout.addRow(QLabel("Description:"), self.description_edit)

        layout.addLayout(self.form_layout)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.save_btn = GreenButton("Save")
        self.save_btn.clicked.connect(self.save_changes)
        button_layout.addWidget(self.save_btn)
        self.cancel_btn = RedButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)

    def load_data(self):
        self.ensure_default_types()
        self.load_door_types()
        self.load_wood_types()

        service_type = self.service.get_value('service_type') or 'Door Service'
        self.door_radio.setChecked(service_type == 'Door Service')
        self.custom_radio.setChecked(service_type == 'Custom Service')

        self.code_edit.setText(self.service.get_value('service_code') or '')
        self.name_edit.setText(self.service.get_value('name') or '')
        self.description_edit.setPlainText(self.service.get_value('description') or '')
        self.color_edit.setText(self.service.get_value('color') or '')
        self.unit_combo.setCurrentText(self.service.get_value('unit') or 'cm')
        self.length_spin.setValue(self.service.get_value('length') or 0.0)
        self.width_spin.setValue(self.service.get_value('width') or 0.0)
        self.thickness_spin.setValue(self.service.get_value('thickness') or 0.0)

        wood_type = self.service.get_value('wood_type') or ''
        if wood_type and wood_type in [self.wood_type_combo.itemText(i) for i in range(self.wood_type_combo.count())]:
            self.wood_type_combo.setCurrentText(wood_type)

        selected_id = self.service.get_value('door_type_id') or 0
        if selected_id and selected_id in [self.door_type_combo.itemData(i) for i in range(self.door_type_combo.count())]:
            self.door_type_combo.setCurrentIndex(self.door_type_combo.findData(selected_id))
        else:
            self.door_type_combo.setCurrentIndex(0)

        self.update_visibility()
        self.update_code()

    def ensure_default_types(self):
        if not self.database or not hasattr(self.database, 'cursor'):
            return

        # Seed basic wood types
        self.database.cursor.execute("SELECT COUNT(*) FROM Wood_Types")
        count = self.database.cursor.fetchone()[0]
        if count == 0:
            for name in ["NOGAL", "CHENE", "HETRE", "FREINE"]:
                wood = WoodTypeClass(0, self.database)
                wood.set_value('name', name)
                wood.save_to_database()

        # Seed door types if absent
        self.database.cursor.execute("SELECT COUNT(*) FROM Door_Types")
        count = self.database.cursor.fetchone()[0]
        if count == 0:
            for serial in range(1, 17):
                door = DoorTypeClass(0, self.database)
                door.set_value('name', f"Door Type {serial:03d}")
                door.set_value('serial', serial)
                door.save_to_database()

    def load_door_types(self):
        self.door_type_combo.blockSignals(True)
        self.door_type_combo.clear()
        self.door_types = []

        if not self.database or not hasattr(self.database, 'cursor'):
            self.door_type_combo.blockSignals(False)
            return

        self.database.cursor.execute("SELECT ID, name, serial, image_path FROM Door_Types ORDER BY serial")
        for row in self.database.cursor.fetchall():
            door_id, name, serial, image_path = row
            display_name = f"{name} ({serial:03d})" if serial else name
            icon = QIcon()
            if image_path:
                pixmap = QPixmap(image_path)
                if not pixmap.isNull():
                    icon = QIcon(pixmap.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.door_type_combo.addItem(icon, display_name, door_id)
            self.door_types.append({
                'id': door_id,
                'name': name,
                'serial': serial,
                'image_path': image_path
            })

        self.door_type_combo.blockSignals(False)
        if self.door_type_combo.count() == 0:
            self.door_type_combo.addItem("No door types available", 0)

    def load_wood_types(self):
        self.wood_type_combo.blockSignals(True)
        self.wood_type_combo.clear()

        if not self.database or not hasattr(self.database, 'cursor'):
            self.wood_type_combo.blockSignals(False)
            return

        self.database.cursor.execute("SELECT ID, name FROM Wood_Types ORDER BY name")
        for row in self.database.cursor.fetchall():
            wood_id, name = row
            self.wood_type_combo.addItem(name, wood_id)

        self.wood_type_combo.blockSignals(False)
        if self.wood_type_combo.count() == 0:
            self.wood_type_combo.addItem("No wood types available", 0)

    def get_current_door_type(self):
        current_id = self.door_type_combo.currentData() or 0
        return next((d for d in self.door_types if d['id'] == current_id), None)

    def on_service_type_changed(self):
        self.update_visibility()
        self.update_code()

    def on_door_type_changed(self):
        current = self.get_current_door_type()
        if current and current.get('image_path'):
            self.door_type_preview.set_image_path(current['image_path'])
        else:
            self.door_type_preview.set_image_path(None)
        self.update_code()

    def on_wood_type_changed(self):
        self.update_code()

    def update_visibility(self):
        is_door_service = self.door_radio.isChecked()
        for i in range(self.form_layout.rowCount()):
            label = self.form_layout.itemAt(i, QFormLayout.LabelRole)
            field = self.form_layout.itemAt(i, QFormLayout.FieldRole)
            if label and field:
                widget = field.widget() if hasattr(field, 'widget') else None
                if widget in [self.door_type_combo, self.add_door_type_btn, self.door_type_preview,
                              self.wood_type_row, self.length_spin, self.width_spin,
                              self.thickness_spin, self.unit_combo, self.color_edit]:
                    if widget:
                        widget.setVisible(is_door_service)
                    if label.widget():
                        label.widget().setVisible(is_door_service)

        self.code_edit.setReadOnly(is_door_service)

    def update_code(self):
        if self.door_radio.isChecked():
            wood_type = self.wood_type_combo.currentText() or ''
            door_type = self.get_current_door_type()
            serial = door_type.get('serial') if door_type else None
            code = self.service.generate_door_code(wood_type, serial)
            self.code_edit.setText(code)
        else:
            self.code_edit.setText(self.code_edit.text())

    def manage_door_types(self):
        previous_id = self.door_type_combo.currentData() or 0
        dialog = DoorTypeManagementDialog(self.database, self)
        dialog.exec()
        self.load_door_types()
        if previous_id and self.door_type_combo.findData(previous_id) >= 0:
            self.door_type_combo.setCurrentIndex(self.door_type_combo.findData(previous_id))
        else:
            self.door_type_combo.setCurrentIndex(0)
        self.update_code()

    def manage_wood_types(self):
        previous_wood = self.wood_type_combo.currentText()
        dialog = WoodTypeManagementDialog(self.database, self)
        dialog.exec()
        self.load_wood_types()
        if previous_wood and self.wood_type_combo.findText(previous_wood) >= 0:
            self.wood_type_combo.setCurrentIndex(self.wood_type_combo.findText(previous_wood))
        else:
            self.wood_type_combo.setCurrentIndex(0)
        self.update_code()

    def validate_data(self):
        errors = []
        if not self.code_edit.text().strip():
            errors.append("Code is required")
        if not self.name_edit.text().strip():
            errors.append("Service Name is required")
        if self.door_radio.isChecked():
            if not self.get_current_door_type():
                errors.append("Door Type is required")
            if not self.wood_type_combo.currentText().strip():
                errors.append("Wood Type is required")

        return errors

    def save_changes(self):
        errors = self.validate_data()
        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return

        is_door = self.door_radio.isChecked()
        self.service.set_value('service_type', 'Door Service' if is_door else 'Custom Service')
        self.service.set_value('service_code', self.code_edit.text().strip())
        self.service.set_value('name', self.name_edit.text().strip())
        self.service.set_value('description', self.description_edit.toPlainText().strip())

        if is_door:
            current = self.get_current_door_type() or {}
            self.service.set_value('door_type_id', current.get('id', 0))
            self.service.set_value('door_type_name', current.get('name', ''))
            self.service.set_value('door_type_serial', current.get('serial', 0))
            self.service.set_value('door_type_image_path', current.get('image_path', None))
            self.service.set_value('wood_type', self.wood_type_combo.currentText().strip())
            self.service.set_value('length', self.length_spin.value())
            self.service.set_value('width', self.width_spin.value())
            self.service.set_value('thickness', self.thickness_spin.value())
            self.service.set_value('unit', self.unit_combo.currentText())
            self.service.set_value('color', self.color_edit.text().strip())
        else:
            self.service.set_value('door_type_id', 0)
            self.service.set_value('door_type_name', '')
            self.service.set_value('door_type_serial', 0)
            self.service.set_value('door_type_image_path', None)
            self.service.set_value('wood_type', '')
            self.service.set_value('length', 0.0)
            self.service.set_value('width', 0.0)
            self.service.set_value('thickness', 0.0)
            self.service.set_value('unit', 'cm')
            self.service.set_value('color', '')

        if not self.service.save_to_database():
            QMessageBox.critical(self, "Error", "Failed to save service to database")
            return

        self.accept()

    def get_service_data(self):
        return self.service
