"""
Profile management dialog - create, delete, and switch between user profiles
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QFileDialog, QScrollArea,
                               QSplitter, QWidget, QHBoxLayout, QLineEdit, QPushButton, QMessageBox, QTextEdit)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
import os
import time
import shutil

from ui.widgets.themed_widgets import RedButton, GreenButton, BlueButton
from ui.widgets.cards_list import GridCardsList
from core.profiles import ProfileClass, ProfileManager

class ProfilesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Profiles Manager")
        self.setModal(True)
        self.setMinimumSize(800, 500)
        self.load_config(parent)
        
        self.right_enabled = False
        self.is_editing_existing = False
        self.edit_mode = None  # None, 'new', 'edit', 'duplicate'
        self.source_profile_name = None  # Track source profile for duplication
        
        # Initialize right panel components
        self.image_path = ""
        self.original_image_path = ""  # Track original image to detect changes
        self.right_components = []  # Store all editable components
        self.parameter_edits = {}  # Store parameter line edits by key
        
        # Use parent's profile manager or create new one
        if hasattr(parent, 'profile_manager'):
            self.profile_manager = parent.profile_manager
        else:
            self.profile_manager = ProfileManager()
        
        self.profile_manager.profiles_path = self.profiles_path
        self.empty_profile = self.profile_manager.empty_profile
        self.current_profile = None
        
        # Store references to header and footer buttons for disabling
        self.header_footer_components = []
        
        # Apply dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QScrollArea {
                background-color: #2b2b2b;
                border: none;
            }
            QLabel {
                color: #ffffff;
            }
            QLineEdit {
                background-color: #404040;
                border: 1px solid #555555;
                padding: 5px;
                color: #ffffff;
            }
            QLineEdit:disabled {
                background-color: #2a2a2a;
                border: 1px solid #333333;
                color: #666666;
            }
        """)
        
        # Main vertical layout
        layout = QVBoxLayout()

        # Header row with label, stretch, line edit, and browse button
        header_layout = QHBoxLayout()
        header_label = QLabel("Profiles Dialog")
        header_label.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold;")
        header_layout.addWidget(header_label)

        header_layout.addStretch()

        self.profiles_path_edit = QLineEdit()
        self.profiles_path_edit.setReadOnly(True)
        self.profiles_path_edit.setFixedWidth(350)
        # Set initial path from config
        self.profiles_path_edit.setText(self.profiles_path)
        header_layout.addWidget(self.profiles_path_edit)

        self.browse_btn = BlueButton("Browse")
        self.browse_btn.setFixedSize(100, 30)
        self.browse_btn.clicked.connect(self.browse_profiles_path)
        header_layout.addWidget(self.browse_btn)
        
        # Store browse button for disabling
        self.header_footer_components.append(self.browse_btn)

        layout.addLayout(header_layout)

        # Splitter for left and right layouts
        splitter = QSplitter(Qt.Horizontal)

        # Create left and right widgets and set their layouts
        self.left_widget = QWidget()
        self.right_widget = QWidget()
        self.left_widget.setLayout(self.create_left_layout())
        self.right_widget.setLayout(self.create_right_layout())

        # Store splitter reference for resize handling
        self.splitter = splitter
        splitter.addWidget(self.left_widget)
        splitter.addWidget(self.right_widget)
        splitter.setSizes([250, 250])  # Initial sizes

        # Create overlay widget for left panel (initially hidden)
        self.create_overlay()

        # Connect splitter resize to overlay update
        splitter.splitterMoved.connect(self.update_overlay_size)

        layout.addWidget(splitter, stretch=1)

        # Confirm and Cancel buttons centered
        button_layout = QHBoxLayout()
        self.confirm_btn = GreenButton("Confirm")
        self.confirm_btn.clicked.connect(self.confirm)
        self.confirm_btn.setFixedSize(150, 30)
        self.cancel_btn = RedButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel)
        self.cancel_btn.setFixedSize(150, 30)
        button_layout.addStretch()
        button_layout.addWidget(self.confirm_btn)
        button_layout.addWidget(self.cancel_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        # Store footer buttons for disabling
        self.header_footer_components.extend([self.confirm_btn, self.cancel_btn])
        
        self.setLayout(layout)
        
        # Initialize with empty profile
        self.enable_right_layout(False)
        self.refresh_info()
        
        # Auto-select the currently selected profile
        self.auto_select_current_profile()
    
    def auto_select_current_profile(self):
        """Auto-select the currently selected profile when dialog opens"""
        if (self.profile_manager.selected_profile and 
            self.profile_manager.selected_profile.name in self.profile_manager.available_profiles):
            
            # Select the card in the cards list
            self.cards_list.select_card(self.profile_manager.selected_profile.name)
            
            # Update the right panel with the selected profile
            self.refresh_info(self.profile_manager.selected_profile)
        
    def create_overlay(self):
        """Create semi-transparent overlay for left panel"""
        self.overlay = QWidget(self.left_widget)
        self.overlay.setStyleSheet("""
            QWidget {
                background-color: rgba(0, 0, 0, 120);
                border-radius: 5px;
            }
        """)
        # Position overlay to cover entire left widget
        self.overlay.setGeometry(0, 0, self.left_widget.width(), self.left_widget.height())
        self.overlay.hide()
        
        # Make overlay consume all mouse events to prevent clicks
        self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        
    def update_overlay_size(self):
        """Update overlay size to match left widget"""
        if hasattr(self, 'overlay'):
            self.overlay.setGeometry(0, 0, self.left_widget.width(), self.left_widget.height())
        
    def showEvent(self, event):
        """Ensure overlay is properly sized when dialog is shown"""
        super().showEvent(event)
        self.update_overlay_size()
        
    def resizeEvent(self, event):
        """Update overlay size when dialog is resized"""
        super().resizeEvent(event)
        self.update_overlay_size()
        
    # MARK: Left Layout
    def create_left_layout(self):
        """Setup the left panel with profiles list"""
        left_layout = QVBoxLayout()
        self.cards_list = GridCardsList(category="profiles", parent=self)
        left_layout.addWidget(self.cards_list)
        return left_layout

    # MARK: Right Layout
    def create_right_layout(self):
        """Setup the right panel with profile details"""
        self.right_layout = QVBoxLayout()
        
        # Header with save and cancel buttons
        header_layout = QHBoxLayout()
        header_layout.addStretch()
        
        self.save_btn = GreenButton("Save")
        self.save_btn.setFixedSize(80, 30)
        self.save_btn.clicked.connect(self.save_profile)
        
        self.cancel_edit_btn = RedButton("Cancel")
        self.cancel_edit_btn.setFixedSize(80, 30)
        self.cancel_edit_btn.clicked.connect(self.cancel_edit)
        
        header_layout.addWidget(self.save_btn)
        header_layout.addWidget(self.cancel_edit_btn)
        
        self.right_layout.addLayout(header_layout)
        
        # Scrollable area
        scroll_area = QScrollArea()
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout()
        
        # Image preview
        self.image_label = QLabel("Click to select image")
        self.image_label.setFixedHeight(150)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("""
            QLabel {
                border: 2px dashed #555555;
                background-color: #404040;
                color: #aaaaaa;
            }
        """)
        self.image_label.mousePressEvent = self.select_image
        self.scroll_layout.addWidget(self.image_label)
        
        # Name field
        self.scroll_layout.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit()
        self.scroll_layout.addWidget(self.name_edit)
        
        # Create parameter fields dynamically
        self.parameter_edits = {}
        for param_key in self.empty_profile.available_parameters["dialog"]:
            display_name = self.empty_profile.get_display_name(param_key, self.language)
            self.scroll_layout.addWidget(QLabel(f"{display_name}:"))
            if param_key == "report footer":
                edit = QTextEdit()
                edit.setFixedHeight(100)
                edit.setStyleSheet("QTextEdit { background-color: #404040; border: 1px solid #555555; color: #ffffff; }")
            else:
                edit = QLineEdit()
            self.parameter_edits[param_key] = edit
            self.scroll_layout.addWidget(edit)
        
        # Password fields
        self.scroll_layout.addWidget(QLabel("Password:"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.scroll_layout.addWidget(self.password_edit)
        
        self.scroll_layout.addWidget(QLabel("Confirm Password:"))
        self.confirm_password_edit = QLineEdit()
        self.confirm_password_edit.setEchoMode(QLineEdit.Password)
        self.scroll_layout.addWidget(self.confirm_password_edit)
        
        self.scroll_layout.addStretch()
        
        self.scroll_widget.setLayout(self.scroll_layout)
        scroll_area.setWidget(self.scroll_widget)
        scroll_area.setWidgetResizable(True)
        
        self.right_layout.addWidget(scroll_area)
        
        # Store components for enable/disable functionality
        self.right_components = [
            self.save_btn,
            self.cancel_edit_btn,
            self.name_edit,
            self.password_edit,
            self.confirm_password_edit
        ]
        self.right_components.extend(self.parameter_edits.values())
        
        return self.right_layout
    
    def set_right_panel_edit_mode(self, edit_mode):
        """Set border color based on edit mode"""
        if edit_mode:
            # Blue border for edit mode - apply only to the right widget itself, not children
            self.right_widget.setStyleSheet("""
                QWidget#right_panel {
                    border: 2px solid #2196F3;
                    border-radius: 4px;
                }
            """)
            self.right_widget.setObjectName("right_panel")
        else:
            # Grey border for normal mode
            self.right_widget.setStyleSheet("""
                QWidget#right_panel {
                    border: 2px solid #555555;
                    border-radius: 4px;
                }
            """)
            self.right_widget.setObjectName("right_panel")
    
    def release_image_resources(self):
        """Release any resources held by the image label to prevent file locking"""
        try:
            # Clear the pixmap to release file handles
            self.image_label.clear()
            self.image_label.setText("Click to select image")
            # Force garbage collection of any lingering QPixmap objects
            import gc
            gc.collect()
            # Small delay to ensure file handles are released on Windows
            time.sleep(0.05)
        except Exception as e:
            print(f"Warning: Could not fully release image resources: {e}")
    
    # MARK: Profile Management
    def refresh_info(self, profile=None):
        """Update right panel with profile information"""
        if profile is None:
            profile = self.empty_profile
        
        # Release any existing image resources first
        self.release_image_resources()
        
        self.current_profile = profile
        
        # Update name
        self.name_edit.setText(profile.name)
        
        # Update image preview and track original path
        if profile.preview_path and os.path.exists(profile.preview_path):
            # Load image from file data instead of file path to avoid locking
            with open(profile.preview_path, 'rb') as f:
                image_data = f.read()
            
            pixmap = QPixmap()
            if pixmap.loadFromData(image_data):
                scaled_pixmap = pixmap.scaled(
                    self.image_label.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.image_label.setPixmap(scaled_pixmap)
                self.image_label.setText("")
            
            # Track the original image path
            self.image_path = profile.preview_path
            self.original_image_path = profile.preview_path
        else:
            self.image_label.clear()
            self.image_label.setText("Click to select image")
            self.image_path = ""
            self.original_image_path = ""
        
        # Update parameter fields
        for param_key, edit in self.parameter_edits.items():
            current_value = profile.get_value(param_key)
            if hasattr(edit, 'setPlainText'):
                if current_value is None:
                    default_value = profile.get_parameter_info(param_key, "default") or ""
                    edit.setPlainText(default_value)
                else:
                    edit.setPlainText(current_value)
            else:
                if current_value is None:
                    default_value = profile.get_parameter_info(param_key, "default")
                    edit.setText(default_value if default_value else "")
                else:
                    edit.setText(current_value)
        
        # Enable/disable password fields based on encrypted_phrase
        password_enabled = profile.encrypted_phrase is None and self.right_enabled
        self.password_edit.setEnabled(password_enabled)
        self.confirm_password_edit.setEnabled(password_enabled)
        
        # Clear password fields
        self.password_edit.setText("")
        self.confirm_password_edit.setText("")
    
    def refresh_profiles_list(self):
        """Reload profiles from filesystem and update cards list"""
        self.profile_manager.load_profiles()
        # Clear existing cards and reload
        self.cards_list.load_cards()
    
    # MARK: UI Interactions
    def select_image(self, event):
        """Open file dialog to select profile image"""
        if not self.right_enabled:
            return
            
        dialog = QFileDialog()
        image_path, _ = dialog.getOpenFileName(
            self,
            "Select Profile Image",
            "",
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        
        if image_path:
            # Release current image resources before loading new one
            self.release_image_resources()
            
            self.image_path = image_path
            
            # Load image from file data to avoid locking
            try:
                with open(image_path, 'rb') as f:
                    image_data = f.read()
                
                pixmap = QPixmap()
                if pixmap.loadFromData(image_data):
                    scaled_pixmap = pixmap.scaled(
                        self.image_label.size(),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                    self.image_label.setPixmap(scaled_pixmap)
                    self.image_label.setText("")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not load image: {e}")
    
    def enable_right_layout(self, enabled):
        """Enable or disable all editable components in right layout"""
        # Enable/disable right panel components
        for component in self.right_components:
            if hasattr(component, 'set_enable'):  # Themed buttons
                component.set_enable(enabled)
            elif hasattr(component, 'setEnabled'):  # Line edits and other widgets
                component.setEnabled(enabled)
        
        # Handle image selection separately
        if enabled:
            self.image_label.mousePressEvent = self.select_image
        else:
            self.image_label.mousePressEvent = lambda event: None
            
        # Enable/disable header and footer components (opposite of right panel)
        for component in self.header_footer_components:
            if hasattr(component, 'set_enable'):  # Themed buttons
                component.set_enable(not enabled)
            elif hasattr(component, 'setEnabled'):  # Standard widgets
                component.setEnabled(not enabled)
        
        # Show/hide overlay on left panel
        if enabled:
            self.update_overlay_size()
            self.overlay.show()
            self.overlay.raise_()  # Bring overlay to front
        else:
            self.overlay.hide()
            
        # Update right panel border color based on edit mode
        self.set_right_panel_edit_mode(enabled)
            
        self.right_enabled = enabled
    
    def safe_copy_image(self, source_path, dest_path):
        """Safely copy image file, handling self-copy and file locking"""
        try:
            # Normalize paths for comparison
            source_abs = os.path.abspath(source_path)
            dest_abs = os.path.abspath(dest_path)
            
            # Check if trying to copy file onto itself
            if source_abs == dest_abs:
                print(f"Skipping self-copy: {source_path} -> {dest_path}")
                return True
            
            # Release any image resources that might lock the file
            self.release_image_resources()
            
            # Ensure destination directory exists
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            
            # Copy with retries for Windows file locking
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    shutil.copy2(source_path, dest_path)
                    return True
                except (OSError, IOError) as e:
                    if attempt < max_retries - 1:
                        time.sleep(0.2)  # Wait before retry
                        continue
                    else:
                        raise e
                        
        except Exception as e:
            print(f"Error copying image {source_path} -> {dest_path}: {e}")
            return False
    
    # MARK: Profile Actions
    def save_profile(self):
        """Save current profile data"""
        try:
            # Validate required fields
            name = self.name_edit.text().strip()
            if not name:
                QMessageBox.warning(self, "Error", "Profile name is required.")
                return
            
            # Check password fields if creating new profile
            if self.edit_mode in ['new', 'duplicate']:
                password = self.password_edit.text()
                confirm_password = self.confirm_password_edit.text()
                
                if not password:
                    QMessageBox.warning(self, "Error", "Password is required for new profiles.")
                    return
                
                if password != confirm_password:
                    QMessageBox.warning(self, "Error", "Passwords do not match.")
                    return
            
            # Collect profile data
            profile_data = {'name': name}
            for param_key, edit in self.parameter_edits.items():
                if hasattr(edit, 'toPlainText'):
                    profile_data[param_key] = edit.toPlainText().strip()
                else:
                    profile_data[param_key] = edit.text().strip()
            
            # Handle image copying based on edit mode
            image_to_use = None
            if self.image_path:
                # For edit mode, check if image changed
                if self.edit_mode == 'edit':
                    if self.image_path != self.original_image_path:
                        # Image was changed, use new path
                        image_to_use = self.image_path
                    # If image_path == original_image_path, don't copy (prevents self-copy)
                else:
                    # For new/duplicate, always use selected image
                    image_to_use = self.image_path
            
            # Handle different save modes
            if self.edit_mode == 'new':
                profile = self.profile_manager.create_profile(profile_data, image_to_use)
                
                # Set password and encrypted phrase
                time.sleep(0.1)
                from core.password import PasswordManager
                password_manager = PasswordManager(self.profile_manager)
                profile.encrypted_phrase = password_manager.encrypt_data(
                    password_manager.validation_phrase, password)
                profile.save_to_config()
                
                # Select the newly created profile
                self.profile_manager.selected_profile = profile
                
            elif self.edit_mode == 'duplicate':
                # Use proper duplication method that copies database tables
                if self.source_profile_name:
                    profile = self.profile_manager.duplicate_profile(self.source_profile_name, profile_data['name'])
                    
                    # Update any modified parameter values from the UI
                    for key, value in profile_data.items():
                        if key != 'name':  # name is already set by duplicate_profile
                            profile.set_value(key, value)
                    
                    # Handle image if changed
                    if image_to_use:
                        profile_dir = os.path.dirname(profile.config_path)
                        preview_dest = os.path.join(profile_dir, "preview.png")
                        self.safe_copy_image(image_to_use, preview_dest)
                        profile.preview_path = preview_dest
                    
                    # IMPORTANT: Set new password for duplicate profile
                    password = self.password_edit.text()
                    if password:  # If new password is provided
                        time.sleep(0.1)
                        from core.password import PasswordManager
                        password_manager = PasswordManager(self.profile_manager)
                        profile.encrypted_phrase = password_manager.encrypt_data(
                            password_manager.validation_phrase, password)
                    else:
                        # If no new password provided, use the source profile's password
                        if self.source_profile_name in self.profile_manager.available_profiles:
                            source_profile = self.profile_manager.available_profiles[self.source_profile_name]
                            profile.encrypted_phrase = source_profile.encrypted_phrase
                    
                    # Save the updated profile
                    profile.save_to_config()
                else:
                    # Fallback to regular creation if source profile not found
                    profile = self.profile_manager.create_profile(profile_data, image_to_use)
                
                # Select the newly created profile
                self.profile_manager.selected_profile = profile
                
            elif self.edit_mode == 'edit':
                self.profile_manager.update_profile(self.current_profile.name, profile_data, image_to_use)
                # Keep the same selected profile (it was updated)
                
            # Refresh the profiles list
            self.refresh_profiles_list()
            self.enable_right_layout(False)
            self.source_profile_name = None  # Reset source profile name
            
            # Auto-select the saved profile
            if self.edit_mode in ['new', 'duplicate']:
                self.auto_select_current_profile()
            
            QMessageBox.information(self, "Success", "Profile saved successfully.")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save profile: {str(e)}")
    
    def cancel_edit(self):
        """Cancel current profile editing"""
        self.enable_right_layout(False)
        self.edit_mode = None
        self.source_profile_name = None  # Reset source profile name
        # Reset image paths
        self.image_path = ""
        self.original_image_path = ""
        self.refresh_info()
        
        # Re-select the current profile if there is one
        if self.profile_manager.selected_profile:
            self.auto_select_current_profile()
        
    def browse_profiles_path(self):
        """Open directory dialog to select profiles folder"""
        dialog = QFileDialog()
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        
        # Start from current profiles path or home directory
        start_dir = self.profiles_path if os.path.exists(self.profiles_path) else os.path.expanduser("~")
        
        selected_dir = dialog.getExistingDirectory(
            self, 
            "Select Profiles Directory", 
            start_dir
        )
        
        # Update path if user selected a directory (not cancelled)
        if selected_dir:
            self.profiles_path = selected_dir
            self.profiles_path_edit.setText(selected_dir)
            self.profile_manager.profiles_path = selected_dir
            self.refresh_profiles_list()

    def confirm(self):
        """Save changes and close dialog"""
        if self.profile_manager.selected_profile:
            self.accept()
        else:
            QMessageBox.warning(self, "Warning", "Please select a profile or create a new one.")
        
    def cancel(self):
        """Close dialog without saving changes"""
        self.reject()
    
    # MARK: Cards List Events
    def on_add_card_pressed(self):
        """Handle add card press"""
        self.edit_mode = 'new'
        self.image_path = ""
        self.original_image_path = ""
        
        # Unselect any currently selected card
        self.cards_list.select_card(None)
        
        self.refresh_info(self.empty_profile)
        self.enable_right_layout(True)
    
    def on_card_pressed(self, card_id):
        """Handle regular card press"""
        if card_id in self.profile_manager.available_profiles:
            profile = self.profile_manager.available_profiles[card_id]
            self.profile_manager.selected_profile = profile
            self.refresh_info(profile)
    
    def on_card_edit(self, card_id):
        """Handle card edit"""
        if card_id in self.profile_manager.available_profiles:
            profile = self.profile_manager.available_profiles[card_id]
            self.edit_mode = 'edit'
            self.refresh_info(profile)
            self.enable_right_layout(True)
    
    def on_card_duplicate(self, card_id):
        """Handle card duplicate"""
        if card_id in self.profile_manager.available_profiles:
            source_profile = self.profile_manager.available_profiles[card_id]
            self.edit_mode = 'duplicate'
            self.source_profile_name = source_profile.name  # Store source profile name
            
            # Create a copy with modified name
            duplicate_profile = ProfileClass(f"{source_profile.name}_copy")
            for key, param in source_profile.parameters.items():
                duplicate_profile.parameters[key]["value"] = param["value"]
            duplicate_profile.preview_path = source_profile.preview_path
            
            # IMPORTANT: DO NOT copy the encrypted phrase for UI display
            # This allows password fields to be enabled for setting a new password
            # The encrypted phrase will be copied later in duplicate_profile() if no new password is set
            duplicate_profile.encrypted_phrase = None
            
            # Unselect any currently selected card
            self.cards_list.select_card(None)
            
            self.refresh_info(duplicate_profile)
            self.enable_right_layout(True)
    
    def on_card_delete(self, card_id):
        """Handle card delete"""
        if card_id in self.profile_manager.available_profiles:
            profile_name = self.profile_manager.available_profiles[card_id].name
            
            reply = QMessageBox.question(
                self, "Delete Profile", 
                f"Are you sure you want to delete profile '{profile_name}'?\nThis action cannot be undone.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                try:
                    # Check if we're deleting the currently selected profile
                    was_selected = (self.profile_manager.selected_profile and 
                                  self.profile_manager.selected_profile.name == profile_name)
                    
                    self.profile_manager.delete_profile(card_id)
                    
                    # If we deleted the selected profile, clear the selection
                    if was_selected:
                        self.profile_manager.selected_profile = None
                    
                    self.refresh_profiles_list()
                    QMessageBox.information(self, "Success", "Profile deleted successfully.")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to delete profile: {str(e)}")
    
    # MARK: Config
    def load_config(self, parent):
        """Load configuration from parent or set defaults"""
        if hasattr(parent, 'profiles_path'):
            self.profiles_path = parent.profiles_path
        else:
            self.profiles_path = "./profiles"
        # Use parent's language if available
        if hasattr(parent, 'language') and parent.language:
            self.language = parent.language
        else:
            self.language = "en"
        
    def save_config(self):
        """Save current configuration to file"""
        pass  # Configuration is handled by parent main window