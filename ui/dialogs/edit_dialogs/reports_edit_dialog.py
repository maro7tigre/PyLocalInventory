"""
Reports Edit Dialog - Add or edit a department report
"""
from datetime import datetime
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QComboBox, QTextEdit, QMessageBox, QDateEdit)
from PySide6.QtCore import Qt, QDate
from ui.widgets.themed_widgets import GreenButton, RedButton

DEPARTMENTS = ["sohaib cuisine", "monime porte", "omarchapa", "abd-aziiz vernise", "zohir"]


class ReportsEditDialog(QDialog):
    """Dialog for adding or editing a department report"""

    def __init__(self, report_id=None, database=None, parent=None):
        super().__init__(parent)
        self.report_id = report_id
        self.database = database
        self.setWindowTitle("Add Report" if not report_id else "Edit Report")
        self.setModal(True)
        self.setMinimumSize(520, 430)
        self.setup_ui()
        if report_id:
            self.load_data()
        self.apply_theme()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Add Report" if not self.report_id else "Edit Report")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)

        # Department
        layout.addWidget(self._field_label("Department *"))
        self.dept_combo = QComboBox()
        self.dept_combo.addItem(
            getattr(self.database, "username", None) or "Local Admin"
        )
        self.dept_combo.setEnabled(False)
        layout.addWidget(self.dept_combo)

        # Date
        layout.addWidget(self._field_label("Date *"))
        self.date_edit = QDateEdit()
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd-MM-yyyy")
        layout.addWidget(self.date_edit)

        layout.addWidget(self._field_label("Report Type"))
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "General", "Sales", "Products", "Services", "Clients",
            "Revenue", "Profit", "Activity",
        ])
        layout.addWidget(self.type_combo)

        # Report text
        layout.addWidget(self._field_label("Report *"))
        self.report_text = QTextEdit()
        self.report_text.setPlaceholderText("Write your report here...")
        self.report_text.setMinimumHeight(160)
        layout.addWidget(self.report_text)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.save_btn = GreenButton("Save")
        self.save_btn.clicked.connect(self.save_report)
        btn_layout.addWidget(self.save_btn)
        self.cancel_btn = RedButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    def _field_label(self, text):
        label = QLabel(text)
        label.setStyleSheet("font-size: 14px; color: #cccccc;")
        return label

    def load_data(self):
        if not self.database or not self.report_id:
            return
        try:
            items = self.database.get_reports()
            for item in items:
                if item.get('ID') == self.report_id:
                    dept = item.get('department', '')
                    self.dept_combo.clear()
                    self.dept_combo.addItem(
                        item.get("created_by_username") or dept or "Legacy / Unassigned"
                    )
                    date_str = item.get('date', '')
                    if date_str:
                        for fmt in ['%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y']:
                            try:
                                d = datetime.strptime(date_str, fmt)
                                self.date_edit.setDate(QDate(d.year, d.month, d.day))
                                break
                            except ValueError:
                                pass
                    self.report_text.setPlainText(item.get('report', ''))
                    report_type = item.get("report_type") or "General"
                    type_index = self.type_combo.findText(report_type)
                    self.type_combo.setCurrentIndex(type_index if type_index >= 0 else 0)
                    break
        except Exception as e:
            print(f"Error loading report data: {e}")

    def save_report(self):
        dept = self.dept_combo.currentText().strip()
        date_val = self.date_edit.date().toString("dd-MM-yyyy")
        report_body = self.report_text.toPlainText().strip()

        if not dept:
            QMessageBox.warning(self, "Validation", "Please select a department.")
            return
        if not report_body:
            QMessageBox.warning(self, "Validation", "Please write a report.")
            return

        data = {
            'department': dept,
            'date': date_val,
            'report_type': self.type_combo.currentText(),
            'report': report_body
        }

        try:
            self.save_btn.setEnabled(False)
            self.database.save_report(self.report_id, data)
            self.accept()
        except Exception as e:
            self.save_btn.setEnabled(True)
            QMessageBox.critical(self, "Error", f"Failed to save report:\n{e}")

    def apply_theme(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #E0E0E0;
                background-color: transparent;
            }
            QComboBox, QDateEdit {
                background-color: #2D2D30;
                color: #E0E0E0;
                border: 1px solid #3E3E42;
                padding: 6px;
                border-radius: 4px;
                font-size: 14px;
            }
            QComboBox::drop-down, QDateEdit::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background-color: #2D2D30;
                color: #E0E0E0;
                selection-background-color: #2196F3;
            }
            QTextEdit {
                background-color: #2D2D30;
                color: #E0E0E0;
                border: 1px solid #3E3E42;
                padding: 8px;
                border-radius: 4px;
                font-size: 14px;
            }
            QTextEdit:focus {
                border: 2px solid #2196F3;
            }
        """)
