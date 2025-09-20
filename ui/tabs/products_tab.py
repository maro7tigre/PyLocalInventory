"""
Enhanced Products Tab - With editable table, autocomplete, and proper selection styling
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QTableWidget, QTableWidgetItem, QHeaderView, 
                               QMessageBox, QPushButton, QAbstractItemView,
                               QStyledItemDelegate, QLineEdit)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt
from ui.widgets.themed_widgets import RedButton, BlueButton, GreenButton
from ui.widgets.preview_widget import PreviewWidget
from ui.widgets.autocomplete_widgets import AutoCompleteLineEdit


class ProductsTableDelegate(QStyledItemDelegate):
    """Custom delegate for products table with autocomplete and read-only cells"""
    
    def __init__(self, products_tab, parent=None):
        super().__init__(parent)
        self.products_tab = products_tab
    
    def createEditor(self, parent, option, index):
        """Create appropriate editor based on column and permissions"""
        col = index.column()
        column_key = self.products_tab.table_columns[col]
        
        # Check if this column is editable
        if not self.products_tab.is_column_editable(column_key):
            return None  # No editor for read-only cells
        
        # Check if the item itself is editable (for widget cells)
        item = self.products_tab.table.item(index.row(), index.column())
        if item and not (item.flags() & Qt.ItemIsEditable):
            return None  # No editor for non-editable items
        
        # Don't create editors for widget cells (like images)
        widget = self.products_tab.table.cellWidget(index.row(), index.column())
        if widget is not None:
            return None  # No editor for widget cells
        
        # Get parameter info for autocomplete
        param_info = self.products_tab.get_column_param_info(column_key)
        options = param_info.get('options', [])
        
        if options:
            # Use autocomplete for columns with options
            editor = AutoCompleteLineEdit(parent, options)
        else:
            # Regular line edit for other editable columns
            editor = QLineEdit(parent)
        
        return editor
    
    def setEditorData(self, editor, index):
        """Set current cell value in editor"""
        value = index.model().data(index, Qt.EditRole)
        if isinstance(editor, (QLineEdit, AutoCompleteLineEdit)):
            editor.setText(str(value) if value else "")
    
    def setModelData(self, editor, model, index):
        """Set editor value back to model and update database"""
        if isinstance(editor, (QLineEdit, AutoCompleteLineEdit)):
            new_value = editor.text()
            old_value = model.data(index, Qt.EditRole)
            
            if new_value != old_value:
                # Update the model
                model.setData(index, new_value, Qt.EditRole)
                
                # Update the database
                self.products_tab.update_cell_in_database(index.row(), index.column(), new_value)


class ProductsTab(QWidget):
    """Enhanced Products tab with editable table"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(parent)
        self.database = database
        self.parent_widget = parent
        
        # Get product class info
        from classes.product_class import ProductClass
        temp_product = ProductClass(0, database)
        self.table_columns = temp_product.get_visible_parameters("table")  # This already returns a list
        self.table_permissions = temp_product.available_parameters["table"]
        self.parameter_definitions = temp_product.parameters
        
        self.setup_ui()
        self.refresh_table()
    
    def setup_ui(self):
        """Setup products tab interface"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Header with title and buttons
        header_layout = QHBoxLayout()
        
        title = QLabel("Products Management")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        # Action buttons
        self.add_btn = BlueButton("Add Product")
        self.add_btn.clicked.connect(self.add_product)
        header_layout.addWidget(self.add_btn)
        
        self.edit_btn = BlueButton("Edit Product")
        self.edit_btn.clicked.connect(self.edit_product)
        header_layout.addWidget(self.edit_btn)
        
        self.delete_btn = RedButton("Delete Product")
        self.delete_btn.clicked.connect(self.delete_product)
        header_layout.addWidget(self.delete_btn)
        
        self.refresh_btn = GreenButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_table)
        header_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(header_layout)
        
        # Table setup
        self.table = QTableWidget()
        self.setup_table()
        layout.addWidget(self.table)
        
        # Apply theme
        self.apply_theme()
    
    def setup_table(self):
        """Setup table columns and properties"""
        # Set column count and headers
        self.table.setColumnCount(len(self.table_columns))
        
        # Create display headers
        headers = []
        for column_key in self.table_columns:
            if column_key in self.parameter_definitions:
                from classes.product_class import ProductClass
                temp_obj = ProductClass(0, self.database)
                display_name = temp_obj.get_display_name(column_key)
                headers.append(display_name)
            else:
                headers.append(column_key)
        
        self.table.setHorizontalHeaderLabels(headers)
        
        # Table properties
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        
        # Set row height to accommodate images
        self.table.verticalHeader().setDefaultSectionSize(70)
        
        # Set custom delegate for editing
        self.delegate = ProductsTableDelegate(self)
        self.table.setItemDelegate(self.delegate)
        
        # Set specific column widths for image columns
        for i, column_key in enumerate(self.table_columns):
            if column_key == 'preview_image':
                self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.Fixed)
                self.table.setColumnWidth(i, 80)  # Fixed width for image column
    
    def is_column_editable(self, column_key):
        """Check if column is editable (has 'w' permission)"""
        permission = self.table_permissions.get(column_key, '')
        editable = 'w' in permission.lower()
        print(f"Column {column_key}: permission='{permission}', editable={editable}")  # Debug print
        return editable
    
    def get_column_param_info(self, column_key):
        """Get parameter info for column"""
        return self.parameter_definitions.get(column_key, {})
    
    def refresh_table(self):
        """Refresh table data from database"""
        if not self.database:
            QMessageBox.warning(self, "Error", "No database connection")
            return
        
        try:
            # Get products from database
            products = self.database.get_items("Products")
            self.table.setRowCount(len(products))
            
            print(f"Loading {len(products)} products")
            
            for row, product_data in enumerate(products):
                # Create ProductClass instance to get calculated values
                try:
                    from classes.product_class import ProductClass
                    product = ProductClass(product_data.get('ID', 0), self.database)
                    
                    # Load data from database
                    for key, value in product_data.items():
                        if key in product.parameters and not product.is_parameter_calculated(key):
                            # Map database field names to parameter names
                            param_key = key
                            if key == 'ID':
                                param_key = 'id'
                            elif key == 'preview_image':
                                param_key = 'preview_image'
                            elif key == 'unit_price':
                                param_key = 'unit_price'
                            elif key == 'sale_price':
                                param_key = 'sale_price'
                            
                            try:
                                if param_key in product.parameters:
                                    product.set_value(param_key, value)
                            except (KeyError, ValueError):
                                pass  # Skip invalid parameters
                    
                    # Set table data
                    for col, column_key in enumerate(self.table_columns):
                        self.set_table_cell(row, col, column_key, product)
                
                except Exception as e:
                    print(f"Error processing product row {row}: {e}")
                    # Fallback: show raw data
                    for col, column_key in enumerate(self.table_columns):
                        value = product_data.get(column_key, "")
                        if column_key == 'id':
                            value = product_data.get('ID', "")
                        item = QTableWidgetItem(str(value))
                        item.setData(Qt.UserRole, product_data.get('ID', 0))
                        self.table.setItem(row, col, item)
        
        except Exception as e:
            print(f"Error refreshing products table: {e}")
            QMessageBox.critical(self, "Error", f"Failed to refresh products: {e}")
    
    def set_table_cell(self, row, col, column_key, product):
        """Set table cell value based on parameter type"""
        try:
            value = product.get_value(column_key)
            param_info = product.parameters.get(column_key, {})
            param_type = param_info.get('type', 'string')
            
            if param_type == 'image':
                # Create preview widget for image with fixed size
                preview_widget = PreviewWidget(60, "product")  # Fixed size 60x60
                if value:
                    preview_widget.set_image_path(value)
                
                # Create a container widget to center the preview
                container = QWidget()
                container_layout = QHBoxLayout(container)
                container_layout.setContentsMargins(0, 0, 0, 0)
                container_layout.addStretch()
                container_layout.addWidget(preview_widget)
                container_layout.addStretch()
                
                self.table.setCellWidget(row, col, container)
            
            elif param_type == 'float':
                # Format float values with unit if available
                unit = param_info.get('unit', '')
                if value is not None:
                    formatted_value = f"{float(value):.2f} {unit}".strip()
                else:
                    formatted_value = f"0.00 {unit}".strip()
                
                item = QTableWidgetItem(formatted_value)
                item.setData(Qt.UserRole, value)  # Store raw value
                item.setData(Qt.UserRole + 1, product.id)  # Store product ID
                
                # Make read-only cells non-editable
                if not self.is_column_editable(column_key):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                
                self.table.setItem(row, col, item)
            
            elif param_type == 'int':
                # Format integer values
                formatted_value = str(int(value)) if value is not None else "0"
                item = QTableWidgetItem(formatted_value)
                item.setData(Qt.UserRole, value)  # Store raw value
                item.setData(Qt.UserRole + 1, product.id)  # Store product ID
                
                # Make read-only cells non-editable
                if not self.is_column_editable(column_key):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                
                self.table.setItem(row, col, item)
            
            else:
                # String and other types
                formatted_value = str(value) if value is not None else ""
                item = QTableWidgetItem(formatted_value)
                item.setData(Qt.UserRole, value)  # Store raw value
                item.setData(Qt.UserRole + 1, product.id)  # Store product ID
                
                # Make read-only cells non-editable
                if not self.is_column_editable(column_key):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                
                self.table.setItem(row, col, item)
        
        except Exception as e:
            print(f"Error setting cell ({row}, {col}): {e}")
            item = QTableWidgetItem("Error")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, col, item)
    
    def update_cell_in_database(self, row, col, new_value):
        """Update database when cell is edited"""
        try:
            # Get product ID
            item = self.table.item(row, col)
            if not item:
                return
            
            product_id = item.data(Qt.UserRole + 1)
            if not product_id:
                return
            
            column_key = self.table_columns[col]
            
            # Update database
            data = {column_key: new_value}
            if self.database.update_item(product_id, data, "Products"):
                print(f"Updated {column_key} to '{new_value}' for product {product_id}")
            else:
                QMessageBox.warning(self, "Error", f"Failed to update {column_key}")
                # Revert the change
                self.refresh_table()
        
        except Exception as e:
            print(f"Error updating cell in database: {e}")
            QMessageBox.critical(self, "Error", f"Database update failed: {e}")
            self.refresh_table()
    
    def get_selected_product_id(self):
        """Get ID of selected product"""
        row = self.table.currentRow()
        if row == -1:
            return None
        
        # Get ID from any cell in the row that has it stored
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item:
                product_id = item.data(Qt.UserRole + 1)
                if product_id:
                    return int(product_id)
        
        return None
    
    def add_product(self):
        """Add new product"""
        try:
            from ui.dialogs.edit_dialogs.product_dialog import ProductEditDialog
            
            dialog = ProductEditDialog(None, self.database, self.parent_widget)
            if dialog.exec():
                self.refresh_table()
                QMessageBox.information(self, "Success", "Product added successfully!")
        
        except ImportError as e:
            QMessageBox.warning(self, "Error", f"Could not import ProductEditDialog: {e}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add product: {e}")
    
    def edit_product(self):
        """Edit selected product"""
        product_id = self.get_selected_product_id()
        if product_id is None:
            QMessageBox.warning(self, "Error", "Please select a product to edit")
            return
        
        try:
            from ui.dialogs.edit_dialogs.product_dialog import ProductEditDialog
            
            dialog = ProductEditDialog(product_id, self.database, self.parent_widget)
            if dialog.exec():
                self.refresh_table()
                QMessageBox.information(self, "Success", "Product updated successfully!")
        
        except ImportError as e:
            QMessageBox.warning(self, "Error", f"Could not import ProductEditDialog: {e}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to edit product: {e}")
    
    def delete_product(self):
        """Delete selected product"""
        product_id = self.get_selected_product_id()
        if product_id is None:
            QMessageBox.warning(self, "Error", "Please select a product to delete")
            return
        
        # Get product name for confirmation
        row = self.table.currentRow()
        name_col = None
        
        # Find name column
        for i, column_key in enumerate(self.table_columns):
            if column_key == 'name':
                name_col = i
                break
        
        product_name = f"ID {product_id}"
        if name_col is not None:
            name_item = self.table.item(row, name_col)
            if name_item:
                product_name = name_item.text() or f"ID {product_id}"
        
        reply = QMessageBox.question(
            self, "Confirm Deletion", 
            f"Are you sure you want to delete '{product_name}'?\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                if self.database.delete_item(product_id, "Products"):
                    QMessageBox.information(self, "Success", f"'{product_name}' deleted successfully")
                    self.refresh_table()
                else:
                    QMessageBox.critical(self, "Error", f"Failed to delete '{product_name}'")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error deleting product: {e}")
    
    def apply_theme(self):
        """Apply dark theme styling with blue selection border"""
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
                selection-background-color: transparent;
            }
            QTableWidget::item:selected {
                background-color: #2D2D30;
                border: 2px solid #2196F3;
            }
            QTableWidget::item:focus {
                border: 2px solid #2196F3;
                background-color: #2D2D30;
            }
            QHeaderView::section {
                background-color: #252526;
                color: #CCCCCC;
                padding: 5px;
                border: none;
            }
        """)