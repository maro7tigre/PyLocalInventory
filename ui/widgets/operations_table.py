"""
Operations Table Widget - Clean inline editing table without action buttons
Properly inherits from ParameterTableWidget for consistent behavior
"""
from PySide6.QtWidgets import QTableWidgetItem, QAbstractItemView, QVBoxLayout, QTableWidget, QScrollArea
from PySide6.QtCore import Qt, Signal
from ui.widgets.table_widgets import ParameterTableWidget
from ui.widgets.preview_widget import PreviewWidget
from ui.widgets.parameters_widgets import ButtonWidget


class OperationsTableWidget(ParameterTableWidget):
    """Table widget for operations items with inline editing capabilities"""
    
    items_changed = Signal()
    
    def __init__(self, item_class, parent_operation=None, database=None, columns=None, parent=None):
        self.item_class = item_class
        self.parent_operation = parent_operation
        self.items = []
        self._updating_table = False  # Flag to prevent recursion
        
        # Initialize parent class but without dialog_class (no add/edit/delete buttons)
        super().__init__(item_class, database, None, parent)
        
        # Override columns if specified
        if columns:
            self.table_columns = columns
        
        # Remove the header buttons completely
        self.remove_action_buttons()
        
        # Make table fully editable
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        
        # Connect item change signals
        self.table.itemChanged.connect(self.on_item_changed)
        
        # Setup table with empty row
        self.refresh_table()
    
    def remove_action_buttons(self):
        """Remove the add/edit/delete/refresh buttons from the header"""
        # Get the layout and remove the header with buttons
        layout = self.layout()
        if layout.count() > 0:
            header_layout_item = layout.takeAt(0)  # Remove header layout
            if header_layout_item:
                # Delete all widgets in the header layout
                header_layout = header_layout_item.layout()
                if header_layout:
                    while header_layout.count():
                        child = header_layout.takeAt(0)
                        if child.widget():
                            child.widget().deleteLater()
    
    def setup_ui(self):
        """Setup table interface with dynamic scrollable area that adapts to container size"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create table first
        self.table = QTableWidget()
        self.setup_table()
        
        # Create scroll area and configure it properly
        self.scroll_area = QScrollArea()  # Store reference for dynamic sizing
        self.scroll_area.setWidget(self.table)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Set minimum height
        self.scroll_area.setMinimumHeight(200)
        
        # Make sure the table doesn't have conflicting size policies
        from PySide6.QtWidgets import QSizePolicy
        self.table.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        
        layout.addWidget(self.scroll_area)
        
        # Start timer to update scroll area size dynamically
        from PySide6.QtCore import QTimer
        self.resize_timer = QTimer()
        self.resize_timer.timeout.connect(self.update_scroll_area_size)
        self.resize_timer.start(100)  # Check every 100ms
    
    def setup_table(self):
        """Setup table columns and properties with proper image column sizing"""
        from PySide6.QtWidgets import QHeaderView
        
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
        
        # Set row height to exactly match preview image size
        self.table.verticalHeader().setDefaultSectionSize(45)  # Match preview size
        
        # Set column widths - fixed width for preview and delete columns
        header = self.table.horizontalHeader()
        for i, param_key in enumerate(self.table_columns):
            if param_key == 'product_preview':
                # Fixed width for preview images
                self.table.setColumnWidth(i, 70)  # Slightly reduced width
                header.setSectionResizeMode(i, QHeaderView.Fixed)
            elif param_key == 'delete_action':
                # Fixed width for delete buttons
                self.table.setColumnWidth(i, 50)
                header.setSectionResizeMode(i, QHeaderView.Fixed)
            else:
                # Stretch other columns
                header.setSectionResizeMode(i, QHeaderView.Stretch)
        
        # Apply minimal dark theme to table (no background color override)
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
    
    def update_scroll_area_size(self):
        """Dynamically update scroll area maximum height based on available space"""
        if not hasattr(self, 'scroll_area'):
            return
        
        # Get the widget's current height
        available_height = self.height()
        
        if available_height > 200:  # Only if we have reasonable space
            # Set maximum height to 80% of available space (leave room for headers/margins)
            max_height = int(available_height * 0.8)
            
            # Ensure it's at least minimum and not too large
            max_height = max(200, min(max_height, 600))
            
            # Only update if significantly different to avoid constant resizing
            current_max = self.scroll_area.maximumHeight()
            if abs(current_max - max_height) > 20:  # 20px threshold
                self.scroll_area.setMaximumHeight(max_height)
    
    def resizeEvent(self, event):
        """Handle resize events to update scroll area"""
        super().resizeEvent(event)
        # Trigger immediate update on resize
        if hasattr(self, 'scroll_area'):
            self.update_scroll_area_size()
    
    def refresh_table(self):
        """Refresh table data - override to maintain inline editing behavior"""
        # Clear existing content but keep structure
        self.table.setRowCount(0)
        
        # Load existing items if any (implement this based on your needs)
        # For now, just ensure we have an empty row
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
                    from PySide6.QtWidgets import QWidget, QHBoxLayout
                    container = QWidget()
                    container_layout = QHBoxLayout(container)
                    container_layout.setContentsMargins(0, 0, 0, 0)
                    container_layout.addStretch()
                    container_layout.addWidget(delete_btn)
                    container_layout.addStretch()
                    
                    self.table.setCellWidget(row, col, container)
                elif param_key == 'product_preview':
                    # Add empty preview widget with proper sizing and centering
                    preview_widget = PreviewWidget(45, "product")  # Slightly smaller
                    preview_widget.setFixedSize(45, 45)
                    
                    # Create container widget to center the preview
                    from PySide6.QtWidgets import QWidget, QHBoxLayout
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
        
        # Get product options
        temp_item = self.item_class(0, self.database)
        product_options = temp_item.get_parameter_options('product_name')
        
        # Create autocomplete widget with options
        autocomplete = AutoCompleteLineEdit(options=product_options)
        
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
        # Create a temporary sales item to get product data
        temp_item = self.item_class(0, self.database)
        temp_item.set_value('product_name', product_name)
        temp_item.update_product_selection(product_name)
        
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
            preview_path = temp_item.get_value('product_preview')
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
                        # Get preview from widget container
                        container_widget = self.table.cellWidget(row, col)
                        if container_widget:
                            # Find the PreviewWidget inside the container
                            for child in container_widget.findChildren(PreviewWidget):
                                item.set_value(param_key, child.get_image_path())
                                break
                    elif param_key == 'subtotal':
                        # Calculate subtotal
                        subtotal = item.calculate_subtotal() if hasattr(item, 'calculate_subtotal') else 0.0
                        item.set_value(param_key, subtotal)
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