"""
Operations Table Widget - Clean architecture with proper separation of concerns
"""
from PySide6.QtWidgets import (QWidget, QTableWidget, QTableWidgetItem, QAbstractItemView, 
                             QVBoxLayout, QHBoxLayout, QHeaderView, QSizePolicy)
from PySide6.QtCore import Qt, Signal
from ui.widgets.preview_widget import PreviewWidget
from ui.widgets.parameters_widgets import ButtonWidget


class TableDataManager:
    """Handles data operations and validation"""
    
    def __init__(self, item_class, database):
        self.item_class = item_class
        self.database = database
        
        # Get column definitions from item class
        temp_item = item_class(0, database)
        self.table_columns = temp_item.get_visible_parameters("table") if hasattr(temp_item, 'get_visible_parameters') else []
        self.parameter_definitions = temp_item.parameters if hasattr(temp_item, 'parameters') else {}
    
    def get_column_headers(self):
        """Get display headers for table columns"""
        headers = []
        for param_key in self.table_columns:
            if param_key == 'product_preview':
                headers.append('Preview')
            elif param_key == 'product_name':
                headers.append('Product')
            elif param_key == 'delete_action':
                headers.append('Delete')
            else:
                temp_obj = self.item_class(0, self.database)
                if hasattr(temp_obj, 'get_display_name'):
                    headers.append(temp_obj.get_display_name(param_key))
                else:
                    headers.append(param_key.replace('_', ' ').title())
        return headers
    
    def load_items_from_operation(self, parent_operation):
        """Load existing items from parent operation"""
        if not parent_operation or not hasattr(parent_operation, 'id') or not parent_operation.id:
            return []
            
        try:
            if hasattr(parent_operation, 'get_sales_items'):
                return parent_operation.get_sales_items()
            elif hasattr(parent_operation, 'get_import_items'):
                return parent_operation.get_import_items()
        except Exception as e:
            print(f"Error loading items from operation: {e}")
        return []
    
    def extract_row_data(self, table, row):
        """Extract data from a table row"""
        row_data = {}
        
        for col, param_key in enumerate(self.table_columns):
            if param_key in ['delete_action', 'product_preview', 'subtotal']:
                continue
                
            value = self._get_cell_value(table, row, col)
            
            # Skip placeholder text
            if param_key == 'product_name' and value and value.lower() == 'product name':
                continue
                
            if value:
                row_data[param_key] = self._convert_value_type(param_key, value)
        
        return row_data
    
    def _get_cell_value(self, table, row, col):
        """Get value from table cell (widget or item)"""
        widget = table.cellWidget(row, col)
        if widget and hasattr(widget, 'text'):
            return widget.text().strip()
        
        cell_item = table.item(row, col)
        if cell_item:
            return cell_item.text().strip()
        
        return ""
    
    def _convert_value_type(self, param_key, value):
        """Convert value to proper type based on parameter definition"""
        param_info = self.parameter_definitions.get(param_key, {})
        param_type = param_info.get('type', 'string')
        
        if param_type == 'int':
            try:
                return int(value) if value else 0
            except ValueError:
                return 0
        elif param_type == 'float':
            try:
                return float(value) if value else 0.0
            except ValueError:
                return 0.0
        
        return value


class TableRowFactory:
    """Creates and manages table row widgets"""
    
    def __init__(self, data_manager, delete_callback):
        self.data_manager = data_manager
        self.delete_callback = delete_callback
    
    def create_data_row(self, table, row, item):
        """Create a row with existing item data"""
        for col, param_key in enumerate(self.data_manager.table_columns):
            self._create_cell(table, row, col, param_key, item)
    
    def create_empty_row(self, table, row):
        """Create an empty row for new data entry"""
        for col, param_key in enumerate(self.data_manager.table_columns):
            self._create_cell(table, row, col, param_key, None)
    
    def _create_cell(self, table, row, col, param_key, item=None):
        """Create individual cell based on parameter type"""
        if param_key == 'delete_action':
            self._create_delete_button_cell(table, row, col)
        elif param_key == 'product_preview':
            self._create_preview_cell(table, row, col, item)
        elif param_key == 'product_name':
            self._create_autocomplete_cell(table, row, col, item)
        else:
            self._create_regular_cell(table, row, col, param_key, item)
    
    def _create_delete_button_cell(self, table, row, col):
        """Create delete button cell"""
        button_param = {'text': '🗑️', 'color': 'red', 'size': 30}
        delete_btn = ButtonWidget(button_param)
        delete_btn.setProperty('row', row)  # Store row for callback
        delete_btn.clicked.connect(lambda: self.delete_callback(row))
        
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        layout.addWidget(delete_btn)
        layout.addStretch()
        
        table.setCellWidget(row, col, container)
    
    def _create_preview_cell(self, table, row, col, item):
        """Create preview image cell"""
        preview_widget = PreviewWidget(45, "product")
        preview_widget.setFixedSize(45, 45)
        
        # Set preview image if available
        if item:
            preview_path = item.get_product_preview() if hasattr(item, 'get_product_preview') else None
            if preview_path:
                preview_widget.set_image_path(preview_path)
        
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        layout.addWidget(preview_widget)
        layout.addStretch()
        
        table.setCellWidget(row, col, container)
    
    def _create_autocomplete_cell(self, table, row, col, item):
        """Create autocomplete cell for product names"""
        from ui.widgets.autocomplete_widgets import AutoCompleteLineEdit
        
        # Get product options
        temp_item = self.data_manager.item_class(0, self.data_manager.database)
        product_options_method = temp_item.parameters.get('product_name', {}).get('options')
        
        autocomplete = AutoCompleteLineEdit(options=product_options_method)
        autocomplete.setPlaceholderText("Product name")
        autocomplete.setProperty('row', row)  # Store row for callbacks
        
        # Set current value if item provided
        if item:
            current_name = item.get_product_name() if hasattr(item, 'get_product_name') else ""
            autocomplete.setText(current_name)
        
        table.setCellWidget(row, col, autocomplete)
    
    def _create_regular_cell(self, table, row, col, param_key, item):
        """Create regular text cell"""
        value = ""
        if item and hasattr(item, 'get_value'):
            value = str(item.get_value(param_key) or "")
        elif param_key == 'quantity':
            # Set default quantity for empty rows
            temp_item = self.data_manager.item_class(0, self.data_manager.database)
            default_qty = temp_item.parameters.get('quantity', {}).get('default', 1)
            value = str(default_qty) if not item else value
        
        cell_item = QTableWidgetItem(value)
        
        # Make subtotal read-only
        if param_key == 'subtotal':
            cell_item.setFlags(cell_item.flags() & ~Qt.ItemIsEditable)
        
        table.setItem(row, col, cell_item)


class EmptyRowManager:
    """Manages the single empty row at the bottom"""
    
    def __init__(self, table, row_factory):
        self.table = table
        self.row_factory = row_factory
    
    def ensure_single_empty_row(self):
        """Ensure exactly one empty row exists at the bottom"""
        # Remove all empty rows
        self._remove_all_empty_rows()
        
        # Add one empty row at the end
        self._add_empty_row()
    
    def _remove_all_empty_rows(self):
        """Remove all empty rows from table"""
        rows_to_remove = []
        
        for row in range(self.table.rowCount() - 1, -1, -1):
            if self._is_row_empty(row):
                rows_to_remove.append(row)
        
        for row in rows_to_remove:
            self.table.removeRow(row)
    
    def _add_empty_row(self):
        """Add empty row at the end"""
        row = self.table.rowCount()
        self.table.setRowCount(row + 1)
        self.row_factory.create_empty_row(self.table, row)
    
    def _is_row_empty(self, row):
        """Check if row is empty"""
        # Check product name first (most important)
        product_name = self._get_product_name(row)
        if product_name:
            return False
        
        # Check other meaningful fields
        for col in range(self.table.columnCount()):
            if col >= len(self.row_factory.data_manager.table_columns):
                continue
                
            param_key = self.row_factory.data_manager.table_columns[col]
            
            if param_key in ['delete_action', 'product_preview', 'subtotal', 'quantity']:
                continue
            
            cell_item = self.table.item(row, col)
            if cell_item and cell_item.text().strip():
                return False
        
        return True
    
    def _get_product_name(self, row):
        """Get product name from row"""
        try:
            col = self.row_factory.data_manager.table_columns.index('product_name')
            widget = self.table.cellWidget(row, col)
            if widget and hasattr(widget, 'text'):
                return widget.text().strip()
        except (ValueError, AttributeError):
            pass
        return ""


class TableEventHandler:
    """Handles all table events and interactions"""
    
    def __init__(self, table, data_manager, empty_row_manager, items_changed_callback):
        self.table = table
        self.data_manager = data_manager
        self.empty_row_manager = empty_row_manager
        self.items_changed_callback = items_changed_callback
        self._updating = False
    
    def setup_event_connections(self):
        """Setup event connections"""
        self.table.itemChanged.connect(self._on_item_changed)
        
        # Connect autocomplete widgets
        for row in range(self.table.rowCount()):
            self._connect_row_widgets(row)
    
    def _connect_row_widgets(self, row):
        """Connect widgets in a specific row"""
        try:
            col = self.data_manager.table_columns.index('product_name')
            widget = self.table.cellWidget(row, col)
            if widget and hasattr(widget, 'textChanged'):
                widget.textChanged.connect(lambda text, r=row: self._on_product_name_changed(r, text))
            if widget and hasattr(widget, 'editingFinished'):
                widget.editingFinished.connect(lambda r=row: self._on_product_selection_finished(r))
        except (ValueError, AttributeError):
            pass
    
    def _on_item_changed(self, item):
        """Handle item changes"""
        if self._updating:
            return
        
        row = item.row()
        col = item.column()
        
        if col < len(self.data_manager.table_columns):
            param_key = self.data_manager.table_columns[col]
            
            if param_key in ['quantity', 'unit_price']:
                self._update_row_subtotal(row)
        
        # Ensure empty row management
        if not self.empty_row_manager._is_row_empty(row):
            self.empty_row_manager.ensure_single_empty_row()
            self._reconnect_all_widgets()
        
        self.items_changed_callback()
    
    def _on_product_name_changed(self, row, text):
        """Handle product name text changes"""
        if self._updating:
            return
        
        # Update corresponding table item
        try:
            col = self.data_manager.table_columns.index('product_name')
            item = self.table.item(row, col)
            if not item:
                item = QTableWidgetItem()
                self.table.setItem(row, col, item)
            
            self._updating = True
            item.setText(text)
            self._updating = False
        except (ValueError, IndexError):
            pass
    
    def _on_product_selection_finished(self, row):
        """Handle when product selection is completed"""
        product_name = self.empty_row_manager._get_product_name(row)
        if product_name:
            self._handle_product_selection(row, product_name)
            self.empty_row_manager.ensure_single_empty_row()
            self._reconnect_all_widgets()
            self.items_changed_callback()
    
    def _handle_product_selection(self, row, product_name):
        """Handle product selection and auto-fill"""
        temp_item = self.data_manager.item_class(0, self.data_manager.database)
        temp_item.set_value('product_name', product_name)
        
        # Auto-fill quantity if empty
        self._auto_fill_quantity(row)
        
        # Auto-fill unit price
        self._auto_fill_unit_price(row, temp_item)
        
        # Update preview
        self._update_preview(row, temp_item)
        
        # Update subtotal
        self._update_row_subtotal(row)
    
    def _auto_fill_quantity(self, row):
        """Auto-fill quantity with default value"""
        try:
            col = self.data_manager.table_columns.index('quantity')
            qty_item = self.table.item(row, col)
            
            current_qty = 0
            if qty_item and qty_item.text().strip():
                try:
                    current_qty = float(qty_item.text())
                except ValueError:
                    current_qty = 0
            
            if current_qty == 0:
                if not qty_item:
                    qty_item = QTableWidgetItem()
                    self.table.setItem(row, col, qty_item)
                qty_item.setText("1")
        except ValueError:
            pass
    
    def _auto_fill_unit_price(self, row, temp_item):
        """Auto-fill unit price from product data"""
        try:
            col = self.data_manager.table_columns.index('unit_price')
            unit_price = temp_item.get_value('unit_price')
            
            if unit_price is not None:
                price_item = self.table.item(row, col)
                if not price_item:
                    price_item = QTableWidgetItem()
                    self.table.setItem(row, col, price_item)
                price_item.setText(str(unit_price))
        except ValueError:
            pass
    
    def _update_preview(self, row, temp_item):
        """Update preview image"""
        try:
            col = self.data_manager.table_columns.index('product_preview')
            if hasattr(temp_item, 'get_product_preview'):
                preview_path = temp_item.get_product_preview()
                container_widget = self.table.cellWidget(row, col)
                if container_widget:
                    for child in container_widget.findChildren(PreviewWidget):
                        if preview_path:
                            child.set_image_path(preview_path)
                        break
        except ValueError:
            pass
    
    def _update_row_subtotal(self, row):
        """Update subtotal for a row"""
        try:
            qty_col = self.data_manager.table_columns.index('quantity')
            price_col = self.data_manager.table_columns.index('unit_price')
            subtotal_col = self.data_manager.table_columns.index('subtotal')
            
            qty_item = self.table.item(row, qty_col)
            price_item = self.table.item(row, price_col)
            
            quantity = float(qty_item.text()) if qty_item and qty_item.text().strip() else 0.0
            unit_price = float(price_item.text()) if price_item and price_item.text().strip() else 0.0
            subtotal = quantity * unit_price
            
            subtotal_item = self.table.item(row, subtotal_col)
            if not subtotal_item:
                subtotal_item = QTableWidgetItem()
                self.table.setItem(row, subtotal_col, subtotal_item)
                subtotal_item.setFlags(subtotal_item.flags() & ~Qt.ItemIsEditable)
            
            subtotal_item.setText(f"{subtotal:.2f}")
            
        except (ValueError, AttributeError, IndexError):
            pass
    
    def _reconnect_all_widgets(self):
        """Reconnect all widget events after table changes"""
        for row in range(self.table.rowCount()):
            self._connect_row_widgets(row)


class OperationsTableWidget(QWidget):
    """Clean operations table with proper separation of concerns"""
    
    items_changed = Signal()
    
    def __init__(self, item_class, parent_operation=None, database=None, columns=None, parent=None):
        super().__init__(parent)
        
        # Core components
        self.data_manager = TableDataManager(item_class, database)
        self.parent_operation = parent_operation
        
        # Override columns if provided
        if columns:
            self.data_manager.table_columns = columns
        
        # Setup UI
        self._setup_ui()
        
        # Create managers
        self.row_factory = TableRowFactory(self.data_manager, self._delete_row)
        self.empty_row_manager = EmptyRowManager(self.table, self.row_factory)
        self.event_handler = TableEventHandler(self.table, self.data_manager, 
                                             self.empty_row_manager, self._on_items_changed)
        
        # Load data
        self.refresh_table()
    
    def _setup_ui(self):
        """Setup user interface"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.table = QTableWidget()
        self._configure_table()
        
        layout.addWidget(self.table)
    
    def _configure_table(self):
        """Configure table properties"""
        # Set columns
        headers = self.data_manager.get_column_headers()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        
        # Table properties
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(45)
        
        # Column widths
        header = self.table.horizontalHeader()
        for i, param_key in enumerate(self.data_manager.table_columns):
            if param_key == 'product_preview':
                self.table.setColumnWidth(i, 70)
                header.setSectionResizeMode(i, QHeaderView.Fixed)
            elif param_key == 'delete_action':
                self.table.setColumnWidth(i, 50)
                header.setSectionResizeMode(i, QHeaderView.Fixed)
            else:
                header.setSectionResizeMode(i, QHeaderView.Stretch)
        
        # Styling
        self._apply_theme()
    
    def refresh_table(self):
        """Refresh table data"""
        self.table.setRowCount(0)
        
        # Load existing items
        items = self.data_manager.load_items_from_operation(self.parent_operation)
        for item in items:
            row = self.table.rowCount()
            self.table.setRowCount(row + 1)
            self.row_factory.create_data_row(self.table, row, item)
        
        # Ensure empty row
        self.empty_row_manager.ensure_single_empty_row()
        
        # Setup events
        self.event_handler.setup_event_connections()
    
    def get_current_table_data(self):
        """Get all non-empty rows as data dictionaries"""
        items_data = []
        
        for row in range(self.table.rowCount()):
            if not self.empty_row_manager._is_row_empty(row):
                row_data = self.data_manager.extract_row_data(self.table, row)
                if row_data.get('product_name'):
                    items_data.append(row_data)
        
        return items_data
    
    def get_items_data(self):
        """Get items as object instances (compatibility method)"""
        items = []
        items_data = self.get_current_table_data()
        
        for item_data in items_data:
            item = self.data_manager.item_class(0, self.data_manager.database)
            for key, value in item_data.items():
                item.set_value(key, value)
            
            # Only include items with valid product_id
            try:
                if hasattr(item, 'get_value') and item.get_value('product_id'):
                    items.append(item)
            except Exception:
                items.append(item)  # Include if we can't check product_id
        
        return items
    
    def _delete_row(self, row):
        """Delete a specific row"""
        if row < self.table.rowCount():
            self.table.removeRow(row)
            self.empty_row_manager.ensure_single_empty_row()
            self.event_handler._reconnect_all_widgets()
            self._on_items_changed()
    
    def _on_items_changed(self):
        """Handle items changed event"""
        self.items_changed.emit()
    
    def _apply_theme(self):
        """Apply styling"""
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