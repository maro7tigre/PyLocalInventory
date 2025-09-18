"""
Parameter Widgets System
Provides specialized widgets for different parameter types used by BaseEditDialog
"""

from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLineEdit, 
                               QLabel, QSpinBox, QDoubleSpinBox, QCompleter, 
                               QFileDialog, QPushButton, QFrame, QTextEdit)
from PySide6.QtCore import Qt, QStringListModel, Signal
from PySide6.QtGui import QPixmap, QValidator
import os
import shutil


class AutoCompleteLineEdit(QLineEdit):
    """String parameter with autocomplete suggestions and validation"""
    
    def __init__(self, options=None, parent=None):
        super().__init__(parent)
        self.options = options or []
        self.is_valid_option = True
        
        if self.options:
            # Setup autocomplete
            completer = QCompleter(self.options)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchStartsWith)
            self.setCompleter(completer)
        
        # Connect text change to validation
        self.textChanged.connect(self._validate_input)
        self._apply_default_style()
        
    def _validate_input(self, text):
        """Validate input against options and update border color"""
        if not self.options:
            self.is_valid_option = True
            self._update_border_color("#ffffff")
            return
            
        # Check if text matches any option (case insensitive)
        matches = any(option.lower() == text.lower() for option in self.options)
        self.is_valid_option = matches or text == ""
        
        # Update border color
        if text == "":
            self._update_border_color("#ffffff")  # Default
        elif matches:
            self._update_border_color("#4CAF50")  # Green for valid
        else:
            self._update_border_color("#ff9800")  # Orange for invalid
    
    def _update_border_color(self, color):
        """Update border color"""
        self.setStyleSheet(f"""
            QLineEdit {{
                background-color: #3c3c3c;
                color: #ffffff;
                border: 2px solid {color};
                padding: 8px;
                border-radius: 4px;
            }}
            QLineEdit:focus {{
                border-color: #2196F3;
            }}
        """)
    
    def _apply_default_style(self):
        """Apply default styling"""
        self._update_border_color("#ffffff")


class NumericWidget(QWidget):
    """Numeric parameter (int/float) with unit display and validation"""
    
    def __init__(self, param_type="float", unit="", minimum=None, maximum=None, parent=None):
        super().__init__(parent)
        self.param_type = param_type
        self.unit = unit
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create appropriate numeric input
        if param_type == "int":
            self.input = QSpinBox()
            if minimum is not None:
                self.input.setMinimum(int(minimum))
            if maximum is not None:
                self.input.setMaximum(int(maximum))
        else:  # float
            self.input = QDoubleSpinBox()
            self.input.setDecimals(2)
            if minimum is not None:
                self.input.setMinimum(float(minimum))
            if maximum is not None:
                self.input.setMaximum(float(maximum))
        
        # Style the input
        self.input.setStyleSheet("""
            QSpinBox, QDoubleSpinBox {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 2px solid #ffffff;
                padding: 8px;
                border-radius: 4px;
            }
        """)
        
        layout.addWidget(self.input)
        
        # Add unit label if provided
        if unit:
            unit_label = QLabel(unit)
            unit_label.setStyleSheet("color: #cccccc; margin-left: 5px;")
            layout.addWidget(unit_label)
    
    def value(self):
        """Get current value"""
        return self.input.value()
    
    def setValue(self, value):
        """Set value"""
        try:
            if self.param_type == "int":
                self.input.setValue(int(float(value)))
            else:
                self.input.setValue(float(value))
        except (ValueError, TypeError):
            self.input.setValue(0)
    
    def setEnabled(self, enabled):
        """Enable/disable input"""
        self.input.setEnabled(enabled)


class ImagePreviewWidget(QWidget):
    """Image parameter with preview and browse capability"""
    
    imageChanged = Signal(str)  # Emits new image path
    
    def __init__(self, size=(100, 100), browsing_enabled=True, profile_images_dir=None, parent=None):
        super().__init__(parent)
        self.size = size
        self.browsing_enabled = browsing_enabled
        self.profile_images_dir = profile_images_dir  # Directory to copy images to
        self.current_image_path = ""
        
        self.setFixedSize(*size)
        self.setup_ui()
        
    def setup_ui(self):
        """Setup preview area"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        
        # Preview label
        self.preview_label = QLabel("Click to browse")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("""
            QLabel {
                border: 2px dashed #555555;
                background-color: #404040;
                color: #aaaaaa;
                border-radius: 4px;
            }
        """)
        
        layout.addWidget(self.preview_label)
        
        # Connect click event if browsing is enabled
        if self.browsing_enabled:
            self.preview_label.mousePressEvent = self._browse_image
    
    def _browse_image(self, event):
        """Open file dialog to select image"""
        if not self.browsing_enabled:
            return
            
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "", 
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        
        if file_path:
            self.set_image_path(file_path)
    
    def set_image_path(self, path, copy_to_profile=True):
        """Set image path and update preview"""
        if not os.path.exists(path):
            return
            
        # Copy to profile images directory if specified
        final_path = path
        if copy_to_profile and self.profile_images_dir:
            try:
                os.makedirs(self.profile_images_dir, exist_ok=True)
                filename = os.path.basename(path)
                dest_path = os.path.join(self.profile_images_dir, filename)
                
                # Handle duplicate filenames
                counter = 1
                while os.path.exists(dest_path):
                    name, ext = os.path.splitext(filename)
                    dest_path = os.path.join(self.profile_images_dir, f"{name}_{counter}{ext}")
                    counter += 1
                
                shutil.copy2(path, dest_path)
                final_path = dest_path
            except Exception as e:
                print(f"Failed to copy image: {e}")
                final_path = path
        
        self.current_image_path = final_path
        self._update_preview(final_path)
        self.imageChanged.emit(final_path)
    
    def _update_preview(self, path):
        """Update preview with image"""
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(
                self.size[0] - 6, self.size[1] - 6,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.preview_label.setPixmap(scaled_pixmap)
            self.preview_label.setText("")  # Clear text when image is loaded
        else:
            self.preview_label.setText("Invalid image")
    
    def get_image_path(self):
        """Get current image path"""
        return self.current_image_path
    
    def set_browsing_enabled(self, enabled):
        """Enable/disable browsing"""
        self.browsing_enabled = enabled
        if enabled:
            self.preview_label.mousePressEvent = self._browse_image
        else:
            self.preview_label.mousePressEvent = lambda e: None


class MultiLineTextWidget(QTextEdit):
    """Multi-line text widget for longer text fields like notes"""
    
    def __init__(self, height=80, parent=None):
        super().__init__(parent)
        self.setMaximumHeight(height)
        
        # Apply dark theme styling
        self.setStyleSheet("""
            QTextEdit {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 2px solid #ffffff;
                padding: 8px;
                border-radius: 4px;
            }
        """)
    
    def text(self):
        """Get plain text (compatible with QLineEdit interface)"""
        return self.toPlainText()
    
    def setText(self, text):
        """Set plain text (compatible with QLineEdit interface)"""
        self.setPlainText(text)


class ParameterWidgetFactory:
    """Factory to create appropriate widgets based on parameter definition"""
    
    @staticmethod
    def create_widget(param_info, ui_config=None, profile_images_dir=None):
        """
        Create widget based on parameter info
        
        Args:
            param_info: dict with parameter definition from classes
            ui_config: dict with UI-specific configuration like:
                {
                    'size': (100, 100),  # For image widgets
                    'browsing_enabled': True,  # For image widgets
                    'read_only': False,  # For all widgets
                    'height': 80,  # For text widgets
                    'minimum': 0,  # For numeric widgets
                    'maximum': 1000,  # For numeric widgets
                    'unit': '€'  # For numeric widgets
                }
            profile_images_dir: Directory to store copied images
        """
        if ui_config is None:
            ui_config = {}
            
        param_type = param_info.get('type', 'string')
        
        # Create widget based on type
        if param_type == 'string':
            options = param_info.get('options', [])
            widget = AutoCompleteLineEdit(options)
            
        elif param_type in ['int', 'float']:
            # Get unit from UI config or param info
            unit = ui_config.get('unit', param_info.get('unit', ''))
            # Get min/max from UI config or param info
            minimum = ui_config.get('minimum', param_info.get('minimum'))
            maximum = ui_config.get('maximum', param_info.get('maximum'))
            
            widget = NumericWidget(param_type, unit, minimum, maximum)
            
        elif param_type == 'text':
            # Multi-line text area
            height = ui_config.get('height', 80)
            widget = MultiLineTextWidget(height)
            
        elif param_type == 'image':
            size = ui_config.get('size', (100, 100))
            browsing_enabled = ui_config.get('browsing_enabled', True)
            widget = ImagePreviewWidget(size, browsing_enabled, profile_images_dir)
            
        else:
            # Fallback to simple line edit
            widget = QLineEdit()
            widget.setStyleSheet("""
                QLineEdit {
                    background-color: #3c3c3c;
                    color: #ffffff;
                    border: 2px solid #ffffff;
                    padding: 8px;
                    border-radius: 4px;
                }
            """)
            
        # Apply read-only setting
        if ui_config.get('read_only', False):
            widget.setEnabled(False)
            
        return widget


# Example and testing
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    
    app = QApplication(sys.argv)
    
    # Test window
    window = QWidget()
    window.setWindowTitle("Parameter Widgets Test")
    window.resize(400, 500)
    
    layout = QVBoxLayout(window)
    
    # Test different widget types
    
    # String with options
    layout.addWidget(QLabel("String with options:"))
    string_widget = ParameterWidgetFactory.create_widget({
        'type': 'string',
        'options': ['Option 1', 'Option 2', 'Option 3']
    })
    layout.addWidget(string_widget)
    
    # Float with unit
    layout.addWidget(QLabel("Float with unit:"))
    float_widget = ParameterWidgetFactory.create_widget({
        'type': 'float',
        'unit': '€',
        'minimum': 0,
        'maximum': 1000
    })
    layout.addWidget(float_widget)
    
    # Text area
    layout.addWidget(QLabel("Text area:"))
    text_widget = ParameterWidgetFactory.create_widget({
        'type': 'text'
    }, {'height': 60})
    layout.addWidget(text_widget)
    
    # Image preview
    layout.addWidget(QLabel("Image preview:"))
    image_widget = ParameterWidgetFactory.create_widget({
        'type': 'image'
    }, {'size': (80, 80)})
    layout.addWidget(image_widget)
    
    # Apply dark theme to window
    window.setStyleSheet("""
        QWidget {
            background-color: #2b2b2b;
            color: #ffffff;
        }
        QLabel {
            color: #ffffff;
            font-weight: bold;
            margin-top: 10px;
        }
    """)
    
    window.show()
    sys.exit(app.exec())