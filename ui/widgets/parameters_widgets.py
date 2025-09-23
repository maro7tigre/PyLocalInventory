"""
Parameter Widgets Factory - Creates appropriate widgets for different parameter types
"""
import os
from datetime import datetime
from PySide6.QtWidgets import (QLineEdit, QSpinBox, QDoubleSpinBox, QWidget, 
                               QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
                               QFileDialog, QMessageBox, QDateEdit)
from PySide6.QtCore import Qt, Signal, QDate
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


class DateWidget(QWidget):
    """Widget for date parameters"""
    
    def __init__(self, param_info, editable=True, parent=None):
        super().__init__(parent)
        self.param_info = param_info
        self.editable = editable
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())  # Default to today
        self.date_edit.setEnabled(editable)
        
        layout.addWidget(self.date_edit)
        self.apply_style()
    
    def date(self):
        """Get date as string in YYYY-MM-DD format"""
        return self.date_edit.date().toString("yyyy-MM-dd")
    
    def setDate(self, date_str):
        """Set date from string (YYYY-MM-DD format)"""
        if date_str and isinstance(date_str, str):
            try:
                date_obj = QDate.fromString(date_str, "yyyy-MM-dd")
                if date_obj.isValid():
                    self.date_edit.setDate(date_obj)
            except:
                # Fallback to current date if invalid
                self.date_edit.setDate(QDate.currentDate())
        else:
            self.date_edit.setDate(QDate.currentDate())
    
    def apply_style(self):
        if not self.editable:
            self.date_edit.setStyleSheet("""
                QDateEdit {
                    background-color: #1e1e1e;
                    color: #888888;
                    border: 1px solid #444444;
                }
            """)
        else:
            self.date_edit.setStyleSheet("""
                QDateEdit {
                    background-color: #2D2D2D;
                    color: white;
                    border: 1px solid #555555;
                    padding: 5px;
                }
                QDateEdit::drop-down {
                    border: none;
                    background-color: #404040;
                }
                QDateEdit::down-arrow {
                    image: none;
                    border-left: 5px solid transparent;
                    border-right: 5px solid transparent;
                    border-top: 5px solid white;
                }
            """)


class ButtonWidget(QWidget):
    """Widget for button parameters (like delete buttons in tables)"""
    
    clicked = Signal()  # Signal emitted when button is clicked
    
    def __init__(self, param_info, editable=True, parent=None):
        super().__init__(parent)
        self.param_info = param_info
        self.editable = editable
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Get button properties from param_info
        button_text = param_info.get('text', '🗑️')  # Default trash emoji
        button_color = param_info.get('color', 'red')  # Default red
        button_size = param_info.get('size', 30)  # Default size
        
        self.button = QPushButton(button_text)
        self.button.setFixedSize(button_size, button_size)
        self.button.setEnabled(editable)
        self.button.clicked.connect(self.clicked.emit)
        
        layout.addWidget(self.button)
        layout.addStretch()
        
        self.apply_style(button_color)
    
    def apply_style(self, color='red'):
        """Apply button styling based on color"""
        if color == 'red':
            border_color = '#f44336'
            hover_bg = '#f44336'
        elif color == 'blue':
            border_color = '#2196F3'
            hover_bg = '#2196F3'
        elif color == 'green':
            border_color = '#4CAF50'
            hover_bg = '#4CAF50'
        else:
            border_color = '#666666'
            hover_bg = '#666666'
        
        if not self.editable:
            self.button.setStyleSheet(f"""
                QPushButton {{
                    background-color: #1e1e1e;
                    color: #888888;
                    border: 1px solid #444444;
                    border-radius: 4px;
                }}
            """)
        else:
            self.button.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {border_color};
                    border: 2px solid {border_color};
                    border-radius: 4px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {hover_bg};
                    color: white;
                }}
                QPushButton:pressed {{
                    background-color: {hover_bg};
                    opacity: 0.8;
                }}
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
        elif param_type == 'date':
            return DateWidget(param_info, editable)
        elif param_type == 'button':
            return ButtonWidget(param_info, editable)
        elif param_type == 'table':
            # Table parameters are now handled directly by OperationsTableWidget
            # Return a placeholder since table parameters should be created directly
            placeholder = QLabel("Table parameters should use OperationsTableWidget directly")
            placeholder.setStyleSheet("color: #ff9800; font-style: italic;")
            return placeholder
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
        elif isinstance(widget, DateWidget):
            return widget.date()
        elif isinstance(widget, ButtonWidget):
            return None  # Buttons don't have values
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
        elif isinstance(widget, DateWidget):
            widget.setDate(value)
        elif isinstance(widget, ButtonWidget):
            pass  # Buttons don't have settable values
        else:
            # Fallback for unknown widget types
            if hasattr(widget, 'setText'):
                widget.setText(str(value) if value is not None else '')
            elif hasattr(widget, 'setValue'):
                widget.setValue(float(value) if value is not None else 0)


# Test widget for sales table - as requested
class SalesTableTestWidget(QWidget):
    """Test widget for sales table with delete buttons"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.apply_theme()
    
    def setup_ui(self):
        """Setup test interface"""
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("Sales Table Test - With Delete Buttons")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        layout.addWidget(title)
        
        # Create table parameter directly using table type
        table_param_info = {
            'type': 'table',
            'item_class': None,  # Will be set below
            'parent_operation': None,
            'display_name': {'en': 'Sales Items'}
        }
        
        # Import SalesItemClass for the test
        try:
            from classes.sales_item_class import SalesItemClass
            table_param_info['item_class'] = SalesItemClass
            
            # Create the table widget
            self.sales_table = ParameterWidgetFactory.create_widget(table_param_info, editable=True)
            layout.addWidget(self.sales_table)
            
            # Connect to changes
            if hasattr(self.sales_table, 'items_changed'):
                self.sales_table.items_changed.connect(self.on_items_changed)
            
        except ImportError as e:
            error_label = QLabel(f"Could not load SalesItemClass: {e}")
            error_label.setStyleSheet("color: #f44336; font-style: italic;")
            layout.addWidget(error_label)
    
    def on_items_changed(self):
        """Handle when items change"""
        print("Sales items changed!")
    
    def apply_theme(self):
        """Apply theme"""
        self.setStyleSheet("""
            QWidget { background-color: #2b2b2b; color: #ffffff; }
            QLabel { color: #ffffff; }
        """)


if __name__ == "__main__":
    """Test the sales table widget"""
    import sys
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont
    
    app = QApplication(sys.argv)
    
    # Test the sales table
    window = SalesTableTestWidget()
    window.setWindowTitle("Sales Table Parameter Test")
    window.resize(900, 600)
    window.show()
    
    sys.exit(app.exec())