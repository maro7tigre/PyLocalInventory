"""
Login Widget - Connects to a remote PyLocalInventory host over the LAN
instead of opening a local profile database.
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, Signal
from ui.widgets.themed_widgets import GreenButton, ColoredLineEdit, PasswordInputWidget


class LoginWidget(QWidget):
    """Host/port/username/password entry for connecting to a network host."""

    login_submitted = Signal(str, str, str, str)  # host, port, username, password
    back_requested = Signal()  # Emitted when user wants to go back to local profiles

    def __init__(self, default_host="", default_port="", parent=None):
        super().__init__(parent)
        self.default_host = default_host
        self.default_port = default_port
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
        form_layout.addWidget(self.username_input)

        form_layout.addWidget(QLabel("Password:"))
        self.password_input = PasswordInputWidget()
        self.password_input.setPlaceholderText("Enter your password...")
        self.password_input.returnPressed().connect(self._submit)
        form_layout.addWidget(self.password_input)

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
        self.login_submitted.emit(host, port, username, password)

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
