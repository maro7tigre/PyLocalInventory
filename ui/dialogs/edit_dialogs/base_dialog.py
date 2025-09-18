"""
Unified Edit Dialog System
Replaces all your repetitive edit dialogs with a single, flexible dialog
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QMessageBox, QScrollArea, QWidget,
                               QFormLayout)
from PySide6.QtCore import Qt
from ui.widgets.themed_widgets import GreenButton, RedButton
from ui.widgets.parameters_widgets import ParameterWidgetFactory
from classes.product_class import ProductClass
from classes.client_class import ClientClass
from classes.supplier_class import SupplierClass
import os


class BaseEditDialog(QDialog):
    """
    Single dialog that can handle any object type using the parameter system
    Replaces client_dialog.py, product_dialog.py, supplier_dialog.py, etc.
    """
    
    def __init__(self, data_object, ui_config=None, parent=None):
        """
        data_object: Instance of ClientClass, ProductClass, etc.
        ui_config: Dict specifying UI behavior for each parameter
        """
        super().__init__(parent)
        self.data_object = data_object
        self.ui_config = ui_config or {}
        self.parameter_widgets = {}
        
        # Set dialog title based on object type
        self.setWindowTitle(f"Edit {self.data_object.section}")
        self.setMinimumSize(450, 400)
        
        self.setup_ui()
        self.load_data()
        self.apply_theme()
    
    def setup_ui(self):
        """Setup dialog UI using parameter definitions"""
        layout = QVBoxLayout(self)
        
        # Show ID (read-only)
        if hasattr(self.data_object, 'id'):
            id_layout = QHBoxLayout()
            id_layout.addWidget(QLabel("ID:"))
            id_label = QLabel(str(self.data_object.id))
            id_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
            id_layout.addWidget(id_label)
            id_layout.addStretch()
            layout.addLayout(id_layout)
        
        # Scrollable form area
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        form_layout = QFormLayout(scroll_widget)
        
        # Get parameters that should be shown in dialog
        dialog_params = self.data_object.available_parameters.get("dialog", [])
        
        # Create widgets for each parameter
        for param_key in dialog_params:
            if param_key not in self.data_object.parameters:
                continue
                
            param_info = self.data_object.parameters[param_key]
            
            # Get UI config for this specific parameter
            param_ui_config = self.ui_config.get(param_key, {})
            
            # Create appropriate widget using factory
            widget = self.create_parameter_widget(param_info, param_ui_config)
            self.parameter_widgets[param_key] = widget
            
            # Get display name (with language support)
            display_name = self.get_display_name(param_info, param_key)
            
            # Add required indicator
            if param_info.get('required', False):
                display_name += " *"
            
            form_layout.addRow(QLabel(display_name + ":"), widget)
        
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.save_btn = GreenButton("Save")
        self.save_btn.clicked.connect(self.save_changes)
        button_layout.addWidget(self.save_btn)
        
        self.cancel_btn = RedButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
    
    def create_parameter_widget(self, param_info, ui_config):
        """Create appropriate widget based on parameter type"""
        
        # Get profile images directory if available
        profile_images_dir = None
        if hasattr(self.parent(), 'profile_manager') and self.parent().profile_manager.selected_profile:
            profile_dir = os.path.dirname(self.parent().profile_manager.selected_profile.config_path)
            profile_images_dir = os.path.join(profile_dir, "images")
        
        return ParameterWidgetFactory.create_widget(param_info, ui_config, profile_images_dir)
    
    def get_display_name(self, param_info, fallback_key):
        """Get localized display name"""
        display_names = param_info.get('display name', {})
        # Default to English, fallback to key
        return display_names.get('en', display_names.get('fr', fallback_key))
    
    def load_data(self):
        """Load current data into widgets"""
        for param_key, widget in self.parameter_widgets.items():
            current_value = self.data_object.get_value(param_key)
            if current_value is None:
                current_value = self.data_object.parameters[param_key].get('default', '')
            
            self.set_widget_value(widget, current_value)
    
    def set_widget_value(self, widget, value):
        """Set value for different widget types"""
        if hasattr(widget, 'setText'):  # QLineEdit, AutoCompleteLineEdit
            widget.setText(str(value) if value is not None else '')
        elif hasattr(widget, 'setValue'):  # NumericWidget (QSpinBox/QDoubleSpinBox)
            widget.setValue(float(value) if value is not None else 0)
        elif hasattr(widget, 'set_image_path'):  # ImagePreviewWidget
            if value and os.path.exists(str(value)):
                widget.set_image_path(str(value), copy_to_profile=False)
    
    def get_widget_value(self, widget):
        """Get value from different widget types"""
        if hasattr(widget, 'text'):  # QLineEdit, AutoCompleteLineEdit
            return widget.text().strip()
        elif hasattr(widget, 'value'):  # NumericWidget
            return widget.value()
        elif hasattr(widget, 'get_image_path'):  # ImagePreviewWidget
            return widget.get_image_path()
        return None
    
    def validate_data(self):
        """Validate all parameters"""
        errors = []
        
        for param_key, widget in self.parameter_widgets.items():
            param_info = self.data_object.parameters[param_key]
            value = self.get_widget_value(widget)
            
            # Check required fields
            if param_info.get('required', False) and not value:
                display_name = self.get_display_name(param_info, param_key)
                errors.append(f"{display_name} is required")
                continue
            
            # Type-specific validation
            param_type = param_info.get('type', 'string')
            
            if param_type == 'string':
                # Check autocomplete validity
                if hasattr(widget, 'is_valid_option') and not widget.is_valid_option and value:
                    display_name = self.get_display_name(param_info, param_key)
                    errors.append(f"{display_name} must be one of the suggested options")
            
            elif param_type in ['int', 'float']:
                # Min/max validation is handled by QSpinBox/QDoubleSpinBox automatically
                pass
        
        return errors
    
    def save_changes(self):
        """Validate and save changes"""
        # Validate data
        errors = self.validate_data()
        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return
        
        # Update data object
        try:
            for param_key, widget in self.parameter_widgets.items():
                value = self.get_widget_value(widget)
                self.data_object.set_value(param_key, value)
            
            # You could add database save here
            # self.data_object.save_to_database()
            
            self.accept()  # Close dialog successfully
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {str(e)}")
    
    def apply_theme(self):
        """Apply dark theme"""
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
        """)


# Usage examples showing how this replaces all your dialog files
class EditDialogManager:
    """Manager class showing how to use the unified dialog"""
    
    def __init__(self, database, profile_manager):
        self.database = database
        self.profile_manager = profile_manager
    
    def edit_client(self, client_id=None):
        """Edit client - replaces client_dialog.py completely"""
        
        if client_id:
            # Load existing client
            client = ClientClass(client_id, self.database, "Existing Client")
            client.load_database_data()
        else:
            # New client
            client = ClientClass(0, self.database, "New Client")
        
        # Define UI configuration for client editing
        ui_config = {
            'preview image': {
                'size': (120, 120),
                'browsing_enabled': True
            },
            'notes': {
                'multiline': True  # Could extend system for text areas
            }
        }
        
        dialog = BaseEditDialog(client, ui_config)
        if dialog.exec() == QDialog.Accepted:
            # Save to database
            if client_id:
                self.database.update_item(client_id, client.get_value(destination="database"), "Clients")
            else:
                self.database.add_item(client.get_value(destination="database"), "Clients")
            return True
        return False
    
    def edit_product(self, product_id=None):
        """Edit product - replaces product_dialog.py completely"""
        
        if product_id:
            product = ProductClass(product_id, self.database, "Existing Product")
            product.load_database_data()
        else:
            product = ProductClass(0, self.database, "New Product")
        
        # Smaller image for products, different validation
        ui_config = {
            'preview image': {
                'size': (80, 80),
                'browsing_enabled': True
            }
        }
        
        dialog = BaseEditDialog(product, ui_config)
        return dialog.exec() == QDialog.Accepted
    
    def edit_supplier(self, supplier_id=None):
        """Edit supplier - replaces supplier_dialog.py completely"""
        
        if supplier_id:
            supplier = SupplierClass(supplier_id, self.database, "Existing Supplier")
            supplier.load_database_data()
        else:
            supplier = SupplierClass(0, self.database, "New Supplier")
        
        ui_config = {
            'preview image': {
                'size': (100, 100),
                'browsing_enabled': True
            }
        }
        
        dialog = BaseEditDialog(supplier, ui_config)
        return dialog.exec() == QDialog.Accepted