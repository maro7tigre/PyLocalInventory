"""
Table Parameter Widget - Simple editable table for operations items
Clean and minimal implementation that just works
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
                               QTableWidgetItem, QHeaderView, QAbstractItemView, 
                               QLabel, QPushButton)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont
from ui.widgets.themed_widgets import RedButton, BlueButton
try:
    from ui.widgets.preview_widget import PreviewWidget
except ImportError:
    PreviewWidget = None


class DeleteButtonWidget(QWidget):
    """Simple delete button widget"""
    
    delete_clicked = Signal(int)
    
    def __init__(self, row_index, parent=None):
        super().__init__(parent)
        self.row_index = row_index
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.delete_btn = RedButton("🗑️")
        self.delete_btn.setFixedSize(25, 25)
        self.delete_btn.clicked.connect(lambda: self.delete_clicked.emit(self.row_index))
        
        layout.addWidget(self.delete_btn)


class TableParameterWidget(QWidget):
    """Simple editable table for operations items"""
    
    items_changed = Signal()
    
    def __init__(self, item_class, parent_operation=None, database=None, 
                 columns=None, parent=None):
        super().__init__(parent)
        self.item_class = item_class
        self.parent_operation = parent_operation
        self.database = database
        self.items = []
        
        # Get info from item class
        temp_item = item_class(0, database)
        self.parameters = temp_item.parameters
        self.permissions = temp_item.available_parameters.get("table", {})
        self.section = temp_item.section
        
        # Columns to show
        if columns:
            self.table_columns = columns
        else:
            self.table_columns = temp_item.get_visible_parameters("table")
        
        self.setup_ui()
        self.apply_theme()
        self.load_existing_items()
        self.add_empty_row()
    
    def load_existing_items(self):
        """Load existing items from parent operation"""
        if self.parent_operation and hasattr(self.parent_operation, 'get_value'):
            try:
                items_data = self.parent_operation.get_value('items')
                if items_data and isinstance(items_data, list):
                    for item_obj in items_data:
                        if hasattr(item_obj, 'parameters'):
                            self.items.append(item_obj)
                            self.add_item_row(item_obj, is_empty=False)
            except Exception as e:
                print(f"Error loading existing items: {e}")
    
    def add_empty_row(self):
        """Add an empty row"""
        empty_item = self.item_class(0, self.database)
        
        # Set parent operation ID
        if self.parent_operation and hasattr(self.parent_operation, 'id'):
            if hasattr(empty_item, 'set_value'):
                if self.section == 'Sales_Items':
                    empty_item.set_value('sales_id', self.parent_operation.id)
                elif self.section == 'Import_Items':
                    empty_item.set_value('import_id', self.parent_operation.id)
        
        self.items.append(empty_item)
        self.add_item_row(empty_item, is_empty=True)
    
    def setup_ui(self):
        """Setup table interface"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Optional header
        if hasattr(self, 'show_header') and self.show_header:
            header_layout = QHBoxLayout()
            
            title = QLabel(f"{self.section} Items")
            title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
            header_layout.addWidget(title)
            header_layout.addStretch()
            
            # Add control buttons if needed
            clear_btn = BlueButton("Clear All")
            clear_btn.clicked.connect(self.clear_all_items)
            header_layout.addWidget(clear_btn)
            
            layout.addLayout(header_layout)
        
        # Table setup
        self.table = QTableWidget()
        self.setup_table()
        layout.addWidget(self.table)
    
    def setup_table(self):
        """Setup table"""
        self.table.setColumnCount(len(self.table_columns))
        
        # Headers
        headers = []
        for col in self.table_columns:
            display_name = self.parameters.get(col, {}).get('display_name', {}).get('en', col)
            headers.append(display_name)
        
        self.table.setHorizontalHeaderLabels(headers)
        
        # Properties
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        
        # Make button columns narrow
        for i, col in enumerate(self.table_columns):
            param_info = self.parameters.get(col, {})
            if param_info.get('type') == 'button':
                self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                self.table.setColumnWidth(i, 40)
        
        # Connect signal
        self.table.itemChanged.connect(self.on_cell_changed)
    
    def refresh_calculated_fields(self, row):
        """Refresh calculated fields for a row"""
        if row >= len(self.items):
            return
        
        item_obj = self.items[row]
        
        for col_idx, param_key in enumerate(self.table_columns, start=1):
            if (hasattr(item_obj, 'is_parameter_calculated') and 
                item_obj.is_parameter_calculated(param_key)):
                
                value = item_obj.get_value(param_key)
                param_info = self.parameters.get(param_key, {})
                param_type = param_info.get('type', 'string')
                
                if param_type == 'float':
                    unit = param_info.get('unit', '')
                    display_value = f"{float(value):.2f} {unit}".strip() if value else ""
                else:
                    display_value = str(value) if value else ""
                
                item = self.table.item(row, col_idx)
                if item:
                    self.table.blockSignals(True)
                    item.setText(display_value)
                    self.table.blockSignals(False)
    
    def add_item_row(self, item_obj, is_empty=False):
        """Add a row for an item object"""
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        # Add data cells
        for col_idx, param_key in enumerate(self.table_columns):
            self.set_table_cell(row, col_idx, param_key, item_obj, is_empty)
    
    def set_table_cell(self, row, col, param_key, item_obj, is_empty=False):
        """Set table cell value"""
        try:
            value = item_obj.get_value(param_key) if hasattr(item_obj, 'get_value') else ""
            param_info = self.parameters.get(param_key, {})
            param_type = param_info.get('type', 'string')
            
            if param_type == 'button':
                # Handle button parameters
                if not is_empty:  # Only show buttons for non-empty rows
                    # Create container widget for proper alignment like images
                    button_widget = QWidget()
                    button_layout = QHBoxLayout(button_widget)
                    button_layout.setContentsMargins(0, 0, 0, 0)
                    
                    button_text = param_info.get('text', '🗑️')
                    button = RedButton(button_text)
                    button.setFixedSize(25, 25)
                    
                    # Connect to action if available
                    action = param_info.get('action')
                    if action and callable(action):
                        button.clicked.connect(lambda checked=False, a=action, r=row, obj=item_obj: self.handle_button_action(a, r, obj))
                    
                    # Center the button
                    button_layout.addStretch()
                    button_layout.addWidget(button)
                    button_layout.addStretch()
                    
                    self.table.setCellWidget(row, col, button_widget)
                else:
                    # Empty cell for empty rows
                    self.table.setItem(row, col, QTableWidgetItem(""))
                return
            
            # For empty rows, show truly empty cells
            if is_empty or not value:
                display_value = ""
            elif param_type == 'float':
                unit = param_info.get('unit', '')
                display_value = f"{float(value):.2f} {unit}".strip()
            elif param_type == 'int':
                display_value = str(int(value))
            else:
                display_value = str(value)
            
            item = QTableWidgetItem(display_value)
            item.setData(Qt.ItemDataRole.UserRole, param_key)
            
            # Make calculated fields read-only
            if (hasattr(item_obj, 'is_parameter_calculated') and 
                item_obj.is_parameter_calculated(param_key)):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            
            self.table.setItem(row, col, item)
            
        except Exception as e:
            print(f"Error setting cell: {e}")
            self.table.setItem(row, col, QTableWidgetItem(""))
    
    def handle_button_action(self, action, row, item_obj):
        """Handle button click actions"""
        try:
            result = action()  # Call the action method (like delete_self)
            
            # For delete actions, always remove the row from the UI
            # regardless of database success (empty items don't have DB records)
            if 0 <= row < len(self.items):
                self.items.pop(row)
                self.table.removeRow(row)
                
                # Update button widget references for remaining rows
                self.update_button_references()
                
                self.items_changed.emit()
                print(f"Row {row} deleted successfully")
                
        except Exception as e:
            print(f"Error handling button action: {e}")
    
    def update_button_references(self):
        """Update button references after row deletion"""
        for row in range(self.table.rowCount()):
            for col_idx, param_key in enumerate(self.table_columns):
                param_info = self.parameters.get(param_key, {})
                if param_info.get('type') == 'button':
                    widget = self.table.cellWidget(row, col_idx)
                    if widget:  # Update the button's action with correct row
                        # Find the button inside the container widget
                        button = None
                        for child in widget.findChildren(RedButton):
                            button = child
                            break
                        
                        if button and row < len(self.items):
                            # Reconnect with updated row and item_obj
                            item_obj = self.items[row]
                            action = param_info.get('action')
                            if action and callable(action):
                                button.clicked.disconnect()  # Disconnect old signal
                                button.clicked.connect(lambda checked=False, a=action, r=row, obj=item_obj: self.handle_button_action(a, r, obj))
    
    def delete_row(self, row_index):
        """Delete a row"""
        if 0 <= row_index < len(self.items):
            item_to_delete = self.items[row_index]
            
            # Delete from database if needed
            if (hasattr(item_to_delete, 'id') and item_to_delete.id and 
                hasattr(item_to_delete, 'database') and item_to_delete.database):
                try:
                    item_to_delete.database.delete_item(item_to_delete.id, self.section)
                except Exception as e:
                    print(f"Error deleting from database: {e}")
            
            # Remove from list and table
            self.items.pop(row_index)
            self.table.removeRow(row_index)
            
            # Update delete button indices
            for row in range(self.table.rowCount()):
                widget = self.table.cellWidget(row, 0)
                if isinstance(widget, DeleteButtonWidget):
                    widget.row_index = row
            
            self.items_changed.emit()
    
    def get_items_data(self):
        """Get all non-empty items"""
        result = []
        for item_obj in self.items:
            has_content = False
            for param_key in self.table_columns:
                if hasattr(item_obj, 'get_value'):
                    value = item_obj.get_value(param_key)
                    if value and str(value).strip():
                        has_content = True
                        break
            if has_content:
                result.append(item_obj)
        return result
    
    def save_all_items(self):
        """Save all items to database"""
        success_count = 0
        for item_obj in self.get_items_data():
            if hasattr(item_obj, 'save_to_database'):
                try:
                    if item_obj.save_to_database():
                        success_count += 1
                except Exception as e:
                    print(f"Error saving item: {e}")
        return success_count
    
    def clear_all_items(self):
        """Clear all items"""
        self.items.clear()
        self.table.setRowCount(0)
        self.add_empty_row()
        self.items_changed.emit()
    
    def on_cell_changed(self, item):
        """Handle cell changes"""
        row = item.row()
        col = item.column()
        
        if row >= len(self.items):
            return
        
        param_key = item.data(Qt.ItemDataRole.UserRole)
        new_value = item.text()
        
        if param_key:
            item_obj = self.items[row]
            if hasattr(item_obj, 'set_value'):
                try:
                    item_obj.set_value(param_key, new_value)
                    self.refresh_calculated_fields(row)
                    
                    # Check if this row just became non-empty and needs buttons
                    if row == len(self.items) - 1:  # Last row
                        if new_value and str(new_value).strip():  # Row now has content
                            # Update button columns for this row
                            for col_idx, col_param in enumerate(self.table_columns):
                                param_info = self.parameters.get(col_param, {})
                                if param_info.get('type') == 'button':
                                    self.set_table_cell(row, col_idx, col_param, item_obj, is_empty=False)
                            
                            # Add new empty row
                            self.check_and_add_empty_row()
                    
                    self.items_changed.emit()
                except Exception as e:
                    print(f"Error: {e}")
    
    def refresh_calculated_fields(self, row):
        """Refresh calculated fields for a specific row"""
        if row >= len(self.items):
            return
        
        item_obj = self.items[row]
        
        for col_idx, param_key in enumerate(self.table_columns, start=1):
            if (hasattr(item_obj, 'is_parameter_calculated') and 
                item_obj.is_parameter_calculated(param_key)):
                
                # Get updated calculated value
                value = item_obj.get_value(param_key)
                param_info = self.parameter_definitions.get(param_key, {})
                
                # Update the cell display
                item = self.table.item(row, col_idx)
                if item:
                    param_type = param_info.get('type', 'string')
                    if param_type == 'float':
                        unit = param_info.get('unit', '')
                        try:
                            formatted_value = f"{float(value):.2f} {unit}".strip()
                        except (ValueError, TypeError):
                            formatted_value = f"0.00 {unit}".strip()
                    else:
                        formatted_value = str(value) if value is not None else ""
                    
                    # Temporarily disconnect signal to avoid recursion
                    self.table.blockSignals(True)
                    item.setText(formatted_value)
                    self.table.blockSignals(False)
    
    def refresh_calculated_fields(self, row):
        """Refresh calculated fields for a row"""
        if row >= len(self.items):
            return
        
        item_obj = self.items[row]
        
        for col_idx, param_key in enumerate(self.table_columns, start=1):
            if (hasattr(item_obj, 'is_parameter_calculated') and 
                item_obj.is_parameter_calculated(param_key)):
                
                value = item_obj.get_value(param_key)
                param_info = self.parameters.get(param_key, {})
                param_type = param_info.get('type', 'string')
                
                if param_type == 'float':
                    unit = param_info.get('unit', '')
                    display_value = f"{float(value):.2f} {unit}".strip() if value else ""
                else:
                    display_value = str(value) if value else ""
                
                item = self.table.item(row, col_idx)
                if item:
                    self.table.blockSignals(True)
                    item.setText(display_value)
                    self.table.blockSignals(False)

    def check_and_add_empty_row(self):
        """Check if we need to add empty row"""
        if not self.items:
            return
        
        # Check if last row has content
        last_item = self.items[-1]
        has_content = False
        
        for param_key in self.table_columns:
            if hasattr(last_item, 'get_value'):
                value = last_item.get_value(param_key)
                if value and str(value).strip():
                    has_content = True
                    break
        
        # Add empty row if last row has content
        if has_content:
            self.add_empty_row()
    
    def delete_row(self, row_index):
        """Delete a row and its associated item"""
        if 0 <= row_index < len(self.items):
            # Get the item to delete
            item_to_delete = self.items[row_index]
            
            # Remove from database if it has an ID
            if (hasattr(item_to_delete, 'id') and item_to_delete.id and 
                hasattr(item_to_delete, 'database') and item_to_delete.database):
                try:
                    item_to_delete.database.delete_item(item_to_delete.id, self.section)
                except Exception as e:
                    print(f"Error deleting item from database: {e}")
            
            # Remove from list and table
            self.items.pop(row_index)
            self.table.removeRow(row_index)
            
            # Update row indices for delete buttons
            self.update_delete_button_indices()
            
            # Emit change signal
            self.items_changed.emit()
    

    
    def apply_theme(self):
        """Apply consistent theming"""
        self.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
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
            QTableWidget::item:focus {
                border: 2px solid #2196F3;
            }
            QHeaderView::section {
                background-color: #252526;
                color: #CCCCCC;
                padding: 5px;
                border: none;
                border-right: 1px solid #3E3E42;
            }
            QLabel {
                color: #E0E0E0;
            }
        """)


# Test wrapper for demonstration
class TestTableParameterWidget(QWidget):
    """Simple test widget"""
    
    def __init__(self):
        super().__init__()
        self.setup_ui()
        self.apply_theme()
    
    def setup_ui(self):
        """Setup test interface"""
        layout = QVBoxLayout(self)
        
        title = QLabel("Table Parameter Widget Test")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        layout.addWidget(title)
        
        # Simple demo item class
        class DemoItem:
            def __init__(self, id, database):
                self.id = id
                self.database = database
                self.section = "Demo_Items"
                self.parameters = {
                    'name': {'type': 'string', 'display_name': {'en': 'Product'}},
                    'qty': {'type': 'int', 'display_name': {'en': 'Quantity'}},
                    'price': {'type': 'float', 'display_name': {'en': 'Price'}, 'unit': '$'},
                    'total': {'type': 'float', 'display_name': {'en': 'Total'}, 'unit': '$'}
                }
                self.available_parameters = {
                    "table": {'name': 'rw', 'qty': 'rw', 'price': 'rw', 'total': 'r'}
                }
                self.values = {'name': '', 'qty': 0, 'price': 0.0, 'total': 0.0}
            
            def get_visible_parameters(self, view_type="table"):
                return ['name', 'qty', 'price', 'total']
            
            def get_value(self, key):
                if key == 'total':
                    return self.values['qty'] * self.values['price']
                return self.values.get(key, '')
            
            def set_value(self, key, value):
                if key in self.parameters:
                    if self.parameters[key]['type'] == 'int':
                        self.values[key] = int(float(value)) if value else 0
                    elif self.parameters[key]['type'] == 'float':
                        self.values[key] = float(value) if value else 0.0
                    else:
                        self.values[key] = str(value)
            
            def is_parameter_calculated(self, key):
                return key == 'total'
        
        # Create table widget
        self.table_widget = TableParameterWidget(DemoItem, None, None)
        self.table_widget.items_changed.connect(lambda: print("Items changed!"))
        layout.addWidget(self.table_widget)
        
        # Control buttons
        controls = QHBoxLayout()
        show_btn = BlueButton("Show Data")
        show_btn.clicked.connect(self.show_data)
        controls.addWidget(show_btn)
        layout.addLayout(controls)
    
    def show_data(self):
        """Show current data"""
        items = self.table_widget.get_items_data()
        print(f"\n=== {len(items)} Items ===")
        for i, item in enumerate(items, 1):
            print(f"Item {i}: {item.values}")
    
    def apply_theme(self):
        """Apply theme"""
        self.setStyleSheet("""
            QWidget { background-color: #2b2b2b; color: #ffffff; }
            QLabel { color: #ffffff; }
        """)

