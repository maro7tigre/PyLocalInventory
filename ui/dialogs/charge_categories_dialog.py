"""
Charge Categories Dialog - Manage charge categories
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QMessageBox, QHeaderView, QAbstractItemView, QLineEdit,
    QCheckBox, QWidget, QFormLayout
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from ui.widgets.themed_widgets import BlueButton, RedButton


class ChargeCategoriesDialog(QDialog):
    """Dialog for managing charge categories"""
    
    def __init__(self, database, parent=None):
        super().__init__(parent)
        self.database = database
        
        self.setWindowTitle("Charge Categories Management")
        self.resize(600, 500)
        
        self._setup_ui()
        self._load_categories()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Categories table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            "Name", "Active", "Charges Count", "Actions"
        ])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.add_btn = BlueButton("Add Category")
        self.add_btn.clicked.connect(self.add_category)
        btn_layout.addWidget(self.add_btn)
        
        self.edit_btn = BlueButton("Edit")
        self.edit_btn.clicked.connect(self.edit_category)
        btn_layout.addWidget(self.edit_btn)
        
        self.delete_btn = RedButton("Delete")
        self.delete_btn.clicked.connect(self.delete_category)
        btn_layout.addWidget(self.delete_btn)
        
        btn_layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
    
    def _load_categories(self):
        """Load all categories using backend API"""
        try:
            categories = self.database.get_charge_categories()
            
            self.table.setRowCount(0)
            for cat in categories:
                row = self.table.rowCount()
                self.table.insertRow(row)
                
                self.table.setItem(row, 0, QTableWidgetItem(cat["name"]))
                
                active_item = QTableWidgetItem("Yes" if cat["active"] else "No")
                active_item.setForeground(
                    QColor("#4CAF50") if cat["active"] else QColor("#f44336")
                )
                self.table.setItem(row, 1, active_item)
                
                usage = int(cat.get("charges_count", 0)) + int(
                    cat.get("templates_count", 0)
                )
                self.table.setItem(row, 2, QTableWidgetItem(str(usage)))
                
                # Actions
                actions_widget = QWidget()
                actions_layout = QHBoxLayout(actions_widget)
                actions_layout.setContentsMargins(2, 2, 2, 2)
                
                edit_btn = QPushButton("Edit")
                edit_btn.clicked.connect(lambda _, cid=cat["id"]: self.edit_category_direct(cid))
                actions_layout.addWidget(edit_btn)
                
                toggle_btn = QPushButton("Disable" if cat["active"] else "Enable")
                toggle_btn.clicked.connect(lambda _, cid=cat["id"], act=cat["active"]: 
                                           self.toggle_category(cid, not act))
                actions_layout.addWidget(toggle_btn)
                
                delete_btn = QPushButton("Delete")
                delete_btn.setStyleSheet("color: red;")
                delete_btn.clicked.connect(lambda _, cid=cat["id"]: self.delete_category_direct(cid))
                actions_layout.addWidget(delete_btn)
                
                self.table.setCellWidget(row, 3, actions_widget)
                
                # Store ID
                self.table.item(row, 0).setData(Qt.UserRole, cat["id"])
                
        except Exception as e:
            if hasattr(self.database, 'conn') and self.database.conn:
                try:
                    self.database.conn.rollback()
                except:
                    pass
            QMessageBox.critical(self, "Error", f"Failed to load categories: {str(e)}")
    
    def add_category(self):
        """Add a new category"""
        dialog = CategoryEditDialog(None, self.database, self)
        if dialog.exec():
            self._load_categories()
    
    def edit_category(self):
        """Edit selected category"""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "No Selection", "Please select a category to edit.")
            return
        cat_id = self.table.item(row, 0).data(Qt.UserRole)
        if cat_id:
            self.edit_category_direct(cat_id)
    
    def edit_category_direct(self, cat_id):
        """Edit category by ID"""
        dialog = CategoryEditDialog(cat_id, self.database, self)
        if dialog.exec():
            self._load_categories()
    
    def delete_category(self):
        """Delete selected category"""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "No Selection", "Please select a category to delete.")
            return
        
        cat_id = self.table.item(row, 0).data(Qt.UserRole)
        if cat_id:
            self.delete_category_direct(cat_id)
    
    def delete_category_direct(self, cat_id):
        """Delete category by ID"""
        reply = QMessageBox.question(
            self, "Delete Category",
            "Are you sure you want to delete this category? "
            "Categories used by charges or recurring templates cannot be deleted.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.database.delete_charge_category(cat_id)
                self._load_categories()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete category: {str(e)}")
    
    def toggle_category(self, cat_id, active):
        """Toggle category active status"""
        try:
            self.database.update_charge_category(cat_id, active=active)
            self._load_categories()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to toggle category: {str(e)}")


class CategoryEditDialog(QDialog):
    """Dialog for adding/editing a charge category"""
    
    def __init__(self, category_id=None, database=None, parent=None):
        super().__init__(parent)
        self.category_id = category_id
        self.database = database
        
        self.setWindowTitle("Edit Category" if category_id else "New Category")
        self.resize(400, 200)
        
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Category name")
        form.addRow("Name *", self.name_edit)
        
        self.active_check = QCheckBox("Active")
        self.active_check.setChecked(True)
        form.addRow(self.active_check)
        
        layout.addLayout(form)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save_category)
        btn_layout.addWidget(self.save_btn)
        
        layout.addLayout(btn_layout)
        
        if category_id:
            self._load_category(category_id)
    
    def _load_category(self, cat_id):
        try:
            categories = self.database.get_charge_categories()
            for cat in categories:
                if cat["id"] == cat_id:
                    self.name_edit.setText(cat["name"] or "")
                    self.active_check.setChecked(bool(cat["active"]))
                    break
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load category: {str(e)}")
    
    def save_category(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation Error", "Name is required")
            return
        
        active = self.active_check.isChecked()
        
        try:
            if self.category_id:
                self.database.update_charge_category(self.category_id, name, active)
            else:
                self.database.add_charge_category(name)
            QMessageBox.information(self, "Success", "Category saved successfully")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save category: {str(e)}")
