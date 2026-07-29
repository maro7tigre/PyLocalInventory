"""
Main window - Updated with unified tabs approach
All tabs now use consistent BaseTab experience
"""
import os

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, 
                             QTabWidget, QMenu, QMessageBox)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QAction, QActionGroup

from ui.widgets.themed_widgets import ThemedMainWindow
from ui.widgets.welcome_widget import WelcomeWidget
from ui.widgets.password_widget import PasswordWidget
from ui.widgets.login_widget import LoginWidget, NetworkUnlockWidget
from ui.dialogs.profiles_dialog import ProfilesDialog
from ui.dialogs.backups_dialog import BackupsDialog
from ui.dialogs.network_dialog import NetworkDialog
from ui.tabs.home_tab import HomeTab
from ui.tabs.products_tab import ProductsTab
from ui.tabs.services_tab import ServicesTab
from ui.tabs.clients_tab import ClientsTab
from ui.tabs.suppliers_tab import SuppliersTab
from ui.tabs.sales_tab import SalesTab
from ui.tabs.imports_tab import ImportsTab
from ui.tabs.reports_tab import ReportsTab
# from ui.tabs.log_tab import LogTab  # Hidden per request

from classes.product_class import ProductClass
from classes.service_class import ServiceClass
from classes.door_type_class import DoorTypeClass
from classes.wood_type_class import WoodTypeClass
from classes.client_class import ClientClass
from classes.supplier_class import SupplierClass
from classes.sales_class import SalesClass
from classes.sales_item_class import SalesItemClass
from classes.import_class import ImportClass
from classes.import_item_class import ImportItemClass
from classes.reports_class import ReportsClass

from core.profiles import ProfileManager
from core.runtime_paths import portable_dir
from core.password import PasswordManager
from core.database import Database
from core.network.client import RemoteDatabase
from core.network.protocol import AuthError, ConnectionFailedError, RemoteError, DEFAULT_PORT
from core.user_settings import (
    load_settings,
    remember_profile_enabled,
    get_remembered_profile_id,
    set_remembered_profile,
    clear_remembered_profile,
    get_remembered_network,
    set_remembered_network,
    clear_remembered_network,
    set_startup_enabled,
)


class MainWindow(ThemedMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyLocalInventory")
        self.setMinimumSize(1000, 700)
        
        # Load application settings
        self.settings = QSettings("PyLocalInventory", "MainApp")
        self.load_app_config()
        self.user_settings = load_settings()
        self.ensure_startup_registration()
        
        # Core managers
        self.profile_manager = ProfileManager()
        self.password_manager = PasswordManager(self.profile_manager)

        # Network state: 'standalone' (default, unaffected) or 'client' (connected
        # to a remote host instead of a local profile database). network_server is
        # only set when this instance is also hosting (super-admin toggled it on).
        self.remembered_network = get_remembered_network(self.user_settings)
        self.connection_mode = 'client' if self.remembered_network else 'standalone'
        self._client_connected = False
        self._network_unlock_mode = bool(self.remembered_network)
        self.network_server = None
        self.network_port = DEFAULT_PORT
        self.last_network_host = ''

        # Always show the welcome/entry screen on launch, even if a profile was
        # remembered from last time - only auto-skip to it on later refreshes
        # (e.g. after picking a profile, changing language, logging out).
        self._initial_screen_shown = False

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
        self.database.register_class(ServiceClass)
        self.database.register_class(DoorTypeClass)
        self.database.register_class(WoodTypeClass)
        self.database.register_class(ClientClass)
        self.database.register_class(SupplierClass)
        self.database.register_class(SalesClass)
        self.database.register_class(SalesItemClass)
        self.database.register_class(ImportClass)
        self.database.register_class(ImportItemClass)
        self.database.register_class(ReportsClass)

        print(f"✓ Registered {len(self.database.registered_classes)} parameter classes")
    
    def load_app_config(self):
        """Load application configuration from QSettings"""
        # Restore window geometry
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        # Use an absolute default because Startup shortcuts have an unrelated
        # working directory (commonly C:\\Windows\\System32).
        profiles_path = self.settings.value("profiles_path", portable_dir("profiles"))
        if not os.path.isabs(profiles_path):
            # Migrate the legacy "./profiles" preference to per-user storage.
            profiles_path = portable_dir("profiles")
        self.profiles_path = profiles_path

        # Load language (default to 'en')
        self.language = self.settings.value("language", "en")

        # Load warning toggles (default True = warnings enabled)
        def _bool(val, default=True):
            if val is None:
                return default
            if isinstance(val, bool):
                return val
            return str(val).lower() not in ('false', '0', 'no')

        self.warn_missing_client   = _bool(self.settings.value("warn_missing_client"))
        self.warn_missing_supplier = _bool(self.settings.value("warn_missing_supplier"))
        self.warn_missing_product  = _bool(self.settings.value("warn_missing_product"))
        self.warn_insufficient_stock = _bool(self.settings.value("warn_insufficient_stock"))

        # Load tab visibility (default True = tab visible)
        self.tab_visibility = {
            'home':      _bool(self.settings.value("tab_visible/home")),
            'products':  _bool(self.settings.value("tab_visible/products")),
            'services':  _bool(self.settings.value("tab_visible/services")),
            'clients':   _bool(self.settings.value("tab_visible/clients")),
            'suppliers': _bool(self.settings.value("tab_visible/suppliers")),
            'sales':     _bool(self.settings.value("tab_visible/sales")),
            'imports':   _bool(self.settings.value("tab_visible/imports")),
            'reports':   _bool(self.settings.value("tab_visible/reports")),
        }
    
    def ensure_startup_registration(self):
        """Ensure startup registration state is consistent with saved settings."""
        if self.user_settings.get("start_with_windows"):
            try:
                set_startup_enabled(True)
            except Exception as exc:
                print(f"Warning: could not enable startup registration: {exc}")

    def load_saved_profile(self):
        """Load the last selected profile from config or the remembered profile settings."""
        self.profile_manager.profiles_path = self.profiles_path
        self.profile_manager.load_profiles()

        # Prefer the remembered profile stored in per-user settings
        remembered_profile_name = get_remembered_profile_id(self.user_settings)
        if remembered_profile_name:
            if self.profile_manager.load_profile(remembered_profile_name):
                print(f"✓ Loaded remembered profile: {remembered_profile_name}")
                return
            print(f"⚠️  Could not load remembered profile: {remembered_profile_name}")
            clear_remembered_profile(self.user_settings)

        # Fall back to the last selected profile stored in QSettings
        saved_profile_name = self.settings.value("selected_profile")
        if saved_profile_name:
            if self.profile_manager.load_profile(saved_profile_name):
                print(f"✓ Loaded saved profile: {saved_profile_name}")
            else:
                print(f"⚠️  Could not load saved profile: {saved_profile_name}")
    
    def save_app_config(self):
        """Save application configuration to QSettings"""
        # Save window geometry
        self.settings.setValue("geometry", self.saveGeometry())
        
        # Save profiles path
        self.settings.setValue("profiles_path", getattr(self, 'profiles_path', portable_dir("profiles")))
        
        # Save selected profile
        if self.profile_manager.selected_profile:
            self.settings.setValue("selected_profile", self.profile_manager.selected_profile.name)
        else:
            self.settings.setValue("selected_profile", "")

        # Save language selection
        self.settings.setValue("language", getattr(self, 'language', 'en'))

        # Save warning toggles
        self.settings.setValue("warn_missing_client",   self.warn_missing_client)
        self.settings.setValue("warn_missing_supplier", self.warn_missing_supplier)
        self.settings.setValue("warn_missing_product",  self.warn_missing_product)
        self.settings.setValue("warn_insufficient_stock", self.warn_insufficient_stock)

        # Save tab visibility
        for key, visible in self.tab_visibility.items():
            self.settings.setValue(f"tab_visible/{key}", visible)
    
    def closeEvent(self, event):
        """Handle application close event"""
        self.save_app_config()
        if self.network_server and self.network_server.is_running:
            self.network_server.stop()
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

        # Network dropdown: database settings are always reachable, while the
        # hosting / users / roles tools stay gated by an unlocked profile.
        network_menu = QMenu("Network", self)

        database_config_action = QAction("Database Config", self)
        database_config_action.triggered.connect(self.open_database_config)
        network_menu.addAction(database_config_action)

        network_config_action = QAction("Network Config", self)
        network_config_action.triggered.connect(self.open_network_dialog)
        network_menu.addAction(network_config_action)

        menubar.addMenu(network_menu)

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

        # ── View menu ──────────────────────────────────────────────────────────
        view_menu = QMenu("View", self)

        # Tab visibility sub-menu
        tabs_menu = QMenu("Tabs", self)
        tab_labels_en = {
            'home':      "🏠 Home",
            'products':  "📦 Products",
            'services':  "🛠️ Services",
            'clients':   "👥 Clients",
            'suppliers': "🏭 Suppliers",
            'sales':     "💰 Sales",
            'imports':   "📥 Imports",
            'reports':   "📝 Reports",
        }
        self._tab_visibility_actions = {}
        for key, label in tab_labels_en.items():
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(self.tab_visibility.get(key, True))
            action.triggered.connect(lambda checked, k=key: self._toggle_tab_visible(k, checked))
            tabs_menu.addAction(action)
            self._tab_visibility_actions[key] = action
        view_menu.addMenu(tabs_menu)

        view_menu.addSeparator()

        # Warnings sub-menu
        warnings_menu = QMenu("Warnings", self)

        self._warn_client_action = QAction("Unregistered Client", self)
        self._warn_client_action.setCheckable(True)
        self._warn_client_action.setChecked(self.warn_missing_client)
        self._warn_client_action.triggered.connect(
            lambda checked: self._toggle_warning('missing_client', checked))
        warnings_menu.addAction(self._warn_client_action)

        self._warn_supplier_action = QAction("Unregistered Supplier", self)
        self._warn_supplier_action.setCheckable(True)
        self._warn_supplier_action.setChecked(self.warn_missing_supplier)
        self._warn_supplier_action.triggered.connect(
            lambda checked: self._toggle_warning('missing_supplier', checked))
        warnings_menu.addAction(self._warn_supplier_action)

        self._warn_product_action = QAction("Unregistered Product", self)
        self._warn_product_action.setCheckable(True)
        self._warn_product_action.setChecked(self.warn_missing_product)
        self._warn_product_action.triggered.connect(
            lambda checked: self._toggle_warning('missing_product', checked))
        warnings_menu.addAction(self._warn_product_action)

        warnings_menu.addSeparator()

        self._warn_stock_action = QAction("Insufficient Stock", self)
        self._warn_stock_action.setCheckable(True)
        self._warn_stock_action.setChecked(self.warn_insufficient_stock)
        self._warn_stock_action.triggered.connect(
            lambda checked: self._toggle_warning('insufficient_stock', checked))
        warnings_menu.addAction(self._warn_stock_action)

        view_menu.addMenu(warnings_menu)
        menubar.addMenu(view_menu)
        # ───────────────────────────────────────────────────────────────────────

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

        if self.connection_mode == 'client':
            if not self._client_connected:
                if self._network_unlock_mode and self.remembered_network:
                    self.setup_network_unlock()
                else:
                    self.setup_login_entry()
            else:
                self.setup_main_tabs()
            return

        # Set profiles path in profile manager
        self.profile_manager.profiles_path = getattr(self, 'profiles_path', portable_dir("profiles"))

        # Show the remembered profile's password entry directly if the user has
        # chosen to remember a profile and it is valid.
        if not self._initial_screen_shown:
            self._initial_screen_shown = True
            if remember_profile_enabled(self.user_settings) and self.profile_manager.validate():
                self.setup_password_entry()
            else:
                self.setup_profile_selection()
        elif not self.profile_manager.validate():
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
        welcome_widget.network_login_requested.connect(self.start_network_login)
        self.main_layout.addWidget(welcome_widget)

    def setup_password_entry(self):
        """Show password entry widget"""
        self.user_settings = load_settings()
        remember_checked = remember_profile_enabled(self.user_settings)
        startup_checked = bool(self.user_settings.get("start_with_windows"))
        password_widget = PasswordWidget(
            self.profile_manager.selected_profile,
            remember_profile=remember_checked,
            startup_enabled=startup_checked,
        )
        password_widget.password_submitted.connect(self.validate_password)
        password_widget.profile_change_requested.connect(self.open_profiles_dialog)
        self.main_layout.addWidget(password_widget)

    def setup_login_entry(self):
        """Show the network login widget (client mode)"""
        saved = self.remembered_network or {}
        login_widget = LoginWidget(
            default_host=saved.get("host", self.last_network_host),
            default_port=str(saved.get("port", self.network_port or '')),
            default_username=saved.get("username", ""),
            remember_connection=bool(saved),
            startup_enabled=bool(self.user_settings.get("start_with_windows")),
        )
        login_widget.login_submitted.connect(self.attempt_network_login)
        login_widget.back_requested.connect(self.cancel_network_login)
        self.main_layout.addWidget(login_widget)

    def setup_network_unlock(self):
        widget = NetworkUnlockWidget(
            self.remembered_network,
            startup_enabled=bool(self.user_settings.get("start_with_windows")),
        )
        widget.login_submitted.connect(self.attempt_network_login)
        widget.change_requested.connect(self.change_network_connection)
        self.main_layout.addWidget(widget)

    def change_network_connection(self):
        self._network_unlock_mode = False
        self.refresh_app()

    def start_network_login(self):
        """Switch from local-profile flow to connecting to a network host"""
        self.connection_mode = 'client'
        self._client_connected = False
        self._network_unlock_mode = False
        self.refresh_app()

    def cancel_network_login(self):
        """Switch back from the network login screen to local profiles"""
        self.connection_mode = 'standalone'
        self._client_connected = False
        self._network_unlock_mode = False
        self.refresh_app()

    def attempt_network_login(self, host, port, username, password,
                              remember_connection=False, startup_enabled=False):
        """Try to log into a remote host; on success swap self.database for a
        RemoteDatabase and proceed exactly like a normal profile unlock."""
        try:
            port_num = int(port) if port else DEFAULT_PORT
        except ValueError:
            self._show_login_error("Invalid port. Enter a number from 1 to 65535.")
            return
        if not 1 <= port_num <= 65535:
            self._show_login_error("Invalid port. Enter a number from 1 to 65535.")
            return

        remote_db = RemoteDatabase(self.profile_manager, host, port_num, username, password)
        try:
            remote_db.connect()
        except (AuthError, ConnectionFailedError, RemoteError) as e:
            self._show_login_error(str(e))
            return

        if remember_connection:
            self.user_settings = set_remembered_network(
                self.user_settings, host, port_num, username
            )
            self.remembered_network = get_remembered_network(self.user_settings)
        else:
            self.user_settings = clear_remembered_network(self.user_settings)
            self.remembered_network = {}
        try:
            set_startup_enabled(bool(startup_enabled))
            self.user_settings = load_settings()
        except Exception as exc:
            QMessageBox.warning(self, "Startup Registration", f"Could not update startup registration: {exc}")

        self.database = remote_db
        self.database.language = getattr(self, 'language', 'en')
        self.register_parameter_classes()

        self.last_network_host = host
        self.network_port = port_num
        self._client_connected = True
        self.refresh_app()

    def _show_login_error(self, message):
        for i in range(self.main_layout.count()):
            widget = self.main_layout.itemAt(i).widget()
            if hasattr(widget, 'set_error'):
                widget.set_error(message)
                if hasattr(widget, 'clear_password'):
                    widget.clear_password()
                break
    
    def setup_main_tabs(self):
        """Show main application tabs - all using unified BaseTab approach"""
        # Connect to database with current profile (already connected if we just
        # logged into a network host - skip re-doing the handshake here)
        if not self._client_connected:
            try:
                connected = self.database.connect()
            except (AuthError, ConnectionFailedError, RemoteError) as e:
                self.show_database_error(str(e))
                return
            if not connected:
                self.show_database_error(getattr(self.database, 'last_error', None))
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

        # Add all entity tabs - now all using BaseTab for consistency. A tab is
        # only added at all if the logged-in user (or the local host, which is
        # always fully permitted) has read access to its section - a user with
        # no read permission never sees the tab exist, rather than seeing it
        # and hitting a permission-denied error when it tries to load.
        entity_tabs = [
            ('products',  'Products',  lambda: ProductsTab(self.database, self)),
            ('services',  'Services',  lambda: ServicesTab(self.database, self)),
            ('clients',   'Clients',   lambda: ClientsTab(self.database, self)),
            ('suppliers', 'Suppliers', lambda: SuppliersTab(self.database, self)),
            ('sales',     'Sales',     lambda: SalesTab(self.database, self)),
            ('imports',   'Imports',   lambda: ImportsTab(self.database, self)),
            ('reports',   'Reports',   lambda: ReportsTab(self.database, self)),
        ]

        self._tab_key_to_index = {'home': 0}
        readable_keys = {'home'}

        for key, section, factory in entity_tabs:
            if section != "Reports" and not self.database.has_permission(section, 'read'):
                print(f"– Skipped {section} tab: no read permission")
                continue
            try:
                tab = factory()
                self._tab_key_to_index[key] = tab_widget.addTab(tab, labels[key])
                readable_keys.add(key)
                print(f"✓ Added {section} tab (BaseTab)")
            except Exception as e:
                print(f"✗ Error adding {section} tab: {e}")
                self._tab_key_to_index[key] = self.add_error_tab(tab_widget, section, e)
                readable_keys.add(key)

    # Hidden per request: Log tab
    # tab_widget.addTab(LogTab(self.database), labels['log'])

        # Style change: increase tab title font size (fixed)
        tab_widget.setStyleSheet("QTabBar::tab { font-size: 18px; }")

        # Apply stored tab visibility
        self._apply_tab_visibility()

        # Sections the user has no read permission for never got a tab/index at
        # all, so the "Tabs" view-menu toggle for them is meaningless - hide it
        # rather than let it look like a working option.
        for key, action in getattr(self, '_tab_visibility_actions', {}).items():
            action.setVisible(key in readable_keys)

        # Sync home tab quick-action cards with current tab visibility
        home_tab = tab_widget.widget(0)
        if hasattr(home_tab, 'update_quick_actions_visibility'):
            home_tab.update_quick_actions_visibility(self.tab_visibility)

        self.main_layout.addWidget(tab_widget)
        
        # Debug info
        print(f"\n📊 Database Status:")
        print(f"   • Connected: {self.database.conn is not None}")
        print(f"   • Registered classes: {len(self.database.registered_classes)}")
        print(f"   • Unified Experience: ✓ All tabs now use BaseTab")
        print(f"   • Operations: Sales & Imports use BaseOperationDialog")
        print("   • Startup row-count scan: skipped (tabs load their own data)")

    # ──────────────────────────── View menu helpers ────────────────────────────

    def _apply_tab_visibility(self):
        """Apply self.tab_visibility to the current tab_widget."""
        if not hasattr(self, 'tab_widget') or not self.tab_widget:
            return
        mapping = getattr(self, '_tab_key_to_index', {})
        for key, index in mapping.items():
            visible = True if key == "reports" else self.tab_visibility.get(key, True)
            self.tab_widget.setTabVisible(index, visible)

    def _toggle_tab_visible(self, key: str, checked: bool):
        """Called when a tab-visibility action is toggled."""
        self.tab_visibility[key] = checked
        self._apply_tab_visibility()
        # Keep action in sync (Qt usually does this, but be explicit)
        if hasattr(self, '_tab_visibility_actions') and key in self._tab_visibility_actions:
            self._tab_visibility_actions[key].setChecked(checked)
        # Sync home tab quick-action cards
        if hasattr(self, 'tab_widget') and self.tab_widget:
            home_tab = self.tab_widget.widget(0)
            if hasattr(home_tab, 'update_quick_actions_visibility'):
                home_tab.update_quick_actions_visibility(self.tab_visibility)

    def _toggle_warning(self, warning_key: str, checked: bool):
        """Called when a warning toggle action changes state."""
        if warning_key == 'missing_client':
            self.warn_missing_client = checked
        elif warning_key == 'missing_supplier':
            self.warn_missing_supplier = checked
        elif warning_key == 'missing_product':
            self.warn_missing_product = checked
        elif warning_key == 'insufficient_stock':
            self.warn_insufficient_stock = checked

    # ───────────────────────────────────────────────────────────────────────────

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
                'services': "🛠️ Services",
                'clients': "👥 Clients",
                'suppliers': "🏭 Fournisseurs",
                'sales': "💰 Ventes",
                'imports': "📥 Importations",
                'reports': "📝 Rapports",
                'log': "📋 Journal",
            }
        if l == 'es':
            return {
                'home': "🏠 Inicio",
                'products': "📦 Productos",
                'services': "🛠️ Servicios",
                'clients': "👥 Clientes",
                'suppliers': "🏭 Proveedores",
                'sales': "💰 Ventas",
                'imports': "📥 Importaciones",
                'reports': "📝 Informes",
                'log': "📋 Registro",
            }
        # default English
        return {
            'home': "🏠 Home",
            'products': "📦 Products",
            'services': "🛠️ Services",
            'clients': "👥 Clients",
            'suppliers': "🏭 Suppliers",
            'sales': "💰 Sales",
            'imports': "📥 Imports",
            'reports': "📝 Reports",
            'log': "📋 Log",
        }
    
    def add_error_tab(self, tab_widget, tab_name, error):
        """Add error placeholder tab. Returns the new tab's index."""
        error_widget = QWidget()
        error_layout = QVBoxLayout(error_widget)
        error_label = QLabel(f"{tab_name} tab error: {str(error)}")
        error_label.setStyleSheet("color: red; padding: 20px;")
        error_layout.addWidget(error_label)
        return tab_widget.addTab(error_widget, f"{tab_name} (Error)")
    
    def show_database_error(self, message=None):
        """Show database connection error"""
        error_widget = QWidget()
        error_layout = QVBoxLayout(error_widget)
        text = message or "Database connection failed. Please check your profile configuration."
        error_label = QLabel(text)
        error_label.setWordWrap(True)
        error_label.setStyleSheet("color: red; font-size: 16px; text-align: center; padding: 50px;")
        error_layout.addWidget(error_label, Qt.AlignCenter)
        self.main_layout.addWidget(error_widget)
    
    def validate_password(self, password, remember_profile=False, startup_enabled=False):
        """Validate entered password"""
        if not self.password_manager.validate(password):
            # Find the password widget and show error
            for i in range(self.main_layout.count()):
                widget = self.main_layout.itemAt(i).widget()
                if hasattr(widget, 'set_password_error'):
                    widget.set_password_error()
                    break
            return False

        self.password_manager.set_password(password)

        # Persist profile preferences and Windows startup registration.
        if remember_profile:
            self.user_settings = set_remembered_profile(self.user_settings, self.profile_manager.selected_profile.name)
        else:
            self.user_settings = clear_remembered_profile(self.user_settings)

        try:
            if startup_enabled:
                set_startup_enabled(True)
            else:
                set_startup_enabled(False)
        except Exception as exc:
            QMessageBox.warning(self, "Startup Registration", f"Could not update startup registration: {exc}")

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
            if self.user_settings.get("remember_profile") and self.profile_manager.selected_profile:
                self.user_settings = set_remembered_profile(
                    self.user_settings,
                    self.profile_manager.selected_profile.name,
                )
            # Save the new profile selection
            self.save_app_config()
            self.refresh_app()
    
    def open_backups_dialog(self):
        """Open backups management dialog"""
        # Network clients intentionally have no local business profile. Their
        # backup dialog downloads a host-generated archive to this PC.
        if (
            self.connection_mode != "client"
            and (not self.profile_manager or not self.profile_manager.selected_profile)
        ):
            QMessageBox.warning(self, "No Profile Selected", 
                              "Please select a profile before accessing backups.")
            return
            
        dialog = BackupsDialog(self)
        dialog.exec()

    def open_database_config(self):
        """Open the shared PostgreSQL connection settings dialog."""
        if self.connection_mode == 'client':
            QMessageBox.information(
                self, "Not Available",
                "Database configuration isn't available while connected as a network client."
            )
            return

        dialog = NetworkDialog(self, focus_tab=0)
        dialog.exec()

    def open_network_dialog(self):
        """Open the network hosting / users & roles management dialog."""
        if self.connection_mode == 'client':
            QMessageBox.information(
                self, "Not Available",
                "Network hosting isn't available while connected as a network client."
            )
            return

        dialog = NetworkDialog(self, focus_tab=1)
        dialog.exec()

    def logout(self):
        """Log out current user"""
        self.database.close()

        if self.connection_mode == 'client':
            # Drop the RemoteDatabase and go back to local-profile mode
            self.connection_mode = 'standalone'
            self._client_connected = False
            self.database = Database(self.profile_manager)
            self.database.language = getattr(self, 'language', 'en')
            self.register_parameter_classes()
        else:
            self.password_manager.logout()
            self.profile_manager.logout()
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
