"""
Import Edit Dialog - Updated to use inline import items table
For managing import transactions with items table
"""

from classes.import_class import ImportClass
from classes.import_item_class import ImportItemClass
from ui.widgets.operations_table import OperationsTableWidget
from PySide6.QtWidgets import QDialog, QMessageBox, QVBoxLayout, QHBoxLayout, QLabel, QWidget
from PySide6.QtGui import QFont
from datetime import datetime


class ImportEditDialog(QDialog):
    """Import-specific edit dialog with inline import items editing"""
    
    def __init__(self, import_id=None, database=None, parent=None):
        """
        Initialize import dialog
        
        Args:
            import_id: ID of existing import (None for new import)
            database: Database instance
            parent: Parent widget
        """
        self.import_id = import_id
        self.database = database
        
        # Create or load import object
        if import_id:
            self.import_obj = ImportClass(import_id, database, 0)
            self.import_obj.load_database_data()
        else:
            self.import_obj = ImportClass(0, database, 0)
            # Set default date to today
            self.import_obj.set_value("date", datetime.now().strftime("%Y-%m-%d"))
        
        # Define import-specific UI configuration
        ui_config = {
            'supplier_username': {
                'autocomplete': True
            },
            # TVA now checkbox
        }
        
        # Initialize QDialog directly, not BaseEditDialog to avoid layout conflicts
        QDialog.__init__(self, parent)
        self.data_object = self.import_obj
        self.ui_config = ui_config
        self.parameter_widgets = {}
        
        # Set dialog properties
        self.setModal(True)
        
        # Set specific window title
        if import_id:
            self.setWindowTitle(f"Edit Import - ID {import_id}")
        else:
            self.setWindowTitle("New Import")
        
        # Setup our custom UI
        self.setup_ui()
    
    def setup_ui(self):
        """Setup dialog UI with simple, clean layout that ensures table scrolling works"""
        from PySide6.QtWidgets import QFormLayout, QWidget
        
        # Set reasonable default size but allow resizing
        self.resize(900, 700)
        # Calculate proper minimum size to prevent overlay
        # 120 (params) + 30 (label) + 200 (table min) + 60 (totals) + 50 (buttons) + 60 (margins/spacing + buffer)
        self.setMinimumSize(600, 520)  # Added extra 15px buffer to prevent overlay
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # Show ID (read-only) if available
        if hasattr(self.import_obj, 'id') and self.import_obj.id:
            id_layout = QHBoxLayout()
            id_layout.addWidget(QLabel("ID:"))
            id_label = QLabel(str(self.import_obj.id))
            id_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
            id_layout.addWidget(id_label)
            id_layout.addStretch()
            layout.addLayout(id_layout)
        
        # Import parameters section (compact, fixed height)
        params_widget = QWidget()
        params_widget.setFixedHeight(120)  # Fixed height for parameters
        params_layout = QFormLayout(params_widget)
        params_layout.setContentsMargins(5, 5, 5, 5)
        params_layout.setSpacing(8)
        
        # Get parameters that should be shown in dialog
        visible_params = self.import_obj.get_visible_parameters("dialog")
        
        # Create widgets for each visible parameter
        for param_key in visible_params:
            if param_key not in self.import_obj.parameters:
                continue
            
            param_info = self.import_obj.parameters[param_key]
            
            # Skip calculated parameters
            if self.import_obj.is_parameter_calculated(param_key):
                continue
            
            # Check if parameter is editable
            editable = self.import_obj.is_parameter_editable(param_key, "dialog")
            
            # Get profile images directory
            profile_images_dir = self.get_profile_images_dir()
            
            # Create appropriate widget
            from ui.widgets.parameters_widgets import ParameterWidgetFactory
            widget = ParameterWidgetFactory.create_widget(
                param_info, 
                self.ui_config.get(param_key, {}), 
                profile_images_dir,
                editable
            )
            
            self.parameter_widgets[param_key] = widget
            
            # Connect TVA widget to update totals when value changes
            if param_key == 'tva':
                if hasattr(widget, 'spinbox'):
                    widget.spinbox.valueChanged.connect(lambda _val: self.update_totals())
                if hasattr(widget, 'checkbox'):
                    widget.checkbox.stateChanged.connect(lambda _state: self.update_totals())
            
            # Get display name
            display_name = self.import_obj.get_display_name(param_key)
            
            # Add required indicator
            if param_info.get('required', False):
                display_name += " *"
            
            params_layout.addRow(QLabel(display_name + ":"), widget)
        
        layout.addWidget(params_widget)
        
        # Import Items label
        items_label = QLabel("Import Items")
        items_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        items_label.setStyleSheet("color: #ffffff; margin: 5px 0;")
        layout.addWidget(items_label)
        
        # Create import items table (this will have internal scrolling)
        self.import_items_table = OperationsTableWidget(
            item_class=ImportItemClass,
            parent_operation=self.import_obj,
            database=self.database,
            columns=['product_preview', 'product_name', 'quantity', 'unit_price', 'subtotal', 'delete_action'],
            parent=self,
            highlight_stock_exceed=False
        )
        
        # Connect table changes to update totals
        self.import_items_table.items_changed.connect(self.update_totals)
        
        # Give the table most of the remaining space (stretches with dialog)
        self.import_items_table.setMinimumHeight(200)  # Reduced minimum for better resizing
        layout.addWidget(self.import_items_table, 1)  # Stretch factor 1 = takes extra space
        
        # Totals section (compact, fixed height) - ALWAYS AFTER TABLE
        totals_widget = QWidget()
        totals_widget.setFixedHeight(60)  # Fixed height for totals
        totals_layout = QHBoxLayout(totals_widget)
        totals_layout.setContentsMargins(5, 5, 5, 5)
        
        # Add total fields
        self.add_total_fields(totals_layout)
        
        layout.addWidget(totals_widget)
        
        # Button section (fixed height)
        button_widget = QWidget()
        button_widget.setFixedHeight(50)
        button_layout = QHBoxLayout(button_widget)
        button_layout.addStretch()
        
        from ui.widgets.themed_widgets import GreenButton, RedButton
        self.save_btn = GreenButton("Save")
        self.save_btn.clicked.connect(self.save_changes)
        button_layout.addWidget(self.save_btn)
        
        self.cancel_btn = RedButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addWidget(button_widget)
        
        # Apply dark theme
        self.apply_theme()
    
    def minimumSizeHint(self):
        """Calculate minimum size to prevent component overlay"""
        from PySide6.QtCore import QSize
        
        # Calculate minimum height needed for all components
        min_height = (
            120 +  # params section (fixed)
            30 +   # import items label 
            200 +  # table minimum height
            60 +   # totals section (fixed)
            50 +   # button section (fixed)
            60     # margins and spacing + buffer
        )
        
        return QSize(600, min_height)
    
    def apply_theme(self):
        """Apply dark theme styling"""
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
            QScrollArea {
                background-color: #2b2b2b;
                border: none;
            }
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
        """)
    
    def get_profile_images_dir(self):
        """Get profile images directory if available"""
        try:
            if (hasattr(self.parent(), 'profile_manager') and 
                self.parent().profile_manager and
                self.parent().profile_manager.selected_profile):
                
                import os
                profile_dir = os.path.dirname(self.parent().profile_manager.selected_profile.config_path)
                return os.path.join(profile_dir, "images")
        except:
            pass
        return None
    
    def add_total_fields(self, parent_layout):
        """Add read-only total calculation fields in horizontal layout"""
        from ui.widgets.parameters_widgets import ParameterWidgetFactory
        
        # Subtotal
        subtotal_widget = ParameterWidgetFactory.create_widget(
            {
                'type': 'float',
                'display_name': {'en': 'Subtotal'},
                'unit': 'MAD'
            },
            {},
            None,
            editable=False
        )
        ParameterWidgetFactory.set_widget_value(subtotal_widget, 0.0)
        self.subtotal_widget = subtotal_widget
        
        # VAT Amount  
        vat_widget = ParameterWidgetFactory.create_widget(
            {
                'type': 'float',
                'display_name': {'en': 'VAT Amount'},
                'unit': 'MAD'
            },
            {},
            None,
            editable=False
        )
        ParameterWidgetFactory.set_widget_value(vat_widget, 0.0)
        self.vat_widget = vat_widget
        
        # Total
        total_widget = ParameterWidgetFactory.create_widget(
            {
                'type': 'float',
                'display_name': {'en': 'Total Price'},
                'unit': 'MAD'
            },
            {},
            None,
            editable=False
        )
        ParameterWidgetFactory.set_widget_value(total_widget, 0.0)
        self.total_widget = total_widget
        
        # Add labels and widgets to horizontal layout
        parent_layout.addWidget(QLabel("Subtotal:"))
        parent_layout.addWidget(subtotal_widget)
        parent_layout.addWidget(QLabel("VAT:"))
        parent_layout.addWidget(vat_widget)
        parent_layout.addWidget(QLabel("Total:"))
        parent_layout.addWidget(total_widget)
        parent_layout.addStretch()  # Push everything to the left
        
        # Initial calculation
        self.update_totals()
    
    def get_widget_value(self, widget):
        """Helper method to get value from widget"""
        from ui.widgets.parameters_widgets import ParameterWidgetFactory
        return ParameterWidgetFactory.get_widget_value(widget)
    
    def update_totals(self):
        """Update total calculation fields"""
        try:
            # Get current items
            items = self.import_items_table.get_items_data()
            
            # Calculate subtotal
            subtotal = sum(item.get_value('subtotal') or 0 for item in items)
            
            # Get VAT percentage from the tva parameter widget
            vat_percent = 0
            if 'tva' in self.parameter_widgets:
                try:
                    vat_percent = float(self.get_widget_value(self.parameter_widgets['tva']) or 0)
                except Exception:
                    vat_percent = 0
            
            # Calculate VAT amount
            vat_amount = subtotal * (vat_percent / 100)
            
            # Calculate total
            total = subtotal + vat_amount
            
            # Update widgets
            from ui.widgets.parameters_widgets import ParameterWidgetFactory
            if hasattr(self, 'subtotal_widget'):
                ParameterWidgetFactory.set_widget_value(self.subtotal_widget, subtotal)
            if hasattr(self, 'vat_widget'):
                ParameterWidgetFactory.set_widget_value(self.vat_widget, vat_amount)
            if hasattr(self, 'total_widget'):
                ParameterWidgetFactory.set_widget_value(self.total_widget, total)
                
        except Exception as e:
            print(f"Error updating totals: {e}")
    

    def validate_data(self):
        """Import-specific validation"""
        errors = []
        
        # Basic parameter validation
        for param_key, widget in self.parameter_widgets.items():
            param_info = self.import_obj.parameters.get(param_key, {})
            
            # Check if required parameter is empty
            if param_info.get('required', False):
                value = self.get_widget_value(widget)
                if not value or (isinstance(value, str) and not value.strip()):
                    display_name = self.import_obj.get_display_name(param_key)
                    errors.append(f"{display_name} is required")
        
        # Additional import-specific validation
        supplier_username = self.get_widget_value(self.parameter_widgets.get('supplier_username', ''))
        
        # Validate supplier username exists
        if supplier_username and not self._validate_supplier_exists(supplier_username):
            errors.append(f"Supplier username '{supplier_username}' does not exist")
        
        # Check if we have at least one item
        items = self.import_items_table.get_items_data()
        if not items:
            errors.append("Please add at least one item to the import")
        
        return errors
    
    def _validate_supplier_exists(self, username):
        """Check if supplier username exists in database"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return False
        
        try:
            self.database.cursor.execute("SELECT COUNT(*) FROM Suppliers WHERE username = ?", (username,))
            result = self.database.cursor.fetchone()
            return result[0] > 0 if result else False
        except Exception as e:
            print(f"Error validating supplier: {e}")
            return False
    
    def save_changes(self):
        """Save import changes to database using simple approach"""
        # Validate data first
        errors = self.validate_data()
        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return
        
        try:
            # Update import object with form data
            for param_key, widget in self.parameter_widgets.items():
                value = self.get_widget_value(widget)
                self.import_obj.set_value(param_key, value)
            
            # Save import to database first
            if self.import_id:
                # Update existing import
                success = self.import_obj.save_to_database()
                action = "updated"
            else:
                # Add new import and get the new ID
                success = self.import_obj.save_to_database()
                if success:
                    self.import_id = self.import_obj.id
                    action = "created"
            
            if success:
                # Simple approach: Clear all existing items and add current ones
                operation_id = self.import_obj.id
                
                # Delete all existing import items for this operation
                if hasattr(self.import_obj, 'get_import_items'):
                    existing_items = self.import_obj.get_import_items()
                    for item in existing_items:
                        if hasattr(item, 'id') and item.id:
                            self.database.delete_item(item.id, "Import_Items")
                
                # Add all current table items
                current_data = self.import_items_table.get_current_table_data()
                items_saved = 0
                
                for item_data in current_data:
                    item_data['import_id'] = operation_id
                    if self.database.add_item(item_data, "Import_Items"):
                        items_saved += 1
                
                QMessageBox.information(self, "Success", 
                    f"Import {action} successfully!\n{items_saved} items saved.")
                self.accept()  # Close dialog
            else:
                QMessageBox.critical(self, "Error", "Failed to save import to database")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save import: {str(e)}")
    
    def get_import_data(self):
        """Get the import object (useful for parent windows)"""
        return self.import_obj