"""
Operations Table Widget - Minimal changes to preserve working functionality
Only fix the consistency issues, keep the working logic intact
"""
from PySide6.QtWidgets import (QWidget, QTableWidget, QTableWidgetItem, QAbstractItemView, 
                             QVBoxLayout, QHBoxLayout, QHeaderView, QSizePolicy)
from PySide6.QtCore import Qt, Signal
from ui.widgets.preview_widget import PreviewWidget
from ui.widgets.parameters_widgets import ButtonWidget


class OperationsTableWidget(QWidget):
    """Simple operations table - UI only, database handles CRUD"""
    
    items_changed = Signal()
    
    def __init__(self, item_class, parent_operation=None, database=None, columns=None, parent=None):
        super().__init__(parent)
        
        self.item_class = item_class
        self.parent_operation = parent_operation
        self.database = database
        self.table_columns = columns or []
        self._updating_table = False  # Flag to prevent recursion
        
        # Setup the UI
        self.setup_ui()
        
        # Load and display existing items if we have a parent operation with ID
        self.refresh_table()
    
    def setup_ui(self):
        """Setup simple table interface - keep original"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Create table widget
        self.table = QTableWidget()
        self.setup_table()
        
        # Set proper size policies
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Enable native scrolling
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        layout.addWidget(self.table)
        self.setLayout(layout)
    
    def setup_table(self):
        """Setup table columns and properties - keep original logic"""
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
    
    def refresh_table(self):
        """Refresh table by loading items from database"""
        self.table.setRowCount(0)
        
        # Load existing items from database if we have a parent operation
        if (self.parent_operation and hasattr(self.parent_operation, 'id') and 
            self.parent_operation.id and self.database):
            
            try:
                # Get existing items directly from database
                if hasattr(self.parent_operation, 'get_sales_items'):
                    existing_items = self.parent_operation.get_sales_items()
                elif hasattr(self.parent_operation, 'get_import_items'):  
                    existing_items = self.parent_operation.get_import_items()
                else:
                    existing_items = []
                
                # Add rows for existing items
                for item in existing_items:
                    self.add_item_row(item)
                    
            except Exception as e:
                print(f"Error loading existing items: {e}")
        
        # Always ensure we have exactly one empty row at the end
        self.ensure_single_empty_row()
    
    def add_item_row(self, item):
        """Add a row for an existing item"""
        row = self.table.rowCount()
        self.table.setRowCount(row + 1)
        
        for col, param_key in enumerate(self.table_columns):
            if param_key == 'delete_action':
                # Add delete button
                delete_btn = self.create_delete_button(row)
                container = QWidget()
                container_layout = QHBoxLayout(container)
                container_layout.setContentsMargins(0, 0, 0, 0)
                container_layout.addStretch()
                container_layout.addWidget(delete_btn)
                container_layout.addStretch()
                self.table.setCellWidget(row, col, container)
                
            elif param_key == 'product_preview':
                # Add preview widget
                preview_widget = PreviewWidget(45, "product")
                preview_widget.setFixedSize(45, 45)
                
                # Set preview image if available
                preview_path = item.get_product_preview() if hasattr(item, 'get_product_preview') else None
                if preview_path:
                    preview_widget.set_image_path(preview_path)
                
                container = QWidget()
                container_layout = QHBoxLayout(container)
                container_layout.setContentsMargins(0, 0, 0, 0)
                container_layout.addStretch()
                container_layout.addWidget(preview_widget)
                container_layout.addStretch()
                self.table.setCellWidget(row, col, container)
                
            elif param_key == 'product_name':
                # Add autocomplete widget with current value
                autocomplete_widget = self.create_product_autocomplete_widget(row)
                current_name = item.get_product_name() if hasattr(item, 'get_product_name') else ""
                if hasattr(autocomplete_widget, 'setText'):
                    autocomplete_widget.setText(current_name)
                self.table.setCellWidget(row, col, autocomplete_widget)
                
            else:
                # Add regular cell with item value
                value = item.get_value(param_key) if hasattr(item, 'get_value') else ""
                cell_item = QTableWidgetItem(str(value))
                
                # Make subtotal read-only
                if param_key == 'subtotal':
                    cell_item.setFlags(cell_item.flags() & ~Qt.ItemIsEditable)
                
                self.table.setItem(row, col, cell_item)
    
    def ensure_single_empty_row(self):
        """Ensure there's exactly one empty row at the bottom"""
        if self._updating_table:
            return
        
        # Remove any extra empty rows, keep only one at the end
        rows_to_remove = []
        empty_row_count = 0
        
        for row in range(self.table.rowCount() - 1, -1, -1):  # Go backwards
            if self.is_row_empty(row):
                empty_row_count += 1
                if empty_row_count > 1:  # Keep only one empty row
                    rows_to_remove.append(row)
        
        # Remove extra empty rows
        for row in rows_to_remove:
            self.table.removeRow(row)
        
        # If no empty row exists, add one
        if empty_row_count == 0:
            self.add_empty_row()
    
    def add_empty_row(self):
        """Add a new empty row - keep original logic"""
        if self._updating_table:
            return
        
        self._updating_table = True
        try:
            row = self.table.rowCount()
            self.table.setRowCount(row + 1)
            
            for col, param_key in enumerate(self.table_columns):
                if param_key == 'delete_action':
                    delete_btn = self.create_delete_button(row)
                    container = QWidget()
                    container_layout = QHBoxLayout(container)
                    container_layout.setContentsMargins(0, 0, 0, 0)
                    container_layout.addStretch()
                    container_layout.addWidget(delete_btn)
                    container_layout.addStretch()
                    self.table.setCellWidget(row, col, container)
                    
                elif param_key == 'product_preview':
                    preview_widget = PreviewWidget(45, "product")
                    preview_widget.setFixedSize(45, 45)
                    container = QWidget()
                    container_layout = QHBoxLayout(container)
                    container_layout.setContentsMargins(0, 0, 0, 0)
                    container_layout.addStretch()
                    container_layout.addWidget(preview_widget)
                    container_layout.addStretch()
                    self.table.setCellWidget(row, col, container)
                    
                elif param_key == 'product_name':
                    autocomplete_widget = self.create_product_autocomplete_widget(row)
                    self.table.setCellWidget(row, col, autocomplete_widget)
                    
                elif param_key == 'quantity':
                    temp_item = self.item_class(0, self.database)
                    default_qty = temp_item.parameters.get('quantity', {}).get('default', 1)
                    self.table.setItem(row, col, QTableWidgetItem(str(default_qty)))
                    
                else:
                    self.table.setItem(row, col, QTableWidgetItem(""))
        finally:
            self._updating_table = False
    
    def create_delete_button(self, row):
        """Create a delete button for a specific row"""
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
        
        # Get product options
        temp_item = self.item_class(0, self.database)
        product_options_method = temp_item.parameters.get('product_name', {}).get('options')
        
        autocomplete = AutoCompleteLineEdit(options=product_options_method)
        # Visual placeholder only; QLineEdit.placeholderText doesn't affect .text()
        try:
            autocomplete.setPlaceholderText("Product name")
        except Exception:
            pass
        autocomplete.textChanged.connect(lambda text, r=row: self.handle_product_name_change(r, text))
        autocomplete.editingFinished.connect(lambda r=row: self.handle_product_selection_finished(r))
        
        return autocomplete
    
    def get_row_product_name(self, row):
        """Get product name from a specific row"""
        if 'product_name' in self.table_columns:
            col = self.table_columns.index('product_name')
            widget = self.table.cellWidget(row, col)
            if widget and hasattr(widget, 'text'):
                return widget.text().strip()
            item = self.table.item(row, col)
            if item:
                return item.text().strip()
        return ''
    
    def is_row_empty(self, row):
        """Check if a row is empty or only has default values"""
        # Get product name - this is the most important field
        product_name = self.get_row_product_name(row)
        if product_name:
            return False
            
        # Check other meaningful fields
        for col in range(self.table.columnCount()):
            param_key = self.table_columns[col] if col < len(self.table_columns) else ''
            
            # Skip certain columns
            if param_key in ['delete_action', 'product_preview', 'subtotal', 'quantity']:
                continue
                
            item = self.table.item(row, col)
            if item and item.text().strip():
                return False
                
            widget = self.table.cellWidget(row, col)
            if widget and hasattr(widget, 'text') and widget.text().strip():
                return False
                
        return True
    
    def on_item_changed(self, item):
        """Handle when a table item is changed"""
        if self._updating_table:
            return
        
        row = item.row()
        col = item.column()
        
        if col < len(self.table_columns):
            param_key = self.table_columns[col]
            new_value = item.text()
            
            if param_key == 'product_name' and new_value.strip():
                self.handle_product_selection(row, new_value.strip())
            elif param_key in ['quantity', 'unit_price']:
                self.update_row_subtotal(row)
        
        # If this was the empty row and now has content, ensure we have exactly one empty row
        if not self.is_row_empty(row):
            self.ensure_single_empty_row()
        
        self.items_changed.emit()
    
    def handle_product_name_change(self, row, text):
        """Handle product name text change"""
        if self._updating_table:
            return
        
        if 'product_name' in self.table_columns:
            col = self.table_columns.index('product_name')
            item = self.table.item(row, col)
            if not item:
                item = QTableWidgetItem()
                self.table.setItem(row, col, item)
            self.table.itemChanged.disconnect()
            item.setText(text)
            self.table.itemChanged.connect(self.on_item_changed)
    
    def handle_product_selection_finished(self, row):
        """Handle when product selection is finished"""
        if 'product_name' in self.table_columns:
            col = self.table_columns.index('product_name')
            widget = self.table.cellWidget(row, col)
            if widget and hasattr(widget, 'text'):
                product_name = widget.text().strip()
                if product_name:
                    self.handle_product_selection(row, product_name)
                    self.ensure_single_empty_row()
                    self.items_changed.emit()
    
    def handle_product_selection(self, row, product_name):
        """Handle product selection and auto-fill - keep original logic"""
        temp_item = self.item_class(0, self.database)
        temp_item.set_value('product_name', product_name)
        
        # Set quantity to 1 if empty
        if 'quantity' in self.table_columns:
            qty_col = self.table_columns.index('quantity')
            qty_item = self.table.item(row, qty_col)
            current_qty = 0
            if qty_item and qty_item.text().strip():
                try:
                    current_qty = float(qty_item.text())
                except ValueError:
                    current_qty = 0
            
            if current_qty == 0:
                if not qty_item:
                    qty_item = QTableWidgetItem()
                    self.table.setItem(row, qty_col, qty_item)
                qty_item.setText("1")
        
        # Update unit_price
        if 'unit_price' in self.table_columns:
            price_col = self.table_columns.index('unit_price')
            unit_price = temp_item.get_value('unit_price')
            if unit_price is not None:
                price_item = self.table.item(row, price_col)
                if not price_item:
                    price_item = QTableWidgetItem()
                    self.table.setItem(row, price_col, price_item)
                price_item.setText(str(unit_price))
        
        # Update preview
        if 'product_preview' in self.table_columns:
            preview_col = self.table_columns.index('product_preview')
            if hasattr(temp_item, 'get_product_preview'):
                preview_path = temp_item.get_product_preview()
                container_widget = self.table.cellWidget(row, preview_col)
                if container_widget:
                    for child in container_widget.findChildren(PreviewWidget):
                        if preview_path:
                            child.set_image_path(preview_path)
                        break
        
        self.update_row_subtotal(row)
    
    def update_row_subtotal(self, row):
        """Update the subtotal for a specific row"""
        if 'quantity' in self.table_columns and 'unit_price' in self.table_columns and 'subtotal' in self.table_columns:
            qty_col = self.table_columns.index('quantity')
            price_col = self.table_columns.index('unit_price')
            subtotal_col = self.table_columns.index('subtotal')
            
            qty_item = self.table.item(row, qty_col)
            price_item = self.table.item(row, price_col)
            
            try:
                quantity = float(qty_item.text()) if qty_item and qty_item.text().strip() else 0.0
                unit_price = float(price_item.text()) if price_item and price_item.text().strip() else 0.0
                subtotal = quantity * unit_price
                
                subtotal_item = self.table.item(row, subtotal_col)
                if not subtotal_item:
                    subtotal_item = QTableWidgetItem()
                    self.table.setItem(row, subtotal_col, subtotal_item)
                subtotal_item.setText(f"{subtotal:.2f}")
                
            except (ValueError, AttributeError):
                pass
    
    def delete_row(self, row):
        """Delete a specific row from UI"""
        if row < self.table.rowCount():
            self.table.removeRow(row)
            self.update_delete_buttons()
            
            # Ensure we always have exactly one empty row at the end
            self.ensure_single_empty_row()
                
            self.items_changed.emit()
    
    def update_delete_buttons(self):
        """Update delete button connections after row changes"""
        for row in range(self.table.rowCount()):
            for col, param_key in enumerate(self.table_columns):
                if param_key == 'delete_action':
                    container_widget = self.table.cellWidget(row, col)
                    if container_widget:
                        for child in container_widget.findChildren(ButtonWidget):
                            child.clicked.disconnect()
                            child.clicked.connect(lambda r=row: self.delete_row(r))
                            break
    
    def get_current_table_data(self):
        """Get all non-empty rows from the table as simple data dictionaries"""
        items_data = []
        
        for row in range(self.table.rowCount()):
            if not self.is_row_empty(row):
                row_data = {}
                
                # Extract data from each column
                for col, param_key in enumerate(self.table_columns):
                    if param_key in ['delete_action', 'product_preview', 'subtotal']:
                        continue
                        
                    # Get value from table cell
                    value = None
                    widget = self.table.cellWidget(row, col)
                    if widget and hasattr(widget, 'text'):
                        value = widget.text().strip()
                    else:
                        cell_item = self.table.item(row, col)
                        if cell_item:
                            value = cell_item.text().strip()
                    
                    # Ignore visual placeholder text for product_name
                    if param_key == 'product_name' and value and value.lower() == 'product name':
                        value = None

                    if value:
                        # Convert to proper type
                        temp_item = self.item_class(0, self.database)
                        param_info = temp_item.parameters.get(param_key, {})
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
                        
                        row_data[param_key] = value
                
                # Only add rows that have meaningful data (at least product_name)
                if row_data.get('product_name'):
                    items_data.append(row_data)
        
        return items_data
    
    def get_items_data(self):
        """Compatibility method for base operation dialog - returns item objects"""
        items = []
        items_data = self.get_current_table_data()
        
        for item_data in items_data:
            # Create item object and populate it
            item = self.item_class(0, self.database)
            for key, value in item_data.items():
                item.set_value(key, value)
            # Skip items with invalid or unknown product (no product_id resolved)
            try:
                if item.get_value('product_id'):
                    items.append(item)
            except Exception:
                # If item doesn't expose product_id, keep it to avoid accidental drops
                items.append(item)
            
        return items
    
    def apply_table_theme(self):
        """Apply minimal dark theme styling"""
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