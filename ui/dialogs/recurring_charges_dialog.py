"""
Recurring Charges Dialog - Manage recurring charge templates and due charges
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QMessageBox, QHeaderView, QAbstractItemView, QLabel, QWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from ui.widgets.themed_widgets import BlueButton, GreenButton, RedButton


class RecurringChargesDialog(QDialog):
    """Dialog for managing recurring charge templates and due charges"""
    
    def __init__(self, database, parent=None):
        super().__init__(parent)
        self.database = database
        
        self.setWindowTitle("Recurring Charges Management")
        self.resize(1000, 700)
        
        self._setup_ui()
        self._load_templates()
        self._load_due_charges()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Templates section
        templates_label = QLabel("Recurring Charge Templates")
        templates_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(templates_label)
        
        # Templates table
        self.templates_table = QTableWidget()
        self.templates_table.setColumnCount(8)
        self.templates_table.setHorizontalHeaderLabels([
            "Name", "Category", "Amount", "Frequency", "Next Due", 
            "Payment Method", "Enabled", "Actions"
        ])
        self.templates_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.templates_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.templates_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.templates_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.templates_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.templates_table)
        
        # Template buttons
        template_btns = QHBoxLayout()
        self.add_template_btn = BlueButton("Add Template")
        self.add_template_btn.clicked.connect(self.add_template)
        template_btns.addWidget(self.add_template_btn)
        
        self.edit_template_btn = BlueButton("Edit Template")
        self.edit_template_btn.clicked.connect(self.edit_template)
        template_btns.addWidget(self.edit_template_btn)
        
        self.delete_template_btn = RedButton("Delete Template")
        self.delete_template_btn.clicked.connect(self.delete_template)
        template_btns.addWidget(self.delete_template_btn)
        
        template_btns.addStretch()
        layout.addLayout(template_btns)
        
        # Due charges section
        due_label = QLabel("Due Recurring Charges")
        due_label.setStyleSheet("font-size: 16px; font-weight: bold; margin-top: 10px;")
        layout.addWidget(due_label)
        
        self.due_table = QTableWidget()
        self.due_table.setColumnCount(7)
        self.due_table.setHorizontalHeaderLabels([
            "Name", "Category", "Amount", "Frequency", "Due Date", 
            "Payment Method", "Actions"
        ])
        self.due_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.due_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.due_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.due_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.due_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.due_table)
        
        # Due charges buttons
        due_btns = QHBoxLayout()
        self.confirm_btn = GreenButton("Confirm Selected")
        self.confirm_btn.clicked.connect(self.confirm_selected)
        due_btns.addWidget(self.confirm_btn)
        
        self.confirm_all_btn = GreenButton("Confirm All Due")
        self.confirm_all_btn.clicked.connect(self.confirm_all_due)
        due_btns.addWidget(self.confirm_all_btn)
        
        due_btns.addStretch()
        layout.addLayout(due_btns)
        
        # Close button
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_layout.addWidget(close_btn)
        layout.addLayout(close_layout)
    
    def _load_templates(self):
        """Load recurring charge templates"""
        try:
            templates = self.database.get_recurring_templates()
            
            self.templates_table.setRowCount(0)
            for template in templates:
                row = self.templates_table.rowCount()
                self.templates_table.insertRow(row)
                
                self.templates_table.setItem(row, 0, QTableWidgetItem(template.get("name", "")))
                
                cat_name = template.get("category_name", "")
                self.templates_table.setItem(row, 1, QTableWidgetItem(cat_name))
                
                self.templates_table.setItem(row, 2, QTableWidgetItem(f"{float(template.get('default_amount', 0)):,.2f} MAD"))
                self.templates_table.setItem(row, 3, QTableWidgetItem(template.get("frequency", "").title()))
                self.templates_table.setItem(row, 4, QTableWidgetItem(template.get("next_due_date", "")))
                payment = template.get("payment_method", "")
                self.templates_table.setItem(
                    row, 5, QTableWidgetItem("Bank Transfer" if payment == "Bank" else payment)
                )
                
                enabled = template.get("enabled", False)
                enabled_item = QTableWidgetItem("Yes" if enabled else "No")
                enabled_item.setForeground(
                    QColor("#4CAF50") if enabled else QColor("#f44336")
                )
                self.templates_table.setItem(row, 6, enabled_item)
                
                # Actions column
                actions_widget = QWidget()
                actions_layout = QHBoxLayout(actions_widget)
                actions_layout.setContentsMargins(2, 2, 2, 2)
                
                edit_btn = QPushButton("Edit")
                edit_btn.clicked.connect(lambda _, t=template: self.edit_template_direct(t))
                actions_layout.addWidget(edit_btn)
                
                delete_btn = QPushButton("Delete")
                delete_btn.setStyleSheet("color: red;")
                delete_btn.clicked.connect(lambda _, tid=template["id"]: self.delete_template_direct(tid))
                actions_layout.addWidget(delete_btn)
                
                self.templates_table.setCellWidget(row, 7, actions_widget)
                
                # Store full template data for direct access
                self.templates_table.item(row, 0).setData(Qt.UserRole, template)
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load templates: {str(e)}")
    
    def _load_due_charges(self):
        """Load due recurring charges"""
        try:
            from datetime import date
            today = date.today().strftime("%Y-%m-%d")
            due_charges = self.database.get_due_recurring_charges(today)
            
            self.due_table.setRowCount(0)
            for charge in due_charges:
                row = self.due_table.rowCount()
                self.due_table.insertRow(row)
                
                self.due_table.setItem(row, 0, QTableWidgetItem(charge.get("name", "")))
                
                cat_name = charge.get("category_name", "")
                self.due_table.setItem(row, 1, QTableWidgetItem(cat_name))
                
                self.due_table.setItem(row, 2, QTableWidgetItem(f"{float(charge.get('default_amount', 0)):,.2f} MAD"))
                self.due_table.setItem(row, 3, QTableWidgetItem(charge.get("frequency", "").title()))
                self.due_table.setItem(row, 4, QTableWidgetItem(charge.get("next_due_date", "")))
                payment = charge.get("payment_method", "")
                self.due_table.setItem(
                    row, 5, QTableWidgetItem("Bank Transfer" if payment == "Bank" else payment)
                )
                
                # Confirm button - store full charge data
                confirm_btn = QPushButton("Confirm")
                confirm_btn.clicked.connect(lambda _, c=charge: self.confirm_charge_direct(c))
                self.due_table.setCellWidget(row, 6, confirm_btn)
                self.due_table.item(row, 0).setData(Qt.UserRole, charge)
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load due charges: {str(e)}")
    
    def add_template(self):
        """Add a new recurring template"""
        from ui.dialogs.charge_recurring_template_dialog import RecurringTemplateDialog
        dialog = RecurringTemplateDialog(None, self.database, self)
        if dialog.exec():
            self._load_templates()
            self._load_due_charges()
    
    def edit_template(self):
        """Edit selected template"""
        row = self.templates_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "No Selection", "Please select a template to edit.")
            return
        
        template = self.templates_table.item(row, 0).data(Qt.UserRole)
        if template:
            self.edit_template_direct(template)
    
    def edit_template_direct(self, template):
        """Edit template from direct reference"""
        from ui.dialogs.charge_recurring_template_dialog import RecurringTemplateDialog
        dialog = RecurringTemplateDialog(template["id"], self.database, self)
        if dialog.exec():
            self._load_templates()
            self._load_due_charges()
    
    def delete_template(self):
        """Delete selected template"""
        row = self.templates_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "No Selection", "Please select a template to delete.")
            return
        
        template = self.templates_table.item(row, 0).data(Qt.UserRole)
        if template:
            self.delete_template_direct(template["id"])
    
    def delete_template_direct(self, template_id):
        reply = QMessageBox.question(
            self, "Delete Template",
            "Are you sure you want to delete this recurring template? "
            "This will not delete already confirmed charges.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.database.delete_recurring_template(template_id)
                self._load_templates()
                self._load_due_charges()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete template: {str(e)}")
    
    def confirm_selected(self):
        """Confirm selected due charge"""
        row = self.due_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "No Selection", "Please select a charge to confirm.")
            return
        charge = self.due_table.item(row, 0).data(Qt.UserRole)
        if charge:
            self.confirm_charge_direct(charge)
    
    def confirm_charge_direct(self, charge):
        """Confirm a single recurring charge"""
        try:
            result = self.database.confirm_recurring_charge(charge["id"])
            QMessageBox.information(
                self, "Success", 
                f"Charge confirmed! Created charge ID: {result['charge_id']}\n"
                f"Next due date for this template: {result['next_due_date']}"
            )
            self._load_templates()
            self._load_due_charges()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to confirm charge: {str(e)}")
    
    def confirm_all_due(self):
        """Confirm all due charges"""
        if self.due_table.rowCount() == 0:
            QMessageBox.information(self, "Nothing Due", "No recurring charges are due.")
            return
        
        reply = QMessageBox.question(
            self, "Confirm All",
            f"Confirm all {self.due_table.rowCount()} due charges?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        
        confirmed = 0
        errors = []
        for row in range(self.due_table.rowCount()):
            charge_data = self.due_table.item(row, 0).data(Qt.UserRole)
            if charge_data:
                try:
                    self.database.confirm_recurring_charge(charge_data["id"])
                    confirmed += 1
                except Exception as e:
                    errors.append(f"{charge_data.get('name', 'Unknown')}: {str(e)}")
        
        msg = f"Confirmed {confirmed} charges."
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors)
        QMessageBox.information(self, "Done", msg)
        self._load_templates()
        self._load_due_charges()
