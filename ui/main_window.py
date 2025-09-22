"""
Main window - Updated with all tabs
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
from ui.tabs.products_tab import ProductsTab
from ui.tabs.clients_tab import ClientsTab
from ui.tabs.suppliers_tab import SuppliersTab
from ui.tabs.log_tab import LogTab

from classes.product_class import ProductClass
from classes.client_class import ClientClass
from classes.supplier_class import SupplierClass

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
        
        # Initialize database system
        self.database = Database(self.profile_manager)
        
        # Register parameter classes manually
        self.register_parameter_classes()

        # UI setup
        self.setup_menu()
        self.setup_main_widget()
        self.refresh_app()
    
    def register_parameter_classes(self):
        """Register parameter classes with the database"""
        print("📋 Registering parameter classes...")
        
        # Register all parameter classes
        self.database.register_class(ProductClass)
        self.database.register_class(ClientClass)
        self.database.register_class(SupplierClass)
        
        print(f"✓ Registered {len(self.database.registered_classes)} parameter classes")
    
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
                print(f"✓ Loaded saved profile: {saved_profile_name}")
            else:
                print(f"⚠️  Could not load saved profile: {saved_profile_name}")
    
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
        if self.database:
            self.database.close()
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
        # Connect to database with current profile
        if not self.database.connect():
            self.show_database_error()
            return
        
        tab_widget = QTabWidget()
        
        # Add tabs manually
        tab_widget.addTab(HomeTab(self.database), "Home")
        
        # Add Products tab
        try:
            products_tab = ProductsTab(self.database, self)
            tab_widget.addTab(products_tab, "Products")
            print("✓ Added Products tab successfully")
        except Exception as e:
            print(f"✗ Error adding Products tab: {e}")
            import traceback
            traceback.print_exc()
            
            # Add error placeholder
            error_widget = QWidget()
            error_layout = QVBoxLayout(error_widget)
            error_label = QLabel(f"Products tab error: {str(e)}")
            error_label.setStyleSheet("color: red; padding: 20px;")
            error_layout.addWidget(error_label)
            tab_widget.addTab(error_widget, "Products (Error)")
        
        # Add Clients tab
        try:
            clients_tab = ClientsTab(self.database, self)
            tab_widget.addTab(clients_tab, "Clients")
            print("✓ Added Clients tab successfully")
        except Exception as e:
            print(f"✗ Error adding Clients tab: {e}")
            import traceback
            traceback.print_exc()
            
            # Add error placeholder
            error_widget = QWidget()
            error_layout = QVBoxLayout(error_widget)
            error_label = QLabel(f"Clients tab error: {str(e)}")
            error_label.setStyleSheet("color: red; padding: 20px;")
            error_layout.addWidget(error_label)
            tab_widget.addTab(error_widget, "Clients (Error)")
        
        # Add Suppliers tab
        try:
            suppliers_tab = SuppliersTab(self.database, self)
            tab_widget.addTab(suppliers_tab, "Suppliers")
            print("✓ Added Suppliers tab successfully")
        except Exception as e:
            print(f"✗ Error adding Suppliers tab: {e}")
            import traceback
            traceback.print_exc()
            
            # Add error placeholder
            error_widget = QWidget()
            error_layout = QVBoxLayout(error_widget)
            error_label = QLabel(f"Suppliers tab error: {str(e)}")
            error_label.setStyleSheet("color: red; padding: 20px;")
            error_layout.addWidget(error_label)
            tab_widget.addTab(error_widget, "Suppliers (Error)")
        
        tab_widget.addTab(LogTab(self.database), "Log")
        
        self.main_layout.addWidget(tab_widget)
        
        # Debug info
        print(f"\n📊 Database Status:")
        print(f"   • Connected: {self.database.conn is not None}")
        print(f"   • Registered classes: {len(self.database.registered_classes)}")
        for section_name in self.database.registered_classes.keys():
            try:
                items_count = len(self.database.get_items(section_name))
                print(f"   • {section_name}: {items_count} items")
            except Exception as e:
                print(f"   • {section_name}: error getting items ({e})")
    
    def show_database_error(self):
        """Show database connection error"""
        error_widget = QWidget()
        error_layout = QVBoxLayout(error_widget)
        error_label = QLabel("Database connection failed. Please check your profile configuration.")
        error_label.setStyleSheet("color: red; font-size: 16px; text-align: center; padding: 50px;")
        error_layout.addWidget(error_label, Qt.AlignCenter)
        self.main_layout.addWidget(error_widget)
    
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
        self.database.close()
        # Clear saved profile
        self.settings.setValue("selected_profile", "")
        self.refresh_app()