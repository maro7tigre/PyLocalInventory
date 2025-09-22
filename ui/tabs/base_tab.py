"""
Base Tab Class - Reduces repetition across different entity tabs
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
    """Base tab with editable table - inherit from this for specific entity tabs"""
    
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
        
        self.setup_ui()
        self.refresh_table()
    
    def setup_ui(self):
        """Setup tab interface"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Header with title and buttons
        header_layout = QHBoxLayout()
        
        title = QLabel(f"{self.section} Management")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        # Action buttons
        entity_name = self.section[:-1] if self.section.endswith('s') else self.section
        
        self.add_btn = BlueButton(f"Add {entity_name}")
        self.add_btn.clicked.connect(self.add_item)
        header_layout.addWidget(self.add_btn)
        
        self.edit_btn = BlueButton(f"Edit {entity_name}")
        self.edit_btn.clicked.connect(self.edit_item)
        header_layout.addWidget(self.edit_btn)
        
        self.delete_btn = RedButton(f"Delete {entity_name}")
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
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        
        # Set row height to accommodate images
        self.table.verticalHeader().setDefaultSectionSize(70)
        
        # Set custom delegate for editing
        self.delegate = BaseTableDelegate(self)
        self.table.setItemDelegate(self.delegate)
        
        # Set specific column widths for image columns
        for i, column_key in enumerate(self.table_columns):
            if 'image' in column_key or 'preview' in column_key:
                self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.Fixed)
                self.table.setColumnWidth(i, 80)  # Fixed width for image column
    
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
            # Get items from database
            items = self.database.get_items(self.section)
            self.table.setRowCount(len(items))
            
            for row, item_data in enumerate(items):
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
                    
                    # Set table data
                    for col, column_key in enumerate(self.table_columns):
                        self.set_table_cell(row, col, column_key, obj)
                
                except Exception as e:
                    print(f"Error processing {self.section} row {row}: {e}")
                    # Fallback: show raw data
                    for col, column_key in enumerate(self.table_columns):
                        value = item_data.get(column_key, "")
                        if column_key == 'id':
                            value = item_data.get('ID', "")
                        item = QTableWidgetItem(str(value))
                        item.setData(Qt.UserRole, item_data.get('ID', 0))
                        self.table.setItem(row, col, item)
        
        except Exception as e:
            print(f"Error refreshing {self.section} table: {e}")
            QMessageBox.critical(self, "Error", f"Failed to refresh {self.section}: {e}")
    
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
                # String and other types
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
    
    def get_preview_category(self):
        """Override in subclasses to specify preview category"""
        return "individual"  # Default category
    
    def update_cell_in_database(self, row, col, new_value):
        """Update database when cell is edited"""
        try:
            # Get object ID
            item = self.table.item(row, col)
            if not item:
                return
            
            obj_id = item.data(Qt.UserRole + 1)
            if not obj_id:
                return
            
            column_key = self.table_columns[col]
            
            # Update database
            data = {column_key: new_value}
            if self.database.update_item(obj_id, data, self.section):
                print(f"Updated {column_key} to '{new_value}' for {self.section} {obj_id}")
            else:
                QMessageBox.warning(self, "Error", f"Failed to update {column_key}")
                # Revert the change
                self.refresh_table()
        
        except Exception as e:
            print(f"Error updating cell in database: {e}")
            QMessageBox.critical(self, "Error", f"Database update failed: {e}")
            self.refresh_table()
    
    def get_selected_id(self):
        """Get ID of selected item"""
        row = self.table.currentRow()
        if row == -1:
            return None
        
        # Get ID from any cell in the row that has it stored
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item:
                obj_id = item.data(Qt.UserRole + 1)
                if obj_id:
                    return int(obj_id)
        
        return None
    
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
                    self.refresh_table()
                else:
                    QMessageBox.critical(self, "Error", f"Failed to delete '{item_name}'")
            except Exception as e:
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