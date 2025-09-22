"""
Operations Table Widget - Editable table with auto-expanding rows
"""
import sys
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QTableWidget, QTableWidgetItem, QHeaderView, 
                               QAbstractItemView, QLineEdit, QDoubleSpinBox, 
                               QSpinBox, QLabel, QPushButton, QHBoxLayout)
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtCore import Qt, QTimer


class DemoOperationClass:
    """Demo class representing an operation with various parameter types"""
    
    def __init__(self, operation_id=0, database=None):
        self.id = operation_id
        self.database = database
        self.section = "Operations"
        
        # Define parameters similar to the existing classes
        self.parameters = {
            'id': {
                'type': 'int',
                'display_name': 'ID',
                'visible': {'table': True, 'form': False}
            },
            'operation_name': {
                'type': 'string',
                'display_name': 'Operation Name',
                'visible': {'table': True, 'form': True},
                'default': ''
            },
            'duration': {
                'type': 'float',
                'display_name': 'Duration',
                'visible': {'table': True, 'form': True},
                'unit': 'min',
                'default': 0.0
            },
            'cost': {
                'type': 'float',
                'display_name': 'Cost',
                'visible': {'table': True, 'form': True},
                'unit': '$',
                'default': 0.0
            },
            'priority': {
                'type': 'int',
                'display_name': 'Priority',
                'visible': {'table': True, 'form': True},
                'default': 1
            },
            'description': {
                'type': 'string',
                'display_name': 'Description',
                'visible': {'table': True, 'form': True},
                'default': ''
            }
        }
        
        # Initialize values with defaults
        self.values = {}
        for key, param in self.parameters.items():
            self.values[key] = param.get('default', '')
    
    def get_visible_parameters(self, view_type="table"):
        """Get list of parameters visible in specified view"""
        return [key for key, param in self.parameters.items() 
                if param.get('visible', {}).get(view_type, False)]
    
    def get_display_name(self, param_key):
        """Get display name for parameter"""
        return self.parameters.get(param_key, {}).get('display_name', param_key)
    
    def get_value(self, param_key):
        """Get parameter value"""
        return self.values.get(param_key, self.parameters.get(param_key, {}).get('default', ''))
    
    def set_value(self, param_key, value):
        """Set parameter value"""
        if param_key in self.parameters:
            param_type = self.parameters[param_key].get('type', 'string')
            
            # Convert value to appropriate type
            if param_type == 'int':
                try:
                    self.values[param_key] = int(float(value)) if value != '' else 0
                except (ValueError, TypeError):
                    self.values[param_key] = 0
            elif param_type == 'float':
                try:
                    self.values[param_key] = float(value) if value != '' else 0.0
                except (ValueError, TypeError):
                    self.values[param_key] = 0.0
            else:
                self.values[param_key] = str(value) if value is not None else ''


class OperationsTableWidget(QWidget):
    """Editable operations table with auto-expanding rows"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.operation_class = DemoOperationClass
        self.operations = []  # List to store operation objects
        self.next_id = 1
        
        # Create a temporary object to get parameter information
        temp_obj = self.operation_class(0)
        self.section = temp_obj.section
        self.table_columns = temp_obj.get_visible_parameters("table")
        self.parameter_definitions = temp_obj.parameters
        
        self.setup_ui()
        self.apply_theme()
        self.add_empty_row()  # Start with one empty row
    
    def setup_ui(self):
        """Setup table interface"""
        layout = QVBoxLayout(self)
        
        # Header with title
        header_layout = QHBoxLayout()
        
        title = QLabel(f"{self.section} Table")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        # Clear button for testing
        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self.clear_all)
        header_layout.addWidget(clear_btn)
        
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
                temp_obj = self.operation_class(0)
                display_name = temp_obj.get_display_name(param_key)
                headers.append(display_name)
            else:
                headers.append(param_key)
        
        self.table.setHorizontalHeaderLabels(headers)
        
        # Table properties
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        
        # Connect cell changed signal
        self.table.itemChanged.connect(self.on_cell_changed)
        
        # Hide ID column if present
        if 'id' in self.table_columns:
            id_index = self.table_columns.index('id')
            self.table.setColumnHidden(id_index, True)
    
    def add_empty_row(self):
        """Add an empty row to the table"""
        # Create new operation object
        operation = self.operation_class(self.next_id)
        self.operations.append(operation)
        
        # Add row to table
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        # Set up editable cells
        for col, param_key in enumerate(self.table_columns):
            self.create_editable_cell(row, col, param_key, operation)
        
        self.next_id += 1
    
    def create_editable_cell(self, row, col, param_key, operation):
        """Create an editable cell based on parameter type"""
        param_info = self.parameter_definitions.get(param_key, {})
        param_type = param_info.get('type', 'string')
        default_value = operation.get_value(param_key)
        
        if param_type == 'float':
            # Use QDoubleSpinBox for float values
            widget = QDoubleSpinBox()
            widget.setRange(-999999.99, 999999.99)
            widget.setDecimals(2)
            widget.setValue(float(default_value) if default_value else 0.0)
            widget.valueChanged.connect(lambda value, r=row, c=col, k=param_key: 
                                      self.on_widget_value_changed(r, c, k, value))
            self.table.setCellWidget(row, col, widget)
            
        elif param_type == 'int':
            # Use QSpinBox for integer values
            widget = QSpinBox()
            widget.setRange(-999999, 999999)
            widget.setValue(int(default_value) if default_value else 0)
            widget.valueChanged.connect(lambda value, r=row, c=col, k=param_key: 
                                      self.on_widget_value_changed(r, c, k, value))
            self.table.setCellWidget(row, col, widget)
            
        else:
            # Use QTableWidgetItem for string values
            item = QTableWidgetItem(str(default_value))
            item.setData(Qt.ItemDataRole.UserRole, param_key)
            self.table.setItem(row, col, item)
    
    def on_cell_changed(self, item):
        """Handle cell value changes"""
        row = item.row()
        col = item.column()
        param_key = item.data(Qt.ItemDataRole.UserRole)
        new_value = item.text()
        
        if param_key and row < len(self.operations):
            # Update operation object
            self.operations[row].set_value(param_key, new_value)
            
            # Check if this was the last empty row and now has content
            self.check_and_add_row(row)
    
    def on_widget_value_changed(self, row, col, param_key, value):
        """Handle widget value changes"""
        if row < len(self.operations):
            # Update operation object
            self.operations[row].set_value(param_key, value)
            
            # Check if this was the last empty row and now has content
            self.check_and_add_row(row)
    
    def check_and_add_row(self, changed_row):
        """Check if we need to add a new empty row"""
        # Only check if this is the last row
        if changed_row != self.table.rowCount() - 1:
            return
        
        # Check if the last row has any non-empty content
        operation = self.operations[changed_row]
        has_content = False
        
        for param_key in self.table_columns:
            if param_key == 'id':  # Skip ID column
                continue
            value = operation.get_value(param_key)
            if value and str(value).strip():
                has_content = True
                break
        
        # If the last row has content, add a new empty row
        if has_content:
            # Use QTimer to add row after current processing is complete
            QTimer.singleShot(0, self.add_empty_row)
    
    def clear_all(self):
        """Clear all rows and start fresh"""
        self.table.setRowCount(0)
        self.operations.clear()
        self.next_id = 1
        self.add_empty_row()
    
    def get_operations_data(self):
        """Get all operations data (excluding empty rows)"""
        data = []
        for operation in self.operations:
            # Check if operation has any meaningful content
            has_content = False
            for param_key in self.table_columns:
                if param_key == 'id':
                    continue
                value = operation.get_value(param_key)
                if value and str(value).strip():
                    has_content = True
                    break
            
            if has_content:
                data.append({param_key: operation.get_value(param_key) 
                           for param_key in self.table_columns})
        
        return data
    
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
            QSpinBox, QDoubleSpinBox {
                background-color: #2D2D30;
                border: 1px solid #3E3E42;
                color: #E0E0E0;
                padding: 2px;
            }
            QSpinBox:focus, QDoubleSpinBox:focus {
                border: 1px solid #007ACC;
            }
            QPushButton {
                background-color: #0E639C;
                border: none;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1177BB;
            }
            QPushButton:pressed {
                background-color: #005A9E;
            }
        """)


class TestApp(QMainWindow):
    """Simple test application for the OperationsTableWidget"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Operations Table Widget Test")
        self.setGeometry(100, 100, 1000, 600)
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        
        # Add instructions
        instructions = QLabel("""
Instructions:
• Start typing in any cell to add data
• Use Tab to move between cells
• When you fill the last row, a new empty row will automatically be added
• Number fields use spinboxes for easier editing
• Click 'Clear All' to reset the table
        """)
        instructions.setStyleSheet("color: #CCCCCC; padding: 10px; background-color: #252526; border-radius: 4px;")
        layout.addWidget(instructions)
        
        # Create operations table
        self.operations_table = OperationsTableWidget()
        layout.addWidget(self.operations_table)
        
        # Add button to show current data
        show_data_btn = QPushButton("Show Current Data")
        show_data_btn.clicked.connect(self.show_data)
        layout.addWidget(show_data_btn)
        
        # Apply dark theme
        self.apply_theme()
    
    def show_data(self):
        """Show current operations data"""
        data = self.operations_table.get_operations_data()
        print("\n=== Current Operations Data ===")
        for i, operation in enumerate(data, 1):
            print(f"Operation {i}:")
            for key, value in operation.items():
                if key != 'id':  # Skip ID in display
                    print(f"  {key}: {value}")
        print("=" * 30)
    
    def apply_theme(self):
        """Apply dark theme to main window"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
                color: #ffffff;
            }
        """)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle('Fusion')
    
    window = TestApp()
    window.show()
    
    sys.exit(app.exec())