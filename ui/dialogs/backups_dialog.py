"""
Backup management dialog - create and restore database backups
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QHBoxLayout, 
                               QMessageBox, QInputDialog, QLineEdit)
from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
import os
import re
import shutil
import time
from datetime import datetime

from ui.widgets.themed_widgets import RedButton, GreenButton, BlueButton
from ui.widgets.cards_list import GridCardsList
from core import pg_backup
from core.attachments import attachment_backup_root


class _BackupCreateWorker(QObject):
    finished = Signal(bool)
    failed = Signal(str)

    def __init__(self, callback, operation="backup_operation"):
        super().__init__()
        self.callback = callback
        self.operation = operation

    @Slot()
    def run(self):
        started = time.perf_counter()
        try:
            self.finished.emit(bool(self.callback()))
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            print(
                f"[PERFORMANCE] {self.operation} completed in "
                f"{time.perf_counter() - started:.2f} seconds"
            )

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
        self._backup_running = False
        
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
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #9ecbff;")
        layout.addWidget(self.status_label)

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
                dump_files = [
                    name for name in os.listdir(backup_path)
                    if name in ("database.dump", "schema.dump")
                    or name.lower().endswith(".backup")
                ]
                has_valid_dump = any(
                    os.path.isfile(os.path.join(backup_path, name))
                    and os.path.getsize(os.path.join(backup_path, name)) > 0
                    for name in dump_files
                )
                has_legacy_schema = os.path.isfile(
                    os.path.join(backup_path, "manifest.json")
                )
                if os.path.exists(config_path) and (has_valid_dump or has_legacy_schema):
                    backups[item] = {
                        'name': item,
                        'path': backup_path,
                        'config_path': config_path
                    }
        
        return backups
    
    def create_backup(self, backup_name, show_errors=True):
        """Create a new backup with given name"""
        backup_path = None
        try:
            backup_name = backup_name.strip()
            if (
                not backup_name
                or backup_name in (".", "..")
                or re.search(r'[<>:"/\\|?*]', backup_name)
                or backup_name.endswith((" ", "."))
            ):
                message = (
                    "Use a Windows-safe name without < > : \" / \\ | ? * and "
                    "do not end it with a space or period."
                )
                if show_errors:
                    QMessageBox.warning(self, "Invalid Backup Name", message)
                    return False
                raise ValueError(message)
            backup_path = os.path.join(self.backups_dir, backup_name)
            
            if backup_path and os.path.exists(backup_path):
                message = f"Backup '{backup_name}' already exists."
                if show_errors:
                    QMessageBox.warning(self, "Error", message)
                    return False
                raise ValueError(message)
            
            # Create backup directory
            os.makedirs(backup_path)

            # Attachments are copied separately from their canonical storage
            # root below. In portable builds that root may live inside the
            # profile directory, so copying it here as well would make the
            # dedicated copy fail on Windows with error 183 (destination
            # already exists).
            for item in os.listdir(self.profile_dir):
                if item in ("backups", "attachments"):
                    continue

                source_path = os.path.join(self.profile_dir, item)
                dest_path = os.path.join(backup_path, item)

                try:
                    if os.path.isfile(source_path):
                        shutil.copy2(source_path, dest_path)
                    elif os.path.isdir(source_path):
                        shutil.copytree(source_path, dest_path)
                except OSError as e:
                    print(f"Warning: Could not backup {source_path}: {e}")
                    # Continue with other files - partial backup is better than no backup

            # Dump the profile's actual data out of Postgres into the backup folder
            if getattr(self.current_profile, 'database_name', None):
                pg_backup.backup_database(self.current_profile.database_name, backup_path)
            else:
                pg_backup.backup_schema(self.current_profile.schema_name, backup_path)

            # Files are centrally stored beside the host application's data,
            # not in PostgreSQL or a workstation profile directory.
            db = getattr(self.parent(), 'database', None)
            if db:
                source = attachment_backup_root(db)
                if source.exists():
                    shutil.copytree(
                        source,
                        os.path.join(backup_path, "attachments"),
                        dirs_exist_ok=True,
                    )

            return True
            
        except Exception as e:
            # Clean up partial backup on failure
            if backup_path and os.path.exists(backup_path):
                try:
                    shutil.rmtree(backup_path)
                except:
                    pass
            if show_errors:
                QMessageBox.critical(self, "Error", f"Failed to create backup: {str(e)}")
                return False
            raise
    
    def restore_backup(self):
        """Restore selected backup"""
        if self._backup_running:
            return
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
        
        backup_path = os.path.join(self.backups_dir, self.selected_backup)
        database = getattr(self.parent(), "database", None)
        if database:
            print("Closing database connection for backup restore...")
            database.close()

        self._backup_running = True
        self.restore_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.status_label.setText("Restoring backup…")
        thread = QThread(self)
        worker = _BackupCreateWorker(
            lambda: self._restore_backup_data(backup_path, database),
            "restore_backup",
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._restore_completed)
        worker.failed.connect(self._restore_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(lambda: setattr(self, "_backup_thread", None))
        thread.finished.connect(thread.deleteLater)
        self._backup_thread = thread
        self._backup_worker = worker
        thread.start()

    def _restore_backup_data(self, backup_path, database):
        """Worker-thread portion of restore; never touches Qt widgets."""
        for item in os.listdir(self.profile_dir):
            if item == "backups":
                continue
            item_path = os.path.join(self.profile_dir, item)
            if os.path.isfile(item_path):
                os.remove(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)

        skip_names = {"manifest.json", "schema.dump", "database.dump", "attachments"}
        for item in os.listdir(backup_path):
            if item in skip_names or item.endswith(".csv") or item.lower().endswith(".backup"):
                continue
            source_path = os.path.join(backup_path, item)
            dest_path = os.path.join(self.profile_dir, item)
            if os.path.isfile(source_path):
                shutil.copy2(source_path, dest_path)
            elif os.path.isdir(source_path):
                shutil.copytree(source_path, dest_path)

        if getattr(self.current_profile, "database_name", None):
            pg_backup.restore_database(self.current_profile.database_name, backup_path)
        else:
            pg_backup.restore_schema(self.current_profile.schema_name, backup_path)

        stored = os.path.join(backup_path, "attachments")
        if database and os.path.isdir(stored):
            target = attachment_backup_root(database)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(stored, target)
        return True

    def _reconnect_after_restore(self):
        database = getattr(self.parent(), "database", None)
        if database:
            print("Reconnecting database after backup restore...")
            return bool(database.connect())
        return True

    def _restore_completed(self, success):
        self._backup_running = False
        self.close_btn.setEnabled(True)
        self.status_label.setText("")
        if not success or not self._reconnect_after_restore():
            self.restore_btn.setEnabled(bool(self.selected_backup))
            QMessageBox.critical(self, "Error", "The backup finished but the database could not reconnect.")
            return
        if hasattr(self.parent(), "refresh_all_tabs"):
            self.parent().refresh_all_tabs()
        QMessageBox.information(
            self, "Success",
            "Backup restored successfully.\nThe application has been refreshed with the restored data.",
        )
        self.accept()

    def _restore_failed(self, error):
        self._backup_running = False
        self.close_btn.setEnabled(True)
        self.restore_btn.setEnabled(bool(self.selected_backup))
        self.status_label.setText("")
        reconnect_error = ""
        try:
            if not self._reconnect_after_restore():
                reconnect_error = "\nThe database could not reconnect."
        except Exception as exc:
            reconnect_error = f"\nReconnect failed: {exc}"
        QMessageBox.critical(
            self, "Error", f"Failed to restore backup: {error}{reconnect_error}"
        )
    
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
        if self._backup_running:
            return
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
            self._backup_running = True
            self.restore_btn.setEnabled(False)
            self.close_btn.setEnabled(False)
            self.status_label.setText("Creating backup…")
            thread = QThread(self)
            worker = _BackupCreateWorker(
                lambda: self.create_backup(backup_name, show_errors=False),
                "create_backup",
            )
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.finished.connect(self._backup_created)
            worker.failed.connect(self._backup_failed)
            worker.finished.connect(thread.quit)
            worker.failed.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            worker.failed.connect(worker.deleteLater)
            thread.finished.connect(lambda: setattr(self, "_backup_thread", None))
            thread.finished.connect(thread.deleteLater)
            self._backup_thread = thread
            self._backup_worker = worker
            thread.start()

    def _backup_created(self, success):
        self._backup_running = False
        self.close_btn.setEnabled(True)
        self.status_label.setText("")
        self.cards_list.load_cards()
        self.restore_btn.setEnabled(bool(self.selected_backup))
        if success:
            QMessageBox.information(self, "Success", "Backup created successfully.")

    def _backup_failed(self, error):
        self._backup_running = False
        self.close_btn.setEnabled(True)
        self.status_label.setText("")
        self.restore_btn.setEnabled(bool(self.selected_backup))
        QMessageBox.critical(self, "Error", f"Failed to create backup: {error}")
    
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

    def closeEvent(self, event):
        if self._backup_running:
            event.ignore()
            return
        super().closeEvent(event)
