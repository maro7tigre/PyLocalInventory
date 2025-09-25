"""
Main window - Updated with unified tabs approach
All tabs now use consistent BaseTab experience
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, 
                             QTabWidget, QMenu, QMessageBox)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QAction, QActionGroup

from ui.widgets.themed_widgets import ThemedMainWindow
from ui.widgets.welcome_widget import WelcomeWidget
from ui.widgets.password_widget import PasswordWidget
from ui.dialogs.profiles_dialog import ProfilesDialog
from ui.dialogs.backups_dialog import BackupsDialog
from ui.tabs.home_tab import HomeTab
from ui.tabs.products_tab import ProductsTab
from ui.tabs.clients_tab import ClientsTab
from ui.tabs.suppliers_tab import SuppliersTab
from ui.tabs.sales_tab import SalesTab
from ui.tabs.imports_tab import ImportsTab
# from ui.tabs.log_tab import LogTab  # Hidden per request

from classes.product_class import ProductClass
from classes.client_class import ClientClass
from classes.supplier_class import SupplierClass
from classes.sales_class import SalesClass
from classes.sales_item_class import SalesItemClass
from classes.import_class import ImportClass
from classes.import_item_class import ImportItemClass

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
        # Propagate current language to database for display name resolution
        self.database.language = getattr(self, 'language', 'en')
        
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
        self.database.register_class(SalesClass)
        self.database.register_class(SalesItemClass)
        self.database.register_class(ImportClass)
        self.database.register_class(ImportItemClass)
        
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

        # Load language (default to 'en')
        self.language = self.settings.value("language", "en")
    
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

        # Save language selection
        self.settings.setValue("language", getattr(self, 'language', 'en'))
    
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

        # Language selector menu (between Backups and Log Out)
        lang_menu = QMenu("Language", self)

        # Create an exclusive action group for languages
        lang_group = QActionGroup(self)
        lang_group.setExclusive(True)

        # Supported languages and labels
        languages = {
            'en': 'English',
            'fr': 'Français',
            'es': 'Español',
        }

        # Build language actions
        self._lang_actions = {}
        current_lang = getattr(self, 'language', 'en')
        for code, label in languages.items():
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(code == current_lang)
            action.triggered.connect(lambda checked, c=code: self.change_language(c))
            lang_group.addAction(action)
            lang_menu.addAction(action)
            self._lang_actions[code] = action

        menubar.addMenu(lang_menu)
        
        # Log out menu action
        logout_action = QAction("Log Out", self)
        logout_action.triggered.connect(self.logout)
        menubar.addAction(logout_action)

    def change_language(self, code: str):
        """Set UI language preference and persist with app config on close."""
        # Update in-memory language
        self.language = code
        # Propagate to database so BaseClass.get_display_name picks it up
        if hasattr(self, 'database') and self.database:
            self.database.language = code
        
        # Reflect the selection in the menu if actions exist
        if hasattr(self, '_lang_actions') and code in self._lang_actions:
            for c, act in self._lang_actions.items():
                act.setChecked(c == code)
        
        # Rebuild main content to refresh labels/display names in the chosen language
        try:
            self.refresh_app()
        except Exception as e:
            print(f"Error refreshing UI after language change: {e}")
        
        print(f"🌐 Language set to: {code}")
    
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
        """Show main application tabs - all using unified BaseTab approach"""
        # Connect to database with current profile
        if not self.database.connect():
            self.show_database_error()
            return
        
        tab_widget = QTabWidget()
        
        # Connect tab change signal to refresh the newly selected tab
        tab_widget.currentChanged.connect(self.on_tab_changed)
        
        # Store reference to tab widget for later access
        self.tab_widget = tab_widget

        # Resolve localized tab labels
        labels = self._get_tab_labels(getattr(self, 'language', 'en'))

        # Add Home tab
        tab_widget.addTab(HomeTab(self.database, language=getattr(self, 'language', 'en')), labels['home'])
        
        # Add all entity tabs - now all using BaseTab for consistency
        try:
            products_tab = ProductsTab(self.database, self)
            tab_widget.addTab(products_tab, labels['products'])
            print("✓ Added Products tab (BaseTab)")
        except Exception as e:
            print(f"✗ Error adding Products tab: {e}")
            self.add_error_tab(tab_widget, "Products", e)
        
        try:
            clients_tab = ClientsTab(self.database, self)
            tab_widget.addTab(clients_tab, labels['clients'])
            print("✓ Added Clients tab (BaseTab)")
        except Exception as e:
            print(f"✗ Error adding Clients tab: {e}")
            self.add_error_tab(tab_widget, "Clients", e)
        
        try:
            suppliers_tab = SuppliersTab(self.database, self)
            tab_widget.addTab(suppliers_tab, labels['suppliers'])
            print("✓ Added Suppliers tab (BaseTab)")
        except Exception as e:
            print(f"✗ Error adding Suppliers tab: {e}")
            self.add_error_tab(tab_widget, "Suppliers", e)
        
        try:
            # Sales tab now uses BaseTab with BaseOperationDialog - unified experience!
            sales_tab = SalesTab(self.database, self)
            tab_widget.addTab(sales_tab, labels['sales'])
            print("✓ Added Sales tab (BaseTab + BaseOperationDialog)")
        except Exception as e:
            print(f"✗ Error adding Sales tab: {e}")
            self.add_error_tab(tab_widget, "Sales", e)
        
        try:
            # Imports tab now uses BaseTab with BaseOperationDialog - unified experience!
            imports_tab = ImportsTab(self.database, self)
            tab_widget.addTab(imports_tab, labels['imports'])
            print("✓ Added Imports tab (BaseTab + BaseOperationDialog)")
        except Exception as e:
            print(f"✗ Error adding Imports tab: {e}")
            self.add_error_tab(tab_widget, "Imports", e)
        
    # Hidden per request: Log tab
    # tab_widget.addTab(LogTab(self.database), labels['log'])

        # Style change: increase tab title font size (fixed)
        tab_widget.setStyleSheet("QTabBar::tab { font-size: 18px; }")

        self.main_layout.addWidget(tab_widget)
        
        # Debug info
        print(f"\n📊 Database Status:")
        print(f"   • Connected: {self.database.conn is not None}")
        print(f"   • Registered classes: {len(self.database.registered_classes)}")
        print(f"   • Unified Experience: ✓ All tabs now use BaseTab")
        print(f"   • Operations: Sales & Imports use BaseOperationDialog")
        for section_name in self.database.registered_classes.keys():
            try:
                items_count = len(self.database.get_items(section_name))
                print(f"   • {section_name}: {items_count} items")
            except Exception as e:
                print(f"   • {section_name}: error getting items ({e})")

    def _get_tab_labels(self, lang: str):
        """Return localized tab labels including emojis."""
        # Normalize
        l = (lang or 'en').lower()
        if l not in ('en', 'fr', 'es'):
            l = 'en'

        if l == 'fr':
            return {
                'home': "🏠 Accueil",
                'products': "📦 Produits",
                'clients': "👥 Clients",
                'suppliers': "🏭 Fournisseurs",
                'sales': "💰 Ventes",
                'imports': "📥 Importations",
                'log': "📋 Journal",
            }
        if l == 'es':
            return {
                'home': "🏠 Inicio",
                'products': "📦 Productos",
                'clients': "👥 Clientes",
                'suppliers': "🏭 Proveedores",
                'sales': "💰 Ventas",
                'imports': "📥 Importaciones",
                'log': "📋 Registro",
            }
        # default English
        return {
            'home': "🏠 Home",
            'products': "📦 Products",
            'clients': "👥 Clients",
            'suppliers': "🏭 Suppliers",
            'sales': "💰 Sales",
            'imports': "📥 Imports",
            'log': "📋 Log",
        }
    
    def add_error_tab(self, tab_widget, tab_name, error):
        """Add error placeholder tab"""
        error_widget = QWidget()
        error_layout = QVBoxLayout(error_widget)
        error_label = QLabel(f"{tab_name} tab error: {str(error)}")
        error_label.setStyleSheet("color: red; padding: 20px;")
        error_layout.addWidget(error_label)
        tab_widget.addTab(error_widget, f"{tab_name} (Error)")
    
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
        # Check if profile is selected before opening backups
        if not self.profile_manager or not self.profile_manager.selected_profile:
            QMessageBox.warning(self, "No Profile Selected", 
                              "Please select a profile before accessing backups.")
            return
            
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
        
    def refresh_all_tabs(self):
        """Refresh all tabs after database changes (e.g., backup restore)"""
        try:
            if hasattr(self, 'tab_widget') and self.tab_widget:
                # Refresh all tabs that have refresh methods
                for i in range(self.tab_widget.count()):
                    tab_widget = self.tab_widget.widget(i)
                    if hasattr(tab_widget, 'refresh_on_tab_switch'):
                        try:
                            tab_widget.refresh_on_tab_switch()
                            print(f"✓ Refreshed tab {i}: {self.tab_widget.tabText(i)}")
                        except Exception as e:
                            print(f"✗ Error refreshing tab {i}: {e}")
                
                print("✓ All tabs refreshed after backup restore")
        except Exception as e:
            print(f"Error during tab refresh: {e}")
    
    def on_tab_changed(self, index):
        """Handle tab change to refresh data in the newly selected tab"""
        try:
            if hasattr(self, 'tab_widget') and self.tab_widget:
                current_widget = self.tab_widget.widget(index)
                
                # Check if the current widget has a refresh_on_tab_switch method (BaseTab instances)
                if hasattr(current_widget, 'refresh_on_tab_switch'):
                    current_widget.refresh_on_tab_switch()
                
        except Exception as e:
            print(f"Error refreshing tab on switch: {e}")