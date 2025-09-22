"""
Parameter Widgets Factory - Creates appropriate widgets for different parameter types
"""
import os
from PySide6.QtWidgets import (QLineEdit, QSpinBox, QDoubleSpinBox, QWidget, 
                               QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
                               QFileDialog, QMessageBox)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap

try:
    from ui.widgets.autocomplete_widgets import AutoCompleteLineEdit
except ImportError:
    # Fallback if autocomplete widget not available
    AutoCompleteLineEdit = None

try:
    from ui.widgets.preview_widget import PreviewWidget
except ImportError:
    # Fallback if preview widget not available
    PreviewWidget = None

import shutil


class NumericWidget(QWidget):
    """Widget for int/float parameters with validation"""
    
    def __init__(self, param_info, editable=True, parent=None):
        super().__init__(parent)
        self.param_info = param_info
        self.editable = editable
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Determine if int or float
        param_type = param_info.get('type', 'int')
        
        if param_type == 'float':
            self.spinbox = QDoubleSpinBox()
            self.spinbox.setDecimals(2)
        else:
            self.spinbox = QSpinBox()
        
        # Set range
        min_val = param_info.get('min', -999999)
        max_val = param_info.get('max', 999999)
        self.spinbox.setRange(min_val, max_val)
        
        # Set enabled state
        self.spinbox.setEnabled(editable)
        
        layout.addWidget(self.spinbox)
        
        # Add unit label if present
        unit = param_info.get('unit', '')
        if unit:
            unit_label = QLabel(unit)
            layout.addWidget(unit_label)
        
        self.apply_style()
    
    def value(self):
        return self.spinbox.value()
    
    def setValue(self, value):
        if value is not None:
            self.spinbox.setValue(float(value))
    
    def apply_style(self):
        if not self.editable:
            self.spinbox.setStyleSheet("""
                QSpinBox, QDoubleSpinBox {
                    background-color: #1e1e1e;
                    color: #888888;
                    border: 1px solid #444444;
                }
            """)
        else:
            self.spinbox.setStyleSheet("""
                QSpinBox, QDoubleSpinBox {
                    background-color: #2D2D2D;
                    color: white;
                    border: 1px solid #555555;
                }
            """)


class StringWidget(QWidget):
    """Widget for string parameters with autocomplete and validation"""
    
    def __init__(self, param_info, editable=True, parent=None):
        super().__init__(parent)
        self.param_info = param_info
        self.editable = editable
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Get options for autocomplete
        options = param_info.get('options', [])
        
        if options and AutoCompleteLineEdit:
            self.line_edit = AutoCompleteLineEdit(options=options)
        else:
            self.line_edit = QLineEdit()
        
        # Set enabled state
        self.line_edit.setEnabled(editable)
        
        # Connect validation
        self.line_edit.textChanged.connect(self.validate_input)
        
        layout.addWidget(self.line_edit)
        self.apply_style()
    
    def text(self):
        return self.line_edit.text()
    
    def setText(self, text):
        if text is not None:
            self.line_edit.setText(str(text))
    
    def validate_input(self, text):
        """Validate input against min/max length if specified"""
        # You can add length validation here if needed
        pass
    
    def apply_style(self):
        if not self.editable:
            self.line_edit.setStyleSheet("""
                QLineEdit {
                    background-color: #1e1e1e;
                    color: #888888;
                    border: 1px solid #444444;
                }
            """)
        else:
            self.line_edit.setStyleSheet("""
                QLineEdit {
                    background-color: #2D2D2D;
                    color: white;
                    border: 1px solid #555555;
                }
            """)


class ImageWidget(QWidget):
    """Widget for image parameters with preview and file selection - Fixed alignment"""
    
    def __init__(self, param_info, editable=True, profile_images_dir=None, parent=None):
        super().__init__(parent)
        self.param_info = param_info
        self.editable = editable
        self.profile_images_dir = profile_images_dir
        self.current_path = None
        
        # Main horizontal layout - preview on left, buttons on right
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)
        
        # Preview widget with fixed size
        preview_size = param_info.get('preview_size', 100)
        if PreviewWidget:
            self.preview = PreviewWidget(size=preview_size, category="product")
        else:
            # Fallback to simple label
            self.preview = QLabel("Image Preview")
            self.preview.setStyleSheet("border: 1px solid gray; text-align: center;")
        
        # Set fixed size for preview
        self.preview.setFixedSize(preview_size, preview_size)
        main_layout.addWidget(self.preview)
        
        # Buttons container (only if editable)
        if editable:
            buttons_container = QWidget()
            buttons_container.setFixedSize(100, preview_size)  # Match preview height
            buttons_layout = QVBoxLayout(buttons_container)
            buttons_layout.setContentsMargins(0, 0, 0, 0)
            buttons_layout.setSpacing(5)
            
            # Calculate button height to fit nicely in container
            button_height = (preview_size - 5) // 2  # Subtract spacing, divide by 2
            
            self.browse_btn = QPushButton("Browse...")
            self.browse_btn.setFixedHeight(button_height)
            self.browse_btn.clicked.connect(self.browse_image)
            buttons_layout.addWidget(self.browse_btn)
            
            self.clear_btn = QPushButton("Clear")
            self.clear_btn.setFixedHeight(button_height)
            self.clear_btn.clicked.connect(self.clear_image)
            buttons_layout.addWidget(self.clear_btn)
            
            main_layout.addWidget(buttons_container)
        
        # Add stretch to push everything to the left
        main_layout.addStretch()
        
        self.apply_style()
    
    def get_image_path(self):
        return self.current_path
    
    def set_image_path(self, path, copy_to_profile=True):
        """Set image path and optionally copy to profile directory"""
        if not path or not os.path.exists(path):
            self.current_path = None
            if hasattr(self.preview, 'set_image_path'):
                self.preview.set_image_path(None)
            return
        
        if copy_to_profile and self.profile_images_dir:
            try:
                # Ensure profile images directory exists
                os.makedirs(self.profile_images_dir, exist_ok=True)
                
                # Copy file to profile directory
                filename = os.path.basename(path)
                dest_path = os.path.join(self.profile_images_dir, filename)
                
                # Handle duplicate filenames
                counter = 1
                base_name, ext = os.path.splitext(filename)
                while os.path.exists(dest_path):
                    new_filename = f"{base_name}_{counter}{ext}"
                    dest_path = os.path.join(self.profile_images_dir, new_filename)
                    counter += 1
                
                shutil.copy2(path, dest_path)
                self.current_path = dest_path
            except Exception as e:
                QMessageBox.warning(self, "Warning", f"Could not copy image: {e}")
                self.current_path = path
        else:
            self.current_path = path
        
        if hasattr(self.preview, 'set_image_path'):
            # Using PreviewWidget
            self.preview.set_image_path(self.current_path)
        else:
            # Using fallback label
            if self.current_path and os.path.exists(self.current_path):
                self.preview.setText(f"Image: {os.path.basename(self.current_path)}")
            else:
                self.preview.setText("No Image")
    
    def browse_image(self):
        """Open file dialog to select image"""
        if not self.editable:
            return
            
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Image",
            "",
            "Image Files (*.png *.jpg *.jpeg *.gif *.bmp *.svg)"
        )
        
        if file_path:
            self.set_image_path(file_path)
    
    def clear_image(self):
        """Clear current image"""
        self.current_path = None
        if hasattr(self.preview, 'set_image_path'):
            self.preview.set_image_path(None)
        else:
            self.preview.setText("No Image")
    
    def apply_style(self):
        if hasattr(self, 'browse_btn'):
            self.browse_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3C3C3C;
                    color: white;
                    border: 1px solid #555555;
                    padding: 4px 8px;
                }
                QPushButton:hover {
                    background-color: #4C4C4C;
                }
            """)
        
        if hasattr(self, 'clear_btn'):
            self.clear_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3C3C3C;
                    color: white;
                    border: 1px solid #555555;
                    padding: 4px 8px;
                }
                QPushButton:hover {
                    background-color: #4C4C4C;
                }
            """)


class ParameterWidgetFactory:
    """Factory class to create appropriate widgets for parameters"""
    
    @staticmethod
    def create_widget(param_info, ui_config=None, profile_images_dir=None, editable=True):
        """Create appropriate widget based on parameter type"""
        ui_config = ui_config or {}
        param_type = param_info.get('type', 'string')
        
        if param_type in ['int', 'float']:
            return NumericWidget(param_info, editable)
        elif param_type == 'image':
            return ImageWidget(param_info, editable, profile_images_dir)
        else:  # string or unknown type
            return StringWidget(param_info, editable)
    
    @staticmethod
    def get_widget_value(widget):
        """Get value from any parameter widget"""
        if isinstance(widget, NumericWidget):
            return widget.value()
        elif isinstance(widget, StringWidget):
            return widget.text()
        elif isinstance(widget, ImageWidget):
            return widget.get_image_path()
        else:
            # Fallback for unknown widget types
            if hasattr(widget, 'text'):
                return widget.text()
            elif hasattr(widget, 'value'):
                return widget.value()
            return None
    
    @staticmethod
    def set_widget_value(widget, value):
        """Set value on any parameter widget"""
        if isinstance(widget, NumericWidget):
            widget.setValue(value)
        elif isinstance(widget, StringWidget):
            widget.setText(value)
        elif isinstance(widget, ImageWidget):
            widget.set_image_path(value, copy_to_profile=False)
        else:
            # Fallback for unknown widget types
            if hasattr(widget, 'setText'):
                widget.setText(str(value) if value is not None else '')
            elif hasattr(widget, 'setValue'):
                widget.setValue(float(value) if value is not None else 0)