"""
Recurring Template Dialog - Add/Edit recurring charge template
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, 
    QDateEdit, QLineEdit, QDoubleSpinBox, QCheckBox, QTextEdit,
    QPushButton, QMessageBox
)
from PySide6.QtCore import Qt, QDate
from ui.widgets.themed_widgets import BlueButton


class RecurringTemplateDialog(QDialog):
    """Dialog for adding/editing recurring charge templates"""
    
    def __init__(self, template_id=None, database=None, parent=None):
        super().__init__(parent)
        self.template_id = template_id
        self.database = database
        
        self.setWindowTitle("Edit Recurring Template" if template_id else "New Recurring Template")
        self.resize(500, 600)
        
        self._setup_ui()
        self._load_categories()
        
        if template_id:
            self._load_template(template_id)
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        
        # Name
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g., Monthly Rent")
        form.addRow("Name *", self.name_edit)
        
        # Category
        self.category_combo = QComboBox()
        form.addRow("Category *", self.category_combo)
        
        # Default Amount
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0, 999999999.99)
        self.amount_spin.setDecimals(2)
        self.amount_spin.setSpecialValueText("")
        self.amount_spin.setSuffix(" MAD")
        form.addRow("Default Amount *", self.amount_spin)
        
        # Frequency
        self.frequency_combo = QComboBox()
        self.frequency_combo.addItems(["Monthly", "Weekly", "Yearly"])
        form.addRow("Frequency *", self.frequency_combo)
        
        # Next Due Date
        self.next_due_date = QDateEdit()
        self.next_due_date.setCalendarPopup(True)
        self.next_due_date.setDisplayFormat("yyyy-MM-dd")
        self.next_due_date.setDate(QDate.currentDate())
        form.addRow("Next Due Date *", self.next_due_date)
        
        # Payment Method
        self.payment_combo = QComboBox()
        for label, value in (
            ("Cash", "Cash"), ("Bank Transfer", "Bank"), ("Check", "Check"),
            ("Card", "Card"), ("Other", "Other"),
        ):
            self.payment_combo.addItem(label, value)
        form.addRow("Payment Method", self.payment_combo)
        
        # Reference Template
        self.reference_edit = QLineEdit()
        form.addRow("Reference Template", self.reference_edit)
        
        # Notes
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)
        form.addRow("Notes", self.notes_edit)
        
        # Enabled
        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.setChecked(True)
        form.addRow(self.enabled_check)
        
        layout.addLayout(form)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        self.save_btn = BlueButton("Save")
        self.save_btn.clicked.connect(self.save_template)
        btn_layout.addWidget(self.save_btn)
        
        layout.addLayout(btn_layout)
    
    def _load_categories(self):
        """Load charge categories into combo using backend API"""
        try:
            categories = self.database.get_charge_categories()
            self.category_combo.clear()
            self.category_combo.addItem("Select category...", 0)
            for cat in categories:
                if cat["active"]:
                    self.category_combo.addItem(cat["name"], cat["id"])
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load categories: {str(e)}")
    
    def _load_template(self, template_id):
        """Load existing template data using backend API"""
        try:
            templates = self.database.get_recurring_templates()
            template = next((t for t in templates if t["id"] == template_id), None)
            if template:
                self.name_edit.setText(template.get("name", "") or "")
                
                cat_id = template.get("category_id")
                if cat_id:
                    idx = self.category_combo.findData(cat_id)
                    if idx >= 0:
                        self.category_combo.setCurrentIndex(idx)
                
                self.amount_spin.setValue(float(template.get("default_amount", 0) or 0))
                
                freq = template.get("frequency", "monthly").lower()
                idx = self.frequency_combo.findText(freq.title(), Qt.MatchFixedString)
                if idx >= 0:
                    self.frequency_combo.setCurrentIndex(idx)
                
                next_due = template.get("next_due_date")
                if next_due:
                    self.next_due_date.setDate(QDate.fromString(next_due, "yyyy-MM-dd"))
                
                pm = template.get("payment_method", "Cash")
                idx = self.payment_combo.findData(pm)
                if idx >= 0:
                    self.payment_combo.setCurrentIndex(idx)
                
                self.reference_edit.setText(template.get("reference_template", "") or "")
                self.notes_edit.setPlainText(template.get("notes", "") or "")
                self.enabled_check.setChecked(bool(template.get("enabled", False)))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load template: {str(e)}")
    
    def save_template(self):
        """Save the recurring template"""
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation Error", "Name is required")
            return
        
        category_id = self.category_combo.currentData()
        if not category_id:
            QMessageBox.warning(self, "Validation Error", "Category is required")
            return
        
        amount = self.amount_spin.value()
        if amount <= 0:
            QMessageBox.warning(self, "Validation Error", "Amount must be greater than zero")
            return
        
        next_due = self.next_due_date.date().toString("yyyy-MM-dd")
        frequency = self.frequency_combo.currentText().lower()
        
        try:
            QDate.fromString(next_due, "yyyy-MM-dd")  # validate
        except:
            QMessageBox.warning(self, "Validation Error", "Invalid date")
            return
        
        data = {
            "name": name,
            "category_id": category_id,
            "default_amount": self.amount_spin.value(),
            "frequency": frequency,
            "next_due_date": next_due,
            "payment_method": self.payment_combo.currentData(),
            "reference_template": self.reference_edit.text().strip(),
            "notes": self.notes_edit.toPlainText().strip(),
            "enabled": self.enabled_check.isChecked(),
        }
        
        try:
            result = self.database.save_recurring_template(
                data, self.template_id
            )
            QMessageBox.information(self, "Success", "Template saved successfully")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save template: {str(e)}")
