"""
Main window class - coordinates all UI components and handles window layout
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QTabWidget, QMenuBar, QMenu)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QAction

from ui.widgets.themed_widgets import ThemedMainWindow, GreenButton, ColoredLineEdit
from ui.dialogs.profiles_dialog import ProfilesDialog
from ui.dialogs.backups_dialog import BackupsDialog
from ui.dialogs.encryption_dialog import EncryptionDialog
from ui.tabs.home_tab import HomeTab
from ui.tabs.operations_tab import OperationsTab
from ui.tabs.products_tab import ProductsTab
from ui.tabs.clients_tab import ClientsTab
from ui.tabs.suppliers_tab import SuppliersTab
from ui.tabs.log_tab import LogTab
from core.profiles import ProfileManager
from core.password import PasswordManager
from core.database import Database

class MainWindow(ThemedMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyLocalInventory")
        self.setMinimumSize(1000, 700)
        
        # Load application settings
        self.settings = QSettings("PyLocalInventory", "MainApp")
        self.load_app_config()
        
        # Core managers
        self.profile_manager = ProfileManager()
        self.password_manager = PasswordManager(self.profile_manager)
        
        # Database sections configuration
        self.sections_dictionary = {
            "Inventory": ["ID", "Company", "Role", "Product", "Price_HT", "Price_TTC", "Quantity", "Icon"],
            "Clients": ["ID", "Name", "Email", "Phone", "Address"],
            "Orders": ["ID", "Client_ID", "Product_ID", "Quantity", "Total_Price", "Date"],
            "Products": ["ID", "Name", "Unit_Price", "Sale_Price"],
            "Suppliers": ["ID", "Name", "Email", "Phone", "Address"]
        }
        
        # Database manager
        self.database = Database(self.profile_manager, self.sections_dictionary)

        
        # UI setup
        self.setup_menu()
        self.setup_main_widget()
        self.refresh_app()
    
    def load_app_config(self):
        """Load application configuration from QSettings"""
        # Restore window geometry
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        # Load profiles path (default to ./profiles)
        profiles_path = self.settings.value("profiles_path", "./profiles")
        # Store for use by ProfileManager
        self.profiles_path = profiles_path
    
    def save_app_config(self):
        """Save application configuration to QSettings"""
        # Save window geometry
        self.settings.setValue("geometry", self.saveGeometry())
        
        # Save profiles path
        self.settings.setValue("profiles_path", getattr(self, 'profiles_path', './profiles'))
    
    def closeEvent(self, event):
        """Handle application close event"""
        self.save_app_config()
        event.accept()
    
    def setup_menu(self):
        """Create menu bar with main navigation options"""
        menubar = self.menuBar()
        
        # Profiles menu action
        profiles_action = QAction("Profiles", self)
        profiles_action.triggered.connect(self.open_profiles_dialog)
        menubar.addAction(profiles_action)
        
        # Backups menu action
        backups_action = QAction("Backups", self)
        backups_action.triggered.connect(self.open_backups_dialog)
        menubar.addAction(backups_action)
        
        # Log out menu action
        logout_action = QAction("Log Out", self)
        logout_action.triggered.connect(self.logout)
        menubar.addAction(logout_action)
    
    def setup_main_widget(self):
        """Initialize main widget container"""
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QVBoxLayout(self.main_widget)
    
    def refresh_app(self): 
        """Reset and rebuild main widget based on current state"""
        # Clear existing layout properly
        self.clear_layout(self.main_layout)
        
        # Set profiles path in profile manager
        self.profile_manager.profiles_path = getattr(self, 'profiles_path', './profiles')
        
        if not self.profile_manager.validate():
            self.setup_profile_selection()
        elif not self.password_manager.validate():
            self.setup_password_entry()
        else:
            self.setup_main_tabs()
    
    def clear_layout(self, layout):
        """Properly clear all items from a layout"""
        while layout.count():
            child = layout.takeAt(0)  # Take the item instead of just getting it
            if child.widget():
                child.widget().deleteLater()  # Schedule widget for deletion
            elif child.layout():
                self.clear_layout(child.layout())  # Recursively clear nested layouts
                child.layout().deleteLater()  # Delete the layout too
    
    def setup_profile_selection(self):
        """Show profile selection interface"""
        # Center the open profile button
        self.main_layout.addStretch()
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        open_profile_btn = GreenButton("Open Profile")
        open_profile_btn.clicked.connect(self.open_profiles_dialog)
        button_layout.addWidget(open_profile_btn)
        
        button_layout.addStretch()
        self.main_layout.addLayout(button_layout)
        self.main_layout.addStretch()
    
    def setup_password_entry(self):
        """Show password entry interface"""
        # Center the password form
        self.main_layout.addStretch()
        
        form_layout = QVBoxLayout()
        form_layout.setAlignment(Qt.AlignCenter)
        
        # Password label
        password_label = QLabel("Password:")
        password_label.setAlignment(Qt.AlignCenter)
        form_layout.addWidget(password_label)
        
        # Password input
        self.password_input = ColoredLineEdit()
        self.password_input.setEchoMode(ColoredLineEdit.Password)
        self.password_input.setMaximumWidth(300)
        self.password_input.returnPressed.connect(self.validate_password)
        self.password_input.textChanged.connect(self.reset_password_border)
        form_layout.addWidget(self.password_input, alignment=Qt.AlignCenter)
        
        # Confirm button
        confirm_btn = GreenButton("Confirm")
        confirm_btn.clicked.connect(self.validate_password)
        confirm_btn.setMaximumWidth(100)
        form_layout.addWidget(confirm_btn, alignment=Qt.AlignCenter)
        
        self.main_layout.addLayout(form_layout)
        self.main_layout.addStretch()
    
    def setup_main_tabs(self):
        """Show main application tabs"""
        # Refresh database connection for current profile
        self.database.refresh_connection()
        
        tab_widget = QTabWidget()
        
        # Add tabs
        tab_widget.addTab(HomeTab(), "Home")
        tab_widget.addTab(OperationsTab(), "Operations")
        tab_widget.addTab(ProductsTab(self.database), "Inventory")
        tab_widget.addTab(ClientsTab(self.database), "Clients")
        tab_widget.addTab(SuppliersTab(self.database), "Suppliers")
        tab_widget.addTab(LogTab(), "Log")
        
        self.main_layout.addWidget(tab_widget)
        
    def validate_password(self):
        """Validate entered password"""
        password = self.password_input.text()
        if not self.password_manager.validate(password):
            self.password_input.set_border_color("#f44336")  # Red border for incorrect password
        else:
            self.password_manager.set_password(password)
            self.refresh_app()
            
    def reset_password_border(self):
        """Reset password input border to default when text changes"""
        self.password_input.reset_border_color()
    
    def open_profiles_dialog(self):
        """Open profiles management dialog"""
        dialog = ProfilesDialog(self)
        if dialog.exec():
            # Profile may have changed, refresh the main window
            self.profiles_path = dialog.profiles_path  # Update profiles path if changed
            self.refresh_app()
    
    def open_backups_dialog(self):
        """Open backups management dialog"""
        dialog = BackupsDialog(self)
        dialog.exec()
    
    def logout(self):
        """Log out current user"""
        self.password_manager.logout()
        self.profile_manager.logout()
        self.refresh_app()