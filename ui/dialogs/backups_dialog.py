"""
Backup management dialog - create and restore database backups
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QHBoxLayout, 
                               QMessageBox, QInputDialog, QLineEdit)
from PySide6.QtCore import Qt
import os
import shutil
import time
from datetime import datetime

from ui.widgets.themed_widgets import RedButton, GreenButton, BlueButton
from ui.widgets.cards_list import GridCardsList

class BackupsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Backups Manager")
        self.setModal(True)
        self.setMinimumSize(400, 500)
        
        # Initialize default values
        self.current_profile = None
        self.profile_dir = None
        self.backups_dir = None
        self.selected_backup = None
        
        # Load configuration - if this fails, dialog will close
        if not self.load_config(parent):
            return
            
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the UI components"""
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
            QInputDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLineEdit {
                background-color: #404040;
                border: 1px solid #555555;
                padding: 5px;
                color: #ffffff;
            }
        """)
        
        # Main vertical layout
        layout = QVBoxLayout()

        # Header
        header_label = QLabel("Database Backups")
        header_label.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold;")
        layout.addWidget(header_label)

        # Cards list for backups
        self.cards_list = GridCardsList(category="backups", parent=self)
        layout.addWidget(self.cards_list, stretch=1)

        # Bottom buttons layout
        button_layout = QHBoxLayout()
        
        # Restore button (main action)
        self.restore_btn = BlueButton("Restore")
        self.restore_btn.clicked.connect(self.restore_backup)
        self.restore_btn.setFixedSize(100, 30)
        self.restore_btn.setEnabled(False)  # Disabled until backup selected
        
        # Close button
        self.close_btn = RedButton("Close")
        self.close_btn.clicked.connect(self.close)
        self.close_btn.setFixedSize(100, 30)
        
        button_layout.addStretch()
        button_layout.addWidget(self.restore_btn)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
        # Load existing backups
        self.refresh_backups_list()
    
    def load_config(self, parent):
        """Load configuration from parent"""
        if hasattr(parent, 'profile_manager') and parent.profile_manager.selected_profile:
            self.current_profile = parent.profile_manager.selected_profile
            self.profile_dir = os.path.dirname(self.current_profile.config_path)
            self.backups_dir = os.path.join(self.profile_dir, "backups")
            
            # Ensure backups directory exists
            os.makedirs(self.backups_dir, exist_ok=True)
            return True
        else:
            QMessageBox.warning(self, "Error", "No profile selected. Please select a profile first.")
            self.reject()
            return False
    
    def refresh_backups_list(self):
        """Reload backups from filesystem and update cards list"""
        # This will be called by the cards list to load backup data
        pass
    
    def get_available_backups(self):
        """Get list of available backup directories"""
        backups = {}
        if not self.backups_dir or not os.path.exists(self.backups_dir):
            return backups
        
        for item in os.listdir(self.backups_dir):
            backup_path = os.path.join(self.backups_dir, item)
            if os.path.isdir(backup_path):
                # Check if it's a valid backup (has config.json and database)
                config_path = os.path.join(backup_path, "config.json")
                if os.path.exists(config_path):
                    backups[item] = {
                        'name': item,
                        'path': backup_path,
                        'config_path': config_path
                    }
        
        return backups
    
    def create_backup(self, backup_name):
        """Create a new backup with given name"""
        try:
            backup_path = os.path.join(self.backups_dir, backup_name)
            
            if os.path.exists(backup_path):
                QMessageBox.warning(self, "Error", f"Backup '{backup_name}' already exists.")
                return False
            
            # Create backup directory
            os.makedirs(backup_path)
            
            # Copy profile contents except backups directory
            for item in os.listdir(self.profile_dir):
                if item == "backups":
                    continue
                    
                source_path = os.path.join(self.profile_dir, item)
                dest_path = os.path.join(backup_path, item)
                
                try:
                    if os.path.isfile(source_path):
                        # For database files, use a retry mechanism
                        if source_path.endswith('.db'):
                            max_retries = 3
                            for attempt in range(max_retries):
                                try:
                                    shutil.copy2(source_path, dest_path)
                                    break
                                except OSError as e:
                                    if attempt < max_retries - 1:
                                        time.sleep(0.1)  # Wait before retry
                                        continue
                                    else:
                                        raise e
                        else:
                            shutil.copy2(source_path, dest_path)
                    elif os.path.isdir(source_path):
                        shutil.copytree(source_path, dest_path)
                except OSError as e:
                    print(f"Warning: Could not backup {source_path}: {e}")
                    # Continue with other files - partial backup is better than no backup
            
            return True
            
        except Exception as e:
            # Clean up partial backup on failure
            if os.path.exists(backup_path):
                try:
                    shutil.rmtree(backup_path)
                except:
                    pass
            QMessageBox.critical(self, "Error", f"Failed to create backup: {str(e)}")
            return False
    
    def restore_backup(self):
        """Restore selected backup"""
        if not self.selected_backup:
            QMessageBox.warning(self, "Warning", "Please select a backup to restore.")
            return
        
        reply = QMessageBox.question(
            self, "Confirm Restore", 
            f"Are you sure you want to restore backup '{self.selected_backup}'?\n\n"
            "This will replace all current data and cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            backup_path = os.path.join(self.backups_dir, self.selected_backup)
            
            # Close database connection to release file locks
            if hasattr(self.parent(), 'database') and self.parent().database:
                print("Closing database connection for backup restore...")
                self.parent().database.close()
            
            # Small delay to ensure file handles are fully released
            time.sleep(0.2)
            
            # Remove current profile contents (except backups)
            for item in os.listdir(self.profile_dir):
                if item == "backups":
                    continue
                    
                item_path = os.path.join(self.profile_dir, item)
                try:
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                except OSError as e:
                    print(f"Warning: Could not remove {item_path}: {e}")
                    # Continue with other files
            
            # Copy backup contents back to profile
            for item in os.listdir(backup_path):
                source_path = os.path.join(backup_path, item)
                dest_path = os.path.join(self.profile_dir, item)
                
                try:
                    if os.path.isfile(source_path):
                        shutil.copy2(source_path, dest_path)
                    elif os.path.isdir(source_path):
                        shutil.copytree(source_path, dest_path)
                except OSError as e:
                    print(f"Warning: Could not copy {source_path}: {e}")
                    # Continue with other files
            
            # Reconnect database with restored files
            if hasattr(self.parent(), 'database') and self.parent().database:
                print("Reconnecting database after backup restore...")
                self.parent().database.connect()
                
                # Refresh all tabs if they exist
                if hasattr(self.parent(), 'refresh_all_tabs'):
                    self.parent().refresh_all_tabs()
            
            QMessageBox.information(self, "Success", "Backup restored successfully.\nThe application has been refreshed with the restored data.")
            self.accept()  # Close dialog after successful restore
            
        except Exception as e:
            # Try to reconnect database even if restore failed
            if hasattr(self.parent(), 'database') and self.parent().database:
                try:
                    self.parent().database.connect()
                except:
                    pass
            QMessageBox.critical(self, "Error", f"Failed to restore backup: {str(e)}")
    
    def delete_backup(self, backup_name):
        """Delete a backup"""
        try:
            backup_path = os.path.join(self.backups_dir, backup_name)
            if os.path.exists(backup_path):
                shutil.rmtree(backup_path)
            return True
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to delete backup: {str(e)}")
            return False
    
    def duplicate_backup(self, source_name):
        """Duplicate a backup with a new name"""
        new_name, ok = QInputDialog.getText(
            self, "Duplicate Backup", 
            "Enter name for the duplicate backup:",
            QLineEdit.Normal,
            f"{source_name}_copy"
        )
        
        if not ok or not new_name.strip():
            return False
        
        new_name = new_name.strip()
        
        try:
            source_path = os.path.join(self.backups_dir, source_name)
            dest_path = os.path.join(self.backups_dir, new_name)
            
            if os.path.exists(dest_path):
                QMessageBox.warning(self, "Error", f"Backup '{new_name}' already exists.")
                return False
            
            shutil.copytree(source_path, dest_path)
            self.cards_list.load_cards()  # Refresh list
            return True
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to duplicate backup: {str(e)}")
            return False
    
    def rename_backup(self, old_name):
        """Rename a backup"""
        new_name, ok = QInputDialog.getText(
            self, "Rename Backup", 
            "Enter new name for the backup:",
            QLineEdit.Normal,
            old_name
        )
        
        if not ok or not new_name.strip():
            return False
        
        new_name = new_name.strip()
        
        if new_name == old_name:
            return False  # No change
        
        try:
            old_path = os.path.join(self.backups_dir, old_name)
            new_path = os.path.join(self.backups_dir, new_name)
            
            if os.path.exists(new_path):
                QMessageBox.warning(self, "Error", f"Backup '{new_name}' already exists.")
                return False
            
            os.rename(old_path, new_path)
            
            # Update selection if the renamed backup was selected
            if self.selected_backup == old_name:
                self.selected_backup = new_name
            
            self.cards_list.load_cards()  # Refresh list
            return True
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to rename backup: {str(e)}")
            return False
    
    # Cards List Events
    def on_add_card_pressed(self):
        """Handle add backup button press"""
        # Generate default timestamp name
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        
        backup_name, ok = QInputDialog.getText(
            self, "Create Backup", 
            "Enter backup name:",
            QLineEdit.Normal,
            timestamp
        )
        
        if ok and backup_name.strip():
            backup_name = backup_name.strip()
            if self.create_backup(backup_name):
                self.cards_list.load_cards()  # Refresh list
                QMessageBox.information(self, "Success", "Backup created successfully.")
    
    def on_card_pressed(self, card_id):
        """Handle backup card selection"""
        self.selected_backup = card_id
        self.restore_btn.setEnabled(True)
    
    def on_card_edit(self, card_id):
        """Handle backup edit (rename)"""
        self.rename_backup(card_id)
    
    def on_card_duplicate(self, card_id):
        """Handle backup duplicate"""
        self.duplicate_backup(card_id)
    
    def on_card_delete(self, card_id):
        """Handle backup delete"""
        reply = QMessageBox.question(
            self, "Delete Backup", 
            f"Are you sure you want to delete backup '{card_id}'?\n"
            "This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if self.delete_backup(card_id):
                if self.selected_backup == card_id:
                    self.selected_backup = None
                    self.restore_btn.setEnabled(False)
                self.cards_list.load_cards()  # Refresh list
                QMessageBox.information(self, "Success", "Backup deleted successfully.")