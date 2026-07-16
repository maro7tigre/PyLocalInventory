"""
Login Widget - Connects to a remote PyLocalInventory host over the LAN
instead of opening a local profile database.
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, Signal
from ui.widgets.themed_widgets import GreenButton, ColoredLineEdit, PasswordInputWidget
from ui.widgets.password_widget import CircularCheckBox


class LoginWidget(QWidget):
    """Host/port/username/password entry for connecting to a network host."""

    login_submitted = Signal(str, str, str, str, bool, bool)
    back_requested = Signal()  # Emitted when user wants to go back to local profiles

    def __init__(self, default_host="", default_port="", default_username="",
                 remember_connection=False, startup_enabled=False, parent=None):
        super().__init__(parent)
        self.default_host = default_host
        self.default_port = default_port
        self.default_username = default_username
        self.remember_connection = remember_connection
        self.startup_enabled = startup_enabled
        self.setup_ui()
        self.apply_styles()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(30)
        main_layout.addStretch(1)

        form_wrapper = QHBoxLayout()
        form_wrapper.addStretch()

        form_card = QWidget()
        form_card.setObjectName("form_card")
        form_card.setMaximumWidth(420)
        form_card.setMinimumWidth(340)
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(30, 30, 30, 30)
        form_layout.setSpacing(15)

        title_label = QLabel("Connect to Network Host")
        title_label.setObjectName("login_title")
        title_label.setAlignment(Qt.AlignCenter)
        form_layout.addWidget(title_label)

        form_layout.addWidget(QLabel("Host / IP address:"))
        self.host_input = ColoredLineEdit()
        self.host_input.setPlaceholderText("e.g. 192.168.1.10")
        self.host_input.setText(self.default_host)
        form_layout.addWidget(self.host_input)

        form_layout.addWidget(QLabel("Port:"))
        self.port_input = ColoredLineEdit()
        self.port_input.setPlaceholderText("8765")
        self.port_input.setText(self.default_port)
        form_layout.addWidget(self.port_input)

        form_layout.addWidget(QLabel("Username:"))
        self.username_input = ColoredLineEdit()
        self.username_input.setPlaceholderText("Enter your username...")
        self.username_input.setText(self.default_username)
        form_layout.addWidget(self.username_input)

        form_layout.addWidget(QLabel("Password:"))
        self.password_input = PasswordInputWidget()
        self.password_input.setPlaceholderText("Enter your password...")
        self.password_input.returnPressed().connect(self._submit)
        form_layout.addWidget(self.password_input)

        self.remember_checkbox = CircularCheckBox("Remember this connection")
        self.remember_checkbox.setChecked(self.remember_connection)
        form_layout.addWidget(self.remember_checkbox)
        self.startup_checkbox = CircularCheckBox("Start PyLocalInventory when Windows starts")
        self.startup_checkbox.setChecked(self.startup_enabled)
        form_layout.addWidget(self.startup_checkbox)

        self.error_label = QLabel("")
        self.error_label.setObjectName("login_error")
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignCenter)
        form_layout.addWidget(self.error_label)

        self.connect_btn = GreenButton("Connect")
        self.connect_btn.setMinimumHeight(45)
        self.connect_btn.clicked.connect(self._submit)
        form_layout.addWidget(self.connect_btn)

        self.back_btn = QPushButton("Use a Local Profile Instead")
        self.back_btn.setObjectName("back_btn")
        self.back_btn.clicked.connect(self.back_requested.emit)
        form_layout.addWidget(self.back_btn)

        form_wrapper.addWidget(form_card)
        form_wrapper.addStretch()
        main_layout.addLayout(form_wrapper)
        main_layout.addStretch(1)

        self.username_input.setFocus()

    def _submit(self):
        self.error_label.setText("")
        host = self.host_input.text().strip()
        port = self.port_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not host or not username or not password:
            self.set_error("Host, username and password are required.")
            return
        self.login_submitted.emit(
            host, port, username, password,
            self.remember_checkbox.isChecked(), self.startup_checkbox.isChecked()
        )

    def clear_password(self):
        self.password_input.setText("")
        self.password_input.setFocus()

    def set_error(self, message):
        self.error_label.setText(message)

    def apply_styles(self):
        self.setStyleSheet("""
            LoginWidget {
                background-color: #2b2b2b;
                min-height: 600px;
            }
            QWidget#form_card {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #3c3c3c, stop:1 #2d2d2d);
                border: 2px solid #2196F3;
                border-radius: 15px;
            }
            QLabel#login_title {
                font-size: 22px;
                font-weight: bold;
                color: #ffffff;
                margin-bottom: 10px;
            }
            QLabel {
                color: #cccccc;
                font-size: 13px;
            }
            QLabel#login_error {
                color: #f44336;
                font-weight: bold;
            }
            QPushButton#back_btn {
                background-color: transparent;
                color: #2196F3;
                border: none;
                padding: 8px;
                font-size: 13px;
            }
            QPushButton#back_btn:hover {
                text-decoration: underline;
            }
        """)


class NetworkUnlockWidget(QWidget):
    """Password-only login for a previously authenticated network connection."""

    login_submitted = Signal(str, str, str, str, bool, bool)
    change_requested = Signal()

    def __init__(self, connection, startup_enabled=False, parent=None):
        super().__init__(parent)
        self.connection = dict(connection)
        self.startup_enabled = bool(startup_enabled)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        card = QWidget()
        card.setObjectName("network_card")
        card.setMinimumWidth(380)
        card.setMaximumWidth(500)
        form = QVBoxLayout(card)
        form.setContentsMargins(35, 30, 35, 30)
        form.setSpacing(16)
        icon = QLabel("🌐")
        icon.setObjectName("network_icon")
        icon.setAlignment(Qt.AlignCenter)
        form.addWidget(icon)
        title = QLabel("Network Connection")
        title.setObjectName("network_title")
        title.setAlignment(Qt.AlignCenter)
        form.addWidget(title)
        for label, value in (
            ("Username", connection.get("username", "")),
            ("Host", connection.get("host", "")),
            ("Port", connection.get("port", "")),
        ):
            info = QLabel(f"{label}:  {value}")
            info.setObjectName("network_info")
            info.setAlignment(Qt.AlignCenter)
            form.addWidget(info)
        form.addWidget(QLabel("Enter Password:"))
        self.password_input = PasswordInputWidget()
        self.password_input.setPlaceholderText("Enter your password...")
        self.password_input.returnPressed().connect(self._submit)
        form.addWidget(self.password_input)
        self.error_label = QLabel()
        self.error_label.setObjectName("network_error")
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignCenter)
        form.addWidget(self.error_label)
        self.connect_btn = GreenButton("Connect")
        self.connect_btn.setMinimumHeight(45)
        self.connect_btn.clicked.connect(self._submit)
        form.addWidget(self.connect_btn)
        change = QPushButton("Change Connection")
        change.setObjectName("change_connection_btn")
        change.clicked.connect(self.change_requested.emit)
        form.addWidget(change)
        row.addWidget(card)
        row.addStretch()
        layout.addLayout(row)
        layout.addStretch()
        self.setStyleSheet("""
            NetworkUnlockWidget { background-color: #2b2b2b; min-height: 600px; }
            QWidget#network_card { background: #333333; border: 2px solid #2196F3; border-radius: 15px; }
            QLabel#network_title { color: white; font-size: 24px; font-weight: bold; }
            QLabel#network_icon { color: #2196F3; font-size: 42px; }
            QLabel#network_info { color: #e0e0e0; font-size: 16px; }
            QLabel#network_error { color: #f44336; font-weight: bold; }
            QPushButton#change_connection_btn { background: transparent; color: #2196F3; border: 2px solid #2196F3; padding: 10px; border-radius: 8px; }
            QPushButton#change_connection_btn:hover { background: #2196F3; color: white; }
        """)
        self.password_input.setFocus()

    def _submit(self):
        password = self.password_input.text()
        if not password:
            self.set_error("Password is required.")
            return
        self.login_submitted.emit(
            str(self.connection.get("host", "")), str(self.connection.get("port", "")),
            str(self.connection.get("username", "")), password, True, self.startup_enabled
        )

    def set_error(self, message):
        self.error_label.setText(message)

    def clear_password(self):
        self.password_input.setText("")
        self.password_input.setFocus()
