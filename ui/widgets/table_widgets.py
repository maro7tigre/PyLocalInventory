"""
Updated Table Widget - Works with parameter system
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QTableWidget, QTableWidgetItem, QHeaderView, 
                               QMessageBox, QDialog, QAbstractItemView)
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtCore import Qt
from ui.widgets.themed_widgets import RedButton, BlueButton, GreenButton
from ui.widgets.preview_widget import PreviewWidget
from ui.widgets.parameters_widgets import ParameterWidgetFactory


class ParameterTableWidget(QWidget):
    """Universal table widget that works with any parameter-based class"""
    
    def __init__(self, object_class, database=None, dialog_class=None, parent=None):
        """
        Args:
            object_class: Class to manage (ProductClass, ClientClass, etc.)
            database: Database instance
            dialog_class: Dialog class for editing (optional)
            parent: Parent widget
        """
        super().__init__(parent)
        self.object_class = object_class
        self.database = database
        self.dialog_class = dialog_class
        self.parent_widget = parent
        
        # Create a temporary object to get parameter information
        temp_obj = object_class(0, database)
        self.section = temp_obj.section
        self.table_columns = temp_obj.get_visible_parameters("table")
        self.parameter_definitions = temp_obj.parameters
        
        self.setup_ui()
        self.apply_theme()
        self.refresh_table()
    
    def setup_ui(self):
        """Setup table interface"""
        layout = QVBoxLayout(self)
        
        # Header with title and buttons
        header_layout = QHBoxLayout()
        
        title = QLabel(f"{self.section} Management")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        # Action buttons
        self.add_btn = BlueButton("Add")
        self.add_btn.clicked.connect(self.add_item)
        header_layout.addWidget(self.add_btn)
        
        self.edit_btn = BlueButton("Edit")
        self.edit_btn.clicked.connect(self.edit_item)
        header_layout.addWidget(self.edit_btn)
        
        self.delete_btn = RedButton("Delete")
        self.delete_btn.clicked.connect(self.delete_item)
        header_layout.addWidget(self.delete_btn)
        
        self.refresh_btn = GreenButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_table)
        header_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(header_layout)
        
        # Table setup
        self.table = QTableWidget()
        self.setup_table()
        layout.addWidget(self.table)
    
    def setup_table(self):
        """Setup table columns and properties"""
        # Set column count and headers
        self.table.setColumnCount(len(self.table_columns))
        
        # Create display headers using parameter display names
        headers = []
        for param_key in self.table_columns:
            if param_key in self.parameter_definitions:
                temp_obj = self.object_class(0, self.database)
                display_name = temp_obj.get_display_name(param_key)
                headers.append(display_name)
            else:
                headers.append(param_key)
        
        self.table.setHorizontalHeaderLabels(headers)
        
        # Table properties
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        
        # Hide ID column if present
        if 'id' in self.table_columns:
            id_index = self.table_columns.index('id')
            self.table.setColumnHidden(id_index, True)
    
    def refresh_table(self):
        """Refresh table data from database"""
        if not self.database:
            return
        
        try:
            # Get all items from database
            items = self.database.get_items(self.section)
            self.table.setRowCount(len(items))
            
            for row, item in enumerate(items):
                # Create object instance to get calculated values
                item_id = item.get('ID', 0)
                obj = self.object_class(item_id, self.database)
                obj.load_database_data()
                
                for col, param_key in enumerate(self.table_columns):
                    self.set_table_cell(row, col, param_key, obj)
        
        except Exception as e:
            print(f"Error refreshing table: {e}")
            QMessageBox.warning(self, "Error", f"Failed to refresh table: {e}")
    
    def set_table_cell(self, row, col, param_key, obj):
        """Set table cell value based on parameter type"""
        try:
            value = obj.get_value(param_key)
            param_info = obj.parameters.get(param_key, {})
            param_type = param_info.get('type', 'string')
            
            if param_type == 'image':
                # Create preview widget for image
                preview_widget = PreviewWidget(50, "product")
                if value:
                    preview_widget.set_image_path(value)
                self.table.setCellWidget(row, col, preview_widget)
            
            elif param_type == 'float':
                # Format float values with unit if available
                unit = param_info.get('unit', '')
                if value is not None:
                    formatted_value = f"{float(value):.2f} {unit}".strip()
                else:
                    formatted_value = f"0.00 {unit}".strip()
                
                item = QTableWidgetItem(formatted_value)
                item.setData(Qt.UserRole, value)  # Store raw value
                self.table.setItem(row, col, item)
            
            elif param_type == 'int':
                # Format integer values
                formatted_value = str(int(value)) if value is not None else "0"
                item = QTableWidgetItem(formatted_value)
                item.setData(Qt.UserRole, value)  # Store raw value
                self.table.setItem(row, col, item)
            
            else:
                # String and other types
                formatted_value = str(value) if value is not None else ""
                item = QTableWidgetItem(formatted_value)
                item.setData(Qt.UserRole, value)  # Store raw value
                self.table.setItem(row, col, item)
        
        except Exception as e:
            print(f"Error setting cell ({row}, {col}): {e}")
            self.table.setItem(row, col, QTableWidgetItem("Error"))
    
    def get_selected_id(self):
        """Get ID of selected item"""
        row = self.table.currentRow()
        if row == -1:
            return None
        
        # Find ID column
        if 'id' not in self.table_columns:
            return None
        
        id_col = self.table_columns.index('id')
        item = self.table.item(row, id_col)
        
        if item:
            return int(item.data(Qt.UserRole) or item.text())
        
        # Fallback: try to get from first column if it's numeric
        first_item = self.table.item(row, 0)
        if first_item and first_item.text().isdigit():
            return int(first_item.text())
        
        return None
    
    def add_item(self):
        """Add new item"""
        if self.dialog_class:
            try:
                dialog = self.dialog_class(None, self.database, self.parent_widget)
                if dialog.exec() == QDialog.Accepted:
                    self.refresh_table()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to open add dialog: {e}")
        else:
            QMessageBox.information(self, "Info", f"Add {self.section[:-1]} dialog not configured")
    
    def edit_item(self):
        """Edit selected item"""
        item_id = self.get_selected_id()
        if item_id is None:
            QMessageBox.warning(self, "Error", f"Please select a {self.section[:-1].lower()} to edit")
            return
        
        if self.dialog_class:
            try:
                dialog = self.dialog_class(item_id, self.database, self.parent_widget)
                if dialog.exec() == QDialog.Accepted:
                    self.refresh_table()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to open edit dialog: {e}")
        else:
            QMessageBox.information(self, "Info", f"Edit {self.section[:-1]} dialog not configured")
    
    def delete_item(self):
        """Delete selected item"""
        item_id = self.get_selected_id()
        if item_id is None:
            QMessageBox.warning(self, "Error", f"Please select a {self.section[:-1].lower()} to delete")
            return
        
        # Get item name for confirmation
        row = self.table.currentRow()
        item_name = "item"
        
        # Try to get name from name column
        if 'name' in self.table_columns:
            name_col = self.table_columns.index('name')
            name_item = self.table.item(row, name_col)
            if name_item:
                item_name = name_item.text() or f"ID {item_id}"
        
        reply = QMessageBox.question(
            self, "Confirm Deletion", 
            f"Are you sure you want to delete '{item_name}'?\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                if self.database.delete_item(item_id, self.section):
                    QMessageBox.information(self, "Success", f"'{item_name}' deleted successfully")
                    self.refresh_table()
                else:
                    QMessageBox.critical(self, "Error", f"Failed to delete '{item_name}'")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error deleting item: {e}")
    
    def apply_theme(self):
        """Apply dark theme styling"""
        self.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #E0E0E0;
            }
            QTableWidget {
                background-color: #2D2D30;
                gridline-color: #3E3E42;
                color: #E0E0E0;
                border: 1px solid #3E3E42;
                alternate-background-color: #252526;
            }
            QTableWidget::item:selected {
                background-color: #3E3E42;
            }
            QHeaderView::section {
                background-color: #252526;
                color: #CCCCCC;
                padding: 5px;
                border: none;
            }
        """)


# Convenience wrapper for products
class ProductsTableWidget(ParameterTableWidget):
    """Specialized table widget for products"""
    
    def __init__(self, database=None, parent=None):
        from classes.product_class import ProductClass
        try:
            from ui.dialogs.edit_dialogs.product_dialog import ProductEditDialog
        except ImportError:
            # Fallback if product dialog isn't available yet
            ProductEditDialog = None
            
        super().__init__(ProductClass, database, ProductEditDialog, parent)