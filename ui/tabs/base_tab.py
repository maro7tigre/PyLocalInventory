"""
Base Tab Class - Enhanced to better support operations
Unified table experience for all entities (Products, Clients, Suppliers, Sales, Imports)
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QTableWidget, QTableWidgetItem, QHeaderView, 
                               QMessageBox, QPushButton, QAbstractItemView,
                               QStyledItemDelegate, QLineEdit, QComboBox)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt
from ui.widgets.themed_widgets import RedButton, BlueButton, GreenButton
from ui.widgets.preview_widget import PreviewWidget
from ui.widgets.autocomplete_widgets import AutoCompleteLineEdit
from datetime import datetime
import re


class BaseTableDelegate(QStyledItemDelegate):
    """Custom delegate for table with autocomplete and read-only cells"""
    
    def __init__(self, base_tab, parent=None):
        super().__init__(parent)
        self.base_tab = base_tab
    
    def createEditor(self, parent, option, index):
        """Create appropriate editor based on column and permissions"""
        col = index.column()
        column_key = self.base_tab.table_columns[col]
        
        # Check if this column is editable
        if not self.base_tab.is_column_editable(column_key):
            return None  # No editor for read-only cells
        
        # Check if the item itself is editable (for widget cells)
        item = self.base_tab.table.item(index.row(), index.column())
        if item and not (item.flags() & Qt.ItemIsEditable):
            return None  # No editor for non-editable items
        
        # Don't create editors for widget cells (like images)
        widget = self.base_tab.table.cellWidget(index.row(), index.column())
        if widget is not None:
            return None  # No editor for widget cells
        
        # Get parameter info for autocomplete
        param_info = self.base_tab.get_column_param_info(column_key)
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
                self.base_tab.update_cell_in_database(index.row(), index.column(), new_value)


class BaseTab(QWidget):
    """Base tab with editable table - unified for all entities including operations"""
    
    def __init__(self, object_class, dialog_class, database=None, parent=None):
        super().__init__(parent)
        self.object_class = object_class
        self.dialog_class = dialog_class
        self.database = database
        self.parent_widget = parent
        
        # Get class info
        temp_object = object_class(0, database)
        self.table_columns = temp_object.get_visible_parameters("table")
        self.table_permissions = temp_object.available_parameters["table"]
        self.parameter_definitions = temp_object.parameters
        self.section = temp_object.section
        
        # Store all items for filtering
        self.all_items = []
        self.filtered_items = []
        
        self.setup_ui()
        self.refresh_table()
    
    def setup_ui(self):
        """Setup tab interface"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Title label (larger)
        title = QLabel(f"{self.section} Management")
        title.setStyleSheet("font-size: 28px; font-weight: bold;")
        layout.addWidget(title)
        
        # Search and controls layout
        controls_layout = QHBoxLayout()
        
        # Search bar
        self.search_bar = AutoCompleteLineEdit(self, self.get_search_options())
        self.search_bar.setPlaceholderText(f"Search {self.section.lower()}...")
        self.search_bar.textChanged.connect(self.filter_table)
        controls_layout.addWidget(self.search_bar)
        
        # Order dropdown
        self.order_combo = QComboBox()
        self.setup_order_options()
        self.order_combo.currentTextChanged.connect(self.filter_table)
        controls_layout.addWidget(self.order_combo)
        
        controls_layout.addStretch()
        
        # Action buttons
        entity_name = self.section[:-1] if self.section.endswith('s') else self.section
        
        self.add_btn = BlueButton(f"Add {entity_name}")
        # Increase size only for toolbar buttons next to search bar
        self.add_btn.setStyleSheet(self.add_btn.styleSheet() + "\nQPushButton { font-size: 14px; padding: 5px 10px; }")
        self.add_btn.setMinimumHeight(20)
        self.add_btn.clicked.connect(self.add_item)
        controls_layout.addWidget(self.add_btn)
        
        self.edit_btn = BlueButton(f"Edit {entity_name}")
        self.edit_btn.setStyleSheet(self.edit_btn.styleSheet() + "\nQPushButton { font-size: 14px; padding: 5px 10px; }")
        self.edit_btn.setMinimumHeight(20)
        self.edit_btn.clicked.connect(self.edit_item)
        controls_layout.addWidget(self.edit_btn)
        
        self.delete_btn = RedButton(f"Delete {entity_name}")
        self.delete_btn.setStyleSheet(self.delete_btn.styleSheet() + "\nQPushButton { font-size: 14px; padding: 5px 10px; }")
        self.delete_btn.setMinimumHeight(20)
        self.delete_btn.clicked.connect(self.delete_item)
        controls_layout.addWidget(self.delete_btn)
        
        self.refresh_btn = GreenButton("Refresh")
        self.refresh_btn.setStyleSheet(self.refresh_btn.styleSheet() + "\nQPushButton { font-size: 14px; padding: 5px 10px; }")
        self.refresh_btn.setMinimumHeight(20)
        self.refresh_btn.clicked.connect(self.refresh_table)
        controls_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(controls_layout)
        
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
                temp_obj = self.object_class(0, self.database)
                display_name = temp_obj.get_display_name(column_key)
                headers.append(display_name)
            else:
                headers.append(column_key)
        
        self.table.setHorizontalHeaderLabels(headers)

        # Table properties
        header = self.table.horizontalHeader()
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)

        # Set row height to accommodate images
        self.table.verticalHeader().setDefaultSectionSize(70)

        # Set custom delegate for editing
        self.delegate = BaseTableDelegate(self)
        self.table.setItemDelegate(self.delegate)

        # Set specific column widths (ID fixed at 100px, image/preview 80px, others stretch)
        for i, column_key in enumerate(self.table_columns):
            if column_key == 'id':
                header.setSectionResizeMode(i, QHeaderView.Fixed)
                self.table.setColumnWidth(i, 80)
            elif 'image' in column_key or 'preview' in column_key:
                header.setSectionResizeMode(i, QHeaderView.Fixed)
                self.table.setColumnWidth(i, 80)
            else:
                header.setSectionResizeMode(i, QHeaderView.Stretch)
    
    def is_column_editable(self, column_key):
        """Check if column is editable (has 'w' permission)"""
        permission = self.table_permissions.get(column_key, '')
        return 'w' in permission.lower()
    
    def get_column_param_info(self, column_key):
        """Get parameter info for column"""
        return self.parameter_definitions.get(column_key, {})
    
    def refresh_table(self):
        """Refresh table data from database"""
        if not self.database:
            QMessageBox.warning(self, "Error", "No database connection")
            return

        try:
            print(f"🔄 Refreshing {self.section} table...")
            
            # Clear table first
            self.table.setRowCount(0)
            
            # Get items from database
            items_data = self.database.get_items(self.section)
            self.all_items = []
            
            print(f"📦 Found {len(items_data)} items in database for {self.section}")

            for item_data in items_data:
                # Create object instance to get calculated values
                try:
                    obj = self.object_class(item_data.get('ID', 0), self.database)

                    # Load data from database
                    for key, value in item_data.items():
                        if key in obj.parameters and not obj.is_parameter_calculated(key):
                            # Map database field names to parameter names
                            param_key = key
                            if key == 'ID':
                                param_key = 'id'

                            try:
                                if param_key in obj.parameters:
                                    obj.set_value(param_key, value)
                            except (KeyError, ValueError):
                                pass  # Skip invalid parameters

                    self.all_items.append(obj)
                    # For operations (Sales / Imports), refresh external snapshots so renamed
                    # client/supplier names appear without manual reopen. This will persist
                    # only if name actually changed (handled inside method).
                    try:
                        if hasattr(obj, 'refresh_external_snapshots'):
                            obj.refresh_external_snapshots()
                    except Exception as snap_e:
                        print(f"Snapshot refresh skipped for {self.section} ID {obj.id}: {snap_e}")

                except Exception as e:
                    print(f"Error processing {self.section} item: {e}")
                    continue

            print(f"✓ Loaded {len(self.all_items)} objects for {self.section}")
            
            # Update search options
            self.search_bar.update_options(self.get_search_options())

            # Apply current filter and repopulate table
            self.filter_table()
            
            print(f"✓ {self.section} table refresh complete")

        except Exception as e:
            print(f"Error refreshing {self.section} table: {e}")
            QMessageBox.critical(self, "Error", f"Failed to refresh {self.section}: {e}")
    
    def refresh_on_tab_switch(self):
        """Refresh data when tab becomes visible - lighter refresh for better performance"""
        try:
            # Only refresh if database is connected
            if self.database and hasattr(self.database, 'conn') and self.database.conn:
                # Refresh table to get latest data including quantity updates from operations
                self.refresh_table()
                print(f"✓ Refreshed {self.section} tab data")
        except Exception as e:
            print(f"Error refreshing {self.section} tab on switch: {e}")
    
    def set_table_cell(self, row, col, column_key, obj):
        """Set table cell value based on parameter type"""
        try:
            value = obj.get_value(column_key)
            param_info = obj.parameters.get(column_key, {})
            param_type = param_info.get('type', 'string')
            
            if param_type == 'image' or 'image' in column_key or 'preview' in column_key:
                # Create preview widget for image with fixed size
                category = self.get_preview_category()
                preview_widget = PreviewWidget(60, category)
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
            
            elif param_type == 'date':
                # Format date as day-month-year
                formatted_value = self.format_date_for_display(value)
                
                item = QTableWidgetItem(formatted_value)
                item.setData(Qt.UserRole, value)  # Store raw value
                item.setData(Qt.UserRole + 1, obj.id)  # Store object ID
                
                # Make read-only cells non-editable
                if not self.is_column_editable(column_key):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                
                self.table.setItem(row, col, item)
            
            elif param_type == 'float':
                # Format float values with unit if available
                unit = param_info.get('unit', '')
                if value is not None:
                    formatted_value = f"{float(value):.2f} {unit}".strip()
                else:
                    formatted_value = f"0.00 {unit}".strip()
                
                item = QTableWidgetItem(formatted_value)
                item.setData(Qt.UserRole, value)  # Store raw value
                item.setData(Qt.UserRole + 1, obj.id)  # Store object ID
                
                # Make read-only cells non-editable
                if not self.is_column_editable(column_key):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                
                self.table.setItem(row, col, item)
            
            elif param_type == 'int':
                # Format integer values
                formatted_value = str(int(value)) if value is not None else "0"
                item = QTableWidgetItem(formatted_value)
                item.setData(Qt.UserRole, value)  # Store raw value
                item.setData(Qt.UserRole + 1, obj.id)  # Store object ID
                
                # Make read-only cells non-editable
                if not self.is_column_editable(column_key):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                
                self.table.setItem(row, col, item)
            
            else:
                # String and other types - handle date formatting
                if column_key == 'date' and value:
                    # Format date as dd-mm-yyyy
                    formatted_value = self.format_date_display(value)
                else:
                    formatted_value = str(value) if value is not None else ""
                
                item = QTableWidgetItem(formatted_value)
                item.setData(Qt.UserRole, value)  # Store raw value
                item.setData(Qt.UserRole + 1, obj.id)  # Store object ID
                
                # Make read-only cells non-editable
                if not self.is_column_editable(column_key):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                
                self.table.setItem(row, col, item)
        
        except Exception as e:
            print(f"Error setting cell ({row}, {col}): {e}")
            item = QTableWidgetItem("Error")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, col, item)
    
    def format_date_for_display(self, date_value):
        """Format date value for display as day-month-year"""
        if not date_value:
            return ""
        
        try:
            # Handle different input formats
            if isinstance(date_value, str):
                # Try parsing different date formats
                date_formats = ['%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d']
                for fmt in date_formats:
                    try:
                        date_obj = datetime.strptime(date_value, fmt)
                        return date_obj.strftime('%d-%m-%Y')
                    except ValueError:
                        continue
                # If no format matches, return as is
                return str(date_value)
            elif hasattr(date_value, 'strftime'):
                # Already a date/datetime object
                return date_value.strftime('%d-%m-%Y')
            else:
                return str(date_value)
        except Exception as e:
            print(f"Error formatting date {date_value}: {e}")
            return str(date_value)
    
    def get_search_options(self):
        """Get autocomplete options for search - override in subclasses"""
        return []
    
    def setup_order_options(self):
        """Setup order dropdown options - override in subclasses"""
        # Default ordering options
        self.order_combo.addItem("Default")
    
    def get_searchable_fields(self):
        """Get fields that can be searched - override in subclasses"""
        return ['name', 'username']
    
    def parse_date_search(self, search_text):
        """Parse date search queries like 'dd-mm-yyyy' or 'dd-mm-yyyy/dd-mm-yyyy'"""
        date_patterns = [
            r'(\d{1,2}-\d{1,2}-\d{4})/(\d{1,2}-\d{1,2}-\d{4})',  # Range: dd-mm-yyyy/dd-mm-yyyy
            r'(\d{1,2}-\d{1,2}-\d{4})'  # Single: dd-mm-yyyy
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, search_text)
            if match:
                if len(match.groups()) == 2:  # Date range
                    try:
                        start_date = datetime.strptime(match.group(1), '%d-%m-%Y').date()
                        end_date = datetime.strptime(match.group(2), '%d-%m-%Y').date()
                        return ('range', start_date, end_date)
                    except ValueError:
                        pass
                else:  # Single date
                    try:
                        date_obj = datetime.strptime(match.group(1), '%d-%m-%Y').date()
                        return ('single', date_obj)
                    except ValueError:
                        pass
        
        return None
    
    def matches_search(self, obj, search_text):
        """Check if object matches search criteria - override in subclasses for specific logic"""
        if not search_text:
            return True
        
        search_lower = search_text.lower()
        searchable_fields = self.get_searchable_fields()
        
        # Check each searchable field
        for field in searchable_fields:
            try:
                value = obj.get_value(field)
                if value and search_lower in str(value).lower():
                    return True
            except:
                pass
        
        return False
    
    def sort_items(self, items, order_option):
        """Sort items based on order option - override in subclasses for specific logic"""
        if not order_option or order_option == "Default":
            return items
        
        # Parse sort option (format: "Field ↑" or "Field ↓")
        if " ↑" in order_option:
            field = order_option.replace(" ↑", "").lower().replace(" ", "_")
            reverse = False
        elif " ↓" in order_option:
            field = order_option.replace(" ↓", "").lower().replace(" ", "_")
            reverse = True
        else:
            return items
        
        try:
            # Sort based on field type
            if field in ['price', 'unit_price', 'sale_price', 'quantity', 'total', 'subtotal']:
                items.sort(key=lambda x: float(x.get_value(field) or 0), reverse=reverse)
            elif field == 'date':
                items.sort(key=lambda x: self.parse_date_for_sorting(x.get_value(field)), reverse=reverse)
            else:
                items.sort(key=lambda x: str(x.get_value(field) or "").lower(), reverse=reverse)
        except Exception as e:
            print(f"Error sorting by {field}: {e}")
        
        return items
    
    def format_date_display(self, date_value):
        """Format date for display as dd-mm-yyyy"""
        if not date_value:
            return ""
        
        try:
            # Try different input formats and convert to dd-mm-yyyy
            input_formats = ['%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d']
            
            for fmt in input_formats:
                try:
                    date_obj = datetime.strptime(str(date_value), fmt)
                    return date_obj.strftime('%d-%m-%Y')
                except ValueError:
                    continue
            
            # If no format matches, return as-is
            return str(date_value)
        except:
            return str(date_value)
    
    def parse_date_for_sorting(self, date_value):
        """Parse date value for sorting"""
        if not date_value:
            return datetime.min
        
        try:
            # Try different date formats
            formats = ['%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y']
            for fmt in formats:
                try:
                    return datetime.strptime(str(date_value), fmt)
                except ValueError:
                    continue
            return datetime.min
        except:
            return datetime.min
    
    def filter_table(self):
        """Filter and sort table based on search and order criteria"""
        if not self.all_items:
            return
        
        search_text = self.search_bar.text().strip()
        order_option = self.order_combo.currentText()
        
        # Filter items
        filtered = [item for item in self.all_items if self.matches_search(item, search_text)]
        
        # Sort items
        filtered = self.sort_items(filtered, order_option)
        
        # Store filtered items for later use
        self.filtered_items = filtered
        
        # Update table
        self.populate_table_with_items(filtered)
    
    def populate_table_with_items(self, items):
        """Populate table with given items"""
        self.table.setRowCount(len(items))
        
        for row, obj in enumerate(items):
            try:
                # Set table data
                for col, column_key in enumerate(self.table_columns):
                    self.set_table_cell(row, col, column_key, obj)
            except Exception as e:
                print(f"Error processing {self.section} row {row}: {e}")
                # Fallback: show basic data
                for col, column_key in enumerate(self.table_columns):
                    try:
                        value = obj.get_value(column_key) if hasattr(obj, 'get_value') else ""
                        item = QTableWidgetItem(str(value))
                        item.setData(Qt.UserRole, value)
                        item.setData(Qt.UserRole + 1, obj.id if hasattr(obj, 'id') else 0)
                        self.table.setItem(row, col, item)
                    except:
                        item = QTableWidgetItem("Error")
                        self.table.setItem(row, col, item)
    
    def get_preview_category(self):
        """Override in subclasses to specify preview category"""
        return "individual"  # Default category
    
    def update_cell_in_database(self, row, col, new_value):
        """Update database when cell is edited"""
        try:
            # Get object ID - enhanced for better reliability
            obj_id = self.get_object_id_from_row(row)
            if not obj_id:
                return
            
            column_key = self.table_columns[col]
            
            # Update database
            data = {column_key: new_value}
            if self.database.update_item(obj_id, data, self.section):
                print(f"Updated {column_key} to '{new_value}' for {self.section} {obj_id}")
                # Refresh only the specific row to show calculated field updates
                self.refresh_table()
            else:
                QMessageBox.warning(self, "Error", f"Failed to update {column_key}")
                # Revert the change
                self.refresh_table()
        
        except Exception as e:
            print(f"Error updating cell in database: {e}")
            QMessageBox.critical(self, "Error", f"Database update failed: {e}")
            self.refresh_table()
    
    def get_object_id_from_row(self, row):
        """Get object ID from any cell in the row - enhanced method"""
        # Try to get ID from stored UserRole data
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item:
                obj_id = item.data(Qt.UserRole + 1)
                if obj_id and obj_id > 0:
                    return int(obj_id)
        
        # Fallback: try to find ID column
        if 'id' in self.table_columns:
            id_col = self.table_columns.index('id')
            item = self.table.item(row, id_col)
            if item:
                try:
                    return int(item.text())
                except ValueError:
                    pass
        
        # Last resort: try first column if it looks like an ID
        first_item = self.table.item(row, 0)
        if first_item and first_item.text().isdigit():
            return int(first_item.text())
        
        return None
    
    def get_selected_id(self):
        """Get ID of selected item"""
        row = self.table.currentRow()
        if row == -1:
            return None
        
        return self.get_object_id_from_row(row)
    
    def add_item(self):
        """Add new item"""
        try:
            dialog = self.dialog_class(None, self.database, self.parent_widget)
            if dialog.exec():
                self.refresh_table()
        
        except ImportError as e:
            QMessageBox.warning(self, "Error", f"Could not import dialog: {e}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add {self.section[:-1].lower()}: {e}")
    
    def edit_item(self):
        """Edit selected item"""
        obj_id = self.get_selected_id()
        if obj_id is None:
            QMessageBox.warning(self, "Error", f"Please select a {self.section[:-1].lower()} to edit")
            return
        
        try:
            dialog = self.dialog_class(obj_id, self.database, self.parent_widget)
            if dialog.exec():
                self.refresh_table()
        
        except ImportError as e:
            QMessageBox.warning(self, "Error", f"Could not import dialog: {e}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to edit {self.section[:-1].lower()}: {e}")
    
    def delete_item(self):
        """Delete selected item"""
        obj_id = self.get_selected_id()
        if obj_id is None:
            QMessageBox.warning(self, "Error", f"Please select a {self.section[:-1].lower()} to delete")
            return
        
        # Get item name for confirmation
        row = self.table.currentRow()
        name_col = None
        
        # Find name column
        for i, column_key in enumerate(self.table_columns):
            if column_key == 'name':
                name_col = i
                break
        
        item_name = f"ID {obj_id}"
        if name_col is not None:
            name_item = self.table.item(row, name_col)
            if name_item:
                item_name = name_item.text() or f"ID {obj_id}"
        
        reply = QMessageBox.question(
            self, "Confirm Deletion", 
            f"Are you sure you want to delete '{item_name}'?\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                if self.database.delete_item(obj_id, self.section):
                    # Force refresh table to show updated data
                    self.refresh_table()
                    print(f"✓ Deleted {self.section[:-1].lower()} '{item_name}' and refreshed table")
                else:
                    QMessageBox.critical(self, "Error", f"Failed to delete '{item_name}'")  
            except Exception as e:
                print(f"Error deleting {self.section[:-1].lower()}: {e}")
                QMessageBox.critical(self, "Error", f"Error deleting {self.section[:-1].lower()}: {e}")
    
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
            QComboBox {
                background-color: #2D2D30;
                color: #E0E0E0;
                border: 1px solid #3E3E42;
                padding: 5px;
                border-radius: 3px;
                font-size: 16px; /* larger order selector font */
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                border: none;
                width: 10px;
                height: 10px;
            }
            QComboBox QAbstractItemView {
                background-color: #2D2D30;
                color: #E0E0E0;
                selection-background-color: #2196F3;
                font-size: 16px; /* larger dropdown items */
            }
            QLineEdit {
                background-color: #2D2D30;
                color: #E0E0E0;
                border: 1px solid #3E3E42;
                padding: 5px;
                border-radius: 3px;
                font-size: 16px; /* larger search bar font */
            }
            QLineEdit:focus {
                border: 2px solid #2196F3;
            }
            QTableWidget {
                background-color: #2D2D30;
                gridline-color: #3E3E42;
                color: #E0E0E0;
                border: 1px solid #3E3E42;
                alternate-background-color: #252526;
                selection-background-color: transparent;
                font-size: 16px; /* larger cell font */
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
                font-size: 16px; /* larger header font */
            }
        """)