"""
Operations Table Widget - Simple standalone inline editing table
No inheritance from complex ParameterTableWidget - clean slate approach
"""
from PySide6.QtWidgets import (QWidget, QTableWidget, QTableWidgetItem, QAbstractItemView, 
                             QVBoxLayout, QHBoxLayout, QHeaderView, QSizePolicy)
from PySide6.QtCore import Qt, Signal
from ui.widgets.preview_widget import PreviewWidget
from ui.widgets.parameters_widgets import ButtonWidget


class OperationsTableWidget(QWidget):
    """Simple, clean table widget for operations items with inline editing"""
    
    items_changed = Signal()
    
    def __init__(self, item_class, parent_operation=None, database=None, columns=None, parent=None):
        super().__init__(parent)
        
        self.item_class = item_class
        self.parent_operation = parent_operation
        self.database = database
        self.table_columns = columns or []
        self.items = []
        self._updating_table = False  # Flag to prevent recursion
        
        # Setup the clean, simple UI
        self.setup_ui()
        
        # Setup table with empty row
        self.refresh_table()
    
    def setup_ui(self):
        """Setup simple table interface"""
        # Create main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Create table widget
        self.table = QTableWidget()
        self.setup_table()
        
        # Set proper size policies for the widget itself
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Set proper size policies for the table
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Enable native scrolling
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Ensure no absolute positioning
        self.table.setStyleSheet("")  # Clear any inherited styles
        
        # Add to layout
        layout.addWidget(self.table)
        
        # Ensure the layout respects the parent
        self.setLayout(layout)
    
    def setup_table(self):
        """Setup table columns and properties"""
        # Set column count and headers
        self.table.setColumnCount(len(self.table_columns))
        
        # Create display headers
        headers = []
        for param_key in self.table_columns:
            if param_key == 'product_preview':
                headers.append('Preview')
            elif param_key == 'product_name':
                headers.append('Product')
            elif param_key == 'delete_action':
                headers.append('Delete')
            else:
                # Use parameter display name if available
                temp_obj = self.item_class(0, self.database)
                if hasattr(temp_obj, 'get_display_name'):
                    headers.append(temp_obj.get_display_name(param_key))
                else:
                    headers.append(param_key.replace('_', ' ').title())
        
        self.table.setHorizontalHeaderLabels(headers)
        
        # Table properties
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        
        # Set row height to exactly match preview image size
        self.table.verticalHeader().setDefaultSectionSize(45)
        
        # Set column widths - fixed width for preview and delete columns
        header = self.table.horizontalHeader()
        for i, param_key in enumerate(self.table_columns):
            if param_key == 'product_preview':
                self.table.setColumnWidth(i, 70)
                header.setSectionResizeMode(i, QHeaderView.Fixed)
            elif param_key == 'delete_action':
                self.table.setColumnWidth(i, 50)
                header.setSectionResizeMode(i, QHeaderView.Fixed)
            else:
                header.setSectionResizeMode(i, QHeaderView.Stretch)
        
        # Connect item change signals
        self.table.itemChanged.connect(self.on_item_changed)
        
        # Apply minimal dark theme
        self.apply_table_theme()
    
    def apply_table_theme(self):
        """Apply minimal dark theme styling to the table"""
        self.table.setStyleSheet("""
            QHeaderView::section {
                background-color: #404040;
                color: #ffffff;
                padding: 8px;
                border: 1px solid #555555;
                font-weight: bold;
            }
            QScrollBar:vertical {
                background-color: #404040;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #666666;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #777777;
            }
        """)
    
    def refresh_table(self):
        """Refresh table data"""
        # Clear existing content
        self.table.setRowCount(0)
        
        # Ensure we have an empty row
        self.ensure_empty_row()
    
    def ensure_empty_row(self):
        """Ensure there's always an empty row at the bottom for adding new items"""
        if self._updating_table:
            return  # Prevent recursion
        
        # Check if we need to add an empty row
        if self.table.rowCount() == 0 or not self.is_row_empty(self.table.rowCount() - 1):
            self.add_empty_row()
    
    def is_row_empty(self, row):
        """Check if a row is empty (all cells are empty or None)"""
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item and item.text().strip():
                return False
            # Check for widgets (like delete buttons or previews)
            widget = self.table.cellWidget(row, col)
            if widget:
                # For preview containers, check the inner PreviewWidget
                if 'product_preview' in self.table_columns and col == self.table_columns.index('product_preview'):
                    for child in widget.findChildren(PreviewWidget):
                        if hasattr(child, 'has_content') and child.has_content():
                            return False
                elif hasattr(widget, 'has_content') and widget.has_content():
                    return False
        return True
    
    def add_empty_row(self):
        """Add a new empty row to the table"""
        if self._updating_table:
            return  # Prevent recursion
        
        self._updating_table = True
        try:
            row = self.table.rowCount()
            self.table.setRowCount(row + 1)
            
            # Create empty cells for each column
            for col, param_key in enumerate(self.table_columns):
                if param_key == 'delete_action':
                    # Add delete button for this row - centered like preview
                    delete_btn = self.create_delete_button(row)
                    
                    # Create container widget to center the delete button
                    container = QWidget()
                    container_layout = QHBoxLayout(container)
                    container_layout.setContentsMargins(0, 0, 0, 0)
                    container_layout.addStretch()
                    container_layout.addWidget(delete_btn)
                    container_layout.addStretch()
                    
                    self.table.setCellWidget(row, col, container)
                elif param_key == 'product_preview':
                    # Add empty preview widget with proper sizing and centering
                    preview_widget = PreviewWidget(45, "product")
                    preview_widget.setFixedSize(45, 45)
                    
                    # Create container widget to center the preview
                    container = QWidget()
                    container_layout = QHBoxLayout(container)
                    container_layout.setContentsMargins(0, 0, 0, 0)
                    container_layout.addStretch()
                    container_layout.addWidget(preview_widget)
                    container_layout.addStretch()
                    
                    self.table.setCellWidget(row, col, container)
                elif param_key == 'product_name':
                    # Add autocomplete widget for product names
                    autocomplete_widget = self.create_product_autocomplete_widget(row)
                    self.table.setCellWidget(row, col, autocomplete_widget)
                elif param_key == 'quantity':
                    # Set default quantity to 1
                    temp_item = self.item_class(0, self.database)
                    default_qty = temp_item.parameters.get('quantity', {}).get('default', 1)
                    self.table.setItem(row, col, QTableWidgetItem(str(default_qty)))
                else:
                    # Add empty editable cell
                    self.table.setItem(row, col, QTableWidgetItem(""))
        finally:
            self._updating_table = False
    
    def create_delete_button(self, row):
        """Create a delete button for a specific row"""
        # Create button parameter info
        button_param = {
            'text': '🗑️',
            'color': 'red',
            'size': 30
        }
        delete_btn = ButtonWidget(button_param)
        delete_btn.clicked.connect(lambda: self.delete_row(row))
        return delete_btn
    
    def create_product_autocomplete_widget(self, row):
        """Create an autocomplete widget for product names"""
        from ui.widgets.autocomplete_widgets import AutoCompleteLineEdit
        
        # Get product options method from the item class
        temp_item = self.item_class(0, self.database)
        product_options_method = temp_item.parameters.get('product_name', {}).get('options')
        
        # Create autocomplete widget with the options method
        autocomplete = AutoCompleteLineEdit(options=product_options_method)
        
        # Connect to handle selection
        autocomplete.textChanged.connect(
            lambda text, r=row: self.handle_product_name_change(r, text)
        )
        autocomplete.editingFinished.connect(
            lambda r=row: self.handle_product_selection_finished(r)
        )
        
        return autocomplete
    
    def delete_row(self, row):
        """Delete a specific row"""
        if row < self.table.rowCount() - 1:  # Don't delete the last (empty) row
            self.table.removeRow(row)
            # Update button connections for remaining rows
            self.update_delete_buttons()
            self.items_changed.emit()
    
    def update_delete_buttons(self):
        """Update delete button connections after row changes"""
        for row in range(self.table.rowCount()):
            for col, param_key in enumerate(self.table_columns):
                if param_key == 'delete_action':
                    container_widget = self.table.cellWidget(row, col)
                    if container_widget:
                        # Find the ButtonWidget inside the container
                        for child in container_widget.findChildren(ButtonWidget):
                            # Disconnect old connections and reconnect with correct row
                            child.clicked.disconnect()
                            child.clicked.connect(lambda r=row: self.delete_row(r))
                            break
    
    def on_item_changed(self, item):
        """Handle when a table item is changed (user edits a cell)"""
        if self._updating_table:
            return  # Prevent recursion
        
        row = item.row()
        col = item.column()
        
        # Get the parameter key for this column
        if col < len(self.table_columns):
            param_key = self.table_columns[col]
            new_value = item.text()
            
            # Handle product name changes (trigger autocomplete/price update)
            if param_key == 'product_name' and new_value.strip():
                self.handle_product_selection(row, new_value.strip())
            
            # Handle quantity or price changes (update subtotal)
            elif param_key in ['quantity', 'unit_price']:
                self.update_row_subtotal(row)
        
        # If this was the empty row and now has content, ensure we have a new empty row
        if row == self.table.rowCount() - 1 and not self.is_row_empty(row):
            self.ensure_empty_row()
        
        # Emit change signal
        self.items_changed.emit()
    
    def handle_product_name_change(self, row, text):
        """Handle product name text change"""
        if self._updating_table:
            return  # Prevent recursion
        
        # Update the corresponding table item for consistency
        if 'product_name' in self.table_columns:
            col = self.table_columns.index('product_name')
            item = self.table.item(row, col)
            if not item:
                item = QTableWidgetItem()
                self.table.setItem(row, col, item)
            # Temporarily disconnect to avoid recursive calls
            self.table.itemChanged.disconnect()
            item.setText(text)
            self.table.itemChanged.connect(self.on_item_changed)
    
    def handle_product_selection_finished(self, row):
        """Handle when product selection is finished (user pressed Enter/Tab)"""
        if 'product_name' in self.table_columns:
            col = self.table_columns.index('product_name')
            widget = self.table.cellWidget(row, col)
            if widget and hasattr(widget, 'text'):
                product_name = widget.text().strip()
                if product_name:
                    self.handle_product_selection(row, product_name)
                    
                    # If this was the empty row, ensure new empty row
                    if row == self.table.rowCount() - 1:
                        self.ensure_empty_row()
                    
                    self.items_changed.emit()
    
    def handle_product_selection(self, row, product_name):
        """Handle product selection and auto-fill price/preview"""
        # Create a temporary item to get product data using connected parameters
        temp_item = self.item_class(0, self.database)
        
        # Use set_value to trigger connected parameters system
        temp_item.set_value('product_name', product_name)
        
        # Set quantity to 1 if it's currently empty/zero
        if 'quantity' in self.table_columns:
            qty_col = self.table_columns.index('quantity')
            qty_item = self.table.item(row, qty_col)
            current_qty = 0
            if qty_item and qty_item.text().strip():
                try:
                    current_qty = float(qty_item.text())
                except ValueError:
                    current_qty = 0
            
            # Set quantity to 1 if it's currently 0 or empty
            if current_qty == 0:
                if not qty_item:
                    qty_item = QTableWidgetItem()
                    self.table.setItem(row, qty_col, qty_item)
                qty_item.setText("1")
        
        # Update unit_price column if it exists
        if 'unit_price' in self.table_columns:
            price_col = self.table_columns.index('unit_price')
            unit_price = temp_item.get_value('unit_price')
            if unit_price is not None:
                price_item = self.table.item(row, price_col)
                if not price_item:
                    price_item = QTableWidgetItem()
                    self.table.setItem(row, price_col, price_item)
                price_item.setText(str(unit_price))
        
        # Update preview if it exists
        if 'product_preview' in self.table_columns:
            preview_col = self.table_columns.index('product_preview')
            preview_path = temp_item.get_product_preview()
            container_widget = self.table.cellWidget(row, preview_col)
            
            # Find the PreviewWidget inside the container
            if container_widget:
                preview_widget = None
                for child in container_widget.findChildren(PreviewWidget):
                    preview_widget = child
                    break
                
                if preview_widget and preview_path:
                    preview_widget.set_image_path(preview_path)
        
        # Calculate subtotal if quantity exists
        self.update_row_subtotal(row)
    
    def update_row_subtotal(self, row):
        """Update the subtotal for a specific row"""
        if 'quantity' in self.table_columns and 'unit_price' in self.table_columns and 'subtotal' in self.table_columns:
            qty_col = self.table_columns.index('quantity')
            price_col = self.table_columns.index('unit_price')
            subtotal_col = self.table_columns.index('subtotal')
            
            # Get quantity and price
            qty_item = self.table.item(row, qty_col)
            price_item = self.table.item(row, price_col)
            
            try:
                quantity = float(qty_item.text()) if qty_item and qty_item.text().strip() else 0.0
                unit_price = float(price_item.text()) if price_item and price_item.text().strip() else 0.0
                subtotal = quantity * unit_price
                
                # Update subtotal cell
                subtotal_item = self.table.item(row, subtotal_col)
                if not subtotal_item:
                    subtotal_item = QTableWidgetItem()
                    self.table.setItem(row, subtotal_col, subtotal_item)
                subtotal_item.setText(f"{subtotal:.2f}")
                
            except (ValueError, AttributeError):
                pass  # Invalid number, ignore
    
    def get_items_data(self):
        """Get all non-empty rows as item objects"""
        items = []
        
        for row in range(self.table.rowCount() - 1):  # Exclude the last (empty) row
            if not self.is_row_empty(row):
                # Create item object and populate from row
                item = self.item_class(0, self.database)
                
                for col, param_key in enumerate(self.table_columns):
                    if param_key == 'delete_action':
                        continue  # Skip action columns
                    elif param_key == 'product_preview':
                        # Skip calculated/method-based parameters - they're auto-calculated
                        continue
                    elif param_key == 'subtotal':
                        # Skip calculated parameters - they're auto-calculated
                        continue
                    else:
                        # Get value from table cell
                        cell_item = self.table.item(row, col)
                        if cell_item:
                            value = cell_item.text().strip()
                            # Convert to appropriate type
                            param_info = item.parameters.get(param_key, {})
                            param_type = param_info.get('type', 'string')
                            
                            if param_type == 'int':
                                try:
                                    value = int(value) if value else 0
                                except ValueError:
                                    value = 0
                            elif param_type == 'float':
                                try:
                                    value = float(value) if value else 0.0
                                except ValueError:
                                    value = 0.0
                            
                            item.set_value(param_key, value)
                
                items.append(item)
        
        return items