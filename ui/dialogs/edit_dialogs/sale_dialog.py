"""
Sale Edit Dialog - Updated to use inline sales items table
For managing sale transactions with items table
"""

from classes.sales_class import SalesClass
from classes.sales_item_class import SalesItemClass
from ui.widgets.operations_table import OperationsTableWidget
from PySide6.QtWidgets import QDialog, QMessageBox, QVBoxLayout, QHBoxLayout, QLabel, QWidget
from PySide6.QtGui import QFont
from core.calculations import calculate_operation_totals, to_decimal
from datetime import datetime
from decimal import Decimal, InvalidOperation


class SaleEditDialog(QDialog):
    """Sale-specific edit dialog with inline sales items editing"""
    
    def __init__(self, sale_id=None, database=None, parent=None):
        """
        Initialize sale dialog
        
        Args:
            sale_id: ID of existing sale (None for new sale)
            database: Database instance
            parent: Parent widget
        """
        self.sale_id = sale_id
        self.database = database
        
        # Create or load sale object
        if sale_id:
            self.sale_obj = SalesClass(sale_id, database, 0)
            self.sale_obj.load_database_data()
        else:
            self.sale_obj = SalesClass(0, database, 0)
            # Set default date to today
            self.sale_obj.set_value("date", datetime.now().strftime("%Y-%m-%d"))
        
        # Define sale-specific UI configuration
        ui_config = {
            'client_username': {
                'autocomplete': True
            },
            # TVA now a checkbox -> no numeric constraints needed
        }
        
        # Initialize QDialog directly, not BaseEditDialog to avoid layout conflicts
        QDialog.__init__(self, parent)
        self.data_object = self.sale_obj
        self.ui_config = ui_config
        self.parameter_widgets = {}
        
        # Set dialog properties
        self.setModal(True)
        
        # Set specific window title
        if sale_id:
            self.setWindowTitle(f"Edit Sale - ID {sale_id}")
        else:
            self.setWindowTitle("New Sale")
        
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
        if hasattr(self.sale_obj, 'id') and self.sale_obj.id:
            id_layout = QHBoxLayout()
            id_layout.addWidget(QLabel("ID:"))
            id_label = QLabel(str(self.sale_obj.id))
            id_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
            id_layout.addWidget(id_label)
            id_layout.addStretch()
            layout.addLayout(id_layout)
        
        # Sale parameters section (compact, fixed height)
        params_widget = QWidget()
        params_widget.setFixedHeight(120)  # Fixed height for parameters
        params_layout = QFormLayout(params_widget)
        params_layout.setContentsMargins(5, 5, 5, 5)
        params_layout.setSpacing(8)
        
        # Get parameters that should be shown in dialog
        visible_params = self.sale_obj.get_visible_parameters("dialog")
        
        # Create widgets for each visible parameter
        for param_key in visible_params:
            if param_key not in self.sale_obj.parameters:
                continue
            
            param_info = self.sale_obj.parameters[param_key]
            
            # Skip calculated parameters
            if self.sale_obj.is_parameter_calculated(param_key):
                continue
            
            # Check if parameter is editable
            editable = self.sale_obj.is_parameter_editable(param_key, "dialog")
            
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
                # Support both legacy numeric and new checkbox widget.
                # Use lambda to ignore the emitted value/state argument so our slot signature matches.
                if hasattr(widget, 'spinbox'):
                    widget.spinbox.valueChanged.connect(lambda _val: self.update_totals())
                if hasattr(widget, 'checkbox'):
                    widget.checkbox.stateChanged.connect(lambda _state: self.update_totals())
            
            # Get display name
            display_name = self.sale_obj.get_display_name(param_key)
            
            # Add required indicator
            if param_info.get('required', False):
                display_name += " *"
            
            params_layout.addRow(QLabel(display_name + ":"), widget)
        
        layout.addWidget(params_widget)
        
        # Sales Items label
        items_label = QLabel("Sales Items")
        items_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        items_label.setStyleSheet("color: #ffffff; margin: 5px 0;")
        layout.addWidget(items_label)
        
        # Create sales items table (this will have internal scrolling)
       
        self.sales_items_table = OperationsTableWidget(
            item_class=SalesItemClass,
            parent_operation=self.sale_obj,
            database=self.database,
            columns=['product_preview', 'product_description','product_name', 'quantity', 'unit_price', 'subtotal', 'delete_action'],
            parent=self,
            highlight_stock_exceed=True
        )
        
        # Connect table changes to update totals
        self.sales_items_table.items_changed.connect(self.update_totals)
        
        # Give the table most of the remaining space (stretches with dialog)
        self.sales_items_table.setMinimumHeight(200)  # Reduced minimum for better resizing
        layout.addWidget(self.sales_items_table, 1)  # Stretch factor 1 = takes extra space
        
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
        if self.sale_id:
            self.attachments_btn = QPushButton("Attachments…")
            self.attachments_btn.clicked.connect(self.show_attachments)
            button_layout.addWidget(self.attachments_btn)
        self.save_btn = GreenButton("Save")
        self.save_btn.clicked.connect(self.save_changes)
        button_layout.addWidget(self.save_btn)
        
        self.cancel_btn = RedButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addWidget(button_widget)
        
        # Apply dark theme
        self.apply_theme()

    def show_attachments(self):
        """Open the sale-specific attachment section without crowding item editing."""
        if not self.sale_id:
            QMessageBox.information(self, "Attachments", "Save the sale first, then reopen it to add attachments.")
            return
        from ui.widgets.attachments_widget import AttachmentPanel
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Sale {self.sale_id} Attachments")
        dialog.resize(900, 600)
        layout = QVBoxLayout(dialog)
        layout.addWidget(AttachmentPanel(self.database, 'sale', int(self.sale_id), dialog))
        dialog.exec()
    
    def minimumSizeHint(self):
        """Calculate minimum size to prevent component overlay"""
        from PySide6.QtCore import QSize
        
        # Calculate minimum height needed for all components
        min_height = (
            120 +  # params section (fixed)
            30 +   # sales items label 
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
            items = self.sales_items_table.get_items_data()
            
            # Calculate subtotal (Decimal line totals through the shared helper)
            subtotal = sum(to_decimal(item.get_value('subtotal') or 0) for item in items)
            
            # Get VAT percentage from the tva parameter widget
            vat_percent = Decimal("0")
            if 'tva' in self.parameter_widgets:
                try:
                    vat_percent = Decimal(str(self.get_widget_value(self.parameter_widgets['tva']) or 0))
                except (InvalidOperation, ValueError, TypeError):
                    vat_percent = Decimal("0")
            
            # Centralized Decimal math: TVA = Subtotal * rate, Total = Subtotal + TVA.
            totals = calculate_operation_totals(subtotal, 0, vat_percent)
            
            # Update widgets
            from ui.widgets.parameters_widgets import ParameterWidgetFactory
            if hasattr(self, 'subtotal_widget'):
                ParameterWidgetFactory.set_widget_value(self.subtotal_widget, totals['original_subtotal'])
            if hasattr(self, 'vat_widget'):
                ParameterWidgetFactory.set_widget_value(self.vat_widget, totals['vat_amount'])
            if hasattr(self, 'total_widget'):
                ParameterWidgetFactory.set_widget_value(self.total_widget, totals['total_ttc'])
                
        except Exception as e:
            print(f"Error updating totals: {e}")
    

    def validate_data(self):
        """Sale-specific validation"""
        errors = []
        
        # Basic parameter validation
        for param_key, widget in self.parameter_widgets.items():
            param_info = self.sale_obj.parameters.get(param_key, {})
            
            # Check if required parameter is empty
            if param_info.get('required', False):
                value = self.get_widget_value(widget)
                if not value or (isinstance(value, str) and not value.strip()):
                    display_name = self.sale_obj.get_display_name(param_key)
                    errors.append(f"{display_name} is required")
        
        # Additional sale-specific validation
        client_username = self.get_widget_value(self.parameter_widgets.get('client_username', ''))
        
        # Validate client username exists
        if client_username and not self._validate_client_exists(client_username):
            errors.append(f"Client username '{client_username}' does not exist")
        
        # Check if we have at least one item
        items = self.sales_items_table.get_items_data()
        if not items:
            errors.append("Please add at least one item to the sale")
        
        return errors
    
    def _validate_client_exists(self, username):
        """Check if client username exists in database"""
        if not self.database or not hasattr(self.database, 'cursor') or not self.database.cursor:
            return False
        
        try:
            self.database.cursor.execute("SELECT COUNT(*) FROM Clients WHERE username = %s", (username,))
            result = self.database.cursor.fetchone()
            return result[0] > 0 if result else False
        except Exception as e:
            print(f"Error validating client: {e}")
            return False
    
    def save_changes(self):
        """Save sale changes to database using simple approach"""
        # Validate data first
        errors = self.validate_data()
        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return
        
        try:
            # Update sale object with form data
            for param_key, widget in self.parameter_widgets.items():
                value = self.get_widget_value(widget)
                self.sale_obj.set_value(param_key, value)
            
            action = "updated" if self.sale_id else "created"
            current_data = self.sales_items_table.get_current_table_data()
            header = {
                key: self.sale_obj.get_value(key)
                for key in self.sale_obj.get_visible_parameters('database')
                if not self.sale_obj.is_parameter_calculated(key)
            }
            result = self.database.save_sale_with_items(
                header, current_data, self.sale_id, len(current_data)
            )
            if not isinstance(result, dict) or result.get('saved') != len(current_data):
                raise RuntimeError(
                    f"Sale was not saved: {len(current_data)} visible items were found, "
                    f"but the server confirmed {result.get('saved', 0) if isinstance(result, dict) else 0}."
                )
            self.sale_id = result['sale_id']
            self.sale_obj.id = result['sale_id']
            QMessageBox.information(
                self, "Success", f"Sale {action} successfully. {result['saved']} items saved."
            )
            self.accept()
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save sale: {str(e)}")
    
    def get_sale_data(self):
        """Get the sale object (useful for parent windows)"""
        return self.sale_obj
