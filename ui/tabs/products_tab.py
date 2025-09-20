"""
Simple Products Tab - Direct implementation without complex imports
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QTableWidget, QTableWidgetItem, QHeaderView, 
                               QMessageBox, QPushButton, QAbstractItemView)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt
from ui.widgets.themed_widgets import RedButton, BlueButton, GreenButton


class ProductsTab(QWidget):
    """Products tab with direct implementation"""
    
    def __init__(self, database=None, parent=None):
        super().__init__(parent)
        self.database = database
        self.parent_widget = parent
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
        # Define columns based on ProductClass parameters
        self.columns = ["ID", "name", "unit_price", "sale_price", "category", "quantity"]
        self.display_headers = ["ID", "Product Name", "Unit Price (MAD)", "Sale Price (MAD)", "Category", "Stock Quantity"]
        
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.display_headers)
        
        # Table properties
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        
        # Hide ID column
        self.table.setColumnHidden(0, True)
    
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
                            if key == 'unit_price':
                                param_key = 'unit_price'
                            elif key == 'sale_price':
                                param_key = 'sale_price'
                            
                            try:
                                product.set_value(param_key, value)
                            except (KeyError, ValueError):
                                pass  # Skip invalid parameters
                    
                    # Set table data
                    for col, column_key in enumerate(self.columns):
                        if column_key == 'quantity':
                            # Get calculated quantity
                            quantity = product.get_value('quantity')
                            item = QTableWidgetItem(str(quantity))
                        elif column_key in ['unit_price', 'sale_price']:
                            # Format prices
                            price = product.get_value(column_key) or 0
                            formatted_price = f"{float(price):.2f}"
                            item = QTableWidgetItem(formatted_price)
                        else:
                            # Regular fields
                            value = product.get_value(column_key) or ""
                            item = QTableWidgetItem(str(value))
                        
                        # Store raw data for easy access
                        if column_key == 'ID':
                            item.setData(Qt.UserRole, product_data.get('ID', 0))
                        
                        self.table.setItem(row, col, item)
                
                except Exception as e:
                    print(f"Error processing product row {row}: {e}")
                    # Fallback: show raw data
                    for col, column_key in enumerate(self.columns):
                        value = product_data.get(column_key, "")
                        item = QTableWidgetItem(str(value))
                        if column_key == 'ID':
                            item.setData(Qt.UserRole, product_data.get('ID', 0))
                        self.table.setItem(row, col, item)
        
        except Exception as e:
            print(f"Error refreshing products table: {e}")
            QMessageBox.critical(self, "Error", f"Failed to refresh products: {e}")
    
    def get_selected_product_id(self):
        """Get ID of selected product"""
        row = self.table.currentRow()
        if row == -1:
            return None
        
        # Get ID from hidden column or UserRole data
        id_item = self.table.item(row, 0)  # ID column
        if id_item:
            stored_id = id_item.data(Qt.UserRole)
            if stored_id:
                return int(stored_id)
            elif id_item.text().isdigit():
                return int(id_item.text())
        
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
        name_item = self.table.item(row, 1)  # Name column
        product_name = name_item.text() if name_item else f"ID {product_id}"
        
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