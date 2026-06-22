"""
Service Dialog - simple product-style editor for services.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QTextEdit, QListWidget, QInputDialog, QMessageBox
)

from classes.service_class import ServiceClass
from ui.widgets.themed_widgets import GreenButton, RedButton, BlueButton


class ServiceEditDialog(QDialog):
    """Dialog for creating or editing services."""

    def __init__(self, service_id=None, database=None, parent=None):
        super().__init__(parent)
        self.service_id = service_id
        self.database = database

        if service_id:
            self.service = ServiceClass(service_id, database)
            self.service.load_database_data()
            window_title = f"Edit Service - {self.service.get_value('name') or service_id}"
        else:
            self.service = ServiceClass(0, database)
            window_title = "New Service"

        self.setWindowTitle(window_title)
        self.setModal(True)
        self.setMinimumSize(460, 420)
        self.setup_ui()
        self.load_data()
        self.apply_theme()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        form_layout = QFormLayout()

        self.name_edit = QLineEdit()
        form_layout.addRow(QLabel("Service Name *:"), self.name_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setFixedHeight(120)
        form_layout.addRow(QLabel("Description:"), self.description_edit)

        keywords_layout = QVBoxLayout()
        self.keywords_list = QListWidget()
        self.keywords_list.setMinimumHeight(100)
        keywords_layout.addWidget(self.keywords_list)

        keyword_buttons = QHBoxLayout()
        self.add_keyword_btn = BlueButton("Add Keyword")
        self.add_keyword_btn.clicked.connect(self.add_keyword)
        keyword_buttons.addWidget(self.add_keyword_btn)

        self.remove_keyword_btn = RedButton("Remove Keyword")
        self.remove_keyword_btn.clicked.connect(self.remove_selected_keyword)
        keyword_buttons.addWidget(self.remove_keyword_btn)
        keyword_buttons.addStretch()
        keywords_layout.addLayout(keyword_buttons)

        form_layout.addRow(QLabel("Sales Keywords:"), keywords_layout)
        layout.addLayout(form_layout)

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
        self.name_edit.setText(self.service.get_value('name') or '')
        self.description_edit.setPlainText(self.service.get_value('description') or '')

        keywords = self._parse_keywords(self.service.get_value('keywords') or '')
        for keyword in keywords:
            self.keywords_list.addItem(keyword)

    def add_keyword(self):
        keyword, ok = QInputDialog.getText(self, "Add Keyword", "Keyword:")
        if not ok:
            return

        keyword = keyword.strip()
        if not keyword:
            return

        existing = {self.keywords_list.item(i).text().lower() for i in range(self.keywords_list.count())}
        if keyword.lower() in existing:
            QMessageBox.information(self, "Keyword Exists", "This keyword is already in the list.")
            return

        self.keywords_list.addItem(keyword)

    def remove_selected_keyword(self):
        row = self.keywords_list.currentRow()
        if row >= 0:
            self.keywords_list.takeItem(row)

    def validate_data(self):
        errors = []
        if not self.name_edit.text().strip():
            errors.append("Service Name is required")
        return errors

    def save_changes(self):
        errors = self.validate_data()
        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return

        name = self.name_edit.text().strip()
        keywords = self._keywords_to_text()

        self.service.set_value('service_type', 'Custom Service')
        self.service.set_value('name', name)
        self.service.set_value('description', self.description_edit.toPlainText().strip())
        self.service.set_value('keywords', keywords)

        if not self.service.save_to_database():
            QMessageBox.critical(self, "Error", "Failed to save service to database")
            return

        self.accept()

    def _keywords_to_text(self):
        return ", ".join(
            self.keywords_list.item(i).text().strip()
            for i in range(self.keywords_list.count())
            if self.keywords_list.item(i).text().strip()
        )

    @staticmethod
    def _parse_keywords(value):
        return [
            part.strip()
            for part in str(value).replace("\n", ",").split(",")
            if part.strip()
        ]

    def get_service_data(self):
        return self.service

    def apply_theme(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
            QLineEdit, QTextEdit, QListWidget {
                background-color: #2D2D2D;
                color: #ffffff;
                border: 1px solid #555555;
                padding: 5px;
            }
        """)
