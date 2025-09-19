"""
Main window class - coordinates all UI components and handles window layout
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QTabWidget, QMenuBar, QMenu)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QAction

from ui.widgets.themed_widgets import ThemedMainWindow, GreenButton, ColoredLineEdit
from ui.widgets.welcome_widget import WelcomeWidget
from ui.widgets.password_widget import PasswordWidget
from ui.dialogs.profiles_dialog import ProfilesDialog
from ui.dialogs.backups_dialog import BackupsDialog
from ui.tabs.home_tab import HomeTab
from ui.tabs.sales_tab import SalesTab
from ui.tabs.imports_tab import ImportsTab
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
        
        # Load saved profile if it exists
        self.load_saved_profile()
        
        # Database sections configuration
        self.sections_dictionary = {
            "Inventory": ["ID", "Company", "Role", "Product", "Price_HT", "Price_TTC", "Quantity", "Icon"],
            "Clients": ["ID", "name", "display_name", "client_type", "address", "email", "phone", "notes", "preview_image"],
            "Products": ["ID", "name", "unit_price", "sale_price"],
            "Suppliers": ["ID", "name", "display_name", "address", "email", "phone", "notes", "preview_image"],
            "Imports": ["ID", "supplier_id", "product_id", "quantity", "unit_price", "tva", "total_price", "date", "notes"],
            "Sales": ["ID", "client_id", "product_id", "quantity", "unit_price", "tva", "total_price", "date", "notes"]
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
        self.profiles_path = profiles_path
    
    def load_saved_profile(self):
        """Load the last selected profile from config"""
        saved_profile_name = self.settings.value("selected_profile")
        if saved_profile_name:
            # Set profiles path first
            self.profile_manager.profiles_path = self.profiles_path
            self.profile_manager.load_profiles()
            
            # Try to load the saved profile
            if self.profile_manager.load_profile(saved_profile_name):
                print(f"Loaded saved profile: {saved_profile_name}")
            else:
                print(f"Could not load saved profile: {saved_profile_name}")
    
    def save_app_config(self):
        """Save application configuration to QSettings"""
        # Save window geometry
        self.settings.setValue("geometry", self.saveGeometry())
        
        # Save profiles path
        self.settings.setValue("profiles_path", getattr(self, 'profiles_path', './profiles'))
        
        # Save selected profile
        if self.profile_manager.selected_profile:
            self.settings.setValue("selected_profile", self.profile_manager.selected_profile.name)
        else:
            self.settings.setValue("selected_profile", "")
    
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
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                self.clear_layout(child.layout())
                child.layout().deleteLater()
    
    def setup_profile_selection(self):
        """Show welcome widget with profile selection"""
        welcome_widget = WelcomeWidget()
        welcome_widget.profile_requested.connect(self.open_profiles_dialog)
        self.main_layout.addWidget(welcome_widget)
    
    def setup_password_entry(self):
        """Show password entry widget"""
        password_widget = PasswordWidget(self.profile_manager.selected_profile)
        password_widget.password_submitted.connect(self.validate_password)
        password_widget.profile_change_requested.connect(self.open_profiles_dialog)
        self.main_layout.addWidget(password_widget)
    
    def setup_main_tabs(self):
        """Show main application tabs"""
        # Refresh database connection for current profile
        self.database.refresh_connection()
        
        tab_widget = QTabWidget()
        
        # Add tabs
        tab_widget.addTab(HomeTab(), "Home")
        tab_widget.addTab(ImportsTab(self.database), "Imports")
        tab_widget.addTab(SalesTab(self.database), "Sales")
        tab_widget.addTab(ProductsTab(self.database), "Products")
        tab_widget.addTab(ClientsTab(self.database), "Clients")
        tab_widget.addTab(SuppliersTab(self.database), "Suppliers")
        tab_widget.addTab(LogTab(), "Log")
        
        self.main_layout.addWidget(tab_widget)
        
    def validate_password(self, password):
        """Validate entered password"""
        if not self.password_manager.validate(password):
            # Find the password widget and show error
            for i in range(self.main_layout.count()):
                widget = self.main_layout.itemAt(i).widget()
                if hasattr(widget, 'set_password_error'):
                    widget.set_password_error()
                    break
            return False
        else:
            self.password_manager.set_password(password)
            # Save the successful profile selection
            self.save_app_config()
            self.refresh_app()
            return True
    
    def open_profiles_dialog(self):
        """Open profiles management dialog"""
        dialog = ProfilesDialog(self)
        if dialog.exec():
            # Profile may have changed, refresh the main window
            self.profiles_path = dialog.profiles_path
            # Save the new profile selection
            self.save_app_config()
            self.refresh_app()
    
    def open_backups_dialog(self):
        """Open backups management dialog"""
        dialog = BackupsDialog(self)
        dialog.exec()
    
    def logout(self):
        """Log out current user"""
        self.password_manager.logout()
        self.profile_manager.logout()
        # Clear saved profile
        self.settings.setValue("selected_profile", "")
        self.refresh_app()