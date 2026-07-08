"""
Network Dialog - Lets the super-admin host the current profile's database on
the LAN and manage the user accounts / per-section role permission matrix
that control what connecting clients can read, insert or delete.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QLineEdit, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QCheckBox, QMessageBox, QInputDialog
)
from PySide6.QtCore import Qt

from core.network.server import DatabaseServer
from core.network.protocol import DEFAULT_PORT
from core.user_manager import UserManager, MATRIX_SECTIONS
from core import pg_config


class NetworkDialog(QDialog):
    """Database settings are always editable; hosting, users and roles are only
    available after a profile has been unlocked and the local database is
    connected."""

    def __init__(self, main_window, focus_tab=0):
        super().__init__(main_window)
        self.main_window = main_window
        self.database = main_window.database
        self.can_manage_network = bool(
            getattr(main_window.profile_manager, 'selected_profile', None)
            and getattr(self.database, 'conn', None)
        )
        self.user_manager = UserManager(self.database) if self.can_manage_network else None
        self.setWindowTitle("Network & Users")
        self.setMinimumSize(640, 520)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_db_server_tab(), "Database Server")
        self.tabs.addTab(self._build_hosting_tab(), "Hosting")
        self.tabs.addTab(self._build_users_tab(), "Users")
        self.tabs.addTab(self._build_roles_tab(), "Roles && Permissions")
        layout.addWidget(self.tabs)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._refresh_db_server_fields()
        self._apply_access_state()

        if self.can_manage_network:
            self._refresh_hosting_status()
            self._refresh_users_table()
            self._refresh_roles_combo()

        self.tabs.setCurrentIndex(min(focus_tab, self.tabs.count() - 1))

    def _apply_access_state(self):
        """Disable the management tabs until a profile has been unlocked."""
        for index in range(1, self.tabs.count()):
            self.tabs.setTabEnabled(index, self.can_manage_network)

        if not self.can_manage_network:
            self.tabs.setTabToolTip(
                1,
                "Unlock a profile before starting or stopping hosting."
            )
            self.tabs.setTabToolTip(
                2,
                "Unlock a profile before managing users."
            )
            self.tabs.setTabToolTip(
                3,
                "Unlock a profile before editing roles and permissions."
            )

    # ---------------- Database Server tab ----------------

    def _build_db_server_tab(self):
        widget = QWidget()
        form = QVBoxLayout(widget)

        note = QLabel(
            "Connection settings for the central PostgreSQL server that stores every "
            "profile's data. These are shared across all profiles on this machine."
        )
        note.setWordWrap(True)
        form.addWidget(note)

        host_row = QHBoxLayout()
        host_row.addWidget(QLabel("Host:"))
        self.db_host_input = QLineEdit()
        host_row.addWidget(self.db_host_input)
        form.addLayout(host_row)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port:"))
        self.db_port_input = QLineEdit()
        port_row.addWidget(self.db_port_input)
        form.addLayout(port_row)

        dbname_row = QHBoxLayout()
        dbname_row.addWidget(QLabel("Maintenance Database:"))
        self.db_name_input = QLineEdit()
        dbname_row.addWidget(self.db_name_input)
        form.addLayout(dbname_row)

        user_row = QHBoxLayout()
        user_row.addWidget(QLabel("User:"))
        self.db_user_input = QLineEdit()
        user_row.addWidget(self.db_user_input)
        form.addLayout(user_row)

        password_row = QHBoxLayout()
        password_row.addWidget(QLabel("Password:"))
        self.db_password_input = QLineEdit()
        self.db_password_input.setEchoMode(QLineEdit.Password)
        password_row.addWidget(self.db_password_input)
        form.addLayout(password_row)

        self.db_status_label = QLabel()
        form.addWidget(self.db_status_label)

        btn_row = QHBoxLayout()
        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self._test_db_server_connection)
        btn_row.addWidget(test_btn)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save_db_server_config)
        btn_row.addWidget(save_btn)
        form.addLayout(btn_row)

        form.addStretch()
        return widget

    def _refresh_db_server_fields(self):
        config = pg_config.load_server_config()
        self.db_host_input.setText(str(config.get("host", "")))
        self.db_port_input.setText(str(config.get("port", "")))
        self.db_name_input.setText(str(config.get("maintenance_database", config.get("database", "postgres"))))
        self.db_user_input.setText(str(config.get("user", "")))
        self.db_password_input.setText(str(config.get("password", "")))

    def _collect_db_server_config(self):
        try:
            port = int(self.db_port_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Invalid Port", "Port must be a number.")
            return None
        return {
            "host": self.db_host_input.text().strip(),
            "port": port,
            "maintenance_database": self.db_name_input.text().strip(),
            "user": self.db_user_input.text().strip(),
            "password": self.db_password_input.text(),
        }

    def _test_db_server_connection(self):
        config = self._collect_db_server_config()
        if config is None:
            return
        ok, message = pg_config.test_connection(config)
        self.db_status_label.setText(f"{'✓' if ok else '✗'} {message}")

    def _save_db_server_config(self):
        config = self._collect_db_server_config()
        if config is None:
            return
        current = pg_config.load_server_config()
        current.update(config)
        pg_config.save_server_config(current)
        QMessageBox.information(self, "Saved", "Database server settings saved.")

    # ---------------- Hosting tab ----------------

    def _build_hosting_tab(self):
        widget = QWidget()
        form = QVBoxLayout(widget)

        if not self.can_manage_network:
            note = QLabel(
                "Unlock a profile first to start hosting this database on the LAN."
            )
            note.setWordWrap(True)
            form.addWidget(note)
            form.addStretch()
            return widget

        self.status_label = QLabel()
        form.addWidget(self.status_label)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port:"))
        self.port_input = QLineEdit(str(getattr(self.main_window, 'network_port', None) or DEFAULT_PORT))
        port_row.addWidget(self.port_input)
        form.addLayout(port_row)

        self.ip_label = QLabel()
        form.addWidget(self.ip_label)

        self.toggle_btn = QPushButton()
        self.toggle_btn.clicked.connect(self._toggle_hosting)
        form.addWidget(self.toggle_btn)

        note = QLabel(
            "Other PyLocalInventory users on this network can connect using the IP "
            "above, this port, and a username/password created in the Users tab.\n"
            "Windows Firewall may prompt to allow this the first time you start hosting."
        )
        note.setWordWrap(True)
        form.addWidget(note)
        form.addStretch()
        return widget

    def _refresh_hosting_status(self):
        server = getattr(self.main_window, 'network_server', None)
        running = bool(server and server.is_running)
        self.status_label.setText("Status: Hosting" if running else "Status: Not hosting")
        self.toggle_btn.setText("Stop Hosting" if running else "Start Hosting")
        self.ip_label.setText(f"Your LAN IP: {DatabaseServer.local_ip()}" if running else "")
        self.port_input.setEnabled(not running)

    def _toggle_hosting(self):
        server = getattr(self.main_window, 'network_server', None)
        if server and server.is_running:
            server.stop()
            self._refresh_hosting_status()
            return

        if not self.user_manager.has_any_superadmin():
            username, ok = QInputDialog.getText(self, "Create Super Admin", "Choose a super-admin username:")
            if not ok or not username.strip():
                return
            password, ok = QInputDialog.getText(
                self, "Create Super Admin", "Choose a super-admin password:", QLineEdit.Password
            )
            if not ok or not password:
                return
            try:
                self.user_manager.create_user(username.strip(), password, role_id=None, is_superadmin=True)
            except ValueError as e:
                QMessageBox.warning(self, "Could not create account", str(e))
                return
            self._refresh_users_table()

        try:
            port = int(self.port_input.text().strip() or DEFAULT_PORT)
        except ValueError:
            QMessageBox.warning(self, "Invalid Port", "Port must be a number.")
            return

        server = DatabaseServer(self.database, port=port)
        try:
            server.start()
        except OSError as e:
            QMessageBox.critical(self, "Could not start hosting", str(e))
            return
        self.main_window.network_server = server
        self.main_window.network_port = port
        self._refresh_hosting_status()

    # ---------------- Users tab ----------------

    def _build_users_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        if not self.can_manage_network:
            note = QLabel(
                "Users can only be created after a profile is unlocked and the local database is connected."
            )
            note.setWordWrap(True)
            layout.addWidget(note)
            layout.addStretch()
            return widget

        self.users_table = QTableWidget(0, 3)
        self.users_table.setHorizontalHeaderLabels(["Username", "Role", "Super Admin"])
        self.users_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.users_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.users_table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add User")
        add_btn.clicked.connect(self._add_user)
        change_role_btn = QPushButton("Change Role")
        change_role_btn.clicked.connect(self._change_user_role)
        change_password_btn = QPushButton("Change Password")
        change_password_btn.clicked.connect(self._change_user_password)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_user)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(change_role_btn)
        btn_row.addWidget(change_password_btn)
        btn_row.addWidget(remove_btn)
        layout.addLayout(btn_row)

        self.users_table.doubleClicked.connect(lambda *_: self._change_user_role())
        return widget

    def _refresh_users_table(self):
        users = self.user_manager.list_users()
        self._users_cache = users
        self.users_table.setRowCount(len(users))
        for row, user in enumerate(users):
            self.users_table.setItem(row, 0, QTableWidgetItem(user['username']))
            role_text = "Super Admin" if user['is_superadmin'] else (user['role_name'] or "(no role)")
            self.users_table.setItem(row, 1, QTableWidgetItem(role_text))
            self.users_table.setItem(row, 2, QTableWidgetItem("Yes" if user['is_superadmin'] else "No"))

    def _add_user(self):
        roles = self.user_manager.list_roles()
        username, ok = QInputDialog.getText(self, "Add User", "Username:")
        if not ok or not username.strip():
            return
        password, ok = QInputDialog.getText(self, "Add User", "Password:", QLineEdit.Password)
        if not ok or not password:
            return

        role_id = None
        if roles:
            role_names = [r['name'] for r in roles]
            role_name, ok = QInputDialog.getItem(self, "Add User", "Role:", role_names, editable=False)
            if not ok:
                return
            role_id = next(r['id'] for r in roles if r['name'] == role_name)
        else:
            QMessageBox.information(
                self, "No Roles Yet",
                "No roles exist yet - this user will have no access until you create a "
                "role in the Roles tab and assign it."
            )

        try:
            self.user_manager.create_user(username.strip(), password, role_id=role_id, is_superadmin=False)
        except ValueError as e:
            QMessageBox.warning(self, "Could not add user", str(e))
            return
        self._refresh_users_table()

    def _change_user_role(self):
        row = self.users_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "No Selection", "Select a user first.")
            return
        user = self._users_cache[row]
        if user['is_superadmin']:
            QMessageBox.warning(self, "Not allowed",
                              "Super-admin accounts always have full access and don't use roles.")
            return

        roles = self.user_manager.list_roles()
        if not roles:
            QMessageBox.information(self, "No Roles Yet", "Create a role in the Roles tab first.")
            return

        role_names = [r['name'] for r in roles]
        current_index = role_names.index(user['role_name']) if user['role_name'] in role_names else 0
        role_name, ok = QInputDialog.getItem(
            self, "Change Role", f"Role for '{user['username']}':", role_names, current_index, editable=False
        )
        if not ok:
            return
        role_id = next(r['id'] for r in roles if r['name'] == role_name)
        self.user_manager.set_user_role(user['id'], role_id)
        self._refresh_users_table()

    def _change_user_password(self):
        row = self.users_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "No Selection", "Select a user first.")
            return
        user = self._users_cache[row]
        password, ok = QInputDialog.getText(
            self, "Change Password", f"New password for '{user['username']}':", QLineEdit.Password
        )
        if not ok or not password:
            return
        self.user_manager.change_password(user['id'], password)
        QMessageBox.information(self, "Password Changed", f"Password updated for '{user['username']}'.")

    def _remove_user(self):
        row = self.users_table.currentRow()
        if row < 0:
            return
        user = self._users_cache[row]
        if user['is_superadmin']:
            QMessageBox.warning(self, "Not allowed", "Super-admin accounts cannot be removed from here.")
            return
        if QMessageBox.question(self, "Remove User", f"Remove user '{user['username']}'?") == QMessageBox.Yes:
            self.user_manager.delete_user(user['id'])
            self._refresh_users_table()

    # ---------------- Roles tab ----------------

    def _build_roles_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        if not self.can_manage_network:
            note = QLabel(
                "Roles and permissions can only be edited after a profile is unlocked and the local database is connected."
            )
            note.setWordWrap(True)
            layout.addWidget(note)
            layout.addStretch()
            return widget

        role_row = QHBoxLayout()
        role_row.addWidget(QLabel("Role:"))
        self.roles_combo = QComboBox()
        self.roles_combo.currentIndexChanged.connect(self._load_role_matrix)
        role_row.addWidget(self.roles_combo, 1)
        add_role_btn = QPushButton("New Role")
        add_role_btn.clicked.connect(self._add_role)
        role_row.addWidget(add_role_btn)
        remove_role_btn = QPushButton("Delete Role")
        remove_role_btn.clicked.connect(self._delete_role)
        role_row.addWidget(remove_role_btn)
        layout.addLayout(role_row)

        self.matrix_table = QTableWidget(len(MATRIX_SECTIONS), 3)
        self.matrix_table.setHorizontalHeaderLabels(["Read", "Write", "Delete"])
        self.matrix_table.setVerticalHeaderLabels(MATRIX_SECTIONS)
        self.matrix_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.matrix_table)

        save_btn = QPushButton("Save Permissions")
        save_btn.clicked.connect(self._save_role_matrix)
        layout.addWidget(save_btn)
        return widget

    def _refresh_roles_combo(self):
        self._roles_cache = self.user_manager.list_roles()
        self.roles_combo.blockSignals(True)
        self.roles_combo.clear()
        for role in self._roles_cache:
            self.roles_combo.addItem(role['name'], role['id'])
        self.roles_combo.blockSignals(False)
        self._load_role_matrix()

    def _current_role_id(self):
        idx = self.roles_combo.currentIndex()
        if idx < 0:
            return None
        return self.roles_combo.itemData(idx)

    def _load_role_matrix(self):
        role_id = self._current_role_id()
        if role_id is None:
            self.matrix_table.setEnabled(False)
            for row in range(len(MATRIX_SECTIONS)):
                for col in range(3):
                    self.matrix_table.setCellWidget(row, col, None)
            return

        self.matrix_table.setEnabled(True)
        perms = self.user_manager.get_role_permissions(role_id)
        for row, section in enumerate(MATRIX_SECTIONS):
            perm = perms[section]
            for col, key in enumerate(('read', 'write', 'delete')):
                checkbox = QCheckBox()
                checkbox.setChecked(perm[key])
                cell = QWidget()
                cell_layout = QHBoxLayout(cell)
                cell_layout.addWidget(checkbox)
                cell_layout.setAlignment(Qt.AlignCenter)
                cell_layout.setContentsMargins(0, 0, 0, 0)
                self.matrix_table.setCellWidget(row, col, cell)

    def _save_role_matrix(self):
        role_id = self._current_role_id()
        if role_id is None:
            return
        for row, section in enumerate(MATRIX_SECTIONS):
            values = []
            for col in range(3):
                cell = self.matrix_table.cellWidget(row, col)
                checkbox = cell.findChild(QCheckBox) if cell else None
                values.append(bool(checkbox.isChecked()) if checkbox else False)
            self.user_manager.set_role_permission(role_id, section, *values)
        QMessageBox.information(self, "Saved", "Permissions saved.")

    def _add_role(self):
        name, ok = QInputDialog.getText(self, "New Role", "Role name:")
        if not ok or not name.strip():
            return
        try:
            self.user_manager.create_role(name.strip())
        except Exception as e:
            QMessageBox.warning(self, "Could not create role", str(e))
            return
        self._refresh_roles_combo()

    def _delete_role(self):
        role_id = self._current_role_id()
        if role_id is None:
            return
        try:
            self.user_manager.delete_role(role_id)
        except ValueError as e:
            QMessageBox.warning(self, "Could not delete role", str(e))
            return
        self._refresh_roles_combo()
