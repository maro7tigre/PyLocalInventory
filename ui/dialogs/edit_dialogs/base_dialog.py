"""
Updated Base Edit Dialog - Uses parameter system and widget factory
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QMessageBox, QScrollArea, QWidget,
                               QFormLayout)
from PySide6.QtCore import Qt
from ui.widgets.themed_widgets import GreenButton, RedButton
# Import will be done locally to avoid circular imports
import os


class BaseEditDialog(QDialog):
    """
    Universal dialog for editing any object using the parameter system
    """
    
    def __init__(self, data_object, ui_config=None, parent=None):
        """
        Args:
            data_object: Instance with parameter system (ClientClass, ProductClass, etc.)
            ui_config: Dict with UI customization for specific parameters
            parent: Parent widget
        """
        super().__init__(parent)
        self.data_object = data_object
        self.ui_config = ui_config or {}
        self.parameter_widgets = {}
        
        # Set dialog properties
        self.setWindowTitle(f"Edit {self.data_object.section}")
        self.setMinimumSize(450, 400)
        self.setModal(True)
        
        self.setup_ui()
        self.load_data()
        self.apply_theme()
    
    def setup_ui(self):
        """Setup dialog UI using parameter definitions"""
        layout = QVBoxLayout(self)
        
        # Show ID (read-only) if available
        if hasattr(self.data_object, 'id') and self.data_object.id:
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
        visible_params = self.data_object.get_visible_parameters("dialog")
        
        # Create widgets for each visible parameter
        for param_key in visible_params:
            if param_key not in self.data_object.parameters:
                continue
            
            param_info = self.data_object.parameters[param_key]
            
            # Skip calculated parameters (they're read-only and calculated dynamically)
            if self.data_object.is_parameter_calculated(param_key):
                continue
            
            # Check if parameter is editable
            editable = self.data_object.is_parameter_editable(param_key, "dialog")
            
            # Get profile images directory
            profile_images_dir = self.get_profile_images_dir()
            
            # Create appropriate widget (import locally to avoid circular imports)
            from ui.widgets.parameters_widgets import ParameterWidgetFactory
            widget = ParameterWidgetFactory.create_widget(
                param_info, 
                self.ui_config.get(param_key, {}), 
                profile_images_dir,
                editable
            )
            
            self.parameter_widgets[param_key] = widget
            
            # Get display name with language support
            display_name = self.data_object.get_display_name(param_key)
            
            # Add required indicator
            if param_info.get('required', False):
                display_name += " *"
            
            form_layout.addRow(QLabel(display_name + ":"), widget)
        
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)
        
        # Button layout
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.save_btn = GreenButton("Save")
        self.save_btn.clicked.connect(self.save_changes)
        button_layout.addWidget(self.save_btn)
        
        self.cancel_btn = RedButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
    
    def get_profile_images_dir(self):
        """Get profile images directory if available"""
        try:
            if (hasattr(self.parent(), 'profile_manager') and 
                self.parent().profile_manager and
                self.parent().profile_manager.selected_profile):
                
                profile_dir = os.path.dirname(self.parent().profile_manager.selected_profile.config_path)
                return os.path.join(profile_dir, "images")
        except:
            pass
        return None
    
    def load_data(self):
        """Load current data into widgets"""
        from ui.widgets.parameters_widgets import ParameterWidgetFactory
        
        for param_key, widget in self.parameter_widgets.items():
            current_value = self.data_object.get_value(param_key)
            ParameterWidgetFactory.set_widget_value(widget, current_value)
    
    def validate_data(self):
        """Validate all parameters using base class validation"""
        from ui.widgets.parameters_widgets import ParameterWidgetFactory
        
        errors = []
        
        for param_key, widget in self.parameter_widgets.items():
            value = ParameterWidgetFactory.get_widget_value(widget)
            
            # Use base class validation but remove options validation
            param_info = self.data_object.parameters[param_key]
            
            # Check required
            if param_info.get('required', False) and not value:
                display_name = self.data_object.get_display_name(param_key)
                errors.append(f"{display_name} is required")
                continue
            
            # Check type-specific constraints
            param_type = param_info.get('type', 'string')
            
            if param_type in ['int', 'float'] and value is not None:
                try:
                    num_value = float(value)
                    
                    min_val = param_info.get('min')
                    max_val = param_info.get('max')
                    
                    if min_val is not None and num_value < min_val:
                        display_name = self.data_object.get_display_name(param_key)
                        errors.append(f"{display_name} must be at least {min_val}")
                    
                    if max_val is not None and num_value > max_val:
                        display_name = self.data_object.get_display_name(param_key)
                        errors.append(f"{display_name} must be at most {max_val}")
                    
                except (ValueError, TypeError):
                    display_name = self.data_object.get_display_name(param_key)
                    errors.append(f"{display_name} must be a valid number")
            
            # NOTE: Removed options validation - autocomplete is just for suggestions
            # elif param_type == 'string':
            #     options = param_info.get('options', [])
            #     if options and value and value not in options:
            #         display_name = self.data_object.get_display_name(param_key)
            #         errors.append(f"{display_name} must be one of: {', '.join(options)}")
        
        return errors
    
    def save_changes(self):
        """Validate and save changes"""
        # Validate data
        errors = self.validate_data()
        
        # Separate warnings from critical errors
        critical_errors = [e for e in errors if not e.lower().startswith('warning')]
        warnings = [e for e in errors if e.lower().startswith('warning')]
        
        # Handle critical errors
        if critical_errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(critical_errors))
            return
        
        # Handle warnings (ask user if they want to continue)
        if warnings:
            reply = QMessageBox.question(
                self, "Warning", 
                "\n".join(warnings) + "\n\nDo you want to continue anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        
        # Update data object
        try:
            from ui.widgets.parameters_widgets import ParameterWidgetFactory
            
            for param_key, widget in self.parameter_widgets.items():
                value = ParameterWidgetFactory.get_widget_value(widget)
                self.data_object.set_value(param_key, value)
            
            # Save to database if method is available
            if hasattr(self.data_object, 'save_to_database'):
                success = self.data_object.save_to_database()
                if not success:
                    QMessageBox.critical(self, "Error", "Failed to save to database")
                    return
            
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
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
        """)


class DialogManager:
    """Helper class for creating dialogs for different object types"""
    
    def __init__(self, database, profile_manager=None):
        self.database = database
        self.profile_manager = profile_manager
    
    def edit_object(self, object_class, object_id=None, ui_config=None, parent=None):
        """
        Generic method to edit any object type
        
        Args:
            object_class: Class to instantiate (ProductClass, ClientClass, etc.)
            object_id: ID of existing object (None for new object)
            ui_config: UI configuration dict
            parent: Parent widget
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        ui_config = ui_config or {}
        
        # Create or load object
        if object_id:
            # Load existing object
            obj = object_class(object_id, self.database, f"Existing {object_class.__name__}")
            obj.load_database_data()
        else:
            # New object
            obj = object_class(0, self.database, f"New {object_class.__name__}")
        
        # Create and show dialog
        dialog = BaseEditDialog(obj, ui_config, parent)
        return dialog.exec() == QDialog.Accepted